# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    bom_count = fields.Integer(
        string='BOMs',
        compute='_compute_bom_count',
        help='Number of BOMs linked to this Sale Order.',
    )

    def _compute_bom_count(self):
        for order in self:
            order.bom_count = self.env['mrp.bom'].search_count([
                ('sale_order_id', '=', order.id)
            ])

    so_confirmed_mo_count = fields.Integer(
        string='Confirmed MOs',
        compute='_compute_so_confirmed_mo_count',
    )

    @api.depends('bom_count')
    def _compute_so_confirmed_mo_count(self):
        for order in self:
            # Find root SO BOMs for this order
            root_boms = self.env['mrp.bom'].search([
                ('sale_order_id', '=', order.id),
                ('project_id', '=', False),
            ])
            if not root_boms:
                order.so_confirmed_mo_count = 0
                continue
            order.so_confirmed_mo_count = self.env['mrp.production'].search_count([
                ('root_bom_id', 'in', root_boms.ids),
                ('state', '!=', 'draft'),
            ])

    def action_view_so_confirmed_mos(self):
        self.ensure_one()
        root_boms = self.env['mrp.bom'].search([
            ('sale_order_id', '=', self.id),
            ('project_id', '=', False),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirmed Manufacturing Orders',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [
                ('root_bom_id', 'in', root_boms.ids),
                ('state', '!=', 'draft'),
            ],
        }

    # ─────────────────────────────────────────────
    # Smart Button Action
    # ─────────────────────────────────────────────
    def action_view_boms(self):
        """Open the parent EVR BOM directly from the Sale Order smart button."""
        self.ensure_one()
        so_digits = self._get_so_digits()
        evr_code = f"EVR{so_digits}"

        parent_bom = self.env['mrp.bom'].search([
            ('sale_order_id', '=', self.id),
            ('code', '=', evr_code),
        ], limit=1)

        if parent_bom:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.bom',
                'res_id': parent_bom.id,
                'view_mode': 'form',
                'name': evr_code,
                'target': 'current',
            }

        # Fallback: show all BOMs for this SO
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.bom',
            'domain': [('sale_order_id', '=', self.id)],
            'view_mode': 'list,form',
            'name': 'Bills of Materials',
            'target': 'current',
        }

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────
    def _get_so_digits(self):
        """
        Extract 5-digit numeric suffix from SO name.
        e.g. S00234 → '00234'  |  SO000234 → '00234' (last 5 digits)
        """
        so_number = self.name or ''
        if so_number.startswith('S'):
            numeric = so_number[1:]  # strip leading 'S'
        else:
            numeric = ''.join(filter(str.isdigit, so_number))
        return numeric.zfill(5)[-5:]

    # ─────────────────────────────────────────────
    # SO Confirmation → BOM Creation
    # ─────────────────────────────────────────────
    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            try:
                order._create_order_boms()
            except Exception as e:
                _logger.error(
                    "Failed to create BOMs for SO %s: %s", order.name, str(e)
                )
        return res

    def _create_order_boms(self):
        """
        Main logic for Sale Order -> recursive EVR BOM hierarchy.
        Performance: Use skip_branch_recompute=True during creation steps.
        """
        self.ensure_one()
        _logger.info("[BOM] Starting SO-BOM creation for SO %s", self.name)
        
        # ── 1. Preparation ────────────────────────────────────────────────
        so_digits = self._get_so_digits()
        evr_code = f"EVR{so_digits}"
        project_id = getattr(self, 'project_id', False)
        project_id = project_id.id if project_id else False

        # ── 2. Parent Product ─────────────────────────────────────────────
        _logger.info("[BOM] Creating parent EVR product: %s", evr_code)
        evr_category = self.env['product.category'].search(
            [('name', '=ilike', 'EVR')], limit=1
        )
        tmpl_vals = {
            'name': evr_code,
            'default_code': evr_code,
            'type': 'consu',
        }
        if evr_category:
            tmpl_vals['categ_id'] = evr_category.id
        parent_template = self.env['product.template'].create(tmpl_vals)
        parent_product = parent_template.product_variant_ids[:1]

        # ── 3. Parent BOM ────────────────────────────────────────────────
        parent_bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', parent_product.product_tmpl_id.id),
            ('sale_order_id', '=', self.id),
        ], limit=1)

        if not parent_bom:
            _logger.info("[BOM] Creating parent BOM: %s for SO %s", evr_code, self.name)
            parent_bom = self.env['mrp.bom'].with_context(skip_branch_recompute=True).create({
                'product_tmpl_id': parent_product.product_tmpl_id.id,
                'product_id': parent_product.id,
                'product_qty': 1.0,
                'type': 'normal',
                'code': evr_code,
                'sale_order_id': self.id,
                'project_id': project_id,
                'is_so_root_bom': True,
            })
        else:
            # Sync project and flag on existing parent BOM
            sync_vals = {}
            if project_id and parent_bom.project_id.id != project_id:
                sync_vals['project_id'] = project_id
            if not parent_bom.is_so_root_bom:
                sync_vals['is_so_root_bom'] = True
            
            if sync_vals:
                parent_bom.with_context(skip_branch_recompute=True).write(sync_vals)

        # ── 4. Child BOMs for each RE line ────────────────────────────────
        re_lines = self.order_line.filtered(
            lambda l: l.re_nre == 're' and l.product_id
        )

        for line in re_lines:
            # Fix product default_code if needed
            line._fix_evr_pending_default_code()

            everest_pn = line.everest_pn or line.product_id.default_code
            if not everest_pn:
                continue

            # Ensure child BOM exists
            child_bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                ('sale_order_id', '=', self.id),
            ], limit=1)

            if not child_bom:
                _logger.info("[BOM] Creating child BOM: %s", everest_pn)
                child_bom = self.env['mrp.bom'].with_context(skip_branch_recompute=True).create({
                    'product_tmpl_id': line.product_id.product_tmpl_id.id,
                    'product_id': line.product_id.id,
                    'product_qty': 1.0,
                    'type': 'normal',
                    'code': everest_pn,
                    'sale_order_id': self.id,
                    'project_id': project_id,
                })
            else:
                # Sync project and code if needed
                sync_vals = {}
                if project_id and child_bom.project_id.id != project_id:
                    sync_vals['project_id'] = project_id
                if child_bom.code != everest_pn:
                    sync_vals['code'] = everest_pn
                
                if sync_vals:
                    child_bom.with_context(skip_branch_recompute=True).write(sync_vals)

            # Link child BOM to the sale order line
            if not line.bom_id:
                line.bom_id = child_bom.id

            # Set location (suppress immediate recompute triggers within this method)
            child_bom.with_context(skip_branch_recompute=True)._set_so_child_bom_location()

            # Add line product as a component in the parent BOM (if not already)
            already_component = parent_bom.bom_line_ids.filtered(
                lambda bl: bl.product_id == line.product_id
            )
            if not already_component:
                _logger.info(
                    "[BOM] Adding component %s to parent BOM %s",
                    line.product_id.display_name, evr_code
                )
                self.env['mrp.bom.line'].with_context(skip_branch_recompute=True).create({
                    'bom_id': parent_bom.id,
                    'product_id': line.product_id.id,
                    'product_qty': line.product_uom_qty,
                })
            else:
                # Sync qty
                if already_component.product_qty != line.product_uom_qty:
                    already_component.with_context(skip_branch_recompute=True, skip_mo_qty_update=True).write({
                        'product_qty': line.product_uom_qty
                    })

        # ── 5. Final Finalization ──────────────────────────────────────────
        _logger.info("[BOM] Finalizing root BOM hierarchy for %s", parent_bom.code)
        try:
            # 5.1 Assign branches
            parent_bom._assign_so_bom_branches()
            
            # 5.2 Create MOs for the whole tree
            _logger.info("[SO BOM] Creating MOs for parent BOM %s", parent_bom.code)
            parent_bom._create_so_bom_mos()
            
        except Exception as e:
            _logger.exception(
                "[SO BOM] Error finalizing branches/MOs for BOM %s: %s",
                parent_bom.code, e
            )
        
        return parent_bom

    # ─────────────────────────────────────────────
    # Write: sync MO origin + project_id to BOMs
    # ─────────────────────────────────────────────
    def write(self, vals):
        res = super().write(vals)

        if 'name' in vals:
            for order in self:
                mos = self.env['mrp.production'].search([
                    ('procurement_group_id', '=', order.procurement_group_id.id)
                ])
                mos.write({'origin': order.name})

        # Sync project_id to all related BOMs (parent and children)
        if 'project_id' in vals:
            for order in self:
                # 1. Sync to parent BOM
                so_digits = order._get_so_digits()
                evr_code = f"EVR{so_digits}"
                parent_boms = self.env['mrp.bom'].search([
                    ('sale_order_id', '=', order.id),
                    ('code', '=', evr_code),
                ])
                if parent_boms:
                    parent_boms.write({'project_id': vals['project_id']})

                # 2. Sync to child BOMs (line-level)
                child_boms = order.order_line.filtered(
                    lambda l: l.bom_id
                ).mapped('bom_id')
                if child_boms:
                    _logger.info(
                        "[BOM Sync] Updating project_id on %d child BOMs for SO %s",
                        len(child_boms), order.name
                    )
                    child_boms.write({'project_id': vals['project_id']})

        return res