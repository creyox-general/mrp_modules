# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api,fields
import logging

from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"


    approve_to_manufacture = fields.Boolean(
        string='Approve to Manufacture',
        default=False,
        help="If checked, MO will be created for this BOM line"
    )

    customer_ref = fields.Char(string='Customer ref')

    def write(self, vals):
        quantity_changed = 'product_qty' in vals

        res = super().write(vals)

        if quantity_changed and not self.env.context.get('skip_mo_qty_update'):
            for line in self:
                if line.bom_id.is_evr and line.child_bom_id:
                    self._update_child_mo_quantities(line, line.bom_id.id)


        return res

    def _update_child_mo_quantities(self, line, root_bom_id, parent_qty=1.0):
        """Recursively update MO quantities for this line and all its children"""
        # Find MOs for this line
        mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom_id),
            ('line', '=', line.id),
            ('state', '=', 'draft')
        ])

        for mo in mos:
            # Calculate new quantity
            new_qty = float(line.product_qty or 1.0) * parent_qty

            # Get locations from context or recalculate
            Branch = self.env['mrp.bom.line.branch']
            branches = Branch.search([
                ('bom_id', '=', root_bom_id),
                ('bom_line_id', '=', line.id)
            ], order='sequence', limit=1)

            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            stock_location = warehouse.lot_stock_id if warehouse else False

            current_branch_location = branches.location_id.id if branches and branches.location_id else False
            print('_update_child_mo_quantities :')
            parent_branch_location = mo.parent_mo_id.branch_intermediate_location_id.id if mo.parent_mo_id else False
            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # Update MO with all three locations - USE with_context to skip component recalculation
            mo.with_context(skip_compute_move_raw_ids=True).write({
                'product_qty': new_qty,
                'location_src_id': stock_location.id if stock_location else mo.location_src_id.id,
                'branch_intermediate_location_id': current_branch_location if current_branch_location else mo.branch_intermediate_location_id.id,
                'location_dest_id': final_dest_location if final_dest_location else mo.location_dest_id.id,
            })

            # Update child MOs recursively
            if line.child_bom_id:
                for child_line in line.child_bom_id.bom_line_ids:
                    if child_line.child_bom_id:
                        self._update_child_mo_quantities(child_line, root_bom_id, new_qty)

    def _collect_affected_root_boms(self):
        """
        For this recordset of bom.lines return a set of root BOMs that must be
        recalculated. Only returns BOMs that are EVR and have project location.
        """
        helpers = self.env['cr.mrp.bom.helpers']
        affected_roots = set()

        for line in self:
            # 1) roots for the containing BOM of this line
            if line.bom_id:
                roots = helpers.get_root_boms_for_bom(line.bom_id)
                for r in roots:
                    if r.is_evr and r.cfe_project_location_id:
                        affected_roots.add(r.id)

            # 2) if this line itself points to a child BOM, include roots for that child
            if line.child_bom_id:
                roots_child = helpers.get_root_boms_for_bom(line.child_bom_id)
                for r in roots_child:
                    if r.is_evr and r.cfe_project_location_id:
                        affected_roots.add(r.id)

        # return browse recordset of root BOMs
        return self.env['mrp.bom'].browse(list(affected_roots))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super(MrpBomLine, self.with_context(skip_branch_recompute=True)).create(vals_list)

        if not self.env.context.get('skip_branch_recompute'):
            roots = lines._collect_affected_root_boms()
            if roots:
                for root in roots:
                    try:
                        root._assign_branches_for_bom()
                    except Exception:
                        _logger.exception(f"Error assigning branches for root BOM {root.id} after create")

        return lines

    def unlink(self):
        roots = self._collect_affected_root_boms() if not self.env.context.get('skip_branch_recompute') else self.env[
            'mrp.bom']

        res = super(MrpBomLine, self.with_context(skip_branch_recompute=True)).unlink()

        if roots:
            for root in roots:
                try:
                    root._assign_branches_for_bom()
                except Exception:
                    _logger.exception(f"Error assigning branches for root BOM {root.id} after unlink")

        return res



    def _skip_bom_line(self, product, never_attribute_values=False):
        """Override to pass context when exploding child BOMs"""
        result = super()._skip_bom_line(product,never_attribute_values)

        if result and self.bom_id.is_evr:
            # Pass this line's ID in context for child BOM explosion
            return result.with_context(parent_bom_line_id=self.id)

        return result

    # def _get_branch_component_for_po(self, root_bom_id):
    #     """
    #     Find the correct branch component for this BOM line.
    #     Uses the same cache logic as the report to ensure consistency.
    #     """
    #     Component = self.env["mrp.bom.line.branch.components"]
    #
    #     # Check for child BOM - if it has one, it's not a component
    #     child_bom = self.env['mrp.bom']._bom_find(self.product_id, bom_type='normal')
    #     if child_bom:
    #         return False
    #
    #     parent_bom = self.bom_id
    #
    #     # ROOT LEVEL COMPONENT
    #     if not parent_bom.parent_id or parent_bom.id == root_bom_id:
    #         components = Component.search([
    #             ('root_bom_id', '=', root_bom_id),
    #             ('bom_id', '=', parent_bom.id),
    #             ('cr_bom_line_id', '=', self.id),
    #             ('is_direct_component', '=', True),
    #         ])
    #
    #         if not components:
    #             return False
    #
    #         if len(components) == 1:
    #             return components[0]
    #
    #         # Multiple components - return first one for PO creation
    #         return components[0]
    #
    #     # CHILD LEVEL COMPONENT
    #     components = Component.search([
    #         ('root_bom_id', '=', root_bom_id),
    #         ('bom_id', '=', parent_bom.id),
    #         ('cr_bom_line_id', '=', self.id),
    #         ('is_direct_component', '=', False),
    #     ], order='id')
    #
    #     if not components:
    #         return False
    #
    #     return components[0]


    def action_toggle_approve_to_manufacture(self, approve):
        self.ensure_one()
        root_bom = self.env.context.get('root_bom_id')

        if not approve:
            self.approve_to_manufacture = False
            return {
                "success": True,
                "message": "Approval removed."
            }

        if not root_bom:
            return {
                "success": False,
                "message": "Root BOM not found in context."
            }

        # Find Parent MO
        print('root_bom : ',root_bom)
        print('self.id : ', self.id)
        parent_mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom),
            ('line', '=', self.id),
            ('state', '=', 'draft')
        ])

        if not parent_mos:
            return {
                "success": False,
                "message": "No parent MO found for this BOM line."
            }

        for parent_mo in parent_mos:
            child_mos = self.env['mrp.production'].search([
                ('parent_mo_id', '=', parent_mo.id)
            ])

            # If no child MOs → allow confirm
            if not child_mos:
                if approve:
                    self.approve_to_manufacture = True
                    print('parent_mo : ',parent_mo)
                    parent_mo.action_confirm()
                    return {
                        "success": True,
                        "message": f"Parent MO {parent_mo.name} confirmed (no child MOs)."
                    }

            # Validate children approval
            not_ready = child_mos.filtered(lambda mo: mo.state == 'draft')

            if not_ready:
                return {
                    "success": False,
                    "message": "Some child Manufacturing Orders are not approved yet."
                }

            # ✅ All Approved
            if approve:
                self.approve_to_manufacture = True
                parent_mo.action_confirm()

                return {
                    "success": True,
                    "message": f"Parent MO {parent_mo.name} auto-confirmed."
                }

        return {
            "success": False,
            "message": "Unexpected condition reached."
        }