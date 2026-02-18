# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, api, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    def create_special_po_approval(self, action_type, quantity, component_id, root_bom_id):
        """Create approval request for special PO"""
        self.ensure_one()

        vendor = (self.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1])
        _logger.info(f'vendor : {vendor}')

        # if not vendor:
        #     raise UserError(f"No vendor found for {self.product_id.display_name}")

        if not vendor:
            return {
                'error': True,
                'message': f"Main vendor is not set for {self.product_id.display_name}"
            }

        approval_category = self.env['approval.category'].search([
            ('name', '=', "Create RFQ's")
        ], limit=1)

        if not approval_category:
            raise UserError("Approval category 'Create RFQ's' not found")

        approval_request = self.env['approval.request'].create({
            'name': f"URGT PO Request - {self.product_id.display_name}",
            'category_id': approval_category.id,
            'request_owner_id': self.env.user.id,
        })

        # Create product line with custom fields
        self.env['approval.product.line'].create({
            'approval_request_id': approval_request.id,
            'product_id': self.product_id.id,
            'quantity': quantity,
            'cr_bom_line_id': self.id,
            'cr_component_id': component_id,
            'cr_root_bom_id': root_bom_id,
            'cr_vendor_id': vendor.partner_id.id,
        })

        return {
            'approval_id': approval_request.id,
        }

    # def _create_instant_pos_with_context(self, root_bom_id, bom_line, qty, componentId):
    #     """Create instant POs respecting independent rules for customer/vendor with detailed messages."""
    #     result = {
    #         "customer_po": False,
    #         "vendor_po": False,
    #         "customer_po_id": False,
    #         "vendor_po_id": False,
    #         "customer_po_name": False,
    #         "vendor_po_name": False,
    #         "messages": [],  # detailed messages
    #     }
    #
    #     cfe_qty = float(bom_line.cfe_quantity or 0)
    #     required_qty = float(qty or 0)
    #     remaining_qty = required_qty - cfe_qty
    #
    #     root_bom = self.env['mrp.bom'].browse(root_bom_id)
    #     project_partner = root_bom.project_id.partner_id if root_bom.project_id else None
    #     product_code = root_bom.product_id.default_code or root_bom.product_tmpl_id.default_code or ''
    #     product_name = root_bom.product_id.name or root_bom.product_tmpl_id.name or ''
    #     cfe_project_location_id = root_bom.cfe_project_location_id
    #     comp = self.env['mrp.bom.line.branch.components'].browse(componentId)
    #
    #     # ----------------------------
    #     # CUSTOMER PO (with bom_line_id)
    #     # ----------------------------
    #     create_customer_po = False
    #     existing_customer_po_line = self.env['purchase.order.line'].search([
    #         ('bom_id', '=', root_bom_id),
    #         ('product_id', '=', bom_line.product_id.id),
    #         ('order_id.partner_id', '=', project_partner.id),
    #         ('bom_line_ids', 'in', [bom_line.id]),
    #         ("order_id.state", "=", "draft"),
    #         ("component_branch_id", '=', componentId),
    #         ("project_id", '=', root_bom.project_id.id)
    #     ], order="id desc", limit=1)
    #
    #     existing_customer_po = existing_customer_po_line.order_id if existing_customer_po_line else False
    #
    #     if existing_customer_po:
    #         if existing_customer_po_line.order_id.state == 'draft':
    #             existing_customer_po.cfe_project_location_id = cfe_project_location_id.id
    #
    #     if not bom_line.customer_po_created:
    #         create_customer_po = True
    #     elif existing_customer_po and existing_customer_po.state != 'draft':
    #         # ✅ if PO exists but not in draft, create new
    #         create_customer_po = True
    #     elif not existing_customer_po:
    #         create_customer_po = True
    #     else:
    #         result['messages'].append(
    #             f"Customer PO not created for {bom_line.product_id.display_name}: "
    #             f"already exists ({existing_customer_po.name if existing_customer_po else 'N/A'}) "
    #         )
    #
    #     if create_customer_po:
    #         if not project_partner:
    #             result['messages'].append(
    #                 f"Customer PO not created for {bom_line.product_id.display_name}: Project partner missing."
    #             )
    #         elif cfe_qty <= 0:
    #             result['messages'].append(
    #                 f"Customer PO not created for {bom_line.product_id.display_name}: CFE Quantity <= 0."
    #             )
    #         else:
    #             po_exist = self.env['purchase.order'].search(
    #                 [('bom_id', '=', root_bom_id), ('state', '=', 'draft'), ("partner_id", "=", project_partner.id),
    #                  ("po_type", "=", "mrp"), ('cfe', '=', True)])
    #
    #             if po_exist:
    #                 if po_exist:
    #                     po_exist.cfe_project_location_id = cfe_project_location_id.id
    #                     po_line = po_exist.order_line.filtered(lambda l: l.product_id.id == bom_line.product_id.id)
    #                     po_exist.cfe = True
    #                     cpo_line_vals = {
    #                         "order_id": po_exist.id,
    #                         "product_id": bom_line.product_id.id,
    #                         "product_qty": cfe_qty,
    #                         "product_uom": bom_line.product_id.uom_po_id.id,
    #                         "price_unit": 0.0,
    #                         "date_planned": fields.Datetime.now(),
    #                         "name": f"CFE - {bom_line.product_id.display_name}",
    #                         "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
    #                         'bom_id': root_bom_id,
    #                         'component_branch_id': componentId,
    #                         "project_id": root_bom.project_id.id,
    #                     }
    #
    #                     if bom_line.product_manufacturer_id:
    #                         cpo_line_vals["manufacturer_id"] = bom_line.product_manufacturer_id.id
    #                     cr_cpo = self.env["purchase.order.line"].create(cpo_line_vals)
    #                     bom_line.customer_po_line_id = cr_cpo.id
    #
    #                     comp.customer_po_ids = [(4, cr_cpo.id)]
    #                     result['messages'].append(
    #                         f"➕ Added {bom_line.product_id.display_name} ({cfe_qty}) to Customer PO {po_exist.name}"
    #                     )
    #
    #                     bom_line.customer_po_created = True
    #
    #             else:
    #                 customer_po_vals = {
    #                     'partner_id': project_partner.id,
    #                     'cfe_project_location_id': cfe_project_location_id.id if cfe_project_location_id else False,
    #                     'origin': f"EVR-Manufacture - [{product_code}] {product_name}",
    #                     'state': 'draft',
    #                     'bom_id': root_bom_id,
    #                     'po_type': 'mrp',
    #                     'cfe': True,
    #                     'order_line': [(0, 0, {
    #                         'product_id': bom_line.product_id.id,
    #                         'product_qty': cfe_qty,
    #                         'product_uom': bom_line.product_id.uom_po_id.id,
    #                         'price_unit': 0.0,
    #                         'date_planned': fields.Datetime.now(),
    #                         'name': f"CFE - {bom_line.product_id.display_name}",
    #                         'manufacturer_id': bom_line.product_manufacturer_id.id if bom_line.product_manufacturer_id else False,
    #                         'bom_line_ids': [(6, 0, [bom_line.id])],
    #                         'bom_id': root_bom_id,
    #                         'component_branch_id': componentId,
    #                         "project_id": root_bom.project_id.id,
    #                     })]
    #                 }
    #
    #                 customer_po = self.env['purchase.order'].create(customer_po_vals)
    #                 find_cpo_line = self.env["purchase.order.line"].search(
    #                     [('product_id', '=', bom_line.product_id.id), ('order_id', '=', customer_po.id)])
    #                 bom_line.customer_po_line_id = find_cpo_line.id
    #                 bom_line.customer_po_created = True
    #                 comp.customer_po_ids = [(4, find_cpo_line.id)]
    #                 result.update({
    #                     'customer_po': True,
    #                     'customer_po_id': customer_po.id,
    #                     'customer_po_name': customer_po.name
    #                 })
    #                 result['messages'].append(f"✅ Customer PO created: {customer_po.name} ({cfe_qty})")
    #
    #     # ----------------------------
    #     # VENDOR PO (Check draft first, then follow full flow)
    #     # ----------------------------
    #     if remaining_qty > 0:
    #         vendor = (bom_line.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
    #                   or bom_line.product_id._select_seller())
    #
    #         if not vendor or not vendor.partner_id:
    #             result['messages'].append(
    #                 f"⚠️ Vendor PO not created for {bom_line.product_id.display_name} ({remaining_qty}): Vendor not configured properly."
    #             )
    #             return result
    #
    #         price = vendor.price or bom_line.product_id.list_price
    #         if not price:
    #             result['messages'].append(
    #                 f"⚠️ Vendor PO not created for {bom_line.product_id.display_name} ({remaining_qty}): No price found."
    #             )
    #             return result
    #
    #         manufacturer_id = bom_line.product_manufacturer_id.id if bom_line.product_manufacturer_id else False
    #         mo_internal_ref = getattr(bom_line.bom_id, 'mo_internal_ref', False)
    #         bom = bom_line.bom_id
    #
    #         # 1️⃣ Check if draft Vendor PO exists
    #         draft_po_line = self.env["purchase.order.line"].search([
    #             ("order_id.partner_id", "=", vendor.partner_id.id),
    #             ("product_id", "=", bom_line.product_id.id),
    #             ("bom_line_ids", "in", [bom_line.id]),
    #             ("order_id.state", "=", "draft"),
    #             ("component_branch_id", '=', componentId),
    #             ("project_id", '=', root_bom.project_id.id)
    #         ], order="id desc", limit=1)
    #
    #         if draft_po_line:
    #             draft_po_line.order_id.cfe_project_location_id = cfe_project_location_id.id
    #             comp.vendor_po_ids = [(4, draft_po_line.id)]
    #             # Draft exists → do nothing
    #             result['messages'].append(
    #                 f"ℹ️ Vendor PO {draft_po_line.order_id.name} already exists in draft for {bom_line.product_id.display_name}, no action needed."
    #             )
    #             bom_line.vendor_po_created = True
    #             result.update({
    #                 "vendor_po": True,
    #                 "vendor_po_id": draft_po_line.order_id.id,
    #                 "vendor_po_name": draft_po_line.order_id.name
    #             })
    #             return result
    #
    #         # 2️⃣ No draft Vendor PO → check non-draft Vendor PO (log warning)
    #         existing_vpo_line = self.env["purchase.order.line"].search([
    #             ("order_id.partner_id", "=", vendor.partner_id.id),
    #             ("product_id", "=", bom_line.product_id.id),
    #             ("bom_line_ids", "in", [bom_line.id]),
    #             ("order_id.state", "!=", "draft"),
    #             ("component_branch_id", '=', componentId),
    #             ("project_id", '=', root_bom.project_id.id)
    #         ], order="id desc", limit=1)
    #
    #         if existing_vpo_line:
    #             existing_vpo_line.order_id.cfe_project_location_id = cfe_project_location_id.id
    #             result['messages'].append(
    #                 f"⚠️ Vendor PO {existing_vpo_line.order_id.name} exists but not in draft, creating new PO."
    #             )
    #
    #         # 3️⃣ No Vendor PO exists → check draft Customer PO for this product
    #         draft_cpo = self.env["purchase.order"].search([
    #             ("partner_id", "=", vendor.partner_id.id),
    #             ("state", "=", "draft"), ("po_type", "=", "mrp"),
    #             ("cfe", '=', False)
    #         ], order="id desc", limit=1)
    #
    #         if draft_cpo:
    #             draft_cpo.cfe_project_location_id = cfe_project_location_id.id
    #
    #             po_line_vals = {
    #                 "order_id": draft_cpo.id,
    #                 "product_id": bom_line.product_id.id,
    #                 "product_qty": remaining_qty,
    #                 "product_uom": bom_line.product_id.uom_po_id.id,
    #                 "price_unit": 0.0,
    #                 "date_planned": fields.Datetime.now(),
    #                 "name": f"CFE - {bom_line.product_id.display_name}",
    #                 "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
    #                 "component_branch_id": componentId,
    #                 "project_id": bom.project_id.id,
    #             }
    #             if manufacturer_id:
    #                 po_line_vals["manufacturer_id"] = manufacturer_id
    #             new_po_line = self.env["purchase.order.line"].create(po_line_vals)
    #             bom_line.po_line_id = new_po_line.id
    #             comp.vendor_po_ids = [(4, new_po_line.id)]
    #
    #             result['messages'].append(
    #                 f"➕ Added {bom_line.product_id.display_name} ({remaining_qty}) to Vendor PO {draft_cpo.name}"
    #             )
    #
    #             bom_line.vendor_po_created = True
    #             result.update({
    #                 "vendor_po": True,
    #                 "vendor_po_id": draft_cpo.id,
    #                 "vendor_po_name": draft_cpo.name
    #             })
    #             return result
    #
    #         # 4️⃣ No draft Customer PO → create new Vendor PO
    #         po_line_vals = {
    #             "product_id": bom_line.product_id.id,
    #             "product_qty": remaining_qty,
    #             "product_uom": bom_line.product_id.uom_po_id.id,
    #             "price_unit": price,
    #             "date_planned": fields.Datetime.now(),
    #             "name": f"Vendor - {bom_line.product_id.display_name}",
    #             "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
    #             "component_branch_id": componentId,
    #             "project_id": bom.project_id.id,
    #         }
    #         if manufacturer_id:
    #             po_line_vals["manufacturer_id"] = manufacturer_id
    #
    #         vendor_po_vals = {
    #             "partner_id": vendor.partner_id.id,
    #             "origin": f"BOM {bom.display_name}",
    #             "order_line": [(0, 0, po_line_vals)],
    #             'cfe_project_location_id': cfe_project_location_id.id,
    #             'po_type': 'mrp'
    #         }
    #         if bom.is_evr and cfe_project_location_id:
    #             vendor_po_vals.update({"cfe_project_location_id": cfe_project_location_id.id})
    #         if mo_internal_ref:
    #             vendor_po_vals["mo_internal_ref"] = mo_internal_ref
    #
    #         vpo = self.env["purchase.order"].create(vendor_po_vals)
    #         find_po_line = self.env["purchase.order.line"].search(
    #             [('product_id', '=', bom_line.product_id.id), ('order_id', '=', vpo.id)])
    #         bom_line.po_line_id = find_po_line.id
    #         comp.vendor_po_ids = [(4, find_po_line.id)]
    #
    #         bom_line.vendor_po_created = True
    #         result.update({
    #             "vendor_po": True,
    #             "vendor_po_id": vpo.id,
    #             "vendor_po_name": vpo.name
    #         })
    #         result['messages'].append(
    #             f"✅ Vendor PO {vpo.name} created for {bom_line.product_id.display_name} ({remaining_qty})"
    #         )
    #         return result
    #
    #     return result
