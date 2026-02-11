# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    # @api.model
    # def create(self, vals):
    #     """Override to set MO source and dest locations from EVR BOM."""
    #     if vals.get("bom_id"):
    #         bom = self.env["mrp.bom"].browse(vals["bom_id"])
    #         if bom.is_evr and bom.cfe_project_location_id:
    #             vals["location_src_id"] = bom.cfe_project_location_id.id
    #             # vals["location_dest_id"] = bom.cfe_project_location_id.id
    #     return super().create(vals)


    @api.model
    def action_validate_and_create_mo(self, bom_id):
        """Validate and recursively create MOs and POs for EVR BOM with detailed notifications."""
        bom = self.env["mrp.bom"].browse(bom_id)
        cfe_project_location_id = bom.cfe_project_location_id
        messages = []
        pos = []

        if not bom or not bom.is_evr:
            msg = "❌ Invalid or non-EVR BOM."
            messages.append({"type": "danger", "msg": msg})
            raise ValidationError(msg)

        project = getattr(bom, "project_id", None)
        if not project or not project.partner_id:
            msg = "⚠️ Project and Customer must be set before Manufacture."
            messages.append({"type": "danger", "msg": msg})
            raise ValidationError(msg)

        mo_internal_ref = getattr(bom, "mo_internal_ref", False)

        # ✅ FIX: Helper function to calculate multiplier through BOM hierarchy
        def get_bom_hierarchy_multiplier(sub_bom, main_bom):
            """
            Calculate the multiplier for a sub-BOM within the main BOM hierarchy.
            For multi-level BOMs: main_qty × parent_qty × ... × current_qty
            """
            multiplier = 1.0
            current_bom = sub_bom

            # Traverse up the BOM hierarchy until we reach the main BOM
            while current_bom and current_bom.id != main_bom.id:
                # Find the parent BOM that references this sub_bom
                parent_lines = main_bom.bom_line_ids.search([
                    ('product_tmpl_id', '=', current_bom.product_tmpl_id.id)
                ])

                if parent_lines:
                    # Multiply by the quantity in the parent BOM
                    multiplier *= float(parent_lines[0].product_qty or 1.0)
                    # Find parent BOM of current BOM
                    current_bom = self.env["mrp.bom"].search([
                        ('product_tmpl_id', '=', parent_lines[0].bom_id.product_tmpl_id.id)
                    ], limit=1)
                else:
                    break

            return multiplier

        # Recursive function for BOM traversal with quantity tracking
        def process_bom_lines(bom_record, parent_qty=1.0):
            """
            Process BOM lines recursively while maintaining quantity multiplier.

            Args:
                bom_record: The current BOM to process
                parent_qty: Accumulated quantity from parent BOMs
            """
            for line in bom_record.bom_line_ids:
                sub_bom = self.env["mrp.bom"].search([
                    ("product_tmpl_id", "=", line.product_id.product_tmpl_id.id)
                ], limit=1)

                if sub_bom:
                    # ✅ FIX: Pass accumulated quantity to recursive call
                    child_qty = float(line.product_qty or 1.0) * parent_qty
                    process_bom_lines(sub_bom, child_qty)
                    continue

                # Skip invalid lines
                if line.lli or not (line.approval_1 and line.approval_2) or not line.cfe_quantity:
                    messages.append({
                        "type": "info",
                        "msg": f"⏩ Skipped {line.product_id.display_name}: "
                               f"LLI={line.lli}, Approvals={line.approval_1}/{line.approval_2}, "
                               f"CFE qty={line.cfe_quantity}"
                    })
                    continue

                # ✅ FIX: Calculate required_qty using parent_qty multiplier
                required_qty = float(line.product_qty or 0) * parent_qty

                cfe_qty = float(line.cfe_quantity or 0)
                remaining_qty = required_qty - cfe_qty


                manufacturer_id = line.product_manufacturer_id.id if line.product_manufacturer_id else False

                # -------------------------
                # CUSTOMER PURCHASE ORDER (draft-first)
                # -------------------------
                if cfe_qty > 0:
                    draft_cpo_line = self.env['purchase.order.line'].search([
                        ('bom_id', '=', bom.id),
                        ('product_id', '=', line.product_id.id),
                        ('order_id.partner_id', '=', project.partner_id.id),
                        ('bom_line_ids', 'in', [line.id]),
                        ("order_id.state", "=", "draft"),
                    ], order="id desc", limit=1)

                    if draft_cpo_line:
                        draft_cpo_line.order_id.cfe_project_location_id = cfe_project_location_id.id
                        messages.append({
                            "type": "info",
                            "msg": f"ℹ️ Customer PO {draft_cpo_line.order_id.name} already exists for {line.product_id.display_name} ({cfe_qty})"
                        })
                        line.customer_po_created = True
                        pos.append(draft_cpo_line.order_id.id)
                    else:
                        po_exist = self.env['purchase.order'].search(
                            [('bom_id', '=', bom.id), ("partner_id", "=", project.partner_id.id),
                             ('state', '=', 'draft')])

                        if po_exist:
                            po_exist.cfe_project_location_id = cfe_project_location_id.id
                            po_line = po_exist.order_line.filtered(
                                lambda l: l.product_id.id == line.product_id.id)
                            if po_line:
                                po_line.product_qty += cfe_qty
                                line.customer_po_line_id = po_line.id
                                if line.id not in po_line.bom_line_ids.ids:
                                    po_line.bom_line_ids = [(4, line.id)]

                                messages.append({
                                    "type": "success",
                                    'msg': f"🔄 Updated Customer PO {po_exist.name}: added {cfe_qty} to {line.product_id.display_name}"
                                })
                            else:
                                cpo_line_vals = {
                                    "order_id": po_exist.id,
                                    "product_id": line.product_id.id,
                                    "product_qty": cfe_qty,
                                    "product_uom": line.product_id.uom_po_id.id,
                                    "price_unit": 0.0,
                                    "date_planned": fields.Datetime.now(),
                                    "name": f"CFE - {line.product_id.display_name}",
                                    "bom_line_ids": [(6, 0, [line.id])],
                                    'bom_id': bom.id,
                                }
                                if line.product_manufacturer_id:
                                    cpo_line_vals["manufacturer_id"] = line.product_manufacturer_id.id
                                cr_cpo = self.env["purchase.order.line"].create(cpo_line_vals)
                                line.customer_po_line_id = cr_cpo.id
                                messages.append({
                                    "type": "success",
                                    "msg": f"➕ Added {line.product_id.display_name} ({cfe_qty}) to Customer PO {po_exist.name}"}
                                )

                            line.customer_po_created = True

                        else:
                            customer_po_vals = {
                                'partner_id': project.partner_id.id,
                                'cfe_project_location_id': cfe_project_location_id.id if cfe_project_location_id else False,
                                'origin': f"EVR-Manufacture",
                                'state': 'draft',
                                'bom_id': bom.id,
                                'order_line': [(0, 0, {
                                    'product_id': line.product_id.id,
                                    'product_qty': cfe_qty,
                                    'product_uom': line.product_id.uom_po_id.id,
                                    'price_unit': 0.0,
                                    'date_planned': fields.Datetime.now(),
                                    'name': f"CFE - {line.product_id.display_name}",
                                    'manufacturer_id': line.product_manufacturer_id.id if line.product_manufacturer_id else False,
                                    'bom_line_ids': [(6, 0, [line.id])],
                                    'bom_id': bom.id,
                                })]
                            }

                            customer_po = self.env['purchase.order'].create(customer_po_vals)
                            find_cpo_line = self.env["purchase.order.line"].search(
                                [('product_id', '=', line.product_id.id), ('order_id', '=', customer_po.id)])
                            line.customer_po_line_id = find_cpo_line.id
                            line.customer_po_created = True

                            messages.append({
                                "type": "success",
                                "msg": f"✅ Customer PO {customer_po.name} created for {line.product_id.display_name} ({cfe_qty})"
                            })

                # -------------------------
                # VENDOR PURCHASE ORDER (instant PO logic + check draft CPO)
                # -------------------------
                if remaining_qty > 0:
                    vendor = (line.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                              or line.product_id._select_seller())
                    if not vendor or not vendor.partner_id:
                        messages.append({
                            "type": "warning",
                            "msg": f"⚠️ Vendor PO not created for {line.product_id.display_name} ({remaining_qty}): Vendor not configured properly."
                        })
                        continue

                    price = vendor.price or line.product_id.list_price
                    if not price:
                        messages.append({
                            "type": "warning",
                            "msg": f"⚠️ Vendor PO not created for {line.product_id.display_name} ({remaining_qty}): No price found."
                        })
                        continue

                    # 1️⃣ Check draft Vendor PO first
                    draft_po_line = self.env["purchase.order.line"].search([
                        ("order_id.partner_id", "=", vendor.partner_id.id),
                        ("product_id", "=", line.product_id.id),
                        ("bom_line_ids", "in", [line.id]),
                        ("order_id.state", "=", "draft")
                    ], order="id desc", limit=1)

                    if draft_po_line:
                        draft_po_line.order_id.cfe_project_location_id = cfe_project_location_id.id
                        messages.append({
                            "type": "info",
                            "msg": f"ℹ️ Vendor PO {draft_po_line.order_id.name} already exists in draft for {line.product_id.display_name}, no action needed."
                        })
                        line.vendor_po_created = True
                        pos.append(draft_po_line.order_id.id)
                        continue

                    # 2️⃣ No draft Vendor PO → check non-draft Vendor PO
                    existing_vpo_line = self.env["purchase.order.line"].search([
                        ("order_id.partner_id", "=", vendor.partner_id.id),
                        ("product_id", "=", line.product_id.id),
                        ("bom_line_ids", "in", [line.id]),
                        ("order_id.state", "!=", "draft")
                    ], order="id desc", limit=1)

                    if existing_vpo_line:
                        messages.append({
                            "type": "warning",
                            "msg": f"⚠️ Vendor PO {existing_vpo_line.order_id.name} exists but not in draft, creating new PO."
                        })

                    # 3️⃣ If no Vendor PO exists at all → check draft Customer POs
                    draft_cpo = self.env["purchase.order"].search([
                        ("partner_id", "=", vendor.partner_id.id),
                        ("state", "=", "draft")
                    ], order="id desc", limit=1)

                    if draft_cpo:
                        draft_cpo.cfe_project_location_id = cfe_project_location_id.id
                        cpo_line = draft_cpo.order_line.filtered(lambda l: l.product_id.id == line.product_id.id)
                        if cpo_line:
                            if line.id not in cpo_line.bom_line_ids.ids:
                                cpo_line.bom_line_ids = [(4, line.id)]
                            cpo_line.product_qty += remaining_qty
                            line.po_line_id = cpo_line.id
                            cpo_line.manufacturer_id = manufacturer_id
                            messages.append({
                                "type": "success",
                                "msg": f"🔄 Updated Customer PO {draft_cpo.name}: added {remaining_qty} to {line.product_id.display_name}"
                            })
                        else:
                            po_line_vals = {
                                "order_id": draft_cpo.id,
                                "product_id": line.product_id.id,
                                "product_qty": remaining_qty,
                                "product_uom": line.product_id.uom_po_id.id,
                                "price_unit": 0.0,
                                "date_planned": fields.Datetime.now(),
                                "name": f"CFE - {line.product_id.display_name}",
                                "bom_line_ids": [(6, 0, [line.id])],
                            }
                            if manufacturer_id:
                                po_line_vals["manufacturer_id"] = manufacturer_id
                            new_po_line = self.env["purchase.order.line"].create(po_line_vals)
                            line.po_line_id = new_po_line.id
                            messages.append({
                                "type": "success",
                                "msg": f"➕ Added {line.product_id.display_name} ({remaining_qty}) to Customer PO {draft_cpo.name}"
                            })

                        line.vendor_po_created = True
                        pos.append(draft_cpo.id)
                        continue

                    # 4️⃣ If no draft Customer PO exists → create new Vendor PO
                    po_line_vals = {
                        "product_id": line.product_id.id,
                        "product_qty": remaining_qty,
                        "product_uom": line.product_id.uom_po_id.id,
                        "price_unit": price,
                        "date_planned": fields.Datetime.now(),
                        "name": f"Vendor - {line.product_id.display_name}",
                        "bom_line_ids": [(6, 0, [line.id])],
                    }
                    if manufacturer_id:
                        po_line_vals["manufacturer_id"] = manufacturer_id

                    vendor_po_vals = {
                        "partner_id": vendor.partner_id.id,
                        "origin": f"BOM {bom.display_name}",
                        "order_line": [(0, 0, po_line_vals)],
                    }
                    if bom.is_evr and cfe_project_location_id:
                        vendor_po_vals.update({"cfe_project_location_id": cfe_project_location_id.id})
                    if mo_internal_ref:
                        vendor_po_vals["mo_internal_ref"] = mo_internal_ref

                    vpo = self.env["purchase.order"].create(vendor_po_vals)
                    find_po_line = self.env["purchase.order.line"].search(
                        [('product_id', '=', line.product_id.id), ('order_id', '=', vpo.id)])
                    line.po_line_id = find_po_line.id
                    line.vendor_po_created = True
                    pos.append(vpo.id)
                    messages.append({
                        "type": "success",
                        "msg": f"✅ Vendor PO {vpo.name} created for {line.product_id.display_name} ({remaining_qty})"
                    })

        # ✅ Start recursion with parent_qty = 1.0
        process_bom_lines(bom, parent_qty=1.0)

        action = {
            "res_model": "mrp.production",
            "name": "Manufacture Orders",
            "type": "ir.actions.act_window",
            "views": [[False, "form"]],
            "target": "current",
            "context": {"default_bom_id": bom.id, "pos": pos},
        }

        return {"action": action, "messages": messages}
