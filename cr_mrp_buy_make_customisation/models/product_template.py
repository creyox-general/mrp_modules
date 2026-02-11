from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    manufacture_purchase = fields.Selection([
        ('buy', 'BUY'),
        ('buy_make', 'BUY/MAKE'),
    ], string='Manufacture/Purchase', tracking=True)

    show_manufacture_purchase = fields.Boolean(
        compute='_compute_show_manufacture_purchase',
        store=False
    )

    @api.depends('categ_id', 'categ_id.mech')
    def _compute_show_manufacture_purchase(self):
        for record in self:
            record.show_manufacture_purchase = record.categ_id.mech

