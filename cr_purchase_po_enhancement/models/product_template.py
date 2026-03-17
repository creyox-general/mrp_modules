# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ProductTemplate(models.Model):
    _inherit = "product.template"

    def write(self, vals):
        res = super(ProductTemplate, self).write(vals)
        # If it's not a deletion or a large batch change that might be performance intensive,
        # ensure we check the single vendor logic.
        # This catch-all ensures "old" records get updated when saved.
        for record in self:
            if record.exists():
                self.env['product.supplierinfo']._check_and_set_main_vendor_for_record(record)
        return res
