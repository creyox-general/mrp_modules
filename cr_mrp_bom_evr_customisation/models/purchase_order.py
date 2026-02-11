# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import fields, models

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    cfe = fields.Boolean(string="CFE")

    def button_confirm(self):
        res = super().button_confirm()

        for order in self:
            if order.cfe:
                vendor = order.partner_id

                # Pickings
                pickings = order.picking_ids


                pickings.write({"owner_id": vendor.id})

                # Move Lines (Detailed operations)
                move_lines = pickings.mapped("move_line_ids")


                move_lines.write({"owner_id": vendor.id})

        return res