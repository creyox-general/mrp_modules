# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    location_id_domain_ids = fields.Many2many(
        'stock.location',
        string='Available Locations',
        compute='_compute_location_id_domain_ids',
        store=False
    )

    @api.depends('move_ids_without_package.product_id', 'move_ids_without_package.product_uom_qty', 'picking_type_id')
    def _compute_location_id_domain_ids(self):
        """Compute available location IDs based on stock"""
        for picking in self:
            if picking.picking_type_id.code == 'internal' and picking.move_ids_without_package:
                move = picking.move_ids_without_package[0]

                if move.product_id:
                    required_qty = move.product_uom_qty or 0

                    quants = self.env['stock.quant'].search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id.usage', '=', 'internal'),
                    ])

                    location_stock = {}
                    for quant in quants:
                        available = quant.available_quantity
                        location = quant.location_id
                        if location not in location_stock:
                            location_stock[location] = 0
                        location_stock[location] += available

                    valid_location_ids = [
                        loc.id for loc, qty in location_stock.items()
                        if qty >= required_qty
                    ]

                    picking.location_id_domain_ids = self.env['stock.location'].browse(valid_location_ids)
                else:
                    picking.location_id_domain_ids = False
            else:
                picking.location_id_domain_ids = False

    @api.depends('picking_type_id', 'partner_id', 'move_ids_without_package', 'move_ids_without_package.location_id','move_ids_without_package.product_id', 'move_ids_without_package.product_uom_qty')
    def _compute_location_id(self):
        """Override to set location from move for internal transfers"""
        # if self.origin and self.origin.startswith('EVR Flow'):
        #     return

        if self.env.context.get('bypass_custom_internal_transfer_restrictions'):
            return

        for picking in self:
            if picking.origin:
                return
            if picking.picking_type_id.code != 'internal':
                return
            # For internal transfers with moves, use the move's location
            if picking.picking_type_id.code == 'internal' and picking.move_ids_without_package:
                first_move = picking.move_ids_without_package[0]
                if first_move.location_id:
                    picking.location_id = first_move.location_id
                    continue

            # Call super for other cases
            if picking.state in ('cancel', 'done') or picking.return_id:
                continue
            picking = picking.with_company(picking.company_id)

            if picking.picking_type_id:
                location_src = picking.picking_type_id.default_location_src_id
                if location_src.usage == 'supplier' and picking.partner_id:
                    location_src = picking.partner_id.property_stock_supplier
                location_dest = picking.picking_type_id.default_location_dest_id
                if location_dest.usage == 'customer' and picking.partner_id:
                    location_dest = picking.partner_id.property_stock_customer
                picking.location_id = location_src.id
                picking.location_dest_id = location_dest.id


    @api.constrains('move_ids_without_package')
    def _check_single_product_internal_transfer(self):
        """Constraint to ensure only one product in internal transfers"""
        # if self.origin and self.origin.startswith('EVR Flow'):
        #     return

        if self.env.context.get('bypass_custom_internal_transfer_restrictions'):
            return

        for picking in self:
            if picking.origin:
                return

            if picking.picking_type_id.code == 'internal':
                if len(picking.move_ids_without_package) > 1:
                    raise ValidationError(_(
                        'Please take into consideration that internal transfers require products that are located in the same source location.'
                    ))
