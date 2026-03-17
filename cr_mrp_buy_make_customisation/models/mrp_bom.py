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
    _inherit = 'mrp.bom'


    def _should_treat_as_component(self, bom_line):
        """Check if BOM line should be treated as normal component despite having child BOM"""
        return (
                bom_line.child_bom_id and
                bom_line.product_id.manufacture_purchase in ('buy_make', 'buy') and
                (
                        bom_line.product_id.manufacture_purchase == 'buy' or
                        bom_line.buy_make_selection == 'buy'
                )
        )


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
        """Assign branch codes incrementally - treat BUY-selected lines as components"""
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        codes = _generate_branch_codes()

        # Get override from context if line was just changed
        changed_line_id = self.env.context.get('changed_line_id')
        new_buy_make_value = self.env.context.get('new_buy_make_value')

        for root_bom in self:
            if self.env.context.get('skip_branch_recompute'):
                continue

            # Root Guard: skip if root_bom is NOT itself in the set of roots
            # (A BOM that has its own cfe_project_location_id is always its own root,
            #  even if it is also used as a sub-BOM inside another root.)
            helpers = self.env['cr.mrp.bom.helpers']
            absolute_roots = helpers.get_root_boms_for_bom(root_bom)
            absolute_root_ids = [r.id for r in absolute_roots]
            if root_bom.id not in absolute_root_ids:
                _logger.info("BOM %s is not an absolute root, skipping branch assignment", root_bom.display_name)
                continue

            # Collect other roots that also contain this BOM, to cascade after own assignment
            other_roots = [r for r in absolute_roots if r.id != root_bom.id]

            # Ensure root_bom has cfe_project_location_id (for standard EVR) or sale_order_id (for SO)
            if not root_bom.cfe_project_location_id and not (hasattr(root_bom, 'sale_order_id') and root_bom.sale_order_id):
                continue

            # Store root location ID (default to False if no project location)
            root_location_id = root_bom.cfe_project_location_id.id if root_bom.cfe_project_location_id else False

            _logger.info(f"\n{'=' * 80}")
            _logger.info(f"Branch assignment (Incremental) for ROOT: {root_bom.display_name}")
            if changed_line_id and new_buy_make_value:
                _logger.info(f"Context override: Line {changed_line_id} = {new_buy_make_value}")
            _logger.info(f"{'=' * 80}\n")

            # Initialize index based on existing branches
            existing_branches = Branch.search([('bom_id', '=', root_bom.id)])
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

            # Clear old root assignments for this root BOM
            root_id_str = str(root_bom.id)
            sub_boms = self.env['mrp.bom'].search([('used_in_root_bom_ids_str', 'ilike', root_id_str)])
            _logger.info(f"DEBUG EVR (BUY/MAKE): Starting assignment for ROOT BOM: {root_bom.id}. Clearing old traces in {len(sub_boms)} sub-boms.")
            for sub_bom in sub_boms:
                if sub_bom.used_in_root_bom_ids_str:
                    ids = [i.strip() for i in sub_bom.used_in_root_bom_ids_str.split(',') if i.strip() and i.strip() != root_id_str]
                    sub_bom.used_in_root_bom_ids_str = ",".join(ids)

            def should_treat_as_component(line):
                """Check if line should be component (no branch creation)"""
                has_child = bool(line.child_bom_id)
                # Point 4: Check if other BOMs exist if this line has no child_bom_id
                if not has_child:
                    possible_bom = root_bom._get_first_created_bom(line.product_id)
                    if possible_bom:
                        has_child = True

                is_buy_make = line.product_id.manufacture_purchase == 'buy_make'
                is_buy_product = line.product_id.manufacture_purchase == 'buy'

                # Use context override if this is the changed line
                if changed_line_id and line.id == changed_line_id:
                    is_buy = (new_buy_make_value == 'buy')
                else:
                    is_buy = line.buy_make_selection == 'buy'

                # Component if: no child BOM OR (has child AND buy_make AND BUY selected) OR product is BUY type
                result = not has_child or (has_child and is_buy_make and is_buy) or is_buy_product

                return result

            def dfs(current_bom, parent_location_id, depth=0, parent_branch_id=None, root_line_id=None):
                nonlocal current_idx_ptr
                indent = "  " * depth

                lines = current_bom.bom_line_ids.sorted(key=lambda r: (r.sequence or 0, r.id))

                for line in lines:
                    # Context for this path
                    current_root_line_id = root_line_id
                    if depth == 0:
                        current_root_line_id = line.id

                    treat_as_comp = should_treat_as_component(line)
                    if treat_as_comp:
                        # Create component record if missing
                        is_direct = (current_bom.id == root_bom.id)

                        existing_comp = Component.search([
                            ('root_bom_id', '=', root_bom.id),
                            ('bom_id', '=', current_bom.id),
                            ('cr_bom_line_id', '=', line.id),
                            ('bom_line_branch_id', '=', parent_branch_id)
                        ], limit=1)

                        if not existing_comp:
                            comp_vals = {
                                'root_bom_id': root_bom.id,
                                'bom_id': current_bom.id,
                                'cr_bom_line_id': line.id,
                                'is_direct_component': is_direct,
                                'location_id': parent_location_id,
                                'bom_line_branch_id': parent_branch_id,
                                'root_line_id': current_root_line_id,
                            }

                            if parent_branch_id:
                                branch_rec = self.env['mrp.bom.line.branch'].browse(parent_branch_id)
                                if branch_rec.location_id:
                                    comp_vals['location_id'] = branch_rec.location_id.id

                            existing_comp = Component.create(comp_vals)

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

                        # STOP HERE - Do NOT process children for components
                        continue

                    # Has child BOM and NOT BUY - check/create branch
                    # Point 4: Use first created BOM
                    child_bom = line.child_bom_id or root_bom._get_first_created_bom(line.product_id)
                    
                    if child_bom:
                        branch = Branch.search([
                            ('bom_id', '=', root_bom.id),
                            ('bom_line_id', '=', line.id),
                            ('parent_branch_id', '=', parent_branch_id)
                        ], limit=1)

                        if not branch:
                            if current_idx_ptr >= len(codes):
                                raise UserError("No more branch codes available")

                            code = codes[current_idx_ptr]
                            current_idx_ptr += 1

                            # Create location for this branch
                            loc = self.env['stock.location'].create({
                                'name': code,
                                'location_id': parent_location_id,
                                'usage': 'internal',
                            })

                            # Create branch record
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
                        
                        _logger.info(f"DEBUG EVR (BUY/MAKE): Checking tracking for child BOM {child_bom.id} (under root {root_id_str}). Current strings: {current_ids}")
                        if root_id_str not in current_ids:
                            current_ids.append(root_id_str)
                            new_str = ",".join(current_ids)
                            child_bom.write({'used_in_root_bom_ids_str': new_str})
                            _logger.info(f"DEBUG EVR (BUY/MAKE): WROTE new string '{new_str}' to child BOM {child_bom.id} ({child_bom.display_name})")
                        else:
                            _logger.info(f"DEBUG EVR (BUY/MAKE): Root {root_id_str} is ALREADY tracked in child BOM {child_bom.id}")

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

                        # Recurse into child BOM
                        dfs(child_bom, parent_location_id, depth + 1, branch.id, current_root_line_id)

            # Start DFS from root
            dfs(root_bom, root_location_id, 0, None)

            # Point 5: Auto-create MOs for newly added branches
            if new_branches_to_mo:
                root_bom.action_create_child_mos_recursive()

        return True


    def action_create_child_mos_recursive(self, root_bom=None, parent_mo=None, index="0", level=0, parent_qty=1.0,
                                          parent_branch_location=None, parent_branch_id=None):
        """
        Create MOs ONLY for BOM lines that have a child BOM.
        Each MO will have:
        1. Components: WH/Stock → Virtual/Production
        2. Finished Product: Virtual/Production → Own Branch Location → Parent Branch Location
        """
        Branch = self.env['mrp.bom.line.branch']

        # Get created MOs list from context - IMPORTANT: get mutable reference
        created_mos_list = self.env.context.get('created_mos_list')
        if created_mos_list is None:
            created_mos_list = []

        if root_bom is None:
            root_bom = self
            if not hasattr(self.__class__, '_branch_assignment_cache'):
                self.__class__._branch_assignment_cache = {}

            cache_key = f"bom_{root_bom.id}"
            self.__class__._branch_assignment_cache[cache_key] = {
                'assignments': {},
                'seen_paths': []
            }

        created_mo = None
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        stock_location = warehouse.lot_stock_id if warehouse else False

        for line_idx, line in enumerate(self.bom_line_ids):

            if self._should_treat_as_component(line):
                continue

            if not line.child_bom_id:
                continue

            child_bom = line.child_bom_id
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

            # CHECK: Does MO already exist for this line in this specific branch context?
            existing_mo = self.env['mrp.production'].search([
                ('root_bom_id', '=', root_bom.id),
                ('line', '=', str(line.id)),
                ('bom_id', '=', child_bom.id),
                ('branch_mapping_id', '=', branch_rec.id if branch_rec else False),
                ('state', '=', 'draft')
            ], limit=1)

            if existing_mo:
                x = existing_mo.write({
                    'product_id': child_bom.product_tmpl_id.product_variant_id.id,
                    'product_uom_id': child_bom.product_uom_id.id,
                    'product_qty': child_qty,
                    'bom_id': child_bom.id,
                    'root_bom_id': root_bom.id,
                    'parent_mo_id': parent_mo.id if parent_mo else False,
                    'project_id': root_bom.project_id.id,
                    'line': line.id,
                    'cr_final_location_id':final_dest_location if final_dest_location else False,
                    'state': 'draft',
                    'branch_mapping_id': branch_rec.id if branch_rec else False,
                    'branch_intermediate_location_id': current_branch_location
                })


            if not existing_mo:
                mo_vals = {
                    'product_id': child_bom.product_tmpl_id.product_variant_id.id,
                    'product_uom_id': child_bom.product_uom_id.id,
                    'product_qty': child_qty,
                    'bom_id': child_bom.id,
                    'root_bom_id': root_bom.id,
                    'parent_mo_id': parent_mo.id if parent_mo else False,
                    'project_id': root_bom.project_id.id,
                    'line': line.id,
                    'cr_final_location_id':final_dest_location if final_dest_location else False,
                    'state': 'draft',
                    'branch_mapping_id': branch_rec.id if branch_rec else False,
                    'branch_intermediate_location_id': current_branch_location
                }

                mo = self.env['mrp.production'].with_context(
                    branch_intermediate_location=current_branch_location,
                    branch_final_location=final_dest_location,
                    skip_component_moves=True,
                    force_skip_component_moves=True,
                    created_mos_list=created_mos_list  # Pass the same list reference
                ).create(mo_vals)

                created_mo = mo

                if created_mo.root_bom_id.id != root_bom.id:
                    created_mo.root_bom_id = root_bom.id

                # Add created MO to list
                created_mos_list.append({
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

                # Pass the SAME list reference through context
                child_bom.with_context(created_mos_list=created_mos_list).action_create_child_mos_recursive(
                    root_bom=root_bom,
                    parent_mo=mo,
                    index=line_index,
                    level=level + 1,
                    parent_qty=child_qty,
                    parent_branch_location=current_branch_location,
                    parent_branch_id=branch_rec.id if branch_rec else False
                )

            else:

                # Pass the SAME list reference through context
                child_bom.with_context(created_mos_list=created_mos_list).action_create_child_mos_recursive(
                    root_bom=root_bom,
                    parent_mo=existing_mo,
                    index=line_index,
                    level=level + 1,
                    parent_qty=child_qty,
                    parent_branch_location=current_branch_location,
                    parent_branch_id=branch_rec.id if branch_rec else False
                )

        if level == 0 and root_bom == self:
            cache_key = f"bom_{root_bom.id}"
            if hasattr(self.__class__, '_branch_assignment_cache'):
                if cache_key in self.__class__._branch_assignment_cache:
                    del self.__class__._branch_assignment_cache[cache_key]


        # Return list at root level, single MO object for recursion
        if level == 0:
            # Always return as list format
            return created_mos_list

        # For recursive calls, return the single MO object
        return created_mo



    def action_verify_branch_assignment(self):
        """Debug action to verify branch assignment"""
        self.ensure_one()

        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']

        branches = Branch.search([('bom_id', '=', self.id)])
        components = Component.search([('root_bom_id', '=', self.id)])

        message = f"BOM: {self.display_name}\n\n"
        message += f"Branches ({len(branches)}):\n"
        for branch in branches:
            message += f"  - {branch.branch_name}: {branch.bom_line_id.product_id.display_name}\n"

        message += f"\nComponents ({len(components)}):\n"
        for comp in components:
            branch_name = comp.bom_line_branch_id.branch_name if comp.bom_line_branch_id else "ROOT"
            message += f"  - {comp.cr_bom_line_id.product_id.display_name} (branch: {branch_name}, direct: {comp.is_direct_component})\n"

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Branch Assignment Verification',
                'message': message,
                'type': 'info',
                'sticky': True,
            }
        }

    def _check_all_children_approved(self, line):
        """
        Override to handle BUY/MAKE selection:
        - If line has buy_make_selection = 'buy': Return True (no child MO needed)
        - If line has buy_make_selection = 'make': Check child BOMs normally
        """
        # If BUY selected, treat as component (always approved)
        if (line.product_id.manufacture_purchase == 'buy_make' and
                line.buy_make_selection == 'buy'):
            _logger.info(
                "BOM line %s has BUY selected, treating as approved component",
                line.id
            )
            return True

        # Normal flow
        return super(MrpBom, self)._check_all_children_approved(line)

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)

        for bom in boms:
            product = bom.product_tmpl_id
            categ = product.categ_id if product else False

            if not categ or not categ.demo_bom_id:
                continue

            demo_bom = categ.demo_bom_id

            # Avoid copying onto the demo BOM itself
            if bom.id == demo_bom.id:
                continue

            result = self._copy_operations_from_demo_bom(bom, demo_bom)

            if result:
                self._send_demo_bom_notification(bom, result)

        return boms

    def _copy_operations_from_demo_bom(self, target_bom, demo_bom):
        operations_copied = 0

        for operation in demo_bom.operation_ids:
            vals = {
                'name': operation.name,
                'workcenter_id': operation.workcenter_id.id,
                'bom_id': target_bom.id,
                'sequence': operation.sequence,
                'time_cycle_manual': operation.time_cycle_manual,
                'time_mode': operation.time_mode,
            }

            self.env['mrp.routing.workcenter'].create(vals)
            operations_copied += 1

        return {
            'bom': target_bom,
            'operations_copied': operations_copied,
            'demo_bom': demo_bom,
        }

    def _send_demo_bom_notification(self, bom, result):
        product = bom.product_tmpl_id
        product.message_post(
            body=(
                f"BOM '{bom.display_name}' created. "
                f"Copied {result['operations_copied']} operations "
                f"from demo BOM '{result['demo_bom'].display_name}'."
            ),
            subject="Demo BOM Operations Copied",
            message_type='notification',
        )


    def _get_branch_location_for_line(self, line, root_bom):
        """
        Get branch location for a BOM line.
        This ensures consistent location retrieval whether MO exists or not.
        """
        Branch = self.env['mrp.bom.line.branch']
        branches = Branch.search([
            ('bom_id', '=', root_bom.id),
            ('bom_line_id', '=', line.id)
        ], order='sequence', limit=1)

        if branches and branches.location_id:
            return branches.location_id.id, branches
        return None, None


    def _get_branch_location_for_line(self, line, root_bom):
        """
        Get branch location for a BOM line.
        This ensures consistent location retrieval whether MO exists or not.
        """
        Branch = self.env['mrp.bom.line.branch']
        branches = Branch.search([
            ('bom_id', '=', root_bom.id),
            ('bom_line_id', '=', line.id)
        ], order='sequence', limit=1)

        if branches and branches.location_id:
            return branches.location_id.id, branches
        return None, None


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

        product_variant = child_bom.product_tmpl_id.product_variant_id
        if product_variant.manufacture_purchase == 'buy':
            return

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
            branch_location_id, branches = self._get_branch_location_for_line(line, root_bom)

            if branch_location_id:
                current_branch_location = branch_location_id

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
                'cr_final_location_id': final_dest_location if final_dest_location else False,
                'branch_mapping_id': branches.id if branches else False,
                'state': 'draft',
            }

            _logger.info(
                f"Creating MO with root_bom_id={root_bom.id} ({root_bom.display_name}), bom_id={child_bom.id} ({child_bom.display_name})")

            current_mo = self.env['mrp.production'].with_context(
                branch_intermediate_location=current_branch_location,
                branch_final_location=final_dest_location,
                skip_component_moves=True
            ).create(mo_vals)

            if current_mo.root_bom_id.id != root_bom.id:
                current_mo.root_bom_id = root_bom.id

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
        else:
            _logger.info(f"MO already exists for line {line.id}: {existing_mo.name}")
            _logger.info(
                f"Existing MO has root_bom_id={existing_mo.root_bom_id.id if existing_mo.root_bom_id else 'None'}, expected={root_bom.id}")

            branch_location_id, branches = self._get_branch_location_for_line(line, root_bom)

            update_vals = {}

            if not existing_mo.root_bom_id or existing_mo.root_bom_id.id != root_bom.id:
                update_vals['root_bom_id'] = root_bom.id
                _logger.warning(
                    f"CORRECTING root_bom_id for MO {existing_mo.name} from {existing_mo.root_bom_id.id if existing_mo.root_bom_id else 'None'} to {root_bom.id}")

            if branches:
                if not existing_mo.branch_mapping_id or existing_mo.branch_mapping_id.id != branches.id:
                    update_vals['branch_mapping_id'] = branches.id
                    update_vals['branch_intermediate_location_id'] = branches.location_id.id
                    _logger.info(f"Updating branch_mapping_id for MO {existing_mo.name}")

            parent_mo_id = parent_mo.id if parent_mo else False
            if existing_mo.parent_mo_id.id if existing_mo.parent_mo_id else False != parent_mo_id:
                update_vals['parent_mo_id'] = parent_mo_id
                _logger.info(f"Updating parent_mo_id for MO {existing_mo.name}: {parent_mo_id}")

            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            if not existing_mo.cr_final_location_id or existing_mo.cr_final_location_id != final_dest_location:
                update_vals['cr_final_location_id'] = final_dest_location
                _logger.info(f"Updating cr_final_location_id for MO {existing_mo.name}: {final_dest_location}")

            if update_vals:
                existing_mo.write(update_vals)
                _logger.info(f"Updated existing MO {existing_mo.name} with: {update_vals}")

            if existing_mo.branch_mapping_id and existing_mo.branch_mapping_id.location_id:
                current_branch_location = existing_mo.branch_mapping_id.location_id.id
            elif branch_location_id:
                current_branch_location = branch_location_id
            elif hasattr(existing_mo, 'cr_final_location_id') and existing_mo.cr_final_location_id:
                current_branch_location = existing_mo.cr_final_location_id

        # Recursively check ALL child lines
        for child_line in child_bom.bom_line_ids:
            if child_line.child_bom_id:
                self._check_and_create_missing_mos(
                    child_line,
                    root_bom,
                    current_mo,
                    child_qty,
                    current_branch_location
                )



