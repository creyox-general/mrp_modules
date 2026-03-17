# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    bom_id = fields.Many2one(
        'mrp.bom',
        string='Bill of Materials',
        copy=False,
        help='Child BOM linked to this sale order line.',
    )

    # ─────────────────────────────────────────────
    # Create: auto-create child BOM if SO is confirmed
    # ─────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if (
                line.order_id.state in ('sale', 'done')
                and line.re_nre == 're'
                and line.product_id
            ):
                # Fix product default_code if it wasn't set correctly
                line._fix_evr_pending_default_code()
                # Create child BOM linked to this line (Performance: Skip recompute)
                child_bom = line.with_context(skip_branch_recompute=True)._create_child_bom()
                
                if child_bom:
                    # Set location (Performance: Skip recompute)
                    child_bom.with_context(skip_branch_recompute=True)._set_so_child_bom_location()
                    
                    # Finally, if parent BOM exists, re-sync branches/MOs once
                    order = line.order_id
                    parent_bom = line.env['mrp.bom'].search([
                        ('sale_order_id', '=', order.id),
                        ('is_so_root_bom', '=', True),
                    ], limit=1)
                    if parent_bom:
                        try:
                            _logger.info("[SO BOM] Updating branches/MOs for parent %s after line addition", parent_bom.code)
                            parent_bom._assign_so_bom_branches()
                            parent_bom._create_so_bom_mos()
                        except Exception as e:
                            _logger.exception("[SO BOM] Error updating parent %s: %s", parent_bom.code, e)
        return lines

    def _fix_evr_pending_default_code(self):
        """
        After line creation, ensure the product's default_code matches
        the line's everest_pn. Assigns everest_pn if default_code is
        different (handles PENDING placeholders, empty codes, or mismatches).
        """
        self.ensure_one()
        product = self.product_id
        template = product.product_tmpl_id
        everest_pn = self.everest_pn

        if not everest_pn:
            return

        current_code = template.default_code or ''
        if current_code != everest_pn:
            _logger.info(
                "[EVR] Updating default_code on product '%s': '%s' -> '%s'",
                template.name, current_code, everest_pn
            )
            template.default_code = everest_pn

    # ─────────────────────────────────────────────
    # Write: sync qty to related BOM
    # ─────────────────────────────────────────────
    def write(self, vals):
        res = super().write(vals)

        if 'product_uom_qty' in vals:
            for line in self:
                if line.bom_id:
                    _logger.info(
                        "[BOM Sync] Updating parent BOM component qty for %s to %s",
                        line.bom_id.code, line.product_uom_qty
                    )
                    # Only sync parent BOM component qty — do NOT change child BOM product_qty.
                    # Child BOM product_qty must stay 1.0 so the overview correctly multiplies:
                    # component_qty = bom_line_qty × (parent_needs / child_bom.product_qty)
                    #               = bom_line_qty × (N / 1) = N × bom_line_qty
                    line._sync_parent_bom_component_qty()
        return res

    # ─────────────────────────────────────────────
    # BOM Creation for a single line
    # ─────────────────────────────────────────────
    def _create_child_bom(self):
        """Create a child BOM for this RE line and add it as component in the parent BOM."""
        self.ensure_one()

        order = self.order_id
        so_digits = order._get_so_digits()
        evr_code = f"EVR{so_digits}"

        # Determine child BOM code
        everest_pn = (
            self.everest_pn
            or f"{evr_code}.{str(self.line_number).zfill(2)}"
        )

        # Check if child BOM already exists for this line
        if self.bom_id:
            return self.bom_id

        # Resolve project_id from the SO
        project_id = getattr(order, 'project_id', False)
        project_id = project_id.id if project_id else False

        _logger.info("[BOM] Creating child BOM: %s for line %s", everest_pn, self.id)
        child_bom = self.env['mrp.bom'].with_context(skip_branch_recompute=True).create({
            'product_tmpl_id': self.product_id.product_tmpl_id.id,
            'product_id': self.product_id.id,
            'product_qty': 1.0,  # Recipe makes 1 unit; component qty lives on parent BOM line
            'type': 'normal',
            'code': everest_pn,
            'sale_order_id': order.id,
            'project_id': project_id,
        })

        # Link child BOM to this line
        self.bom_id = child_bom.id

        # Find parent BOM and add this product as component
        parent_bom = self.env['mrp.bom'].search([
            ('sale_order_id', '=', order.id),
            ('code', '=', evr_code),
        ], limit=1)

        if parent_bom:
            # Add as component if not already present
            already_component = parent_bom.bom_line_ids.filtered(
                lambda bl: bl.product_id == self.product_id
            )
            if not already_component:
                _logger.info(
                    "[BOM] Adding component %s to parent BOM %s",
                    self.product_id.display_name, evr_code
                )
                self.env['mrp.bom.line'].with_context(skip_branch_recompute=True).create({
                    'bom_id': parent_bom.id,
                    'product_id': self.product_id.id,
                    'product_qty': self.product_uom_qty,
                })
        else:
            _logger.warning(
                "[BOM] No parent BOM found with code %s for SO %s",
                evr_code, order.name
            )

        return child_bom

    # ─────────────────────────────────────────────
    # Sync parent BOM component qty
    # ─────────────────────────────────────────────
    def _sync_parent_bom_component_qty(self):
        """When line qty changes, update the matching component qty in the parent BOM."""
        self.ensure_one()
        order = self.order_id
        so_digits = order._get_so_digits()
        evr_code = f"EVR{so_digits}"

        parent_bom = self.env['mrp.bom'].search([
            ('sale_order_id', '=', order.id),
            ('code', '=', evr_code),
        ], limit=1)

        if parent_bom:
            component_line = parent_bom.bom_line_ids.filtered(
                lambda bl: bl.product_id == self.product_id
            )
            if component_line:
                # Performance: Skip recompute triggers on BOM line write
                component_line.with_context(skip_branch_recompute=True, skip_mo_qty_update=True).write({
                    'product_qty': self.product_uom_qty
                })
