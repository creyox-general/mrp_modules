# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductCategory(models.Model):
    _inherit = 'product.category'

    mech = fields.Boolean(
        string='MECH',
        default=False,
        help='Enable Manufacture/Purchase option for products in this category'
    )

    demo_bom_id = fields.Many2one(
        'mrp.bom',
        string='Demo BOM',
        help='Template BOM whose operations will be copied to new products in this category'
    )