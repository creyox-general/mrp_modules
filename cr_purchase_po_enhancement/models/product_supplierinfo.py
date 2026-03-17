# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ProductSupplierInfo(models.Model):
    _inherit = "product.supplierinfo"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._check_and_set_main_vendor()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ['product_id', 'product_tmpl_id']):
            for record in self:
                record._check_and_set_main_vendor()
        return res

    def unlink(self):
        # Collect products before unlinking
        products = self.mapped('product_id')
        templates = self.mapped('product_tmpl_id')
        res = super().unlink()
        # After unlink, check if remaining vendors need to be marked as main
        for product in products:
            if product.exists():
                self._check_and_set_main_vendor_for_record(product)
        for template in templates:
            if template.exists():
                self._check_and_set_main_vendor_for_record(template)
        return res

    def _check_and_set_main_vendor(self):
        self.ensure_one()
        if self.product_id:
            self._check_and_set_main_vendor_for_record(self.product_id)
        elif self.product_tmpl_id:
            self._check_and_set_main_vendor_for_record(self.product_tmpl_id)

    @api.model
    def _check_and_set_main_vendor_for_record(self, record):
        """
        If exactly one vendor exists for the record, set it as main_vendor.
        """
        if not record or not record.exists():
            return
        sellers = record.seller_ids
        if len(sellers) == 1:
            if not sellers.main_vendor:
                sellers.write({'main_vendor': True})
