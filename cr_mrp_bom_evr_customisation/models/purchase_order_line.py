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
    is_manufacturer_readonly = fields.Boolean(
        compute='_compute_is_manufacturer_readonly',
        string='Manufacturer Readonly'
    )

    @api.depends('component_customer_po_id', 'component_vendor_po_id', 'order_id.partner_id')
    def _compute_is_manufacturer_readonly(self):
        """
        Logic: Read-only if:
        1. Linked to a BoM component.
        2. Component has exactly 1 available manufacturer.
        3. The PO partner matches that manufacturer's partner.
        """
        for line in self:
            readonly = False
            # Check both possible links (customer vs vendor PO flow)
            comp = line.component_customer_po_id or line.component_vendor_po_id
            if comp:
                available = comp._get_available_manufacturers()
                if len(available) == 1:
                    manufacturer = available[0]
                    # Check if PO vendor matches the ONLY available manufacturer's company
                    if line.order_id.partner_id == manufacturer.manufacturer_id:
                        readonly = True
            line.is_manufacturer_readonly = readonly

    
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