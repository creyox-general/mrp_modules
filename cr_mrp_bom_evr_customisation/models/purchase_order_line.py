# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import api, fields, models

class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    component_branch_id = fields.Many2one(
        'mrp.bom.line.branch.components',
        string='Component Branch',
        help='Branch component record for this PO line (EVR only)'
    )
    branch_id = fields.Many2one(
        'mrp.bom.line.branch',
        string='Branch',
        help='The specific branch this PO line belongs to'
    )
    
    # In Odoo 18, distribution_analytic_account_ids is computed.
    # We add an inverse to allow direct assignment in our flow.
    distribution_analytic_account_ids = fields.Many2many(
        'account.analytic.account',
        string='Analytic Accounts',
        compute='_compute_distribution_analytic_account_ids',
        inverse='_inverse_distribution_analytic_account_ids',
        search='_search_distribution_analytic_account_ids',
    )
    
    def _inverse_distribution_analytic_account_ids(self):
        for line in self:
            if line.distribution_analytic_account_ids:
                # Assign 100% distribution to the selected account(s)
                # If multiple accounts are selected, we split even (though our flow usually picks one)
                count = len(line.distribution_analytic_account_ids)
                percent = 100.0 / count if count > 0 else 0.0
                line.analytic_distribution = {str(acc.id): percent for acc in line.distribution_analytic_account_ids}
            else:
                line.analytic_distribution = False
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
        moves = super(PurchaseOrderLine, self.with_context(
            bypass_custom_internal_transfer_restrictions=True
        ))._prepare_stock_moves(picking)

        for move_vals in moves:
            # Use component_branch_id if set
            if self.component_branch_id and self.component_branch_id.location_id:
                branch_location = self.component_branch_id.location_id
                print('branch_location : ',branch_location,' name : ',branch_location.name)
                move_vals['location_dest_id'] = branch_location.id
                move_vals['location_final_id'] = branch_location.id

        return moves