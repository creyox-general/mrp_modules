# -*- coding: utf-8 -*-
from odoo import models, api,fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpProduction(models.Model):
    _inherit = 'mrp.production'


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

    def _check_descendant_approval(self, bom):
        """
        Override to skip BUY-selected lines in approval check
        """
        lines = self.env['mrp.bom.line'].search([
            ('bom_id', '=', bom.id),
        ])

        for line in lines:
            # Skip if BUY/MAKE product with BUY selected (treat as component)
            if (line.product_id.manufacture_purchase == 'buy_make' and
                    line.buy_make_selection == 'buy'):
                _logger.info(
                    "Skipping approval check for BOM line %s (BUY selected)",
                    line.id
                )
                continue

            # Skip lines that do NOT have child BOM
            if not line.child_bom_id:
                continue

            # If this line with child BOM is NOT approved → FAIL
            if not line.approve_to_manufacture:
                _logger.warning(
                    "BOM line %s not approved, blocking parent MO confirmation",
                    line.id
                )
                return False

            # If approved and has child BOM → go deeper
            if not self._check_descendant_approval(line.child_bom_id):
                return False

        return True

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









