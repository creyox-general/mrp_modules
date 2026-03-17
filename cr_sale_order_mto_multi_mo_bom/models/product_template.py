# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _set_evr_routes(self):
        """
        Override to prevent automatic assignment of MTO and Manufacture routes
        for EVR category products.
        MOs are now created manually — not triggered by stock rules on SO confirmation.
        """
        return
