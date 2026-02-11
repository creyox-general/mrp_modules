# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    is_evr = fields.Boolean(
        string='Is EVR',
        default=False,
        compute='_compute_is_evr_from_default_code',
        store=True,
        help="Indicates if this BOM is for EVR products"
    )
    cfe_project_location_id = fields.Many2one(
        "stock.location",
        string="Project location",
        domain=[('usage', '=', 'internal')],
        help="Destination location for Customer Furnished Equipment"
    )
    product_default_code = fields.Char(
        string='Internal Reference',
        related='product_tmpl_id.default_code',
        readonly=True
    )

    project_customer_id = fields.Many2one(
        'res.partner',
        string='Project Customer',
        related='project_id.partner_id',
        readonly=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to set is_evr based on product default_code"""
        for vals in vals_list:
            if 'product_tmpl_id' in vals or 'product_id' in vals:
                self._set_is_evr_from_product(vals)
        _logger.info("Created %d BOM records with EVR status", len(vals_list))
        return super().create(vals_list)

    def write(self, vals):
        """Override write to update is_evr when product changes"""
        if 'product_tmpl_id' in vals or 'product_id' in vals:
            self._set_is_evr_from_product(vals)
            _logger.info("Updated BOM records: %s with new product reference", self.ids)
        return super().write(vals)

    def _set_is_evr_from_product(self, vals):
        """Set is_evr based on product internal reference (case-insensitive)"""
        product = None

        if 'product_id' in vals and vals['product_id']:
            product = self.env['product.product'].browse(vals['product_id'])
        elif 'product_tmpl_id' in vals and vals['product_tmpl_id']:
            product_tmpl = self.env['product.template'].browse(vals['product_tmpl_id'])
            if product_tmpl.product_variant_count == 1:
                product = product_tmpl.product_variant_ids[0]

        if product and product.default_code:
            # Case-insensitive check
            vals['is_evr'] = product.default_code.upper().startswith('EVR')
            _logger.debug("Set is_evr=%s for product %s", vals['is_evr'], product.default_code)
        else:
            vals['is_evr'] = False

    @api.onchange('product_tmpl_id', 'product_id')
    def _onchange_product_set_is_evr(self):
        """Update is_evr when product is changed in the form"""
        product = self.product_id or (
            self.product_tmpl_id.product_variant_ids[0]
            if self.product_tmpl_id and self.product_tmpl_id.product_variant_count == 1
            else None
        )

        if product and product.default_code:
            self.is_evr = product.default_code.upper().startswith('EVR')
            _logger.debug("Onchange set is_evr=%s for BOM %s", self.is_evr, self.id)
        else:
            self.is_evr = False

    @api.depends('product_id.default_code', 'product_tmpl_id.default_code')
    def _compute_is_evr_from_default_code(self):
        """Reactive compute: update is_evr if default_code changes"""
        for bom in self:
            product = bom.product_id or (
                bom.product_tmpl_id.product_variant_ids[0]
                if bom.product_tmpl_id and bom.product_tmpl_id.product_variant_count == 1
                else None
            )
            old_is_evr = bom.is_evr
            bom.is_evr = bool(product and product.default_code and product.default_code.upper().startswith('EVR'))

            if old_is_evr != bom.is_evr:
                _logger.info("BOM %s is_evr changed from %s to %s due to product code change",
                             bom.id, old_is_evr, bom.is_evr)




