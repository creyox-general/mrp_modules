# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import fields, models

class PurchaseOrder(models.Model):
    _inherit = "purchase.order.line"

    component_branch_id = fields.Many2one(
        'mrp.bom.line.branch.components',
        string='Component Branch',
        help='Branch component record for this PO line (EVR only)'
    )
    component_customer_po_id = fields.Many2one(
        'mrp.bom.line.branch.components',
        string='Component Customer PO',
        help='Link back to component for customer PO'
    )
    component_vendor_po_id = fields.Many2one(
        'mrp.bom.line.branch.components',
        string='Component Vendor PO',
        help='Link back to component for vendor PO'
    )


    def _prepare_stock_moves(self, picking):
        """Override to set branch location as destination for EVR components"""
        # Use context to bypass internal transfer restrictions for receipts
        moves = super(PurchaseOrder, self.with_context(
            bypass_custom_internal_transfer_restrictions=True
        ))._prepare_stock_moves(picking)

        for move_vals in moves:
            # Use component_branch_id if set
            if self.component_branch_id and self.component_branch_id.location_id:

                branch_location = self.component_branch_id.location_id
                move_vals['location_dest_id'] = branch_location.id
                move_vals['location_final_id'] = branch_location.id

        return moves