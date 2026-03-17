# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models
import logging

_logger = logging.getLogger(__name__)


class MrpBomLineBranch(models.Model):
    _inherit = 'mrp.bom.line.branch'

    def action_toggle_approve_to_manufacture(self, approve):
        """
        Override for SO BOMs (qty > 1 creates multiple MOs per branch).

        When approve=True on a branch that belongs to a root SO BOM:
        - Find ALL draft MOs for (root_bom, line, branch_mapping_id)
          (there will be N of them when the SO line qty = N)
        - Confirm ALL of them in one go

        For non-SO BOMs, or when approve=False, delegate to super().
        """
        self.ensure_one()

        # When unapproving, always delegate to super()
        if not approve:
            return super().action_toggle_approve_to_manufacture(approve)

        root_bom_id = self.env.context.get('root_bom_id')
        line = self.env.context.get('line')

        if not root_bom_id:
            return super().action_toggle_approve_to_manufacture(approve)

        # Check if this branch belongs to a root SO BOM
        root_bom = self.env['mrp.bom'].browse(root_bom_id)
        if not root_bom.exists() or not root_bom.is_so_root_bom or self.bom_id != root_bom:
            # Normal EVR BOM or Nested Component → delegate entirely to super()
            return super().action_toggle_approve_to_manufacture(approve)

        # ── SO BOM path: may have multiple MOs per branch ──
        parent_mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom_id),
            ('line', '=', line),
            ('state', '=', 'draft'),
            ('branch_mapping_id', '=', self.id),
        ])

        if not parent_mos:
            _logger.warning(
                "[SO BOM Approve] No draft MOs found for root_bom=%s, line=%s, branch=%s",
                root_bom_id, line, self.branch_name
            )
            return {
                'success': False,
                'message': 'No Manufacturing Orders found for this branch.',
            }

        # Validate: all child MOs for every parent MO must be confirmed
        for parent_mo in parent_mos:
            child_mos = self.env['mrp.production'].search([
                ('state', '=', 'draft'),
                '|',
                ('parent_mo_id', '=', parent_mo.id),
                ('parent_mo_ids', 'in', [parent_mo.id]),
            ])
            if child_mos:
                return {
                    'success': False,
                    'message': (
                        f"Some child Manufacturing Orders for MO {parent_mo.name} "
                        f"are not approved yet."
                    ),
                }

        # ✅ All child MOs confirmed — approve and confirm all N parent MOs
        self.approve_to_manufacture = True
        confirmed_names = []

        for parent_mo in parent_mos:
            try:
                parent_mo.action_confirm()
                confirmed_names.append(parent_mo.name)
                _logger.info(
                    "[SO BOM Approve] Confirmed MO: %s (part: %s)",
                    parent_mo.name,
                    parent_mo.part_number or 'N/A'
                )
            except Exception as e:
                _logger.warning(
                    "[SO BOM Approve] Could not confirm MO %s: %s",
                    parent_mo.name, e
                )

        count = len(confirmed_names)
        return {
            'success': True,
            'message': (
                f"{count} Manufacturing Order(s) confirmed: "
                + ', '.join(confirmed_names)
            ),
        }
