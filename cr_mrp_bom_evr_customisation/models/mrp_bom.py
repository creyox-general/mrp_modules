# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
import uuid

from odoo import models, fields,api, _
import logging

from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


def _generate_branch_codes():
    codes = []
    for c in range(ord('A'), ord('Z') + 1):
        codes.append(chr(c))
    for c in range(ord('A'), ord('Z') + 1):
        for d in range(1, 10):
            codes.append(f"{chr(c)}{d}")
    for c1 in range(ord('A'), ord('Z') + 1):
        for c2 in range(ord('A'), ord('Z') + 1):
            codes.append(chr(c1) + chr(c2))
    return codes


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    used_in_root_bom_ids_str = fields.Char(
        string='Used In Root BOM IDs',
        help="Comma-separated IDs of the Root BOMs (projects) where this BOM is currently used as a sub-component.",
        default=""
    )
    used_in_root_bom_ids = fields.Many2many(
        'mrp.bom', 
        relation='dummy_mrp_bom_used_in_root_rel', 
        column1='sub_bom_id', 
        column2='root_bom_id',
        string="Dummy"
    ) # Temporary field to fix upgrade catch-22
    root_bom_id = fields.Integer(string="Dummy") # Temporary field to fix upgrade catch-22

    def check_all_components_approved(self, processed_boms=None):
        """
        Recursively check if all BOM components are approved to manufacture.
        Returns (is_approved, unapproved_products) tuple.
        """
        if processed_boms is None:
            processed_boms = set()

        # Prevent infinite loops in case of circular BOM references
        if self.id in processed_boms:
            return True, []

        processed_boms.add(self.id)
        unapproved_products = []

        for bom_line in self.bom_line_ids:
            # Check if this line has a BOM
            component_bom = self.env['mrp.bom']._bom_find(
                bom_line.product_id,
                bom_type='normal'
            )[bom_line.product_id]

            if component_bom:
                # This component has a BOM
                if not bom_line.approve_to_manufacture:
                    unapproved_products.append({
                        'product': bom_line.product_id.display_name,
                        'level': 'current'
                    })

                # Recursively check sub-components
                is_approved, sub_unapproved = component_bom.check_all_components_approved(
                    processed_boms.copy()
                )

                if not is_approved:
                    unapproved_products.extend(sub_unapproved)

        is_all_approved = len(unapproved_products)  == 0
        return is_all_approved, unapproved_products

    def check_bom_components_approval(self):
        """
        Public method to be called from JavaScript.
        Returns dict with approval status and unapproved products.
        """
        self.ensure_one()
        is_approved, unapproved_products = self.check_all_components_approved()

        return {
            'approved': is_approved,
            'unapproved_products': unapproved_products
        }


    def write(self, vals):
        # Validate EVR requirements
        for bom in self:
            check_evr = vals.get('is_evr', bom.is_evr)
            if check_evr:
                # Skip validation for BOMs created from a Sale Order
                # (root SO BOMs have no project_id by design)
                if bom.sale_order_id:
                    continue

                project_id = vals.get('project_id', bom.project_id.id if bom.project_id else False)
                # if not project_id:
                #     raise ValidationError(f"Project must be set for EVR BOM: {bom.display_name}")

                project = self.env['project.project'].browse(project_id) if isinstance(project_id,
                                                                                       int) else bom.project_id
                # if not project.partner_id:
                #     raise ValidationError(f"Customer must be set on Project for EVR BOM: {bom.display_name}")

        # Track changes
        location_changed = 'cfe_project_location_id' in vals

        # Store old line IDs before write
        old_line_ids = {}
        if 'bom_line_ids' in vals:
            for bom in self:
                old_line_ids[bom.id] = set(bom.bom_line_ids.ids)

        # Suppress cascades from mrp_bom_line.create/unlink during this write.
        # mrp.bom.write() is the single owner of the branch-assignment cascade.
        res = super(MrpBom, self.with_context(skip_branch_recompute=True)).write(vals)

        for bom in self:
            # ── EVR-specific logic (only for is_evr=True BOMs) ──────────────
            if bom.is_evr:
                # Handle project location changes
                if 'project_id' in vals or 'is_evr' in vals:
                    project = bom.project_id
                    if project:
                        parent_loc = bom._find_project_parent_location()
                        loc_name = project.name
                        Location = self.env['stock.location']

                        existing = Location.search([
                            ('name', '=', loc_name),
                            ('location_id', '=', parent_loc.id),
                            ('usage', '=', 'internal')
                        ], limit=1)

                        if existing:
                            bom.cfe_project_location_id = existing.id
                        else:
                            new_loc = Location.create({
                                'name': loc_name,
                                'location_id': parent_loc.id,
                                'usage': 'internal',
                            })
                            bom.cfe_project_location_id = new_loc.id

                # Update locations when project location changes
                if location_changed and bom.cfe_project_location_id:
                    branches = self.env['mrp.bom.line.branch'].search([('bom_id', '=', bom.id)])
                    for branch in branches:
                        if branch.location_id and branch.location_id.location_id != bom.cfe_project_location_id:
                            branch.location_id.location_id = bom.cfe_project_location_id.id

                    components = self.env['mrp.bom.line.branch.components'].search([
                        ('root_bom_id', '=', bom.id),
                        ('is_direct_component', '=', True)
                    ])
                    for comp in components:
                        comp.location_id = bom.cfe_project_location_id.id

                    if not self._context.get('skip_branch_recompute'):
                        # Trigger sync when project location is first set
                        _logger.info(f"Triggering branch assignment for BOM {bom.id} after location change")
                        bom.with_context(skip_branch_recompute=False)._assign_branches_for_bom()

                    mos = self.env['mrp.production'].search([
                        ('root_bom_id', '=', bom.id),
                        ('state', '=', 'draft')
                    ])

            # ── Cascade to parent EVR root BOMs when lines change ────────────
            # Runs for ALL BOMs (is_evr=True AND is_evr=False sub-BOMs)
            # so that parent root BOMs always get updated when any sub-BOM changes.
            if bom.id in old_line_ids:
                current_line_ids = set(bom.bom_line_ids.ids)
                new_line_ids = current_line_ids - old_line_ids[bom.id]
                _logger.info(f"[SYNC TRACE] mrp.bom.write triggered for BOM {bom.id} (is_evr={bom.is_evr}). Line changes: +{new_line_ids}")

                if current_line_ids != old_line_ids[bom.id]:
                    parent_roots = set()

                    # Method 1: from explicit used_in_root_bom_ids_str tracking
                    if bom.used_in_root_bom_ids_str:
                        id_strings = [i.strip() for i in bom.used_in_root_bom_ids_str.split(',') if i.strip()]
                        for root_id_str in id_strings:
                            try:
                                parent_roots.add(int(root_id_str))
                            except ValueError:
                                pass

                    # Method 2: BFS ancestor search via product relationship
                    helpers = self.env['cr.mrp.bom.helpers']
                    roots = helpers.get_root_boms_for_bom(bom)
                    for r in roots:
                        parent_roots.add(r.id)

                    # Method 3 (most reliable): directly search BOM lines that explicitly
                    # reference this BOM as child_bom_id, then trace up to their root BOMs.
                    # Essential for non-EVR sub-BOMs that have no cfe_project_location_id.
                    direct_parent_lines = self.env['mrp.bom.line'].search([
                        ('child_bom_id', '=', bom.id)
                    ])
                    for pl in direct_parent_lines:
                        parent_bom = pl.bom_id
                        if not parent_bom:
                            continue
                        _logger.info(f"[SYNC TRACE] Method 3 found parent BOM '{parent_bom.display_name}' via child_bom_id")
                        if parent_bom.is_evr and (parent_bom.cfe_project_location_id or getattr(parent_bom, 'sale_order_id', False)):
                            parent_roots.add(parent_bom.id)
                        for r in helpers.get_root_boms_for_bom(parent_bom):
                            parent_roots.add(r.id)

                    # Also add self if it is its own EVR root
                    if bom.cfe_project_location_id or getattr(bom, 'sale_order_id', False):
                        parent_roots.add(bom.id)

                    final_roots = self.env['mrp.bom'].browse(list(parent_roots)).filtered(
                        lambda r: r.is_evr and (r.cfe_project_location_id or getattr(r, 'sale_order_id', False))
                    )

                    if final_roots:
                        _logger.info(f"[SYNC TRACE] CASCADING branch update from BOM {bom.id} to {len(final_roots)} parent Root BOMs: {[r.display_name for r in final_roots]}")
                        for r in final_roots:
                            r.with_context(skip_branch_recompute=False, force_check_new_lines=True)._assign_branches_for_bom()
                    else:
                        _logger.info(f"[SYNC TRACE] No parent EVR Root BOMs found for BOM {bom.id}.")

                # Now check and create missing MOs for ALL lines (only for EVR BOMs)
                if bom.is_evr:
                    try:
                        for line in bom.bom_line_ids:
                            if line.child_bom_id:
                                bom._check_and_create_missing_mos(line, bom)
                    except Exception as e:
                        _logger.exception(f"Error checking/creating MOs for BOM {bom.id}: {str(e)}")

        return res

    def create(self, vals_list):
        # Validate EVR requirements before creation
        if not isinstance(vals_list, list):
            vals_list = [vals_list]

            # Validate EVR requirements before creation
        for vals in vals_list:
            if vals.get('is_evr'):
                # Skip validation for BOMs created from a Sale Order
                if vals.get('sale_order_id'):
                    continue

                if not vals.get('project_id'):
                    raise ValidationError("Project must be set for EVR BOM")

                project = self.env['project.project'].browse(vals['project_id'])
                if not project.partner_id:
                    raise ValidationError("Customer must be set on Project for EVR BOM")
        # CREATE WITHOUT triggering branch assignment from BOM lines
        boms = super(MrpBom, self.with_context(skip_branch_recompute=True)).create(vals_list)

        for bom in boms:
            # Skip if not EVR
            if not bom.is_evr:
                continue

            # Check project
            project = bom.project_id
            if not project:
                continue

            # parent: Project Location
            parent_loc = bom._find_project_parent_location()
            loc_name = project.name
            Location = self.env['stock.location']

            # Check existing location
            existing = Location.search([
                ('name', '=', loc_name),
                ('location_id', '=', parent_loc.id),
                ('usage', '=', 'internal')
            ], limit=1)

            if existing:
                bom.cfe_project_location_id = existing.id
            else:
                # Create new location
                new_loc = Location.create({
                    'name': loc_name,
                    'location_id': parent_loc.id,
                    'usage': 'internal',
                })
                bom.cfe_project_location_id = new_loc.id

        evr_boms_with_location = boms.filtered(lambda b: b.is_evr and b.cfe_project_location_id)

        if evr_boms_with_location:
            for bom in evr_boms_with_location:
                bom.with_context(skip_branch_recompute=False)._assign_branches_for_bom()

        # Verify branches were created before creating MOs
        for bom in evr_boms_with_location:
            branch_count = self.env['mrp.bom.line.branch'].search_count([('bom_id', '=', bom.id)])

            if branch_count == 0:
                continue

            try:
                bom.action_create_child_mos_recursive()
            except Exception as e:
                _logger.exception(f"Error creating MOs for BOM {bom.id}: {str(e)}")

        return boms

    def _get_first_created_bom(self, product):
        """Find the oldest BOM for a product."""
        domain = [
            '|',
            ('product_id', '=', product.id),
            '&',
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False),
        ]
        return self.env['mrp.bom'].search(domain, order='create_date asc, id asc', limit=1)

    def _assign_branches_for_bom(self):
        """
        Assign branch codes for each root BOM in `self` incrementally.
        """
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        codes = _generate_branch_codes()

        for root_bom in self:
            if self.env.context.get('skip_branch_recompute'):
                continue

            # Root Guard: skip if root_bom is NOT itself in the set of roots
            # (A BOM with cfe_project_location_id is always its own root, even when used in another root.)
            helpers = self.env['cr.mrp.bom.helpers']
            absolute_roots = helpers.get_root_boms_for_bom(root_bom)
            absolute_root_ids = [r.id for r in absolute_roots]
            if root_bom.id not in absolute_root_ids:
                _logger.info("BOM %s is not an absolute root, skipping branch assignment", root_bom.display_name)
                continue

            # Collect OTHER roots that contain this BOM to cascade to after own assignment
            other_roots = [r for r in absolute_roots if r.id != root_bom.id]

            # Ensure root_bom has cfe_project_location_id (for standard EVR) or sale_order_id (for SO)
            if not root_bom.cfe_project_location_id and not (hasattr(root_bom, 'sale_order_id') and root_bom.sale_order_id):
                continue

            # Store root location ID (default to False if no project location)
            root_location_id = root_bom.cfe_project_location_id.id if root_bom.cfe_project_location_id else False

            # Initialize index based on existing branches to preserve sequence
            existing_branches = Branch.search([('bom_id', '=', root_bom.id)])
            existing_names = existing_branches.mapped('branch_name')
            max_idx = -1
            for name in existing_names:
                try:
                    if name in codes:
                        max_idx = max(max_idx, codes.index(name))
                except ValueError:
                    continue
            
            # Start from the next code in sequence
            current_idx_ptr = max_idx + 1
            new_branches_to_mo = []

            # Clear old root assignments for this root BOM
            root_id_str = str(root_bom.id)
            sub_boms = self.env['mrp.bom'].search([('used_in_root_bom_ids_str', 'ilike', root_id_str)])
            _logger.info(f"DEBUG EVR: Starting assignment for ROOT BOM: {root_bom.id}. Clearing old traces in {len(sub_boms)} sub-boms.")
            for sub_bom in sub_boms:
                if sub_bom.used_in_root_bom_ids_str:
                    ids = [i.strip() for i in sub_bom.used_in_root_bom_ids_str.split(',') if i.strip() and i.strip() != root_id_str]
                    sub_bom.used_in_root_bom_ids_str = ",".join(ids)

            # DFS to traverse hierarchy and assign branches/components
            def dfs(current_bom, parent_location_id, depth=0, parent_branch_id=None, root_line_id=None):
                nonlocal current_idx_ptr
                indent = "  " * depth

                lines = current_bom.bom_line_ids.sorted(key=lambda r: (r.sequence or 0, r.id))

                for line in lines:
                    # Context for this path
                    current_root_line_id = root_line_id
                    if depth == 0:
                        current_root_line_id = line.id

                    # Point 4: Use first created BOM
                    child_bom = line.child_bom_id or root_bom._get_first_created_bom(line.product_id)

                    if child_bom:
                        # Ensure Component assignment is properly skipped if already handled
                        # Check if branch already exists for this path (context-aware via parent_branch_id)
                        branch = Branch.search([
                            ('bom_id', '=', root_bom.id),
                            ('bom_line_id', '=', line.id),
                            ('parent_branch_id', '=', parent_branch_id)
                        ], limit=1)

                        if not branch:
                            if current_idx_ptr >= len(codes):
                                raise UserError("No more branch codes available.")

                            code = codes[current_idx_ptr]
                            current_idx_ptr += 1

                            # Create location as sublocation of parent
                            loc = self.env['stock.location'].create({
                                'name': code,
                                'location_id': parent_location_id,
                                'usage': 'internal',
                            })

                            # Create branch
                            branch = Branch.create({
                                'bom_id': root_bom.id,
                                'bom_line_id': line.id,
                                'branch_name': code,
                                'sequence': current_idx_ptr,
                                'path_uid': uuid.uuid4().hex,
                                'location_id': loc.id,
                                'parent_branch_id': parent_branch_id,
                                'root_line_id': current_root_line_id,
                            })
                            new_branches_to_mo.append(line.id)
                        
                        # Track BOM usage in Root BOM (The new logic requested by user)
                        root_id_str = str(root_bom.id)
                        current_ids = [i.strip() for i in (child_bom.used_in_root_bom_ids_str or '').split(',') if i.strip()]
                        
                        _logger.info(f"DEBUG EVR: Checking tracking for child BOM {child_bom.id} (under root {root_id_str}). Current strings: {current_ids}")
                        if root_id_str not in current_ids:
                            current_ids.append(root_id_str)
                            new_str = ",".join(current_ids)
                            child_bom.write({'used_in_root_bom_ids_str': new_str})
                            _logger.info(f"DEBUG EVR: WROTE new string '{new_str}' to child BOM {child_bom.id} ({child_bom.display_name})")
                        else:
                            _logger.info(f"DEBUG EVR: Root {root_id_str} is ALREADY tracked in child BOM {child_bom.id}")

                        # Create/Update assignment for this context
                        Assignment = self.env['mrp.bom.line.branch.assignment']
                        assign_vals = {
                            'root_bom_id': root_bom.id,
                            'bom_id': current_bom.id,
                            'bom_line_id': line.id,
                            'branch_id': parent_branch_id,
                            'own_branch_id': branch.id,
                            'component_id': False,
                            'root_line_id': current_root_line_id,
                        }
                        assignment = Assignment.search([
                            ('root_bom_id', '=', root_bom.id),
                            ('bom_line_id', '=', line.id),
                            ('branch_id', '=', parent_branch_id)
                        ], limit=1)
                        if assignment:
                            assignment.write(assign_vals)
                        else:
                            Assignment.create(assign_vals)

                        # Recurse with original parent location (flat hierarchy under project)
                        dfs(child_bom, parent_location_id, depth + 1, branch.id, current_root_line_id)
                    else:
                        # Leaf line at this level
                        is_direct = (current_bom.id == root_bom.id)
                        
                        # Direct components check
                        existing_comp = Component.search([
                            ('root_bom_id', '=', root_bom.id),
                            ('bom_id', '=', current_bom.id),
                            ('cr_bom_line_id', '=', line.id),
                            ('bom_line_branch_id', '=', parent_branch_id)
                        ], limit=1)

                        if not existing_comp:
                            existing_comp = Component.create({
                                'root_bom_id': root_bom.id,
                                'bom_id': current_bom.id,
                                'cr_bom_line_id': line.id,
                                'is_direct_component': is_direct,
                                'location_id': parent_location_id if is_direct else False,
                                'bom_line_branch_id': parent_branch_id,
                                'root_line_id': current_root_line_id,
                            })
                            # Direct components need MO triggers when created too
                            new_branches_to_mo.append(line.id)

                        # Create/Update assignment for this context
                        Assignment = self.env['mrp.bom.line.branch.assignment']
                        assign_vals = {
                            'root_bom_id': root_bom.id,
                            'bom_id': current_bom.id,
                            'bom_line_id': line.id,
                            'branch_id': parent_branch_id,
                            'own_branch_id': False,
                            'component_id': existing_comp.id,
                            'root_line_id': current_root_line_id,
                        }
                        assignment = Assignment.search([
                            ('root_bom_id', '=', root_bom.id),
                            ('bom_line_id', '=', line.id),
                            ('branch_id', '=', parent_branch_id)
                        ], limit=1)
                        if assignment:
                            assignment.write(assign_vals)
                        else:
                            Assignment.create(assign_vals)

            # Start DFS with root_bom's cfe_project_location_id
            dfs(root_bom, root_location_id)

            # Point 5: Auto-create MOs for newly added branches
            if new_branches_to_mo:
                root_bom.action_create_child_mos_recursive()

            # Notify success
            self.env['bus.bus']._sendone(
                self.env.user.partner_id, "simple_notification",
                {"title": "Sync Complete", "message": f"Project '{root_bom.display_name}' is now up to date.", "sticky": False, "type": "success"}
            )

        return True


    def _find_project_parent_location(self):
        StockLocation = self.env['stock.location']

        wh_location = StockLocation.search([
            ('name', '=', 'WH'),
            ('usage', '=', 'view')
        ], limit=1)

        if not wh_location:
            raise UserError("Warehouse (WH) parent location not found!")

        project_location = StockLocation.search([
            ('name', '=', 'Project Location'),
            ('usage', '=', 'internal'),
            ('location_id', '=', wh_location.id)
        ], limit=1)

        if not project_location:
            project_location = StockLocation.create({
                'name': 'Project Location',
                'usage': 'internal',
                'location_id': wh_location.id,
            })

        return project_location

    def _find_project_parent_location_of_root_bom(self,root_bom):
        project = self._find_project_parent_location()

        StockLocation = self.env['stock.location']

        name = root_bom.project_id.name
        project_location = StockLocation.search([
            ('name', '=', name),
            ('usage', '=', 'internal'),
            ('location_id', '=', project.id)
        ], limit=1)

        if not project_location:
            project_location = StockLocation.create({
                'name': name,
                'usage': 'internal',
                'location_id': project.id,
            })

        return project_location



    def _check_all_children_approved(self, bom_line):
        """
        Recursively check if all children (sub-BOMs) have approve_to_manufacture = True
        Only checks lines that have child BOMs
        """
        # Get child BOM using _bom_find which returns dict in Odoo 18
        bom_dict = self.env['mrp.bom']._bom_find(
            bom_line.product_id,
            bom_type='normal',
            company_id=self.company_id.id
        )

        # Extract actual bom record from dict
        if isinstance(bom_dict, dict):
            child_bom = bom_dict.get('bom', False)
        else:
            child_bom = bom_dict

        if not child_bom or not isinstance(child_bom, type(self)):
            # Leaf line (no child BOM) - always approved, no check needed
            return True

        # Has child BOM - check its approval and all its lines recursively
        if not bom_line.approve_to_manufacture:
            return False

        for child_line in child_bom.bom_line_ids:
            if not self._check_all_children_approved(child_line):
                return False

        return True

    def action_create_mo_from_overview(self):
        """
        Called from BOM overview Manufacture button
        """
        if self.is_evr:
            unapproved_lines = []

            for line in self.bom_line_ids:
                if not self._check_all_children_approved(line):
                    unapproved_lines.append(line.product_id.display_name)

            if unapproved_lines:
                raise ValidationError(
                    "Cannot create MO. The following BOM lines or their sub-components are not approved for manufacture:\n" +
                    "\n".join([f"- {name}" for name in unapproved_lines])
                )

        # Return action to create MO
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'name': 'Manufacture Orders',
            'views': [[False, 'form']],
            'target': 'current',
            'context': {'default_bom_id': self.id},
        }


    def _get_flattened_totals(self, product, quantity=1, bom_line=False):
        """Override to pass parent bom line context"""
        if bom_line and self.is_evr:
            return super(MrpBom, self.with_context(parent_bom_line_id=bom_line.id))._get_flattened_totals(product,
                                                                                                          quantity,
                                                                                                          bom_line)
        return super()._get_flattened_totals(product, quantity, bom_line)

    def _get_sub_boms(self, product, bom_line=False):
        """Stop recursion when EVR line is NOT approved."""
        # If EVR and bom_line exists and is not approved → DO NOT recurse
        if bom_line and self.is_evr and not bom_line.approve_to_manufacture:
            return []

        return super()._get_sub_boms(product, bom_line)



    def action_create_child_mos_recursive(self, root_bom=None, parent_mo=None, index="0", level=0, parent_qty=1.0,
                                          parent_branch_location=None, parent_branch_id=None):
        """
        Create MOs ONLY for BOM lines that have a child BOM.
        Uses context-aware assignment model for path uniqueness.
        """
        Branch = self.env['mrp.bom.line.branch']
        root_bom = self

        # Initialize tracking list if not exists
        if level == 0:
            if not hasattr(self.__class__, '_created_mos_list'):
                self.__class__._created_mos_list = {}
            self.__class__._created_mos_list[root_bom.id] = []

        created_mo = None
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        stock_location = warehouse.lot_stock_id if warehouse else False

        for line_idx, line in enumerate(self.bom_line_ids):
            child_bom = line.child_bom_id or root_bom._get_first_created_bom(line.product_id)
            if not child_bom:
                continue

            child_qty = float(line.product_qty or 1.0) * parent_qty
            line_index = f"{index}{line_idx}"

            # Find assignment for this context (Root + Parent Branch)
            assignment = line.get_assignment(root_bom, parent_branch_id)
            branch_rec = assignment.own_branch_id if assignment else False

            current_branch_location = False
            branch_name = ""

            if branch_rec and branch_rec.location_id:
                current_branch_location = branch_rec.location_id.id
                branch_name = branch_rec.branch_name

            # Determine final destination (parent's branch location or project location)
            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # CHECK: Does MO already exist for this SPECIFIC branch path?
            existing_mo = self.env['mrp.production'].search([
                ('root_bom_id', '=', root_bom.id),
                ('line', '=', str(line.id)),
                ('bom_id', '=', child_bom.id),
                ('branch_mapping_id', '=', branch_rec.id if branch_rec else False),
                ('state', '=', 'draft')
            ], limit=1)

            if existing_mo:
                _logger.info(f"MO {existing_mo.name} already exists for line {line.id} branch {branch_name}, skipping creation")
                # Just continue to next line, don't break
                continue

            mo_vals = {
                'product_id': child_bom.product_tmpl_id.product_variant_id.id,
                'product_uom_id': child_bom.product_uom_id.id,
                'product_qty': child_qty,
                'bom_id': child_bom.id,
                'root_bom_id': root_bom.id,
                'parent_mo_id': parent_mo.id if parent_mo else False,
                'project_id': root_bom.project_id.id,
                'line': line.id,
                'location_src_id': stock_location.id if stock_location else False,
                'location_dest_id': final_dest_location if final_dest_location else False,
                'state': 'draft',
                'branch_mapping_id': branch_rec.id if branch_rec else False,
            }

            mo = self.env['mrp.production'].with_context(
                branch_intermediate_location=current_branch_location,
                branch_final_location=final_dest_location,
                skip_component_moves=True,
                force_skip_component_moves=True
            ).create(mo_vals)

            created_mo = mo

            # Track created MO for the summary notification
            if hasattr(self.__class__, '_created_mos_list') and root_bom.id in self.__class__._created_mos_list:
                self.__class__._created_mos_list[root_bom.id].append({
                    'name': mo.name,
                    'product': mo.product_id.display_name,
                    'qty': mo.product_qty
                })

            src_name = stock_location.display_name if stock_location else "WH/Stock"
            intermediate_name = self.env['stock.location'].browse(
                current_branch_location).display_name if current_branch_location else "N/A"
            final_name = self.env['stock.location'].browse(
                final_dest_location).display_name if final_dest_location else "N/A"

            self.env['bus.bus']._sendone(
                self.env.user.partner_id,
                "simple_notification",
                {
                    "title": "Manufacturing Order Created",
                    "message": (
                        f"MO {mo.name} created for {child_bom.display_name}\n"
                        f"Branch: {branch_name}\n"
                        f"Quantity: {child_qty}\n"
                        f"Flow: {src_name} → {intermediate_name} → {final_name}"
                    ),
                    "sticky": False,
                    "type": "info",
                }
            )

            # Recurse: pass current branch location as parent for children
            child_bom.action_create_child_mos_recursive(
                root_bom=root_bom,
                parent_mo=mo,
                index=line_index,
                level=level + 1,
                parent_qty=child_qty,
                parent_branch_location=current_branch_location,
                parent_branch_id=branch_rec.id if branch_rec else False
            )

        # Return the list at root level
        if level == 0 and root_bom == self:
            created_mos_list = []
            if hasattr(self.__class__, '_created_mos_list') and root_bom.id in self.__class__._created_mos_list:
                created_mos_list = self.__class__._created_mos_list[root_bom.id]
                del self.__class__._created_mos_list[root_bom.id]

            return created_mos_list

        return created_mo




    def _check_and_assign_missing_branches_components(self, line, root_bom, parent_branch_id=None):
        """
        Recursively check if a line has proper branch/component assignments.
        If missing, return False (caller will trigger re-assignment).
        Uses context-aware assignment model.
        """
        assignment = line.get_assignment(root_bom, parent_branch_id)
        if not assignment:
            _logger.info(f"Missing assignment for line {line.id} in context {root_bom.id}/{parent_branch_id}")
            return False

        # If it's a branch, check children
        child_bom = line.child_bom_id or root_bom._get_first_created_bom(line.product_id)
        if child_bom:
            if not assignment.own_branch_id:
                _logger.info(f"Line {line.id} should have a branch but doesn't")
                return False
            
            for child_line in child_bom.bom_line_ids:
                if not self._check_and_assign_missing_branches_components(child_line, root_bom, assignment.own_branch_id.id):
                    return False
        else:
            # Leaf component
            if not assignment or not assignment.component_id:
                _logger.info(f"Line {line.id} should have a component record but doesn't")
                return False

        return True

    def _check_and_create_missing_mos(self, line, root_bom, parent_mo=None, parent_qty=1.0,
                                      parent_branch_location=None, parent_branch_id=None):
        """
        Recursively check if MOs exist for a line and all its children.
        Create missing MOs for entire hierarchy using context-aware assignments.
        """
        child_bom = line.child_bom_id or root_bom._get_first_created_bom(line.product_id)
        if not child_bom:
            return

        child_qty = float(line.product_qty or 1.0) * parent_qty

        # Find assignment for this context
        assignment = line.get_assignment(root_bom, parent_branch_id)
        branch_rec = assignment.own_branch_id if assignment else False

        # Check if MO exists for this SPECIFIC branch path
        existing_mo = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom.id),
            ('line', '=', str(line.id)),
            ('bom_id', '=', child_bom.id),
            ('branch_mapping_id', '=', branch_rec.id if branch_rec else False),
            ('state', '=', 'draft')
        ], limit=1)

        current_mo = existing_mo
        current_branch_location = parent_branch_location

        if not existing_mo:
            if branch_rec and branch_rec.location_id:
                current_branch_location = branch_rec.location_id.id

            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # Get warehouse location
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            stock_location = warehouse.lot_stock_id if warehouse else False

            # Create MO for this line
            _logger.info(f"Creating missing MO for line {line.id} (product: {line.product_id.display_name}) branch {branch_rec.branch_name if branch_rec else 'N/A'}")

            mo_vals = {
                'product_id': child_bom.product_tmpl_id.product_variant_id.id,
                'product_uom_id': child_bom.product_uom_id.id,
                'product_qty': child_qty,
                'bom_id': child_bom.id,
                'root_bom_id': root_bom.id,
                'parent_mo_id': parent_mo.id if parent_mo else False,
                'project_id': root_bom.project_id.id,
                'line': line.id,
                'location_src_id': stock_location.id if stock_location else False,
                'location_dest_id': final_dest_location if final_dest_location else False,
                'state': 'draft',
                'branch_mapping_id': branch_rec.id if branch_rec else False,
            }

            current_mo = self.env['mrp.production'].with_context(
                branch_intermediate_location=current_branch_location,
                branch_final_location=final_dest_location,
                skip_component_moves=True,
                force_skip_component_moves=True
            ).create(mo_vals)

            # Send notification
            branch_name = branch_rec.branch_name if branch_rec else "N/A"
            src_name = stock_location.display_name if stock_location else "WH/Stock"
            intermediate_name = self.env['stock.location'].browse(
                current_branch_location).display_name if current_branch_location else "N/A"
            final_name = self.env['stock.location'].browse(
                final_dest_location).display_name if final_dest_location else "N/A"

            self.env['bus.bus']._sendone(
                self.env.user.partner_id,
                "simple_notification",
                {
                    "title": "Manufacturing Order Created",
                    "message": (
                        f"MO {current_mo.name} created for {child_bom.display_name}\n"
                        f"Branch: {branch_name}\n"
                        f"Quantity: {child_qty}\n"
                        f"Flow: {src_name} → {intermediate_name} → {final_name}"
                    ),
                    "sticky": False,
                    "type": "info",
                }
            )

        # IMPORTANT: Recursively check ALL child lines
        for child_line in child_bom.bom_line_ids:
            self._check_and_create_missing_mos(
                child_line,
                root_bom,
                current_mo,
                child_qty,
                current_branch_location,
                branch_rec.id if branch_rec else False
            )