# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
import logging

from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    branch_mapping_id = fields.Many2one('mrp.bom.line.branch', string='Branch Mapping', help="Branch mapping for this MO (if set, finished goods will go to this branch location)")
    root_bom_id = fields.Many2one("mrp.bom", string="Root BOM", help="Top-level BOM where the chain started.")
    parent_mo_id = fields.Many2one("mrp.production", string="Parent Manufacturing Order")
    line = fields.Char(string='Line')
    branch_intermediate_location_id = fields.Many2one(
        'stock.location',
        string='Branch Intermediate Location',
        help='Intermediate branch location before moving to parent'
    )
    cr_final_location_id = fields.Many2one(
        'stock.location',
        string='Parent Location',
    )



    @api.model_create_multi
    def create(self, vals_list):
        # PART 1: Handle validation for EVR BOMs
        for vals in vals_list:
            if vals.get('bom_id'):
                bom = self.env['mrp.bom'].browse(vals['bom_id'])
                if bom.is_evr:
                    unapproved_lines = []

                    if bom.project_id:
                        vals['project_id'] = bom.project_id.id


        # PART 2: Create MOs with skip context to prevent component computation
        skip_moves = self.env.context.get('skip_component_moves')

        if skip_moves:
            mos = super(MrpProduction, self.with_context(skip_compute_move_raw_ids=True)).create(vals_list)
        else:
            mos = super().create(vals_list)

        return mos

    def action_confirm(self):
        """Override to compute moves when confirming"""
        # Force recompute of raw and finished moves for draft MOs without moves
        for mo in self:
            if mo.state == 'draft' and not mo.move_raw_ids:
                # Trigger computation of component moves
                mo._compute_move_raw_ids()

        # Call original confirmation
        res = super().action_confirm()

        return res

    def _generate_raw_moves(self):
        """Override to skip component moves on creation if context flag is set"""
        if self.env.context.get('skip_component_moves'):
            return self.env['stock.move']
        return super()._generate_raw_moves()



    @api.model
    def _prepare_procurement_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id,
                                    values):
        """Override to pass branch location context"""
        res = super()._prepare_procurement_values(product_id, product_qty, product_uom, location_id, name, origin,
                                                  company_id, values)

        if self.branch_intermediate_location_id:
            print('in _prepare_procurement_values')
            res['branch_intermediate_location'] = self.branch_intermediate_location_id.id

        return res


