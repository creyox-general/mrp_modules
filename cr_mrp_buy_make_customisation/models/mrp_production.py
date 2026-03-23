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
                    if bom_line and getattr(bom_line[0], 'is_buy_make_product', False) and not getattr(bom_line[0], 'buy_make_selection', 'buy'):
                        raise UserError(
                            f"Please select BUY or MAKE option for product '{move.product_id.name}' "
                            f"in BOM before confirming the Manufacturing Order."
                        )

    def action_confirm(self):
        """Override to link raw stock moves to their branch/component records.
        The critical flag is then auto-computed from those links.
        """
        result = super(MrpProduction, self).action_confirm()

        for mo in self:
            # Use root_bom_id if set, otherwise fall back to the MO's own BOM
            effective_root = mo.root_bom_id or mo.bom_id
            if not effective_root:
                _logger.warning("MO %s has no BOM — skipping branch/component link assignment.", mo.name)
                continue

            _logger.info("Assigning branch/component links for MO %s (root BOM: %s)", mo.name, effective_root.display_name)

            for move in mo.move_raw_ids:
                # Match move product to a BOM line (search on both mo.bom_id and effective_root for safety)
                bom_line = (mo.bom_id.bom_line_ids | effective_root.bom_line_ids).filtered(
                    lambda l: l.product_id == move.product_id
                )
                if not bom_line:
                    _logger.info("  Move %s (product %s): no BOM line found — skipping", move.id, move.product_id.display_name)
                    continue
                bom_line = bom_line[0]

                # Priority 1: link to component record
                if self.branch_mapping_id:
                    comp_rec = self.env['mrp.bom.line.branch.components'].search([
                        ('root_bom_id', '=', effective_root.id),
                        ('cr_bom_line_id', '=', bom_line.id),
                        ('bom_line_branch_id','=',self.branch_mapping_id.id)
                    ], limit=1)

                    if comp_rec:
                        _logger.info(
                            "  Move %s → component %s (branch: %s)",
                            move.id, comp_rec.id,
                            comp_rec.bom_line_branch_id.branch_name if comp_rec.bom_line_branch_id else 'none'
                        )
                        move.write({
                            'mrp_bom_line_branch_component_id': comp_rec.id,
                            'mrp_bom_line_branch_id': comp_rec.bom_line_branch_id.id if comp_rec.bom_line_branch_id else False,
                        })
                    else:
                        # Priority 2: link to branch record
                        branch = self.env['mrp.bom.line.branch'].search([
                            ('bom_id', '=', effective_root.id),
                            ('bom_line_id', '=', bom_line.id),
                        ], limit=1)
                        if branch:
                            _logger.info("  Move %s → branch %s (%s)", move.id, branch.id, branch.branch_name)
                            move.write({
                                'mrp_bom_line_branch_id': branch.id,
                                'mrp_bom_line_branch_component_id': False,
                            })
                        else:
                            _logger.info(
                                "  Move %s (product %s): no component or branch found in root BOM %s",
                                move.id, move.product_id.display_name, effective_root.id
                            )
                else:
                    comp_rec = self.env['mrp.bom.line.branch.components'].search([
                        ('root_bom_id', '=', effective_root.id),
                        ('cr_bom_line_id', '=', bom_line.id),
                    ], limit=1)

                    if comp_rec:
                        _logger.info(
                            "  Move %s → component %s (branch: %s)",
                            move.id, comp_rec.id,
                            comp_rec.bom_line_branch_id.branch_name if comp_rec.bom_line_branch_id else 'none'
                        )
                        move.write({
                            'mrp_bom_line_branch_component_id': comp_rec.id,
                            'mrp_bom_line_branch_id': comp_rec.bom_line_branch_id.id if comp_rec.bom_line_branch_id else False,
                        })
                    else:
                        # Priority 2: link to branch record
                        branch = self.env['mrp.bom.line.branch'].search([
                            ('bom_id', '=', effective_root.id),
                            ('bom_line_id', '=', bom_line.id),
                        ], limit=1)
                        if branch:
                            _logger.info("  Move %s → branch %s (%s)", move.id, branch.id, branch.branch_name)
                            move.write({
                                'mrp_bom_line_branch_id': branch.id,
                                'mrp_bom_line_branch_component_id': False,
                            })
                        else:
                            _logger.info(
                                "  Move %s (product %s): no component or branch found in root BOM %s",
                                move.id, move.product_id.display_name, effective_root.id
                            )


        return result


    @api.depends('state', 'reservation_state', 'date_start', 'move_raw_ids', 'move_raw_ids.forecast_availability', 'move_raw_ids.forecast_expected_date', 'move_raw_ids.critical')
    def _compute_components_availability(self):
        # First call original logic
        res = super()._compute_components_availability()

        for production in self:
            # Check if any raw move is critical
            critical_move = production.move_raw_ids.filtered(lambda m: m.critical)

            if critical_move:
                production.components_availability = "Critical"

        return res










