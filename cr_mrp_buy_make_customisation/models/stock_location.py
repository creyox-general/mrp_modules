# -*- coding: utf-8 -*-
from odoo import models, fields

class StockLocation(models.Model):
    _inherit = "stock.location"

    location_category = fields.Selection(
        selection_add=[("tapy", "TAPY Location")],
        ondelete={'tapy': 'set null'}
    )