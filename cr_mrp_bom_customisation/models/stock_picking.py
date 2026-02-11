# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # @api.model
    # def create(self, vals):
    #     """ Override to update location_dest_id for Receipts linked to EVR BOMs """
    #     picking = super().create(vals)
    #
    #     if picking.picking_type_id.code == 'incoming':
    #         print('yes...')# Receipt
    #         for move in picking.move_ids_without_package:
    #             bom = self.env['mrp.bom'].search(
    #                 [('product_tmpl_id', '=', move.product_id.product_tmpl_id.id)],
    #                 limit=1
    #             )
    #             if bom and bom.is_evr and bom.cfe_project_location_id:
    #                 # Update picking destination
    #                 picking.location_dest_id = bom.cfe_project_location_id.id
    #                 # Also update each stock move destination
    #                 move.location_dest_id = bom.cfe_project_location_id.id
    #         picking._compute_destination_location()  # ensure consistency
    #
    #     return picking
