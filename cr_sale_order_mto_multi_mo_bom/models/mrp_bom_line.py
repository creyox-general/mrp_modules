# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    @api.constrains('product_id', 'bom_id')
    def _check_so_bom_consistency(self):
        """
        Validation: If the parent BOM belongs to an SO, any sub-BOMs added as
        components MUST belong to the same SO.
        """
        for line in self:
            parent_bom = line.bom_id
            if not parent_bom.sale_order_id:
                continue

            # Find the BOM for the product on this line
            # We search specifically for the first created BOM as per previous patterns
            child_bom = self.env['mrp.bom']._bom_find(line.product_id, bom_type='normal')[line.product_id]
            
            if child_bom and child_bom.sale_order_id:
                if child_bom.sale_order_id != parent_bom.sale_order_id:
                    raise ValidationError(_(
                        "All components added to a BOM must belong to the same Sales Order / Project "
                        "as the BOM itself.\n\n"
                        "Parent BOM: %s (SO: %s)\n"
                        "Component BOM: %s (SO: %s)"
                    ) % (
                        parent_bom.display_name, parent_bom.sale_order_id.name,
                        child_bom.display_name, child_bom.sale_order_id.name
                    ))

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers: identify SO BOM context
    # ─────────────────────────────────────────────────────────────────────────

    def _get_so_root_bom_for_line(self, bom_id=None):
        """
        Given a BOM (the bom this line belongs to), return the root SO BOM
        if there is one, or False.

        Two cases:
        A) The line's bom_id IS the root SO BOM (no project_id, has sale_order_id)
           → return bom_id itself
        B) The line's bom_id is a CHILD SO BOM (has sale_order_id AND project_id)
           → return the parent root BOM (the EVR root BOM whose line points to this child BOM)
        """
        bom = self.env['mrp.bom'].browse(bom_id) if bom_id else False
        if not bom:
            return False, None

        if not bom.sale_order_id:
            # This BOM has nothing to do with an SO
            return False, None

        if not bom.project_id:
            # Case A: This IS the root SO BOM
            return 'root', bom

        # Case B: This is a child SO BOM — find the root by looking for a BOM
        # that has a line pointing to this BOM as child_bom_id and has sale_order_id
        root_bom = self.env['mrp.bom'].search([
            ('sale_order_id', '=', bom.sale_order_id.id),
            ('project_id', '=', False),
        ], limit=1)

        if root_bom:
            return 'child', (root_bom, bom)

        return False, None

    # ─────────────────────────────────────────────────────────────────────────
    # Create override
    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        lines = super(MrpBomLine, self).create(vals_list)

        if self.env.context.get('skip_branch_recompute'):
            return lines

        # Group affected BOMs
        root_boms_to_reassign = set()      # full reassign needed
        child_bom_partial = {}             # {root_bom_id: child_bom}

        for line in lines:
            case, payload = self._get_so_root_bom_for_line(line.bom_id.id)
            if not case:
                continue

            if case == 'root':
                # Line added directly to root SO BOM → full reassign
                root_boms_to_reassign.add(payload.id)

            elif case == 'child':
                root_bom, child_bom = payload
                if root_bom.id in root_boms_to_reassign:
                    # Full reassign already scheduled, skip partial
                    continue
                # Partial: only reassign components for this child's branch
                child_bom_partial.setdefault(root_bom.id, set()).add(child_bom.id)

        # Execute full reassignments
        for root_bom_id in root_boms_to_reassign:
            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            try:
                _logger.info(
                    "[SO BOM Line Create] Full branch reassign for root BOM: %s",
                    root_bom.code
                )
                root_bom._assign_so_bom_branches()
            except Exception as e:
                _logger.exception(
                    "[SO BOM Line Create] Error reassigning branches for root BOM %s: %s",
                    root_bom.code, e
                )

        # Execute partial reassignments
        for root_bom_id, child_bom_ids in child_bom_partial.items():
            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            for child_bom_id in child_bom_ids:
                child_bom = self.env['mrp.bom'].browse(child_bom_id)
                try:
                    _logger.info(
                        "[SO BOM Line Create] Partial branch component reassign for "
                        "child BOM '%s' under root BOM '%s'",
                        child_bom.code, root_bom.code
                    )
                    root_bom._reassign_branch_components_for_child_bom(child_bom)
                except Exception as e:
                    _logger.exception(
                        "[SO BOM Line Create] Error reassigning branch components "
                        "for child BOM %s under root BOM %s: %s",
                        child_bom.code, root_bom.code, e
                    )

        return lines

    # ─────────────────────────────────────────────────────────────────────────
    # Unlink override
    # ─────────────────────────────────────────────────────────────────────────

    def unlink(self):
        # Collect affected BOMs BEFORE unlinking (records gone after)
        root_boms_to_reassign = set()
        child_bom_partial = {}

        if not self.env.context.get('skip_branch_recompute'):
            for line in self:
                case, payload = self._get_so_root_bom_for_line(line.bom_id.id)
                if not case:
                    continue

                if case == 'root':
                    root_boms_to_reassign.add(payload.id)

                elif case == 'child':
                    root_bom, child_bom = payload
                    if root_bom.id in root_boms_to_reassign:
                        continue
                    child_bom_partial.setdefault(root_bom.id, set()).add(child_bom.id)

        res = super(MrpBomLine, self).unlink()

        # Execute full reassignments
        for root_bom_id in root_boms_to_reassign:
            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            if not root_bom.exists():
                continue
            try:
                _logger.info(
                    "[SO BOM Line Unlink] Full branch reassign for root BOM: %s",
                    root_bom.code
                )
                root_bom._assign_so_bom_branches()
            except Exception as e:
                _logger.exception(
                    "[SO BOM Line Unlink] Error reassigning branches for root BOM %s: %s",
                    root_bom.code, e
                )

        # Execute partial reassignments
        for root_bom_id, child_bom_ids in child_bom_partial.items():
            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            if not root_bom.exists():
                continue
            for child_bom_id in child_bom_ids:
                child_bom = self.env['mrp.bom'].browse(child_bom_id)
                if not child_bom.exists():
                    continue
                try:
                    _logger.info(
                        "[SO BOM Line Unlink] Partial branch component reassign for "
                        "child BOM '%s' under root BOM '%s'",
                        child_bom.code, root_bom.code
                    )
                    root_bom._reassign_branch_components_for_child_bom(child_bom)
                except Exception as e:
                    _logger.exception(
                        "[SO BOM Line Unlink] Error reassigning branch components "
                        "for child BOM %s under root BOM %s: %s",
                        child_bom.code, root_bom.code, e
                    )

        return res

    # ─────────────────────────────────────────────────────────────────────────
    # Write override: sync MO count when qty changes on root SO BOM line
    # ─────────────────────────────────────────────────────────────────────────

    def write(self, vals):
        """
        When product_qty changes on a line that belongs to a ROOT SO BOM,
        add or remove corresponding draft MOs to match the new quantity.

        Increase qty 3→5: creates MOs .04 and .05
        Decrease qty 5→3: removes MOs .05 and .04 (highest part numbers first,
                           only draft MOs)
        """
        # Capture qty-before for affected root SO BOM lines
        qty_changes = {}   # {line_id: (old_qty, new_qty, root_bom)}

        if 'product_qty' in vals and not self.env.context.get('skip_branch_recompute'):
            for line in self:
                case, payload = self._get_so_root_bom_for_line(line.bom_id.id)
                if case != 'root':
                    continue
                # Only track lines that have a child BOM (those get MOs)
                if not line.child_bom_id:
                    continue
                qty_changes[line.id] = (line.product_qty, vals['product_qty'], payload)

        res = super().write(vals)

        # Apply branch/MO sync for changed lines
        for line_id, (old_qty, new_qty, root_bom) in qty_changes.items():
            if int(old_qty or 1) == int(new_qty or 1):
                continue
            
            try:
                _logger.info(
                    "[SO BOM Line Write] Syncing branches/MOs for root BOM %s due to qty change on line %d",
                    root_bom.code, line_id
                )
                # This will call _create_so_bom_mos() internally
                root_bom._assign_so_bom_branches()
            except Exception as e:
                _logger.exception(
                    "[SO BOM Line Write] Error syncing branches for root BOM %s: %s",
                    root_bom.code, e
                )

        return res
