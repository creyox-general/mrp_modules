# -*- coding: utf-8 -*-
from odoo import models, api,fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.model
    def create(self, vals):
        """Override to set MO source and dest locations from EVR BOM."""

        if vals.get("bom_id"):
            bom = self.env["mrp.bom"].browse(vals["bom_id"])
            if bom.is_evr and bom.cfe_project_location_id:
                if not vals.get("branch_intermediate_location_id"):
                    vals["branch_intermediate_location_id"] = bom.cfe_project_location_id.id
                    vals["root_bom_id"] = bom.id

        record = super().create(vals)

        return record


    @api.constrains('state')
    def _check_buy_make_selection_before_confirm(self):
        """Prevent MO confirmation if buy_make products don't have selection"""
        for mo in self:
            if mo.state not in ['draft', 'cancel']:
                for move in mo.move_raw_ids:
                    bom_line = mo.bom_id.bom_line_ids.filtered(
                        lambda l: l.product_id == move.product_id
                    )
                    if bom_line and bom_line.is_buy_make_product and not bom_line.buy_make_selection:
                        raise UserError(
                            f"Please select BUY or MAKE option for product '{move.product_id.name}' "
                            f"in BOM before confirming the Manufacturing Order."
                        )

    def action_confirm(self):
        """Override to copy critical status from BOM lines to stock moves"""
        result = super(MrpProduction, self).action_confirm()

        for mo in self:
            if mo.bom_id:
                for move in mo.move_raw_ids:
                    # Find corresponding BOM line
                    bom_line = mo.bom_id.bom_line_ids.filtered(
                        lambda l: l.product_id == move.product_id
                    )
                    if bom_line:
                        move.critical = bom_line[0].critical

        return result


    @api.depends('state', 'reservation_state', 'date_start', 'move_raw_ids', 'move_raw_ids.forecast_availability', 'move_raw_ids.forecast_expected_date','move_raw_ids.critical')
    def _compute_components_availability(self):
        # First call original logic
        res = super()._compute_components_availability()

        for production in self:
            # Check if any raw move is critical
            critical_move = production.move_raw_ids.filtered(lambda m: m.critical)

            if critical_move:
                production.components_availability = "Critical"

        return res









