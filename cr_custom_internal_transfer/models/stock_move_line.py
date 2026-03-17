# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.constrains('quantity', 'location_id', 'product_id')
    def _check_stock_availability_move_line(self):
        """Validate stock availability on move lines"""
        if self.env.context.get('bypass_custom_internal_transfer_restrictions'):
            return

        for line in self:
            if line.picking_id.picking_type_id.code == 'internal' and line.product_id and line.quantity > 0:
                # Check available quantity in location
                if line.picking_id.origin and line.picking_id.origin.startswith('EVR Flow'):
                    return

                quants = self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.location_id.id),
                ])

                total_available = sum(quant.available_quantity for quant in quants)

                if total_available < line.quantity:
                    # Get max available across all locations
                    all_quants = self.env['stock.quant'].search([
                        ('product_id', '=', line.product_id.id),
                        ('location_id.usage', '=', 'internal'),
                    ])

                    location_stock = {}
                    for quant in all_quants:
                        available = quant.available_quantity
                        if available > 0:
                            location = quant.location_id
                            if location not in location_stock:
                                location_stock[location] = 0
                            location_stock[location] += available

                    if location_stock:
                        max_location = max(location_stock, key=location_stock.get)
                        max_qty = location_stock[max_location]
                        raise ValidationError(_(
                            'Insufficient stock for product "%s" in location "%s".\n'
                            'Available: %.2f, Required: %.2f.\n'
                            'Maximum available quantity is %.2f in location "%s".'
                        ) % (
                                                  line.product_id.display_name,
                                                  line.location_id.complete_name,
                                                  total_available,
                                                  line.quantity,
                                                  max_qty,
                                                  max_location.complete_name
                                              ))
                    else:
                        raise ValidationError(_(
                            'No stock available for product "%s" in any location.'
                        ) % line.product_id.display_name)




