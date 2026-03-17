# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, api, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    def create_special_po_approval(self, action_type, quantity, component_id, root_bom_id):
        """Create approval request for special PO"""
        self.ensure_one()

        vendor = (self.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1])
        _logger.info(f'vendor : {vendor}')

        # if not vendor:
        #     raise UserError(f"No vendor found for {self.product_id.display_name}")

        if not vendor:
            return {
                'error': True,
                'message': f"Main vendor is not set for {self.product_id.display_name}"
            }

        approval_category = self.env['approval.category'].search([
            ('name', '=', "Create RFQ's")
        ], limit=1)

        if not approval_category:
            raise UserError("Approval category 'Create RFQ's' not found")

        approval_request = self.env['approval.request'].create({
            'name': f"URGT PO Request - {self.product_id.display_name}",
            'category_id': approval_category.id,
            'request_owner_id': self.env.user.id,
        })

        # Create product line with custom fields
        self.env['approval.product.line'].create({
            'approval_request_id': approval_request.id,
            'product_id': self.product_id.id,
            'quantity': quantity,
            'cr_bom_line_id': self.id,
            'cr_component_id': component_id,
            'cr_root_bom_id': root_bom_id,
            'cr_vendor_id': vendor.partner_id.id,
        })

        return {
            'approval_id': approval_request.id,
        }

