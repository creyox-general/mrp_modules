# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    part_number = fields.Char(string='Part Number')
    parent_mo_ids = fields.Many2many(
        'mrp.production',
        'mrp_production_parent_rel',
        'child_id', 'parent_id',
        string='Parent MOs',
        copy=False,
    )

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        copy=False,
        index=True,
        help='The Sale Order this Manufacturing Order was generated from.',
    )

    mo_so_part_number = fields.Char(
        string='SO Part Number',
        copy=False,
        index=True,
        help=(
            'Sequential part number assigned when MOs are created from a Sale Order. '
            'Format: EVR00293.01.01, EVR00293.01.02, …'
        ),
    )

    # ─────────────────────────────────────────────────────────
    # Approve all sibling MOs when this one is approved
    # ─────────────────────────────────────────────────────────

    def write(self, vals):
        res = super().write(vals)

        # When branch_mapping_id-level "approve_to_manufacture" fires, approve siblings
        # We detect it via the branch_mapping_id write done on the branch record itself.
        # The actual trigger is when branch.approve_to_manufacture becomes True.
        return res

    # ─────────────────────────────────────────────────────────
    # Action: approve all MOs that share root_bom_id + bom_id + line
    # (same child BOM, same SO line)
    # ─────────────────────────────────────────────────────────

    def action_approve_all_so_part_mos(self):
        """
        When called on any MO in a SO part-number group, approve all sibling MOs
        (same root_bom_id + bom_id + line).
        """
        self.ensure_one()

        if not self.root_bom_id or not self.line:
            return

        sibling_mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', self.root_bom_id.id),
            ('bom_id', '=', self.bom_id.id),
            ('line', '=', self.line),
            ('state', '=', 'draft'),
        ])

        if not sibling_mos:
            return

        # Set approve_to_manufacture on all sibling branches
        for mo in sibling_mos:
            if mo.branch_mapping_id:
                try:
                    mo.branch_mapping_id.write({'approve_to_manufacture': True})
                    _logger.info(
                        "[SO BOM] Approved branch %s for MO %s (part: %s)",
                        mo.branch_mapping_id.branch_name,
                        mo.name,
                        mo.part_number,
                    )
                except Exception as e:
                    _logger.warning(
                        "[SO BOM] Could not approve branch for MO %s: %s", mo.name, e
                    )

        _logger.info(
            "[SO BOM] Approved %d sibling MOs for root BOM %s, line %s",
            len(sibling_mos), self.root_bom_id.code, self.line
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'All MOs Approved',
                'message': (
                    f"Approved {len(sibling_mos)} Manufacturing Order(s) "
                    f"for part group {self.part_number or self.bom_id.code}"
                ),
                'type': 'success',
                'sticky': False,
            },
        }