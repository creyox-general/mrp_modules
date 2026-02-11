# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models

class StockMove(models.Model):
    _inherit = "stock.move"

    def _prepare_procurement_values(self):
        values = super()._prepare_procurement_values()

        if self.bom_line_id and self.raw_material_production_id:
            values.update({
                "bom_id": self.raw_material_production_id.bom_id.id,
                "bom_line_id": self.bom_line_id.id,
                "production_id": self.raw_material_production_id.id
            })
        else:
            print("   ⚠️ No BOM info found → Skipping injection")

        return values
