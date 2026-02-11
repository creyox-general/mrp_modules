# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models,api


class StockRule(models.Model):
    _inherit = 'stock.rule'

    @api.model
    def _prepare_purchase_order_line(self, product_id, product_qty, product_uom, company_id, values, po):
        """Override to set destination to Free Location"""
        res = super(StockRule, self)._prepare_purchase_order_line(
            product_id, product_qty, product_uom, company_id, values, po
        )

        # Find location with 'free' category
        free_location = self.env['stock.location'].search([
            ('location_category', '=', 'free'),
            ('company_id', 'in', [False, company_id.id])
        ], limit=1)

        if free_location:
            res['location_dest_id'] = free_location.id
            print('yes....')

        return res


    def _make_po_get_domain(self, company_id, values, partner):
        domain = super(StockRule, self)._make_po_get_domain(company_id, values, partner)

        new_domain = []
        for item in domain:
            if not (isinstance(item, (list, tuple)) and len(item) == 3 and item[0] == 'dest_address_id'):
                new_domain.append(item)

        # Add draft filter + custom PO type filter
        new_domain.append(('state', '=', 'draft'))
        new_domain.append(('po_type', '=', 'min'))

        return tuple(new_domain)

    def _prepare_purchase_order(self, company_id, origins, values):
        res = super()._prepare_purchase_order(company_id, origins, values)

        res['po_type'] = 'min'

        return res