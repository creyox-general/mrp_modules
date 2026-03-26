# -*- coding: utf-8 -*-
# Part of Creyox Technologies.

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    default_vendor_processed = fields.Boolean(
        string="Default Vendor Processed", 
        default=False, 
        copy=False,
        help="Flag to ensure the 'No vendor' automation only runs once per product."
    )

    def write(self, vals):
        """
        Restrict product category change to Purchase Admins after initial assignment.
        """
        if 'categ_id' in vals:
            for rec in self:
                if rec.categ_id and rec.categ_id.id != vals['categ_id']:
                    if not self.env.user.has_group('purchase.group_purchase_manager'):
                        raise ValidationError(_("Only Purchase Admins can change the product category after it has been assigned."))
        return super(ProductTemplate, self).write(vals)

    @api.model
    def _cron_add_default_vendor(self):
        """
        Scheduled action to add a 'No vendor' record to products created 
        more than 1 hour ago that still have no vendors.
        """
        _logger.info("Starting 'No vendor' automation check...")
        
        # 1. Find or create the "No vendor" partner
        Partner = self.env['res.partner']
        no_vendor = Partner.search([('name', '=', 'No vendor')], limit=1)
        if not no_vendor:
            _logger.info("Creating 'No vendor' partner...")
            no_vendor = Partner.create({'name': 'No vendor'})

        # 2. Find eligible products
        one_hour_ago = datetime.now() - timedelta(hours=1)
        products = self.search([
            ('create_date', '<=', one_hour_ago),
            ('seller_ids', '=', False),
            ('default_vendor_processed', '=', False)
        ])
        
        if not products:
            _logger.info("No products found for 'No vendor' assignment.")
            return

        _logger.info("Automatically assigning 'No vendor' to %s products.", len(products))
        
        for product in products:
            try:
                # Add the vendor record
                self.env['product.supplierinfo'].create({
                    'partner_id': no_vendor.id,
                    'product_tmpl_id': product.id,
                    'delay': 1,
                    'min_qty': 0,
                    'price': 0.0,
                })
                # Mark as processed
                product.default_vendor_processed = True
            except Exception as e:
                _logger.error("Failed to assign 'No vendor' to product %s: %s", product.id, str(e))

        _logger.info("'No vendor' automation check completed.")
