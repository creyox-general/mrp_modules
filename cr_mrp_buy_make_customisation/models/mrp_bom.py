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


    # def _should_treat_as_component(self, bom_line):
    #     """Check if BOM line should be treated as normal component despite having child BOM"""
    #     return (bom_line.child_bom_id and
    #             bom_line.product_id.manufacture_purchase == 'buy_make' and
    #             bom_line.buy_make_selection == 'buy')

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


    def _assign_branches_for_bom(self):
        """Assign branch codes - treat BUY-selected lines as components"""
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        codes = _generate_branch_codes()

        # Get override from context if line was just changed
        changed_line_id = self.env.context.get('changed_line_id')
        new_buy_make_value = self.env.context.get('new_buy_make_value')

        for root_bom in self:
            if self.env.context.get('skip_branch_recompute'):
                continue

            if not root_bom.cfe_project_location_id:
                continue

            root_location_id = root_bom.cfe_project_location_id.id

            _logger.info(f"\n{'=' * 80}")
            _logger.info(f"Branch assignment for ROOT: {root_bom.display_name}")
            if changed_line_id and new_buy_make_value:
                _logger.info(f"Context override: Line {changed_line_id} = {new_buy_make_value}")
            _logger.info(f"{'=' * 80}\n")

            # Delete ALL old records
            Branch.search([('bom_id', '=', root_bom.id)]).unlink()
            Component.search([('root_bom_id', '=', root_bom.id)]).unlink()

            idx = 0

            def should_treat_as_component(line):
                """Check if line should be component (no branch creation)"""
                has_child = bool(line.child_bom_id)
                is_buy_make = line.product_id.manufacture_purchase == 'buy_make'
                is_buy_product = line.product_id.manufacture_purchase == 'buy'

                # Use context override if this is the changed line
                if changed_line_id and line.id == changed_line_id:
                    is_buy = (new_buy_make_value == 'buy')
                    _logger.info(f"        USING CONTEXT OVERRIDE: is_buy={is_buy}")
                else:
                    is_buy = line.buy_make_selection == 'buy'

                _logger.info(
                    f"        has_child={has_child}, is_buy_make={is_buy_make}, is_buy={is_buy}, is_buy_product={is_buy_product}")

                # Component if: no child BOM OR (has child AND buy_make AND BUY selected) OR product is BUY type
                result = not has_child or (has_child and is_buy_make and is_buy) or is_buy_product

                return result

            def dfs(current_bom, parent_location_id, depth=0, parent_branch_id=None):
                nonlocal idx
                indent = "  " * depth

                _logger.info(f"{indent}Processing BOM: {current_bom.display_name} at depth {depth}")

                lines = current_bom.bom_line_ids.sorted(key=lambda r: (r.sequence or 0, r.id))

                for line in lines:
                    _logger.info(f"{indent}  Line: {line.product_id.display_name}")
                    _logger.info(f"{indent}    Product manufacture_purchase: {line.product_id.manufacture_purchase}")
                    _logger.info(f"{indent}    Line buy_make_selection: {line.buy_make_selection}")

                    treat_as_comp = should_treat_as_component(line)
                    _logger.info(f"{indent}    treat_as_component = {treat_as_comp}")

                    if treat_as_comp:
                        # Create component record
                        is_direct = (current_bom.id == root_bom.id)

                        comp_vals = {
                            'root_bom_id': root_bom.id,
                            'bom_id': current_bom.id,
                            'cr_bom_line_id': line.id,
                            'is_direct_component': is_direct,
                            'location_id': parent_location_id,
                        }

                        if parent_branch_id:
                            comp_vals['bom_line_branch_id'] = parent_branch_id
                            comp_vals['location_id'] = self.env['mrp.bom.line.branch'].browse(
                                parent_branch_id).location_id.id

                        comp = Component.create(comp_vals)
                        _logger.info(f"{indent}    ✓ Created COMPONENT (id={comp.id}, direct={is_direct})")

                        # CRITICAL: STOP HERE - Do NOT process children
                        continue

                    # Has child BOM and NOT BUY - create branch
                    if idx >= len(codes):
                        raise UserError("No more branch codes available")

                    code = codes[idx]
                    idx += 1

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
                        'sequence': idx,
                        'path_uid': uuid.uuid4().hex,
                        'location_id': loc.id,
                    })

                    _logger.info(f"{indent}    ✓ Created BRANCH {code} (id={branch.id}, loc={loc.id})")

                    # Recurse into child BOM with this branch's location
                    if line.child_bom_id:
                        _logger.info(f"{indent}    Recursing into child BOM...")
                        dfs(line.child_bom_id, root_location_id, depth + 1, branch.id)

            # Start DFS from root
            dfs(root_bom, root_location_id, 0, None)

            # Log final counts
            final_branches = Branch.search_count([('bom_id', '=', root_bom.id)])
            final_components = Component.search_count([('root_bom_id', '=', root_bom.id)])

            _logger.info(f"\n{'=' * 80}")
            _logger.info(f"FINAL RESULTS for {root_bom.display_name}:")
            _logger.info(f"  Branches: {final_branches}")
            _logger.info(f"  Components: {final_components}")
            _logger.info(f"{'=' * 80}\n")

        return True

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
                existing_mo.branch_mapping_id = branch_rec.id

            # if existing_mo:
            #     _logger.info(f"MO {existing_mo.name} already exists for line {line.id}, skipping creation")
            #     # Just continue to next line, don't break
            #     continue

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
                }

                mo = self.env['mrp.production'].with_context(
                    branch_intermediate_location=current_branch_location,
                    branch_final_location=final_dest_location,
                    skip_component_moves=True,
                    created_mos_list=created_mos_list  # Pass the same list reference
                ).create(mo_vals)

                created_mo = mo

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
                    parent_branch_location=current_branch_location
                )

                # Don't recurse into child BOM if we're only creating for specific line
                # if not create_only_for_line:
                #     # Recurse: pass current branch location as parent for children
                #     child_bom.action_create_child_mos_recursive(
                #         root_bom=root_bom,
                #         parent_mo=mo,
                #         index=line_index,
                #         level=level + 1,
                #         parent_qty=child_qty,
                #         parent_branch_location=current_branch_location
                #     )
            else:

                # Pass the SAME list reference through context
                child_bom.with_context(created_mos_list=created_mos_list).action_create_child_mos_recursive(
                    root_bom=root_bom,
                    parent_mo=existing_mo,
                    index=line_index,
                    level=level + 1,
                    parent_qty=child_qty,
                    parent_branch_location=current_branch_location
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


