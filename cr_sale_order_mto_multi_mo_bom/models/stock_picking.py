# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockPickingSoBom(models.Model):
    _inherit = 'stock.picking'

    # ── helpers ──────────────────────────────────────────────────────────────

    def _is_so_bom_mo(self, mo):
        return bool(mo and mo.root_bom_id and mo.root_bom_id.sale_order_id)

    def _get_related_mo(self, origin):
        return self.env['mrp.production'].search([('name', '=', origin)], limit=1)

    # ── main override ─────────────────────────────────────────────────────────

    def button_validate(self):
        res = super().button_validate()

        for picking in self:
            if picking.picking_type_id.code != 'internal' or not picking.origin:
                continue

            mo = self._get_related_mo(picking.origin)
            if not mo:
                continue

            is_so = self._is_so_bom_mo(mo)
            is_direct_comp = mo.bom_id.sale_order_id

            if picking.picking_type_id.name == 'Pick Components':
                if is_so and is_direct_comp:
                    self._handle_so_pick_components(picking, mo)
                else:
                    self._handle_pick_components(picking, mo)

            elif picking.picking_type_id.name == 'Store Finished Product':
                if is_so and is_direct_comp:
                    self._handle_so_store_finished_product(picking, mo)
                else:
                    self._handle_store_finished_product(picking, mo)
                    self.reset_values(picking, mo)

        return res

    # ── Normal EVR BOM handlers (from cr_mrp_buy_make_customisation) ──────────

    def _handle_pick_components(self, picking, mo):
        ComponentModel = self.env['mrp.bom.line.branch.components']
        BranchModel = self.env['mrp.bom.line.branch']
        MrpModel = self.env['mrp.production']

        for move in picking.move_ids_without_package.filtered(
                lambda m: m.state == 'done' and m.quantity > 0
        ):
            component = ComponentModel.search([
                ('is_direct_component', '=', False),
                ('bom_line_branch_id', '=', mo.branch_mapping_id.id),
                ('cr_bom_line_id.product_id', '=', move.product_id.id),
                ('root_bom_id', '=', mo.root_bom_id.id),
            ], limit=1)

            if component:
                component.write({'used': move.quantity, 'transferred': 0, 'transferred_cfe': 0})
                self._update_child_mo_usage(mo, move, MrpModel)
                continue

            if mo.branch_intermediate_location_id:
                if mo.bom_id.id == mo.root_bom_id.id:
                    branches = BranchModel.search([
                        ('bom_id', '=', mo.root_bom_id.id),
                        ('used', '=', 0),
                    ])
                    matching_branch = branches.filtered(
                        lambda b: b.bom_line_id.product_id == move.product_id
                    )
                    if matching_branch:
                        matching_branch.write({'used': move.quantity, 'transferred': 0})
                else:
                    self._update_child_mo_usage(mo, move, MrpModel)

            if not mo.branch_mapping_id:
                component = ComponentModel.search([
                    ('is_direct_component', '=', True),
                    ('root_bom_id', '=', mo.root_bom_id.id),
                    ('cr_bom_line_id.product_id', '=', move.product_id.id),
                ], limit=1)
                if component:
                    component.write({'used': move.quantity, 'to_order': 0, 'to_order_cfe': 0,
                'ordered': 0, 'ordered_cfe': 0,
                'to_transfer': 0, 'to_transfer_cfe': 0,
                'transferred': 0, 'transferred_cfe': 0,})

    def _update_child_mo_usage(self, mo, move, MrpModel):
        child_mo = MrpModel.search([
            '|',
            ('parent_mo_id', '=', mo.id),
            ('parent_mo_ids', 'in', [mo.id])
        ], limit=1)
        if (
            child_mo
            and child_mo.branch_mapping_id
            and child_mo.branch_mapping_id.bom_line_id.product_id == move.product_id
        ):
            child_mo.branch_mapping_id.sudo().write({'transferred': 0, 'used': move.quantity})

    def _handle_store_finished_product(self, picking, mo):
        if not mo.branch_mapping_id:
            return
        for move in picking.move_ids_without_package.filtered(
                lambda m: m.state == 'done' and m.quantity > 0
        ):
            mo.branch_mapping_id.write({'transferred': move.quantity})
            mo.branch_mapping_id.mrp_bom_line_branch_component_ids.write({
                'to_order': 0, 'to_order_cfe': 0,
                'ordered': 0, 'ordered_cfe': 0,
                'to_transfer': 0, 'to_transfer_cfe': 0,
                'transferred': 0, 'transferred_cfe': 0,
            })

    def reset_values(self, picking, mo):
        if mo.bom_id and mo.root_bom_id and mo.bom_id.id == mo.root_bom_id.id:
            branches = self.env['mrp.bom.line.branch'].search([('bom_id', '=', mo.bom_id.id)])
            for branch in branches:
                branch.write({'transferred': 0, 'used': 0, 'approve_to_manufacture': False})
            components = self.env['mrp.bom.line.branch.components'].search([
                ('root_bom_id', '=', mo.root_bom_id.id)
            ])
            for component in components:
                component.write({'used': 0, 'transferred': 0, 'transferred_cfe': 0})

    # ── SO BOM handlers ───────────────────────────────────────────────────────

    def _handle_so_pick_components(self, picking, mo):
        """
        Per-MO (qty=1) logic:
          used      += 1
          transferred = max(0, transferred - 1)
          all other fields → 0
        """
        if not mo.branch_mapping_id:
            return
        ComponentModel = self.env['mrp.bom.line.branch.components']
        MrpModel = self.env['mrp.production']
        for move in picking.move_ids_without_package.filtered(
                lambda m: m.state == 'done' and m.quantity > 0
        ):
            comp = ComponentModel.search([
                ('is_direct_component', '=', False),
                ('bom_line_branch_id', '=', mo.branch_mapping_id.id),
                ('cr_bom_line_id.product_id', '=', move.product_id.id),
                ('root_bom_id', '=', mo.root_bom_id.id),
            ], limit=1)
            if comp:
                comp.write({
                    'used': (comp.used or 0) + move.quantity,
                    'transferred': 0,
                    'to_order': 0, 'to_order_cfe': 0,
                    'ordered': 0, 'ordered_cfe': 0,
                    'to_transfer': 0, 'to_transfer_cfe': 0,
                    'transferred_cfe': 0,
                })
            else:
                # Fallback: find child MO where current MO is listed as parent
                child_mo = MrpModel.search([
                    '|',
                    ('parent_mo_id', '=', mo.id),
                    ('parent_mo_ids', 'in', [mo.id])
                ], limit=1)
                if (
                    child_mo
                    and child_mo.branch_mapping_id
                    and child_mo.branch_mapping_id.bom_line_id.product_id == move.product_id
                ):
                    child_mo.branch_mapping_id.write({
                        'used': (child_mo.branch_mapping_id.used or 0) + move.quantity,
                        'transferred': 0,
                    })

    def _handle_so_store_finished_product(self, picking, mo):
        """
        Accumulate transferred on branch (no reset — other MOs still pending).
        """
        if not mo.branch_mapping_id:
            return
        for move in picking.move_ids_without_package.filtered(
                lambda m: m.state == 'done' and m.quantity > 0
        ):
            mo.branch_mapping_id.write({
                'transferred': (mo.branch_mapping_id.transferred or 0) + move.quantity,
            })

