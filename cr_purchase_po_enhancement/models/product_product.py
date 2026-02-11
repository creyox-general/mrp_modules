# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models
from odoo.exceptions import UserError

class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_create_special_po_product(self):
        self.ensure_one()

        vendor = (self.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                  or self._select_seller())

        if not vendor:
            raise UserError(f"No vendor found for {self.display_name}")

        approval_category = self.env['approval.category'].search([
            ('name', '=', "Create RFQ's")
        ], limit=1)

        if not approval_category:
            raise UserError("Approval category 'Create RFQ's' not found")


        approval_request = self.env['approval.request'].create({
            'name': f"URGT PO Request - {self.display_name}",
            'category_id': approval_category.id,
            'request_owner_id': self.env.user.id,
        })

        self.env['approval.product.line'].create({
            'product_id': self.id,
            'quantity': 1.0,
            'seller_id': vendor.id,
            'approval_request_id':approval_request.id
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Approval Request',
            'res_model': 'approval.request',
            'res_id': approval_request.id,
            'view_mode': 'form',
            'target': 'current',
        }