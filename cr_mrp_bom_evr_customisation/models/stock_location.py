# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import api, fields, models

class StockLocation(models.Model):
    _inherit = "stock.location"

    location_category = fields.Selection(
        [("free", "Free Location"), ("project", "Project Location")],
        string="Location Category",
    )

    @api.onchange("location_id")
    def _onchange_location_id(self):
        """Set default category from parent if empty."""
        if not self.location_category and self.location_id.location_category:
            self.location_category = self.location_id.location_category

    @api.model
    def create(self, vals):
        if not vals.get("location_category") and vals.get("location_id"):
            parent = self.browse(vals["location_id"])
            vals["location_category"] = parent.location_category
        return super().create(vals)

    def write(self, vals):
        res = super().write(vals)

        if 'location_category' in vals:
            # Recompute free_to_use for all branch components
            self.env['mrp.bom.line.branch.components'].search([])._compute_free_to_use()
            self.env['mrp.bom.line.branch'].search([])._compute_free_to_use()

        return res
