# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models

class StockWarehouseOrderpoint(models.Model):
    _inherit = 'stock.warehouse.orderpoint'

    def _get_procurement_group_values(self):
        values = super()._get_procurement_group_values()
        values['po_type_min'] = True
        return values

    def _prepare_procurement_values(self, date=False, group=False):
        values = super()._prepare_procurement_values(date, group)
        values['po_type_min'] = True
        return values