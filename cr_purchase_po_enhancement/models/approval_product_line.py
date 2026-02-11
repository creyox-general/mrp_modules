# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields

class ApprovalProductLine(models.Model):
    _inherit = 'approval.product.line'

    cr_bom_line_id = fields.Integer(string='BOM Line ID')
    cr_component_id = fields.Integer(string='Component ID')
    cr_root_bom_id = fields.Integer(string='Root BOM ID')
    cr_vendor_id = fields.Integer(string='Vendor ID')