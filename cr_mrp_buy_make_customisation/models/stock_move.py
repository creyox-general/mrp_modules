# -*- coding: utf-8 -*-
from odoo import models, fields, api


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
        move = super(StockMove, self).create(vals)

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

    def _action_done(self, cancel_backorder=False):
        res = super(StockMove, self)._action_done(cancel_backorder=cancel_backorder)

        for move in self:
            if move.raw_material_production_id and move.state == 'done' and move.quantity > 0:
                mo = move.raw_material_production_id
                if mo.branch_mapping_id:
                    component = self.env['mrp.bom.line.branch.components'].search([
                        ('bom_line_branch_id', '=', mo.branch_mapping_id.id),
                        ('cr_bom_line_id.product_id', '=', move.product_id.id)
                    ], limit=1)

                    if component:
                        # component.write({
                        #     'used': component.used + move.quantity
                        # })
                        component.write({
                            'used': move.quantity
                        })

        return res









