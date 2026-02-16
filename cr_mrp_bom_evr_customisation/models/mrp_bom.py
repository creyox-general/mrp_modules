# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
import uuid

from odoo import models, api, _
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
                project_id = vals.get('project_id', bom.project_id.id if bom.project_id else False)
                if not project_id:
                    raise ValidationError(f"Project must be set for EVR BOM: {bom.display_name}")

                project = self.env['project.project'].browse(project_id) if isinstance(project_id,
                                                                                       int) else bom.project_id
                if not project.partner_id:
                    raise ValidationError(f"Customer must be set on Project for EVR BOM: {bom.display_name}")

        # Track changes
        location_changed = 'cfe_project_location_id' in vals

        # Store old line IDs before write
        old_line_ids = {}
        if 'bom_line_ids' in vals:
            for bom in self:
                old_line_ids[bom.id] = set(bom.bom_line_ids.ids)

        res = super().write(vals)

        for bom in self:
            if not bom.is_evr:
                continue

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

                mos = self.env['mrp.production'].search([
                    ('root_bom_id', '=', bom.id),
                    ('state', '=', 'draft')
                ])
                # for mo in mos:
                #     if mo.location_dest_id != bom.cfe_project_location_id:
                #         mo.location_dest_id = bom.cfe_project_location_id.id

            # Handle lines changes (new or modified)
            if bom.id in old_line_ids and bom.cfe_project_location_id:
                current_line_ids = set(bom.bom_line_ids.ids)
                new_line_ids = current_line_ids - old_line_ids[bom.id]

                # Check ALL lines (both old and new) for missing assignments
                needs_full_reassignment = False

                # 1. Check OLD lines (existing before this write)
                old_lines = bom.bom_line_ids.filtered(lambda l: l.id in old_line_ids[bom.id])
                for old_line in old_lines:
                    if not bom._check_and_assign_missing_branches_components(old_line, bom):
                        needs_full_reassignment = True
                        break

                # 2. Check NEW lines
                if new_line_ids:
                    new_lines = self.env['mrp.bom.line'].browse(list(new_line_ids))
                    for new_line in new_lines:
                        if not bom._check_and_assign_missing_branches_components(new_line, bom):
                            needs_full_reassignment = True
                            break

                # If any line is missing assignments, recreate all branches/components
                if needs_full_reassignment:
                    try:
                        _logger.info(f"Recreating all branches and components for BOM {bom.id}")
                        bom.with_context(skip_branch_recompute=False)._assign_branches_for_bom()
                    except Exception as e:
                        _logger.exception(f"Error recreating branches for BOM {bom.id}: {str(e)}")

                # Now check and create missing MOs for ALL lines (old and new)
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
                try:
                    bom.with_context(skip_branch_recompute=False)._assign_branches_for_bom()
                except Exception as e:
                    _logger.exception(f"Error assigning branches for BOM {bom.id}: {str(e)}")

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

    def _assign_branches_for_bom(self):
        """
        Assign branch codes for each root BOM in `self`.
        """
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        codes = _generate_branch_codes()

        for root_bom in self:

            if self.env.context.get('skip_branch_recompute'):
                continue

            # Ensure root_bom has cfe_project_location_id before starting
            if not root_bom.cfe_project_location_id:
                continue

            # Store root location ID
            root_location_id = root_bom.cfe_project_location_id.id

            # Delete old branches/components
            old_branches = Branch.search([('bom_id', '=', root_bom.id)])
            old_components = Component.search([('root_bom_id', '=', root_bom.id)])

            if old_branches:
                old_branches.unlink()
            if old_components:
                old_components.unlink()

            idx = 0
            created_branches = []
            created_components = []


            # DFS
            def dfs(current_bom, parent_location_id, depth=0):
                nonlocal idx
                indent = "  " * depth

                lines = current_bom.bom_line_ids.sorted(key=lambda r: (r.sequence or 0, r.id))

                for line in lines:

                    if line.child_bom_id:

                        if idx >= len(codes):
                            raise UserError("No more branch codes available.")

                        code = codes[idx]
                        idx += 1

                        path_uid = uuid.uuid4().hex

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
                            'sequence': idx,
                            'path_uid': path_uid,
                            'location_id': loc.id,
                        })
                        created_branches.append(branch.id)

                        child_bom = line.child_bom_id

                        # Create component records for all leaf lines in this branch
                        if child_bom:
                            leaf_lines = child_bom.bom_line_ids.filtered(lambda l: not l.child_bom_id)

                            for child_line in leaf_lines:
                                comp = Component.create({
                                    'bom_line_branch_id': branch.id,
                                    'root_bom_id': root_bom.id,
                                    'bom_id': child_bom.id,
                                    'cr_bom_line_id': child_line.id,
                                    'location_id': loc.id,
                                    'is_direct_component': False,
                                })
                                created_components.append(comp.id)

                            # Recurse with current branch location
                            dfs(line.child_bom_id, parent_location_id)
                    else:
                        _logger.info(f"{indent}    Line is a leaf (no child BOM)")

            # Start DFS with root_bom's cfe_project_location_id
            dfs(root_bom, root_location_id)

            # Create components for root-level leaf lines
            root_leaf_lines = root_bom.bom_line_ids.filtered(lambda l: not l.child_bom_id)

            for cr_line in root_leaf_lines:
                comp = Component.create({
                    'root_bom_id': root_bom.id,
                    'bom_id': root_bom.id,
                    'cr_bom_line_id': cr_line.id,
                    'is_direct_component': True,
                    'location_id': root_location_id,
                })
                created_components.append(comp.id)

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


    # def action_create_child_mos_recursive(self, root_bom=None, parent_mo=None, index="0", level=0, parent_qty=1.0,
    #                                       parent_branch_location=None):
    #     """
    #     Create MOs ONLY for BOM lines that have a child BOM.
    #     Each MO will have:
    #     1. Components: WH/Stock → Virtual/Production
    #     2. Finished Product: Virtual/Production → Own Branch Location → Parent Branch Location
    #     """
    #     Branch = self.env['mrp.bom.line.branch']
    #
    #     # Get specific line to create MO for (if called from write)
    #     create_only_for_line = self.env.context.get('create_only_for_line')
    #
    #     if root_bom is None:
    #         root_bom = self
    #         if not hasattr(self.__class__, '_branch_assignment_cache'):
    #             self.__class__._branch_assignment_cache = {}
    #
    #         cache_key = f"bom_{root_bom.id}"
    #         self.__class__._branch_assignment_cache[cache_key] = {
    #             'assignments': {},
    #             'seen_paths': []
    #         }
    #
    #     created_mo = None
    #     warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
    #     stock_location = warehouse.lot_stock_id if warehouse else False
    #
    #     for line_idx, line in enumerate(self.bom_line_ids):
    #         if not line.child_bom_id:
    #             continue
    #
    #         # If we're only creating for a specific line, skip all others
    #         if create_only_for_line and line.id != create_only_for_line:
    #             continue
    #
    #         child_bom = line.child_bom_id
    #         child_qty = float(line.product_qty or 1.0) * parent_qty
    #         line_index = f"{index}{line_idx}"
    #
    #         branches = Branch.search([
    #             ('bom_id', '=', root_bom.id),
    #             ('bom_line_id', '=', line.id)
    #         ], order='sequence')
    #
    #         branch_rec = False
    #         if branches:
    #             if len(branches) == 1:
    #                 branch_rec = branches[0]
    #             else:
    #                 branch_rec = self._get_branch_for_mo_line(
    #                     branches=branches,
    #                     line=line,
    #                     index=line_index,
    #                     root_bom_id=root_bom.id
    #                 )
    #
    #         current_branch_location = False
    #         branch_name = ""
    #
    #         if branch_rec and branch_rec.location_id:
    #             current_branch_location = branch_rec.location_id.id
    #             branch_name = branch_rec.branch_name
    #
    #         # Determine final destination (parent's branch location or project location)
    #         final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id
    #
    #         # CHECK: Does MO already exist for this line?
    #         existing_mo = self.env['mrp.production'].search([
    #             ('root_bom_id', '=', root_bom.id),
    #             ('line', '=', str(line.id)),
    #             ('bom_id', '=', child_bom.id),
    #             ('state', '=', 'draft')
    #         ], limit=1)
    #
    #         if existing_mo:
    #             _logger.info(f"MO {existing_mo.name} already exists for line {line.id}, skipping creation")
    #             # Just continue to next line, don't break
    #             continue
    #
    #         mo_vals = {
    #             'product_id': child_bom.product_tmpl_id.product_variant_id.id,
    #             'product_uom_id': child_bom.product_uom_id.id,
    #             'product_qty': child_qty,
    #             'bom_id': child_bom.id,
    #             'root_bom_id': root_bom.id,
    #             'parent_mo_id': parent_mo.id if parent_mo else False,
    #             'project_id': root_bom.project_id.id,
    #             'line': line.id,
    #             'location_src_id': stock_location.id if stock_location else False,
    #             'location_dest_id': final_dest_location if final_dest_location else False,
    #             'state': 'draft',
    #             'branch_mapping_id': branch_rec.id,
    #         }
    #
    #         mo = self.env['mrp.production'].with_context(
    #             branch_intermediate_location=current_branch_location,
    #             branch_final_location=final_dest_location,
    #             skip_component_moves=True
    #         ).create(mo_vals)
    #
    #         created_mo = mo
    #
    #         src_name = stock_location.display_name if stock_location else "WH/Stock"
    #         intermediate_name = self.env['stock.location'].browse(
    #             current_branch_location).display_name if current_branch_location else "N/A"
    #         final_name = self.env['stock.location'].browse(
    #             final_dest_location).display_name if final_dest_location else "N/A"
    #
    #         self.env['bus.bus']._sendone(
    #             self.env.user.partner_id,
    #             "simple_notification",
    #             {
    #                 "title": "Manufacturing Order Created",
    #                 "message": (
    #                     f"MO {mo.name} created for {child_bom.display_name}\n"
    #                     f"Branch: {branch_name}\n"
    #                     f"Quantity: {child_qty}\n"
    #                     f"Flow: {src_name} → {intermediate_name} → {final_name}"
    #                 ),
    #                 "sticky": False,
    #                 "type": "info",
    #             }
    #         )
    #
    #         # Don't recurse into child BOM if we're only creating for specific line
    #         if not create_only_for_line:
    #             # Recurse: pass current branch location as parent for children
    #             child_bom.action_create_child_mos_recursive(
    #                 root_bom=root_bom,
    #                 parent_mo=mo,
    #                 index=line_index,
    #                 level=level + 1,
    #                 parent_qty=child_qty,
    #                 parent_branch_location=current_branch_location
    #             )
    #
    #     if level == 0 and root_bom == self:
    #         cache_key = f"bom_{root_bom.id}"
    #         if hasattr(self.__class__, '_branch_assignment_cache'):
    #             if cache_key in self.__class__._branch_assignment_cache:
    #                 del self.__class__._branch_assignment_cache[cache_key]
    #
    #     return created_mo

    def action_create_child_mos_recursive(self, root_bom=None, parent_mo=None, index="0", level=0, parent_qty=1.0,
                                          parent_branch_location=None):
        """
        Create MOs ONLY for BOM lines that have a child BOM.
        Each MO will have:
        1. Components: WH/Stock → Virtual/Production
        2. Finished Product: Virtual/Production → Own Branch Location → Parent Branch Location
        """
        Branch = self.env['mrp.bom.line.branch']

        # Get specific line to create MO for (if called from write)
        create_only_for_line = self.env.context.get('create_only_for_line')

        if root_bom is None:
            root_bom = self
            if not hasattr(self.__class__, '_branch_assignment_cache'):
                self.__class__._branch_assignment_cache = {}

            cache_key = f"bom_{root_bom.id}"
            self.__class__._branch_assignment_cache[cache_key] = {
                'assignments': {},
                'seen_paths': []
            }

            # ADD THIS: Initialize MO tracking list at root level
            if not hasattr(self.__class__, '_created_mos_list'):
                self.__class__._created_mos_list = {}
            self.__class__._created_mos_list[root_bom.id] = []

        created_mo = None
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        stock_location = warehouse.lot_stock_id if warehouse else False

        for line_idx, line in enumerate(self.bom_line_ids):
            if not line.child_bom_id:
                continue

            # If we're only creating for a specific line, skip all others
            if create_only_for_line and line.id != create_only_for_line:
                continue

            child_bom = line.child_bom_id
            child_qty = float(line.product_qty or 1.0) * parent_qty
            line_index = f"{index}{line_idx}"

            branches = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', line.id)
            ], order='sequence')

            branch_rec = False
            if branches:
                if len(branches) == 1:
                    branch_rec = branches[0]
                else:
                    branch_rec = self._get_branch_for_mo_line(
                        branches=branches,
                        line=line,
                        index=line_index,
                        root_bom_id=root_bom.id
                    )

            current_branch_location = False
            branch_name = ""

            if branch_rec and branch_rec.location_id:
                current_branch_location = branch_rec.location_id.id
                branch_name = branch_rec.branch_name

            # Determine final destination (parent's branch location or project location)
            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # CHECK: Does MO already exist for this line?
            existing_mo = self.env['mrp.production'].search([
                ('root_bom_id', '=', root_bom.id),
                ('line', '=', str(line.id)),
                ('bom_id', '=', child_bom.id),
                ('state', '=', 'draft')
            ], limit=1)

            if existing_mo:
                _logger.info(f"MO {existing_mo.name} already exists for line {line.id}, skipping creation")
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
                'branch_mapping_id': branch_rec.id,
            }

            mo = self.env['mrp.production'].with_context(
                branch_intermediate_location=current_branch_location,
                branch_final_location=final_dest_location,
                skip_component_moves=True
            ).create(mo_vals)

            created_mo = mo

            # ADD THIS: Track created MO
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

            # Don't recurse into child BOM if we're only creating for specific line
            if not create_only_for_line:
                # Recurse: pass current branch location as parent for children
                child_bom.action_create_child_mos_recursive(
                    root_bom=root_bom,
                    parent_mo=mo,
                    index=line_index,
                    level=level + 1,
                    parent_qty=child_qty,
                    parent_branch_location=current_branch_location
                )

        # ADD THIS: Return the list at root level
        if level == 0 and root_bom == self:
            cache_key = f"bom_{root_bom.id}"
            if hasattr(self.__class__, '_branch_assignment_cache'):
                if cache_key in self.__class__._branch_assignment_cache:
                    del self.__class__._branch_assignment_cache[cache_key]

            # Get the created MOs list and clean up
            created_mos_list = []
            if hasattr(self.__class__, '_created_mos_list') and root_bom.id in self.__class__._created_mos_list:
                created_mos_list = self.__class__._created_mos_list[root_bom.id]
                del self.__class__._created_mos_list[root_bom.id]

            return created_mos_list

        return created_mo


    def _get_branch_for_mo_line(self, branches, line, index, root_bom_id):
        """Determine which branch to use for this MO based on the traversal path."""
        cache_key = f"bom_{root_bom_id}"

        if not hasattr(self.__class__, '_branch_assignment_cache'):
            return branches[0]

        cache = self.__class__._branch_assignment_cache.get(cache_key)
        if not cache:
            return branches[0]

        path_key = f"{root_bom_id}_{line.id}_{index}"

        if path_key not in cache['seen_paths']:
            existing_count = len([p for p in cache['seen_paths']
                                  if p.startswith(f"{root_bom_id}_{line.id}_")])

            if existing_count < len(branches):
                branch = branches[existing_count]
            else:
                branch = branches[-1]

            cache['assignments'][path_key] = branch.id
            cache['seen_paths'].append(path_key)
        else:
            branch_id = cache['assignments'].get(path_key)
            branch = self.env['mrp.bom.line.branch'].browse(branch_id)

        return branch

    def _assign_branches_for_new_lines(self, new_line_ids):
        """
        Assign branches only for new lines without deleting existing branches.
        """
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        codes = _generate_branch_codes()

        for root_bom in self:
            if not root_bom.cfe_project_location_id:
                continue

            # Get existing branches to know which codes are used
            existing_branches = Branch.search([('bom_id', '=', root_bom.id)], order='sequence')
            used_codes = set(existing_branches.mapped('branch_name'))

            # Find next available index
            idx = len(existing_branches)

            root_location_id = root_bom.cfe_project_location_id.id

            # Process only new lines
            new_lines = self.env['mrp.bom.line'].browse(new_line_ids)

            for line in new_lines:
                if not line.child_bom_id:
                    # Create component for leaf line
                    comp = Component.create({
                        'root_bom_id': root_bom.id,
                        'bom_id': root_bom.id,
                        'cr_bom_line_id': line.id,
                        'is_direct_component': True,
                        'location_id': root_location_id,
                    })
                    continue

                # Line has child BOM - create branch
                if idx >= len(codes):
                    raise UserError("No more branch codes available.")

                code = codes[idx]
                idx += 1

                path_uid = uuid.uuid4().hex

                # Create location as sublocation
                loc = self.env['stock.location'].create({
                    'name': code,
                    'location_id': root_location_id,
                    'usage': 'internal',
                })

                # Create branch
                branch = Branch.create({
                    'bom_id': root_bom.id,
                    'bom_line_id': line.id,
                    'branch_name': code,
                    'sequence': idx,
                    'path_uid': path_uid,
                    'location_id': loc.id,
                })

                child_bom = line.child_bom_id

                # Create components for leaf lines in child BOM
                if child_bom:
                    leaf_lines = child_bom.bom_line_ids.filtered(lambda l: not l.child_bom_id)

                    for child_line in leaf_lines:
                        comp = Component.create({
                            'bom_line_branch_id': branch.id,
                            'root_bom_id': root_bom.id,
                            'bom_id': child_bom.id,
                            'cr_bom_line_id': child_line.id,
                            'location_id': loc.id,
                            'is_direct_component': False,
                        })

        return True

    def _check_and_assign_missing_branches_components(self, line, root_bom):
        """
        Recursively check if a line has proper branch/component assignments.
        If missing, create them. Works for both new and old lines.
        """
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']

        if line.child_bom_id:
            # Line has child BOM - check branch assignment
            existing_branch = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', line.id)
            ], limit=1)

            if not existing_branch:
                _logger.info(f"Missing branch for line {line.id}, will recreate all branches")
                return False

            # Recursively check all child lines in the child BOM
            child_bom = line.child_bom_id
            for child_line in child_bom.bom_line_ids:
                if not self._check_and_assign_missing_branches_components(child_line, root_bom):
                    return False
        else:
            # Line is a leaf component - check component assignment
            if line.bom_id.id == root_bom.id:
                # Direct component of root BOM
                existing_component = Component.search([
                    ('root_bom_id', '=', root_bom.id),
                    ('bom_id', '=', root_bom.id),
                    ('cr_bom_line_id', '=', line.id),
                    ('is_direct_component', '=', True)
                ], limit=1)
            else:
                # Nested component
                existing_component = Component.search([
                    ('root_bom_id', '=', root_bom.id),
                    ('bom_id', '=', line.bom_id.id),
                    ('cr_bom_line_id', '=', line.id),
                    ('is_direct_component', '=', False)
                ], limit=1)

            if not existing_component:
                _logger.info(f"Missing component for line {line.id}, will recreate all branches")
                return False

        return True

    def _check_and_create_missing_mos(self, line, root_bom, parent_mo=None, parent_qty=1.0,
                                      parent_branch_location=None):
        """
        Recursively check if MOs exist for a line and all its children.
        Create missing MOs for entire hierarchy.
        """
        if not line.child_bom_id:
            return

        child_bom = line.child_bom_id
        child_qty = float(line.product_qty or 1.0) * parent_qty

        # Check if MO exists for this line
        existing_mo = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom.id),
            ('line', '=', str(line.id)),
            ('bom_id', '=', child_bom.id),
            ('state', '=', 'draft')
        ], limit=1)

        current_mo = existing_mo
        current_branch_location = parent_branch_location

        if not existing_mo:
            # Get branch for this line to determine locations
            Branch = self.env['mrp.bom.line.branch']
            branches = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', line.id)
            ], order='sequence', limit=1)

            if branches and branches.location_id:
                current_branch_location = branches.location_id.id

            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # Get warehouse location
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            stock_location = warehouse.lot_stock_id if warehouse else False

            # Create MO for this line
            _logger.info(f"Creating missing MO for line {line.id} (product: {line.product_id.display_name})")

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
            }

            current_mo = self.env['mrp.production'].with_context(
                branch_intermediate_location=current_branch_location,
                branch_final_location=final_dest_location,
                skip_component_moves=True
            ).create(mo_vals)

            # Send notification
            branch_name = branches.branch_name if branches else "N/A"
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

        # IMPORTANT: Recursively check ALL child lines (whether MO existed or was just created)
        for child_line in child_bom.bom_line_ids:
            if child_line.child_bom_id:
                # This child line also has a BOM, recursively create MOs for it
                self._check_and_create_missing_mos(
                    child_line,
                    root_bom,
                    current_mo,
                    child_qty,
                    current_branch_location
                )