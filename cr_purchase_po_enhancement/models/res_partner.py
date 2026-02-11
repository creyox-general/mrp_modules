# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields,api

class ResPartnerCategory(models.Model):
    _inherit = 'res.partner.category'

    website_vendor = fields.Boolean(string='Website Vendor', default=False)
    is_create_from_po = fields.Boolean(string='Is Create from PO?', default=False)

    @api.model
    def create(self, vals):
        """Set website_vendor to True when created from Purchase Order"""
        # Check if being created from purchase order context
        if self.env.context.get('from_purchase_order'):
            # vals['website_vendor'] = True
            vals['is_create_from_po'] = True

        return super(ResPartnerCategory, self).create(vals)

