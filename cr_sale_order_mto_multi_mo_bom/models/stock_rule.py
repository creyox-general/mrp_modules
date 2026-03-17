# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _prepare_mo_vals(self, product_id, product_qty, product_uom, location_dest_id, name, origin, company_id, values,
                         bom):
        res = super(StockRule, self)._prepare_mo_vals(
            product_id, product_qty, product_uom, location_dest_id,
            name, origin, company_id, values, bom
        )
        if values.get('part_number'):
            res['part_number'] = values['part_number']
        return res