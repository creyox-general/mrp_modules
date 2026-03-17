from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    _inherit = 'product.category'

    mech = fields.Boolean(
        string='MECH',
        compute='_compute_mech',
        inverse='_inverse_mech',
        store=True,
        readonly=False,
        help='Enable Manufacture/Purchase option for products in this category'
    )

    demo_bom_id = fields.Many2one(
        'mrp.bom',
        string='Demo BOM',
        help='Template BOM whose operations will be copied to new products in this category'
    )

    is_mech_readonly = fields.Boolean(compute='_compute_is_mech_readonly')

    @api.depends('complete_name')
    def _compute_mech(self):
        for record in self:
            full_name = (record.complete_name or '').lower()
            if 'mechanical parts' in full_name:
                record.mech = True
            elif 'wiseboard' in full_name:
                record.mech = False
            # For non-locked categories: keep existing stored value (no assignment = no change)

    def _inverse_mech(self):
        # Allows manual edits for categories not matched by the compute rules
        pass

    @api.depends('complete_name')
    def _compute_is_mech_readonly(self):
        for record in self:
            name = (record.complete_name or '').lower()
            record.is_mech_readonly = 'wiseboard' in name or 'mechanical parts' in name

    def _register_hook(self):
        """Force recompute of mech for all existing categories on module install/upgrade."""
        super()._register_hook()
        try:
            all_cats = self.env['product.category'].search([])
            if all_cats:
                _logger.info(
                    "[ProductCategory] Triggering mech recompute for %d categories",
                    len(all_cats)
                )
                all_cats._compute_mech()
        except Exception as e:
            _logger.warning("[ProductCategory] Could not recompute mech: %s", e)