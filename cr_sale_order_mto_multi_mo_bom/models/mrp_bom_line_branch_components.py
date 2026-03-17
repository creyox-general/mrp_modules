# -*- coding: utf-8 -*-
from odoo import models, fields


class MrpBomLineBranchComponentsSoBom(models.Model):
    _inherit = 'mrp.bom.line.branch.components'

    # ── helpers ───────────────────────────────────────────────────────────────

    # def _is_so_bom(self):
    #     """True if component belongs to an SO-generated BOM hierarchy."""
    #     self.ensure_one()
    #     return bool(self.root_bom_id and self.root_bom_id.sale_order_id)

    def _is_so_root_bom(self):
        self.ensure_one()
        return bool(self.root_bom_id and self.root_bom_id.is_so_root_bom)

    # def _get_so_bom_ref(self):
    #     """
    #     For SO BOMs the root BOM has no project_id / cfe_project_location_id.
    #     Return self.bom_id (the child BOM) which does have those fields.
    #     Falls back to root_bom_id for normal EVR BOMs.
    #     """
    #     self.ensure_one()
    #     if self._is_so_bom():
    #         return self.bom_id
    #     return self.root_bom_id

    def _get_so_bom_customer(self):
        self.ensure_one()
        root_bom = self.root_bom_id
        if not (root_bom and root_bom.sale_order_id and not root_bom.project_id):
            return False
        child_bom = self.bom_id
        if child_bom and child_bom.project_id and child_bom.project_id.partner_id:
            return child_bom.project_id.partner_id
        return False

    # ── CFE flow ──────────────────────────────────────────────────────────────

    # def _process_cfe_flow(self):
    #     self.ensure_one()
    #
    #     if not self._is_so_root_bom():
    #         return super()._process_cfe_flow()
    #
    #     root_bom = self.root_bom_id
    #     so_customer = root_bom.project_id.partner_id if root_bom.project_id else False
    #     cfe_qty = float(self.cfe_quantity or 0)
    #     if cfe_qty <= 0:
    #         return
    #     if cfe_qty == self.used:
    #         return
    #
    #     transferred_cfe = self._calculate_transferred_cfe(so_customer)
    #     self.transferred_cfe = transferred_cfe
    #
    #     if self.transferred_cfe >= cfe_qty:
    #         self.transferred_cfe = cfe_qty
    #         self.to_transfer_cfe = 0
    #         self.ordered_cfe = 0
    #         self.to_order_cfe = 0
    #         self._adjust_cfe_po_quantity(so_customer, 0)
    #     else:
    #         to_transfer_cfe = self._calculate_to_transfer_cfe(so_customer, cfe_qty, transferred_cfe)
    #         self.to_transfer_cfe = to_transfer_cfe
    #         total = self.transferred_cfe + self.to_transfer_cfe
    #         if total < cfe_qty:
    #             needed = cfe_qty - total
    #             ordered_cfe = self._calculate_ordered_cfe(so_customer)
    #             ordered_cfe = min(needed, ordered_cfe)
    #             self.ordered_cfe = ordered_cfe
    #             to_order_cfe = cfe_qty - transferred_cfe - to_transfer_cfe - ordered_cfe
    #             self.to_order_cfe = max(0, to_order_cfe)
    #             if to_order_cfe > 0:
    #                 self._create_or_update_cfe_po(so_customer, to_order_cfe)
    #             else:
    #                 self._adjust_cfe_po_quantity(so_customer, to_order_cfe)
    #         else:
    #             self.ordered_cfe = 0
    #             self.to_order_cfe = 0
    #             self._adjust_cfe_po_quantity(so_customer, 0)

    # ── PO creation overrides ─────────────────────────────────────────────────

    # def _create_or_update_cfe_po(self, customer, quantity):
    #     """
    #     Override: for SO BOMs use child BOM's cfe_project_location_id and project_id
    #     instead of root BOM's (root SO BOM has neither by design).
    #     """
    #     if not self._is_so_root_bom():
    #         return super()._create_or_update_cfe_po(customer, quantity)
    #
    #     # ref_bom = self._get_so_bom_ref()   # child BOM
    #     POLine = self.env['purchase.order.line']
    #     PO = self.env['purchase.order']
    #
    #     existing_line = POLine.search([
    #         ('component_branch_id', '=', self.id),
    #         ('order_id.partner_id', '=', customer.id),
    #         ('order_id.state', '=', 'draft'),
    #         ('bom_id', '=', self.root_bom_id.id),
    #     ], limit=1)
    #
    #     if existing_line:
    #         existing_line.order_id.po_type = 'mrp'
    #         if existing_line.product_qty != quantity:
    #             existing_line.product_qty = quantity
    #             self.customer_po_ids = [(4, existing_line.id)]
    #
    #             self._send_notification(
    #                 'Purchase Order Updated (CFE)',
    #                 f'Updated Qty to {existing_line.product_qty} for {existing_line.order_id.name}',
    #                 'success'
    #             )
    #
    #         # self._send_notification(
    #         #     'Purchase Order Updated (CFE)',
    #         #     f'Updated Qty to {existing_line.product_qty} for {existing_line.order_id.name}',
    #         #     'success'
    #         # )
    #     else:
    #         po = PO.search([
    #             ('partner_id', '=', customer.id),
    #             ('state', '=', 'draft'),
    #             ('bom_id', '=', self.root_bom_id.id),
    #             ('po_type', '=', 'mrp'),
    #             ('cfe', '=', True),
    #         ], limit=1)
    #
    #         if not po:
    #             location = self.root_bom_id.cfe_project_location_id
    #             if location:
    #                 curr = location
    #                 while curr.location_id:
    #                     if curr.location_id.name == 'Project Location':
    #                         location = curr
    #                         break
    #                     curr = curr.location_id
    #
    #             po = PO.create({
    #                 'partner_id': customer.id,
    #                 'bom_id': self.root_bom_id.id,
    #                 'origin': f'EVR Flow - {self.root_bom_id.display_name}',
    #                 'cfe_project_location_id': location.id if location else False,
    #                 'state': 'draft',
    #                 'po_type': 'mrp',
    #                 'cfe': True,
    #             })
    #
    #         analytic_account = self.root_bom_id.project_id.account_id
    #
    #         po_line = POLine.create({
    #             'order_id': po.id,
    #             'product_id': self.cr_bom_line_id.product_id.id,
    #             'product_qty': quantity,
    #             'product_uom': self.cr_bom_line_id.product_id.uom_po_id.id,
    #             'price_unit': 0.0,
    #             'date_planned': fields.Datetime.now(),
    #             'component_branch_id': self.id,
    #             'branch_id': self.bom_line_branch_id.id,
    #             'distribution_analytic_account_ids': [(6, 0, [analytic_account.id])] if analytic_account else False,
    #             'bom_line_ids': [(6, 0, [self.cr_bom_line_id.id])],
    #             'bom_id': self.root_bom_id.id,
    #             'project_id': self.root_bom_id.project_id.id,             # child BOM's project
    #         })
    #         self.customer_po_ids = [(4, po_line.id)]
    #         po_line.order_id.po_type = 'mrp'
    #         self._send_notification(
    #             'Purchase Order Created',
    #             f'Created PO {po_line.order_id.name} for {self.cr_bom_line_id.product_id.display_name} ({quantity})',
    #             'success'
    #         )

    # def _create_or_update_po(self, quantity):
    #     """
    #     Override: for SO BOMs use child BOM's cfe_project_location_id and project_id
    #     instead of root BOM's.
    #     """
    #     if not self._is_so_root_bom():
    #         return super()._create_or_update_po(quantity)
    #
    #     # ref_bom = self._get_so_bom_ref()   # child BOM
    #     POLine = self.env['purchase.order.line']
    #     PO = self.env['purchase.order']
    #
    #     bom_line = self.cr_bom_line_id
    #     vendor = (bom_line.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
    #               or bom_line.product_id._select_seller())
    #
    #     if not vendor or not vendor.partner_id:
    #         return
    #
    #     existing_line = POLine.search([
    #         ('component_branch_id', '=', self.id),
    #         ('order_id.partner_id', '=', vendor.partner_id.id),
    #         ('order_id.state', '=', 'draft'),
    #         ('bom_id', '=', self.root_bom_id.id),
    #     ], limit=1)
    #
    #     if existing_line:
    #         existing_line.order_id.po_type = 'mrp'
    #         existing_line.manufacturer_id = self.product_manufacturer_id.id
    #         self.vendor_po_ids = [(4, existing_line.id)]
    #         if existing_line.product_qty != quantity:
    #             existing_line.product_qty = quantity
    #             self._send_notification(
    #                 'Purchase Order Updated (Non - CFE)',
    #                 f'Updated Qty to {existing_line.product_qty} for {existing_line.order_id.name}',
    #                 'success'
    #             )
    #
    #         # self._send_notification(
    #         #     'Purchase Order Updated (Non - CFE)',
    #         #     f'Updated Qty to {existing_line.product_qty} for {existing_line.order_id.name}',
    #         #     'success'
    #         # )
    #     else:
    #         po = PO.search([
    #             ('partner_id', '=', vendor.partner_id.id),
    #             ('state', '=', 'draft'),
    #             ('bom_id', '=', self.root_bom_id.id),
    #             ('po_type', '=', 'mrp'),
    #             ('cfe', '=', False),
    #         ], limit=1)
    #
    #         if not po:
    #             location = self.root_bom_id.cfe_project_location_id
    #             if location:
    #                 curr = location
    #                 while curr.location_id:
    #                     if curr.location_id.name == 'Project Location':
    #                         location = curr
    #                         break
    #                     curr = curr.location_id
    #
    #             po = PO.create({
    #                 'partner_id': vendor.partner_id.id,
    #                 'bom_id': self.root_bom_id.id,
    #                 'origin': f'EVR Flow - {self.root_bom_id.display_name}',
    #                 'cfe_project_location_id': location.id if location else False,
    #                 'state': 'draft',
    #                 'po_type': 'mrp',
    #             })
    #
    #         price = vendor.price or bom_line.product_id.list_price
    #
    #         analytic_account = self.root_bom_id.project_id.account_id
    #
    #         new_line = POLine.create({
    #             'order_id': po.id,
    #             'product_id': bom_line.product_id.id,
    #             'product_qty': quantity,
    #             'product_uom': bom_line.product_id.uom_po_id.id,
    #             'price_unit': price,
    #             'date_planned': fields.Datetime.now(),
    #             'component_branch_id': self.id,
    #             'branch_id': self.bom_line_branch_id.id,
    #             'distribution_analytic_account_ids': [(6, 0, [analytic_account.id])] if analytic_account else False,
    #             'bom_line_ids': [(6, 0, [bom_line.id])],
    #             'bom_id': self.root_bom_id.id,
    #             'project_id': self.root_bom_id.project_id.id,             # child BOM's project
    #             'manufacturer_id': self.product_manufacturer_id.id,
    #         })
    #         new_line.order_id.po_type = 'mrp'
    #         self.vendor_po_ids = [(4, new_line.id)]
    #         self._send_notification(
    #             'Purchase Order Created',
    #             f'Created PO {new_line.order_id.name} for {self.cr_bom_line_id.product_id.display_name} ({quantity})',
    #             'success'
    #         )

