# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    cfe_project_location_id = fields.Many2one(
        'stock.location',
        string='Project location',
        domain=[('usage', '=', 'internal')],
        help='Destination location for Customer Furnished Equipment'
    )
    production_id = fields.Many2one(
        'mrp.production',
        string="Manufacturing Order",
        help="Custom link between PO and MO"
    )
    bom_id = fields.Many2one(
        'mrp.bom',
        string="MRP BOM",
    )

    def _prepare_picking(self):
        """Override to set destination location from BOM if available."""
        res = super(PurchaseOrder, self.with_context(
            bypass_custom_internal_transfer_restrictions=True
        ))._prepare_picking()

        # Check if PO is linked to a BOM via mo_internal_ref
        if self.cfe_project_location_id:
            res["location_dest_id"] = self.cfe_project_location_id.id

        print('location destination : ', res["location_dest_id"])
        return res

    def _create_picking(self):
        """Override to ensure context is passed when creating picking"""
        return super(PurchaseOrder, self.with_context(
            bypass_custom_internal_transfer_restrictions=True
        ))._create_picking()



