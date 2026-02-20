# -*- coding: utf-8 -*-
from odoo import models, fields, api,_
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    critical = fields.Boolean(
        string='Critical',
        default=False,
        help='This component is critical'
    )
    mrp_bom_line_id = fields.Many2one('mrp.bom.line',string='BOM Line')


    @api.model
    def create(self, vals):
        move = super(StockMove, self.with_context(
            bypass_custom_internal_transfer_restrictions=True
        )).create(vals)

        if vals.get('picking_type_id'):
            picking_type = self.env['stock.picking.type'].browse(vals['picking_type_id'])
            if picking_type.code == 'internal' and picking_type.name == 'Pick Components' and vals.get('origin'):
                mo = self.env['mrp.production'].search([('name', '=', vals.get('origin'))], limit=1)
                if mo and mo.branch_intermediate_location_id:
                    move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                        'location_id': mo.branch_intermediate_location_id.id
                    })

            if picking_type.code == 'internal' and picking_type.name == 'Store Finished Product' and vals.get('origin'):
                mo = self.env['mrp.production'].search([('name', '=', vals.get('origin'))], limit=1)
                if mo and mo.cr_final_location_id:
                    move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                        'location_dest_id': mo.cr_final_location_id.id
                    })

        return move


    @api.constrains('product_uom_qty', 'location_id', 'product_id')
    def _check_stock_availability_internal(self):
        """Validate stock availability on save"""
        if self.picking_id.origin:
            return

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









