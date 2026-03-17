# -*- coding: utf-8 -*-
# Part of Creyox Technologies
import uuid
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

# Generate branch codes: A-Z, A1-Z9, AA-ZZ
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
    _inherit = 'mrp.bom'

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        copy=False,
        index=True,
        help='The Sale Order this BOM was generated from.',
    )
    is_so_root_bom = fields.Boolean(
        string='Is SO Root BOM',
        default=False,
        copy=False,
        help="Technical flag for BOMs that are the top-level product of a Sale Order."
    )

    # ─────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────

    def _is_so_bom(self):
        """
        Identify if this BOM is the top-level EVR product for a Sale Order.
        Now uses the explicit 'is_so_root_bom' flag.
        """
        self.ensure_one()
        if self.is_so_root_bom:
            return True
        # Fallback for existing records: match by code and template default_code (EVRxxxxx)
        return bool(
            self.sale_order_id
            and self.code == self.product_tmpl_id.default_code
        )

    def _is_child_so_bom(self):
        """
        Identify if this BOM is a sub-component (everest_pn) created for a Sale Order.
        """
        self.ensure_one()
        if not self.sale_order_id:
            return False
        if self.is_so_root_bom:
            return False
        # If it has an SO but isn't the root, it's a child.
        return self.code != self.product_tmpl_id.default_code

    def _get_so_child_bom_location(self, child_bom):
        """
        Return the cfe_project_location_id of the child BOM (which is
        WH/Project Location/{project.name}/{product.default_code}).
        Ensures it exists; creates it if not.
        """
        child_bom.ensure_one()
        if not child_bom.cfe_project_location_id:
            child_bom._set_so_child_bom_location()
        return child_bom.cfe_project_location_id

    # ─────────────────────────────────────────────────────────
    # cfe_project_location_id assignment for SO child BOMs
    # ─────────────────────────────────────────────────────────

    def _set_so_child_bom_location(self):
        """
        For a child BOM created from a Sale Order, set cfe_project_location_id to:
            WH/Project Location/{project.name}/{product.default_code}

        Called AFTER the BOM is created and the product's default_code is set.
        """
        self.ensure_one()

        if not self.sale_order_id:
            return

        project = self.project_id
        if not project:
            _logger.warning(
                "[CFE Loc] Skipping: no project_id on child BOM %s", self.code
            )
            return

        product_code = self.product_id.default_code or self.product_tmpl_id.default_code
        if not product_code:
            _logger.warning(
                "[CFE Loc] Skipping: no default_code on product for BOM %s", self.code
            )
            return

        Location = self.env['stock.location']

        # Step 1: Find WH/Project Location
        wh_location = Location.search([
            ('name', '=', 'WH'),
            ('usage', '=', 'view'),
        ], limit=1)
        if not wh_location:
            _logger.warning("[CFE Loc] WH location not found")
            return

        project_base = Location.search([
            ('name', '=', 'Project Location'),
            ('usage', '=', 'internal'),
            ('location_id', '=', wh_location.id),
        ], limit=1)
        if not project_base:
            _logger.warning("[CFE Loc] 'Project Location' under WH not found")
            return

        # Step 2: Find/create WH/Project Location/{project.name}
        project_loc = Location.search([
            ('name', '=', project.name),
            ('location_id', '=', project_base.id),
            ('usage', '=', 'internal'),
        ], limit=1)
        if not project_loc:
            _logger.info("[CFE Loc] Creating project location: %s", project.name)
            project_loc = Location.create({
                'name': project.name,
                'location_id': project_base.id,
                'usage': 'internal',
            })

        # Step 3: Find/create WH/Project Location/{project.name}/{product_code}
        product_loc = Location.search([
            ('name', '=', product_code),
            ('location_id', '=', project_loc.id),
            ('usage', '=', 'internal'),
        ], limit=1)
        if not product_loc:
            _logger.info(
                "[CFE Loc] Creating product location: %s under %s",
                product_code, project_loc.display_name
            )
            product_loc = Location.create({
                'name': product_code,
                'location_id': project_loc.id,
                'usage': 'internal',
            })

        if self.cfe_project_location_id.id != product_loc.id:
            _logger.info(
                "[CFE Loc] Setting cfe_project_location_id on BOM '%s' to '%s'",
                self.code, product_loc.display_name
            )
            self.cfe_project_location_id = product_loc.id

    # ─────────────────────────────────────────────────────────
    # Branch assignment for SO-created root BOMs
    # ─────────────────────────────────────────────────────────

    def _assign_branches_for_bom(self):
        """
        Override: dispatch to SO-specific logic for SO root BOMs.
        Skip child SO BOMs entirely (they are handled as branches of the root).
        Fall through to super() for regular EVR BOMs.
        """
        for root_bom in self:
            if self.env.context.get('skip_branch_recompute'):
                continue

            if root_bom.is_so_root_bom:
                # Root SO BOM (is_so_root_bom=True): assign branches per child BOM
                root_bom._assign_so_bom_branches()

            elif root_bom.sale_order_id:
                # Child SO BOM (has SO but is not root) — handled normally via super()
                super(MrpBom, root_bom)._assign_branches_for_bom()

            else:
                # Normal EVR BOM: delegate to super()
                super(MrpBom, root_bom)._assign_branches_for_bom()

        return True

    def _assign_so_bom_branches(self):
        """
        Assign branches for a root BOM created from a Sale Order incrementally and recursively.
        """
        self.ensure_one()

        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        codes = _generate_branch_codes()

        _logger.info(
            "[SO BOM] Starting recursive incremental branch assignment for root BOM: %s", self.display_name
        )

        # 1. Ensure Root SO BOM has a project-level location set (WH/Project Location/ProjectName)
        if not self.cfe_project_location_id:
            project_loc = self._find_project_parent_location_of_root_bom(self)
            if project_loc:
                self.cfe_project_location_id = project_loc.id
                _logger.info("[SO BOM] Set cfe_project_location_id for root BOM: %s", project_loc.display_name)

        # Clear old root assignments for this root BOM
        root_id_str = str(self.id)
        sub_boms = self.env['mrp.bom'].search([('used_in_root_bom_ids_str', 'ilike', root_id_str)])
        _logger.info(f"DEBUG SO BOM: Starting assignment for ROOT BOM: {self.id}. Clearing old traces in {len(sub_boms)} sub-boms.")
        for sub_bom in sub_boms:
            if sub_bom.used_in_root_bom_ids_str:
                ids = [i.strip() for i in sub_bom.used_in_root_bom_ids_str.split(',') if i.strip() and i.strip() != root_id_str]
                sub_bom.used_in_root_bom_ids_str = ",".join(ids)

        # OLD CODE COMMENTED OUT AS REQUESTED
        # # Remove old branches/components for this root BOM
        # Branch.search([('bom_id', '=', self.id)]).unlink()
        # Component.search([('root_bom_id', '=', self.id)]).unlink()

        # Initialize index based on existing branches
        existing_branches = Branch.search([('bom_id', '=', self.id)])
        existing_names = existing_branches.mapped('branch_name')
        max_idx = -1
        for name in existing_names:
            try:
                if name in codes:
                    max_idx = max(max_idx, codes.index(name))
            except ValueError:
                continue
        
        current_idx_ptr = max_idx + 1
        new_branches_to_mo = []

        # Use a dictionary to track which lines were processed for component cleanup
        processed_lines = set()

        def dfs(current_bom, parent_location_id, depth=0, parent_branch_id=None, root_line_id=None):
            nonlocal current_idx_ptr
            indent = "  " * depth

            lines = current_bom.bom_line_ids.sorted(key=lambda r: (r.sequence or 0, r.id))

            for line in lines:
                # Context for this path
                current_root_line_id = root_line_id
                if depth == 0:
                    current_root_line_id = line.id

                # Determine child BOM
                child_bom = line.child_bom_id
                if not child_bom and hasattr(self, '_get_first_created_bom'):
                     child_bom = self._get_first_created_bom(line.product_id)

                if child_bom:
                    # Ensure no stale Component record exists for this path
                    Component.search([
                        ('cr_bom_line_id', '=', line.id), 
                        ('root_bom_id', '=', self.id),
                        ('bom_line_branch_id', '=', parent_branch_id)
                    ]).unlink()

                    # Determine base location for this SO branch
                    # Point 4: Special Rule for SO BOM Hierarchy
                    # - Direct components (depth=0) get their own PN-specific locations.
                    # - Nested components (depth>0) get the Root Project Location.
                    child_loc = parent_location_id
                    if depth == 0:
                        if hasattr(self, '_get_so_child_bom_location'):
                             possible_loc = self._get_so_child_bom_location(child_bom)
                             if possible_loc:
                                 child_loc = possible_loc.id
                    else:
                        # Nested components → Use root BOM's project location
                        if self.cfe_project_location_id:
                            child_loc = self.cfe_project_location_id.id
                        elif parent_location_id:
                            child_loc = parent_location_id

                    # Check/Create Branch (context-aware via parent_branch_id)
                    branch = Branch.search([
                        ('bom_id', '=', self.id),
                        ('bom_line_id', '=', line.id),
                        ('parent_branch_id', '=', parent_branch_id)
                    ], limit=1)

                    if not branch:
                        if current_idx_ptr >= len(codes):
                            _logger.error("[SO BOM] No more branch codes available")
                            return

                        branch_code = codes[current_idx_ptr]
                        current_idx_ptr += 1

                        # Create branch sub-location
                        branch_loc = self.env['stock.location'].create({
                            'name': branch_code,
                            'location_id': child_loc,
                            'usage': 'internal',
                        })

                        # Create branch record
                        branch = Branch.create({
                            'bom_id': self.id,
                            'bom_line_id': line.id,
                            'branch_name': branch_code,
                            'sequence': current_idx_ptr,
                            'path_uid': uuid.uuid4().hex,
                            'location_id': branch_loc.id,
                            'parent_branch_id': parent_branch_id,
                            'root_line_id': current_root_line_id,
                        })
                        new_branches_to_mo.append(line.id)

                    # Track BOM usage in Root BOM (The new logic requested by user)
                    root_id_str = str(self.id)
                    current_ids = [i.strip() for i in (child_bom.used_in_root_bom_ids_str or '').split(',') if i.strip()]
                    
                    _logger.info(f"DEBUG SO BOM: Checking tracking for child BOM {child_bom.id} (under root {root_id_str}). Current strings: {current_ids}")
                    if root_id_str not in current_ids:
                        current_ids.append(root_id_str)
                        new_str = ",".join(current_ids)
                        child_bom.write({'used_in_root_bom_ids_str': new_str})
                        _logger.info(f"DEBUG SO BOM: WROTE new string '{new_str}' to child BOM {child_bom.id} ({child_bom.display_name})")
                    else:
                        _logger.info(f"DEBUG SO BOM: Root {root_id_str} is ALREADY tracked in child BOM {child_bom.id}")

                    # Create/Update assignment for this context
                    Assignment = self.env['mrp.bom.line.branch.assignment']
                    assign_vals = {
                        'root_bom_id': self.id,
                        'bom_id': current_bom.id,
                        'bom_line_id': line.id,
                        'branch_id': parent_branch_id,
                        'own_branch_id': branch.id,
                        'component_id': False,
                        'root_line_id': current_root_line_id,
                    }
                    assignment = Assignment.search([
                        ('root_bom_id', '=', self.id),
                        ('bom_line_id', '=', line.id),
                        ('branch_id', '=', parent_branch_id)
                    ], limit=1)
                    if assignment:
                        assignment.write(assign_vals)
                    else:
                        Assignment.create(assign_vals)

                    # Recurse into child BOM (using the SO-specific child_loc)
                    dfs(child_bom, child_loc, depth + 1, branch.id, current_root_line_id)
                else:
                    # Leaf line
                    # Ensure no stale Branch record exists for this path
                    Branch.search([
                        ('bom_line_id', '=', line.id), 
                        ('bom_id', '=', self.id),
                        ('parent_branch_id', '=', parent_branch_id)
                    ]).unlink()

                    existing_comp = Component.search([
                        ('root_bom_id', '=', self.id),
                        ('bom_id', '=', current_bom.id),
                        ('cr_bom_line_id', '=', line.id),
                        ('bom_line_branch_id', '=', parent_branch_id)
                    ], limit=1)

                    if not existing_comp:
                        # Determine location: if not direct, use parent branch workstation
                        comp_location = parent_location_id
                        if current_bom.id != self.id and parent_branch_id:
                            pb_rec = self.env['mrp.bom.line.branch'].browse(parent_branch_id)
                            if pb_rec.location_id:
                                comp_location = pb_rec.location_id.id

                        existing_comp = Component.create({
                            'root_bom_id': self.id,
                            'bom_id': current_bom.id,
                            'cr_bom_line_id': line.id,
                            'is_direct_component': (current_bom.id == self.id),
                            'location_id': comp_location,
                            'bom_line_branch_id': parent_branch_id,
                            'root_line_id': current_root_line_id,
                        })

                    # Create/Update assignment for this context
                    Assignment = self.env['mrp.bom.line.branch.assignment']
                    assign_vals = {
                        'root_bom_id': self.id,
                        'bom_id': current_bom.id,
                        'bom_line_id': line.id,
                        'branch_id': parent_branch_id,
                        'own_branch_id': False,
                        'component_id': existing_comp.id,
                        'root_line_id': current_root_line_id,
                    }
                    assignment = Assignment.search([
                        ('root_bom_id', '=', self.id),
                        ('bom_line_id', '=', line.id),
                        ('branch_id', '=', parent_branch_id)
                    ], limit=1)
                    if assignment:
                        assignment.write(assign_vals)
                    else:
                        Assignment.create(assign_vals)

        # Start DFS from Root: parent_location_id=False (not used for SO branches at top level), depth=0, pb=None, rl=None
        # Use root project location as the initial parent_location_id for the DFS
        root_proj_loc = self.cfe_project_location_id.id if self.cfe_project_location_id else False
        dfs(self, root_proj_loc, 0, None, None)

        _logger.info(
            "[SO BOM] Incremental recursive branch assignment complete for root BOM: %s",
            self.display_name
        )

        # Sync location info on any existing draft MOs to reflect new branches
        self._sync_so_bom_mo_locations()

        # Point 5: Auto-create MOs for newly added branches
        if new_branches_to_mo:
            self._create_so_bom_mos()

        return True

    def _sync_so_bom_mo_locations(self):
        """
        After branch (re)assignment for a root SO BOM, update all draft MOs
        so their branch_intermediate_location_id, branch_mapping_id and
        cr_final_location_id match the latest branch records.
        """
        self.ensure_one()
        Branch = self.env['mrp.bom.line.branch']

        for line in self.bom_line_ids:
            child_bom = line.child_bom_id
            if not child_bom:
                continue

            branch = Branch.search([
                ('bom_id', '=', self.id),
                ('bom_line_id', '=', line.id),
            ], order='sequence', limit=1)

            child_loc = self._get_so_child_bom_location(child_bom)

            # Point 4: Special location swap for direct components of SO root BOM
            # (root_bom is 'self' here)
            is_direct_so_root_component = self.is_so_root_bom and (self.product_id.name == self.product_id.default_code)
            
            if is_direct_so_root_component and child_loc:
                # cr_final_location_id -> root bom's project_location (parent of child_loc)
                # branch_intermediate_location_id -> its own bom's project_location (child_loc)
                final_loc_id = child_loc.location_id.id
                branch_loc_id = child_loc.id
            else:
                branch_loc_id = branch.location_id.id if branch and branch.location_id else (
                    child_loc.id if child_loc else False
                )
                final_loc_id = child_loc.id if child_loc else False

            if not branch_loc_id and not final_loc_id:
                continue

            draft_mos = self.env['mrp.production'].search([
                ('root_bom_id', '=', self.id),
                ('line', '=', str(line.id)),
                ('bom_id', '=', child_bom.id),
                ('state', '=', 'draft'),
            ])

            if draft_mos:
                update_vals = {}
                if branch_loc_id:
                    update_vals['branch_intermediate_location_id'] = branch_loc_id
                if final_loc_id:
                    update_vals['cr_final_location_id'] = final_loc_id
                if branch:
                    update_vals['branch_mapping_id'] = branch.id
                if update_vals:
                    draft_mos.write(update_vals)
                    _logger.info(
                        "[SO BOM] Synced %d draft MO(s) for line '%s' with new branch locations",
                        len(draft_mos), line.product_id.display_name
                    )


    # ─────────────────────────────────────────────────────────
    # MO creation for SO-created root BOMs
    # ─────────────────────────────────────────────────────────

    def action_create_child_mos_recursive(self, root_bom=None, parent_mo=None,
                                          index="0", level=0, parent_qty=1.0,
                                          parent_branch_location=None, parent_branch_id=None):
        """
        Override: if this is an SO BOM (at root level), delegate to SO-specific logic.
        Otherwise fall through to super().
        """
        if root_bom is None and self.is_so_root_bom:
            return self._create_so_bom_mos(root_bom=self)

        return super().action_create_child_mos_recursive(
            root_bom=root_bom,
            parent_mo=parent_mo,
            index=index,
            level=level,
            parent_qty=parent_qty,
            parent_branch_location=parent_branch_location,
            parent_branch_id=parent_branch_id,
        )

    def _create_so_bom_mos(self, root_bom=None, parent_mos=None, parent_branch_id=None):
        """
        Create MOs for an SO-created root BOM hierarchy recursively.
        - If self == root_bom: split qty N into N separate MOs (qty=1).
        - If self != root_bom: aggregate requirements of all parent_mos into ONE MO.
        - Links child MOs to parents via M2M parent_mo_ids.
        - Preserves branch mappings and locations at all levels.
        """
        self.ensure_one()
        root_bom = root_bom or self
        # Convert single parent_mo to recordset if needed for backward compatibility
        if parent_mos and not isinstance(parent_mos, models.AbstractModel):
             parent_mos = self.env['mrp.production'].browse(parent_mos.id if hasattr(parent_mos, 'id') else parent_mos)
        
        parent_mos = parent_mos or self.env['mrp.production']

        Branch = self.env['mrp.bom.line.branch']
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        stock_location = warehouse.lot_stock_id if warehouse else False
        all_created_mos_data = []

        _logger.info(
            "[SO BOM] Recursive MO creation for BOM: %s (Root: %s, Parents: %s)", 
            self.display_name, root_bom.display_name, parent_mos.mapped('name')
        )

        for line in self.bom_line_ids:
            child_bom = line.child_bom_id
            if not child_bom:
                continue

            # Skip BUY-selected lines
            if (line.product_id.manufacture_purchase in ('buy', 'buy_make') and
                    getattr(line, 'buy_make_selection', '') == 'buy'):
                continue

            # Get child BOM's location (final destination)
            child_loc = self._get_so_child_bom_location(child_bom)
            
            # Find branch mapping for this path (context-aware via root_bom + parent_branch_id)
            # For aggregated components, branch mapping might be one of the parents' mappings
            # or we take the first one.
            branch = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', line.id),
                ('parent_branch_id', '=', parent_branch_id)
            ], order='sequence', limit=1)

            # Determine locations
            is_at_root = (self.id == root_bom.id)
            
            if is_at_root and child_loc:
                final_loc_id = child_loc.location_id.id
                branch_loc_id = child_loc.id
            else:
                # SUB-COMPONENT (Aggregation)
                branch_loc_id = branch.location_id.id if branch and branch.location_id else (
                    child_loc.id if child_loc else stock_location.id if stock_location else False
                )
                # FIX: In sub-hierarchies, final destination is ALWAYS the parent MO's workstation
                # If multiple parents, take the first one or project root
                first_parent = parent_mos[:1]
                if first_parent and first_parent.branch_intermediate_location_id:
                    final_loc_id = first_parent.branch_intermediate_location_id.id
                else:
                    final_loc_id = child_loc.id if child_loc else (
                        stock_location.id if stock_location else False
                    )

            # Quantity and Splitting Logic: 
            # - If at Root BOM: split qty N into N separate MOs of qty 1.
            # - If NOT at Root BOM: create ONE MO for the aggregated qty.
            if is_at_root:
                total_mo_count = int(line.product_qty or 1)
                mo_qty_per_creation = 1.0
            else:
                total_mo_count = 1
                # Aggregated qty = sum of parent mo qties * line qty
                parent_total_qty = sum(parent_mos.mapped('product_qty')) or 1.0
                mo_qty_per_creation = parent_total_qty * line.product_qty

            _logger.info(
                "[SO BOM] Line %s: is_at_root=%s, total_mo_count=%s, mo_qty_per_creation=%s",
                line.product_id.display_name, is_at_root, total_mo_count, mo_qty_per_creation
            )

            child_bom_code = child_bom.code or child_bom.display_name

            # Check existing draft MOs for this path
            # For aggregated MOs, we search for MOs linked to ALL parents? 
            # Actually, just search for an MO for this line/root/parents combination.
            # Since we aggregate into ONE MO for non-root, we check if one exists.
            search_domain = [
                ('root_bom_id', '=', root_bom.id),
                ('line', '=', str(line.id)),
                ('bom_id', '=', child_bom.id),
                ('state', '=', 'draft'),
            ]
            if not is_at_root:
                # For non-root, it must link to at least one of these parents
                # In our case it should be linked to all, but search by first will suffice
                search_domain.append(('parent_mo_ids', 'in', parent_mos.ids))
            else:
                # For root, it has no parents
                search_domain.append(('parent_mo_ids', '=', False))

            existing_mos = self.env['mrp.production'].search(search_domain)
            existing_count = len(existing_mos)

            line_created_mos = self.env['mrp.production']

            # Handle existing MOs: sync locations/quantities
            if existing_mos:
                write_vals = {
                    'branch_intermediate_location_id': branch_loc_id,
                    'cr_final_location_id': final_loc_id,
                    'branch_mapping_id': branch.id if branch else False,
                }
                # For aggregated, sync quantity if parent total changed
                if not is_at_root and existing_mos[0].product_qty != mo_qty_per_creation:
                    write_vals['product_qty'] = mo_qty_per_creation
                
                existing_mos.write(write_vals)
                line_created_mos |= existing_mos

            # Create remaining MOs
            for i in range(existing_count + 1, total_mo_count + 1):
                part_suffix = str(i).zfill(2)
                if is_at_root:
                    part_number = f"{child_bom_code}.{part_suffix}"
                else:
                    part_number = f"{child_bom_code}"

                mo_vals = {
                    'product_id': child_bom.product_tmpl_id.product_variant_id.id,
                    'product_uom_id': child_bom.product_uom_id.id,
                    'product_qty': mo_qty_per_creation,
                    'bom_id': child_bom.id,
                    'root_bom_id': root_bom.id,
                    'parent_mo_ids': [(6, 0, parent_mos.ids)],
                    'parent_mo_id': parent_mos[0].id if parent_mos else False,
                    'line': line.id,
                    'cr_final_location_id': final_loc_id,
                    'branch_intermediate_location_id': branch_loc_id,
                    'branch_mapping_id': branch.id if branch else False,
                    'state': 'draft',
                    'part_number': part_number,
                }
                if root_bom.project_id:
                    mo_vals['project_id'] = root_bom.project_id.id

                mo = self.env['mrp.production'].with_context(
                    branch_intermediate_location=branch_loc_id,
                    branch_final_location=final_loc_id,
                    skip_component_moves=True,
                    force_skip_component_moves=True,
                ).create(mo_vals)
                line_created_mos |= mo

            # Collect results for summary
            for m in line_created_mos:
                all_created_mos_data.append({'name': m.name, 'product': m.product_id.display_name, 'qty': m.product_qty})

            # RECURSE: For each created MO (or the single aggregated one), recurse.
            # If we were at root, we now have multiple unit MOs.
            # If we were NOT at root, we have one aggregated MO.
            # To stick to the aggregation rule:
            # - If self == root_bom, each unit MO recurses separately (because they might have different branches).
            # - Wait, if sub-components are aggregated, then A1 and A2 should share X.
            # - So even at root, after creating [A1, A2], we should call recursion ONCE for child_bom with parents=[A1, A2].
            
            if is_at_root:
                # Call recursion ONCE with all unit MOs as parents for the next level
                child_bom._create_so_bom_mos(root_bom=root_bom, parent_mos=line_created_mos, parent_branch_id=branch.id if branch else False)
            else:
                # We are already aggregated. Recurse with our single aggregated MO.
                for m in line_created_mos:
                     child_bom._create_so_bom_mos(root_bom=root_bom, parent_mos=m, parent_branch_id=branch.id if branch else False)

        # Notify summary (only at the end of the top-level call)
        if self.id == root_bom.id and not parent_mos and all_created_mos_data:
            src_name = stock_location.display_name if stock_location else "WH/Stock"
            self.env['bus.bus']._sendone(
                self.env.user.partner_id,
                'simple_notification',
                {
                    'title': 'Manufacturing Orders Created',
                    'message': (
                        f"Created/Synced {len(all_created_mos_data)} MO records for {root_bom.display_name} hierarchy.\n"
                        f"Source: {src_name}"
                    ),
                    'sticky': False,
                    'type': 'info',
                }
            )

        return all_created_mos_data


    # ─────────────────────────────────────────────────────────
    # Partial branch-component reassignment for child BOM changes
    # ─────────────────────────────────────────────────────────

    def _reassign_branch_components_for_child_bom(self, child_bom):
        """
        Called on the ROOT SO BOM when a line is added or removed inside
        one of its child BOMs (e.g. EVR00288.01).

        Strategy:
        - Do NOT touch other branches (A stays A, B stays B, etc.)
        - Only delete + recreate the mrp.bom.line.branch.components records
          that belong to the branch corresponding to `child_bom`
        - The branch record itself (and its location) are untouched

        This correctly preserves the sequential branch code allocation.
        """
        self.ensure_one()

        # Find the root BOM line that points to this child BOM
        root_line = self.bom_line_ids.filtered(
            lambda l: l.child_bom_id and l.child_bom_id.id == child_bom.id
        )
        if not root_line:
            _logger.warning(
                "[SO BOM] No root BOM line found for child BOM %s in root BOM %s",
                child_bom.code, self.code
            )
            return

        # Find the existing branch record for that root line
        branch = self.env['mrp.bom.line.branch'].search([
            ('bom_id', '=', self.id),
            ('bom_line_id', 'in', root_line.ids),
        ], limit=1)

        if not branch:
            _logger.warning(
                "[SO BOM] No branch found for child BOM %s in root BOM %s — running full reassign",
                child_bom.code, self.code
            )
            self._assign_so_bom_branches()
            return

        _logger.info(
            "[SO BOM] Partial reassign: branch %s for child BOM %s",
            branch.branch_name, child_bom.code
        )

        # Delete only this branch's component records
        self.env['mrp.bom.line.branch.components'].search([
            ('root_bom_id', '=', self.id),
            ('bom_line_branch_id', '=', branch.id),
        ]).unlink()

        # ── Invalidate ORM cache so newly created lines are included ──
        child_bom.invalidate_recordset(['bom_line_ids'])

        # Recreate from current child BOM leaf lines (fresh DB read)
        Component = self.env['mrp.bom.line.branch.components']
        leaf_lines = self.env['mrp.bom.line'].search([
            ('bom_id', '=', child_bom.id),
            ('child_bom_id', '=', False),
        ])
        for leaf_line in leaf_lines:
            Component.create({
                'bom_line_branch_id': branch.id,
                'root_bom_id': self.id,
                'bom_id': child_bom.id,
                'cr_bom_line_id': leaf_line.id,
                'location_id': branch.location_id.id if branch.location_id else False,
                'is_direct_component': False,
            })

        _logger.info(
            "[SO BOM] Partial reassign done: %d components for branch %s",
            len(leaf_lines), branch.branch_name
        )
