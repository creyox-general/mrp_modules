# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    product_default_code = fields.Char(
        string='Internal Reference',
        related='product_id.default_code',
        readonly=True,
        store=True
    )

    product_old_everest_pn = fields.Char(
        string='Old Everest PN',
        related='product_id.old_everest_pn',
        readonly=True,
        store=True
    )

