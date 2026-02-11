# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api

class StockRule(models.Model):
    _inherit = 'stock.rule'

    @api.model
    def _run_buy(self, procurements):
        filtered_procurements = []

        for procurement, rule in procurements:
            product = procurement.product_id
            values = procurement.values

            bom_id = values.get("bom_id")
            bom_line_id = values.get("bom_line_id")
            related_mo_id = self.env["mrp.production"].browse(
                int(values.get("production_id"))
            ) if values.get("production_id") else False

            skip_procurement = False


            if bom_id and bom_line_id:
                bom_line = self.env["mrp.bom.line"].browse(int(bom_line_id))

                # ✅ Check if Vendor PO line exists for this BOM line and its PO is still in draft
                if bom_line.vendor_po_created:
                    vendor_po_line = self.env["purchase.order.line"].search([
                        ("bom_line_ids", "in", [bom_line.id]),
                        ("order_id.state", "=", "draft"),
                        ('bom_id', '=', bom_id),
                    ],order="id desc", limit=1)

                    if vendor_po_line:
                        vendor_po = vendor_po_line.order_id
                        skip_procurement = True
                    else:
                        print("   ⚠️ No draft Vendor PO found for this BOM line → procurement will continue")

            if skip_procurement:
                continue

            filtered_procurements.append((procurement, rule))

        # ✅ Only run buy rule for remaining procurements
        if filtered_procurements:
            return super()._run_buy(filtered_procurements)

        return True
