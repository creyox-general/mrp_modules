# -*- coding: utf-8 -*-
# Part of Creyox Technologies

from odoo import models, fields, api,_
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.onchange('product_id')
    def _onchange_product_id_custom(self):
        """Auto-select location with highest stock when product changes"""
        _logger.info("=== ONCHANGE PRODUCT TRIGGERED ===")
        _logger.info(f"Product: {self.product_id.name if self.product_id else 'None'}")
        _logger.info(f"Picking Type Code: {self.picking_id.picking_type_id.code if self.picking_id else 'None'}")

        if self.picking_id.picking_type_id.code == 'internal' and self.product_id:
            required_qty = self.product_uom_qty if self.product_uom_qty else 0
            max_qty, max_location = self._get_max_available_quantity(self.product_id)

            if max_qty > 0:
                self.location_id = max_location
                self.picking_id.location_id = max_location

                if required_qty > 0 and required_qty > max_qty:
                    return {
                        'warning': {
                            'title': _('Insufficient Stock'),
                            'message': _(
                                'Maximum available quantity is %.2f in location "%s". '
                                'Location has been set to the one with maximum stock.'
                            ) % (max_qty, max_location.complete_name)
                        }
                    }
            else:
                product_name = self.product_id.name
                self.product_id = False
                return {
                    'warning': {
                        'title': _('No Stock Available'),
                        'message': _(
                            'Product "%s" has no stock available in any internal location. '
                            'Please select a product with available stock.'
                        ) % product_name
                    }
                }

    @api.onchange('product_uom_qty')
    def _onchange_product_uom_qty_custom(self):
        """Auto-update location when quantity changes"""
        if self.picking_id.origin and self.picking_id.origin.startswith('EVR Flow'):
            return

        if self.env.context.get('bypass_custom_internal_transfer_restrictions'):
            return

        _logger.info("=== ONCHANGE QTY TRIGGERED ===")
        _logger.info(f"Product: {self.product_id.name if self.product_id else 'None'}")
        _logger.info(f"Qty: {self.product_uom_qty}")

        if self.picking_id.picking_type_id.code == 'internal' and self.product_id and self.product_uom_qty:
            # Get location with highest stock for new quantity
            location = self._get_location_with_highest_stock(self.product_id, self.product_uom_qty)
            _logger.info(f"Found location: {location.complete_name if location else 'None'}")

            if location:
                self.location_id = location
                # Trigger picking location_id recomputation
                self.picking_id._compute_location_id()
            else:
                # Get max available quantity across all locations
                max_qty, max_location = self._get_max_available_quantity(self.product_id)
                if max_qty > 0:
                    return {
                        'warning': {
                            'title': _('Insufficient Stock'),
                            'message': _(
                                'Maximum available quantity is %.2f in location "%s". '
                                'Please reduce the quantity.'
                            ) % (max_qty, max_location.complete_name if max_location else 'N/A')
                        }
                    }
                else:
                    return {
                        'warning': {
                            'title': _('No Stock Available'),
                            'message': _(
                                'No stock available for product "%s" in any location.'
                            ) % self.product_id.display_name
                        }
                    }

    @api.constrains('product_uom_qty', 'location_id', 'product_id')
    def _check_stock_availability_internal(self):
        """Validate stock availability on save"""
        if self.picking_id.origin and self.picking_id.origin.startswith('EVR Flow'):
            return

        if self.env.context.get('bypass_custom_internal_transfer_restrictions'):
            return

        for move in self:
            if move.picking_id.picking_type_id.code == 'internal' and move.product_id and move.product_uom_qty > 0:
                if not move.location_id:
                    max_qty, max_location = move._get_max_available_quantity(move.product_id)
                    if max_qty > 0:
                        raise ValidationError(_(
                            'Maximum available quantity is %.2f in location "%s". '
                            'Please select a valid location or reduce the quantity.'
                        ) % (max_qty, max_location.complete_name))
                    else:
                        raise ValidationError(_(
                            'No stock available for product "%s" in any location.'
                        ) % move.product_id.display_name)

                # Check if selected location has sufficient stock
                available_qty = move._get_available_quantity_in_location(
                    move.product_id, move.location_id
                )
                if available_qty < move.product_uom_qty:
                    max_qty, max_location = move._get_max_available_quantity(move.product_id)
                    raise ValidationError(_(
                        'Insufficient stock in location "%s". Available: %.2f, Required: %.2f.\n'
                        'Maximum available quantity is %.2f in location "%s".'
                    ) % (
                                              move.location_id.complete_name,
                                              available_qty,
                                              move.product_uom_qty,
                                              max_qty,
                                              max_location.complete_name if max_location else 'N/A'
                                          ))

    def _get_location_with_highest_stock(self, product, required_qty):
        """Get location with highest available stock that meets required quantity"""
        if not product:
            return False

        # Search for quants with available quantity >= required quantity
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
        ])

        _logger.info(f"Found {len(quants)} quants for product {product.name}")

        # Filter and find location with highest available quantity
        location_stock = {}
        for quant in quants:
            available = quant.available_quantity
            _logger.info(
                f"Location: {quant.location_id.complete_name}, Available: {available}, Required: {required_qty}")

            if available >= required_qty:
                location = quant.location_id
                if location not in location_stock:
                    location_stock[location] = 0
                location_stock[location] += available

        if location_stock:
            # Return location with highest stock
            best_location = max(location_stock, key=location_stock.get)
            _logger.info(f"Best location: {best_location.complete_name} with qty {location_stock[best_location]}")
            return best_location

        _logger.info("No suitable location found")
        return False

    def _get_max_available_quantity(self, product):
        """Get maximum available quantity and its location for a product"""
        if not product:
            return 0, False

        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
        ])

        location_stock = {}
        for quant in quants:
            available = quant.available_quantity
            if available > 0:
                location = quant.location_id
                if location not in location_stock:
                    location_stock[location] = 0
                location_stock[location] += available

        if location_stock:
            max_location = max(location_stock, key=location_stock.get)
            return location_stock[max_location], max_location

        return 0, False

    def _get_available_quantity_in_location(self, product, location):
        """Get available quantity for product in specific location"""
        if not product or not location:
            return 0

        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ])

        total_available = sum(quant.available_quantity for quant in quants)
        return total_available

    @api.onchange('product_id', 'product_uom_qty')
    def _onchange_location_domain(self):
        """Set domain for location_id to show only locations with sufficient stock"""
        if self.picking_id.origin and self.picking_id.origin.startswith('EVR Flow'):
            return

        if self.env.context.get('bypass_custom_internal_transfer_restrictions'):
            return

        res = {}
        if self.picking_id.picking_type_id.code == 'internal' and self.product_id:
            required_qty = self.product_uom_qty or 0

            # Get all quants for the product
            quants = self.env['stock.quant'].search([
                ('product_id', '=', self.product_id.id),
                ('location_id.usage', '=', 'internal'),
            ])

            # Calculate available quantity per location
            location_stock = {}
            for quant in quants:
                available = quant.available_quantity
                location = quant.location_id
                if location not in location_stock:
                    location_stock[location] = 0
                location_stock[location] += available

            # Filter locations with sufficient stock
            valid_location_ids = [
                loc.id for loc, qty in location_stock.items()
                if qty >= required_qty
            ]

            _logger.info(f"Valid locations for qty {required_qty}: {valid_location_ids}")

            if valid_location_ids:
                res['domain'] = {'location_id': [('id', 'in', valid_location_ids)]}
            else:
                res['domain'] = {'location_id': [('id', '=', False)]}

        return res


