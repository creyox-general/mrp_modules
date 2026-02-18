# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models,fields

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    bom_line_ids = fields.Many2many('mrp.bom.line', string='BOM Line')
    bom_id = fields.Many2one(
        'mrp.bom',
        string="MRP BOM",
    )

    def _prepare_stock_moves(self, picking):
        moves = super()._prepare_stock_moves(picking)

        for move_vals in moves:
            # Check if PO has a CFE project location
            cfe_location = self.order_id.cfe_project_location_id
            if cfe_location:
                move_vals['location_dest_id'] = cfe_location.id

        return moves

