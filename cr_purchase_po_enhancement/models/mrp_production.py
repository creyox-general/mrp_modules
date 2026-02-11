# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models,api,fields
from odoo.exceptions import ValidationError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.model_create_multi
    def create(self, vals_list):
        # PART 1: Handle validation for EVR BOMs
        for vals in vals_list:
            if vals.get('bom_id'):
                bom = self.env['mrp.bom'].browse(vals['bom_id'])
                if bom.is_evr:
                    unapproved_lines = []

                    if bom.project_id:
                        vals['project_id'] = bom.project_id.id

                    for line in bom.bom_line_ids:
                        if not bom._check_all_children_approved(line):
                            unapproved_lines.append(line.product_id.display_name)

                    if unapproved_lines:
                        raise ValidationError(
                            "Cannot create MO. The following BOM lines or their sub-components are not approved for manufacture:\n" +
                            "\n".join([f"- {name}" for name in unapproved_lines])
                        )

            branch_intermediate_location = self.env.context.get('branch_intermediate_location')

            # Store intermediate location
            if branch_intermediate_location:
                vals['branch_intermediate_location_id'] = branch_intermediate_location

        # PART 2: Create MOs WITHOUT skipping component moves when called from write
        skip_moves = self.env.context.get('skip_component_moves', False)
        from_write = self.env.context.get('from_bom_write', False)

        if skip_moves and not from_write:
            mos = super(MrpProduction, self.with_context(skip_compute_move_raw_ids=True)).create(vals_list)
        else:
            mos = super().create(vals_list)

        return mos

    @api.model
    def action_validate_and_create_mo(self, bom_id):
        """Validate and recursively create MOs and POs for EVR BOM with detailed notifications."""
        bom = self.env["mrp.bom"].browse(bom_id)
        cfe_project_location_id = bom.cfe_project_location_id
        messages = []
        pos = []

        # ✅ Initialize cache
        if not hasattr(self.__class__, '_component_assignment_cache'):
            self.__class__._component_assignment_cache = {}

        cache_key = f"bom_{bom.id}"
        self.__class__._component_assignment_cache[cache_key] = {
            'assignments': {},
            'seen_paths': []
        }

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


        # Recursive function for BOM traversal with quantity tracking
        def process_bom_lines(bom_record, parent_qty=1.0,parent_bom=None,line_index="0"):
            """
            Process BOM lines recursively while maintaining quantity multiplier.

            Args:
                bom_record: The current BOM to process
                parent_qty: Accumulated quantity from parent BOMs
            """
            for idx, line in enumerate(bom_record.bom_line_ids):
                current_index = f"{line_index}{idx}"

                # ✅ ALWAYS get component ID for every non-BOM line
                component_id = self._get_component_id_for_line(
                    bom.id,
                    line,
                    bom_record,
                    current_index
                )
                comp = self.env['mrp.bom.line.branch.components'].browse(component_id)

                sub_bom = self.env["mrp.bom"].search([
                    ("product_tmpl_id", "=", line.product_id.product_tmpl_id.id)
                ], limit=1)

                if sub_bom:
                    child_qty = float(line.product_qty or 1.0) * parent_qty
                    process_bom_lines(sub_bom, child_qty, bom_record, current_index)
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
                        ("component_branch_id",'=',component_id),
                        ("project_id",'=',bom.project_id.id)
                    ], order="id desc", limit=1)

                    if draft_cpo_line:
                        draft_cpo_line.order_id.cfe_project_location_id = cfe_project_location_id.id
                        draft_cpo_line.order_id.po_type = 'mrp'
                        draft_cpo_line.order_id.cfe = True
                        messages.append({
                            "type": "info",
                            "msg": f"ℹ️ Customer PO {draft_cpo_line.order_id.name} already exists for {line.product_id.display_name} ({cfe_qty})"
                        })
                        line.customer_po_created = True
                        pos.append(draft_cpo_line.order_id.id)
                    else:
                        po_exist = self.env['purchase.order'].search(
                            [('bom_id', '=', bom.id), ("partner_id", "=", project.partner_id.id),
                             ('state', '=', 'draft'),("po_type", "=", "mrp"),("cfe",'=',True)])

                        if po_exist:
                            po_exist.cfe_project_location_id = cfe_project_location_id.id
                            po_exist.po_type = 'mrp'
                            po_exist.cfe = True
                            po_line = po_exist.order_line.filtered(
                                lambda l: l.product_id.id == line.product_id.id)
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
                                "component_branch_id": component_id,
                                "project_id": bom.project_id.id,
                            }
                            if line.product_manufacturer_id:
                                cpo_line_vals["manufacturer_id"] = line.product_manufacturer_id.id
                            cr_cpo = self.env["purchase.order.line"].create(cpo_line_vals)
                            line.customer_po_line_id = cr_cpo.id
                            comp.customer_po_ids = [(4, cr_cpo.id)]
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
                                'po_type' : 'mrp',
                                'cfe':True,
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
                                    "component_branch_id": component_id,
                                    "project_id": bom.project_id.id,
                                })]
                            }

                            customer_po = self.env['purchase.order'].create(customer_po_vals)
                            find_cpo_line = self.env["purchase.order.line"].search(
                                [('product_id', '=', line.product_id.id), ('order_id', '=', customer_po.id),("project_id",'=',bom.project_id.id)])
                            line.customer_po_line_id = find_cpo_line.id
                            line.customer_po_created = True

                            comp.customer_po_ids = [(4, find_cpo_line.id)]

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
                        ('bom_id', '=', bom.id),
                        ("order_id.partner_id", "=", vendor.partner_id.id),
                        ("product_id", "=", line.product_id.id),
                        ("bom_line_ids", "in", [line.id]),
                        ("order_id.state", "=", "draft"),
                        ("component_branch_id", '=', component_id),
                        ("project_id", '=', bom.project_id.id)
                    ], order="id desc", limit=1)

                    if draft_po_line:
                        draft_po_line.order_id.cfe_project_location_id = cfe_project_location_id.id
                        draft_po_line.order_id.po_type = 'mrp'
                        comp.vendor_po_ids = [(4, draft_po_line.id)]
                        messages.append({
                            "type": "info",
                            "msg": f"ℹ️ Vendor PO {draft_po_line.order_id.name} already exists in draft for {line.product_id.display_name}, no action needed."
                        })
                        line.vendor_po_created = True
                        pos.append(draft_po_line.order_id.id)
                        continue

                    # 2️⃣ No draft Vendor PO → check non-draft Vendor PO
                    existing_vpo_line = self.env["purchase.order.line"].search([
                        ('bom_id', '=', bom.id),
                        ("order_id.partner_id", "=", vendor.partner_id.id),
                        ("product_id", "=", line.product_id.id),
                        ("bom_line_ids", "in", [line.id]),
                        ("order_id.state", "!=", "draft"),
                        ("component_branch_id", '=', component_id),
                        ("project_id", '=', bom.project_id.id)
                    ], order="id desc", limit=1)

                    if existing_vpo_line:
                        messages.append({
                            "type": "warning",
                            "msg": f"⚠️ Vendor PO {existing_vpo_line.order_id.name} exists but not in draft, creating new PO."
                        })

                    # 3️⃣ If no Vendor PO exists at all → check draft Customer POs
                    draft_cpo = self.env["purchase.order"].search([
                        ("partner_id", "=", vendor.partner_id.id),
                        ("state", "=", "draft"),("po_type", "=", "mrp"),("cfe",'=',False),
                    ], order="id desc", limit=1)

                    if draft_cpo:
                        draft_cpo.cfe_project_location_id = cfe_project_location_id.id
                        draft_cpo.po_type = 'mrp'
                        cpo_line = draft_cpo.order_line.filtered(lambda l: l.product_id.id == line.product_id.id)

                        po_line_vals = {
                            "order_id": draft_cpo.id,
                            "product_id": line.product_id.id,
                            "product_qty": remaining_qty,
                            "product_uom": line.product_id.uom_po_id.id,
                            "price_unit": 0.0,
                            "date_planned": fields.Datetime.now(),
                            "name": f"CFE - {line.product_id.display_name}",
                            "bom_line_ids": [(6, 0, [line.id])],
                            "component_branch_id": component_id,
                            "project_id": bom.project_id.id,
                        }
                        if manufacturer_id:
                            po_line_vals["manufacturer_id"] = manufacturer_id
                        new_po_line = self.env["purchase.order.line"].create(po_line_vals)
                        line.po_line_id = new_po_line.id
                        comp.vendor_po_ids = [(4, new_po_line.id)]
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
                        "component_branch_id": component_id,
                        "project_id": bom.project_id.id,
                    }
                    if manufacturer_id:
                        po_line_vals["manufacturer_id"] = manufacturer_id

                    vendor_po_vals = {
                        "partner_id": vendor.partner_id.id,
                        "origin": f"BOM {bom.display_name}",
                        "order_line": [(0, 0, po_line_vals)],
                        'po_type':'mrp'
                    }
                    if bom.is_evr and cfe_project_location_id:
                        vendor_po_vals.update({"cfe_project_location_id": cfe_project_location_id.id})
                    if mo_internal_ref:
                        vendor_po_vals["mo_internal_ref"] = mo_internal_ref

                    vpo = self.env["purchase.order"].create(vendor_po_vals)
                    find_po_line = self.env["purchase.order.line"].search(
                        [('product_id', '=', line.product_id.id), ('order_id', '=', vpo.id),('order_id.cfe','=',False)])
                    line.po_line_id = find_po_line.id
                    line.vendor_po_created = True
                    comp.vendor_po_ids = [(4, find_po_line.id)]
                    pos.append(vpo.id)
                    messages.append({
                        "type": "success",
                        "msg": f"✅ Vendor PO {vpo.name} created for {line.product_id.display_name} ({remaining_qty})"
                    })

        # ✅ Start recursion with parent_qty = 1.0
        # process_bom_lines(bom, parent_qty=1.0,parent_bom=None)
        process_bom_lines(bom, parent_qty=1.0, parent_bom=None, line_index="0")

        # ✅ Clear cache after all processing
        cache_key = f"bom_{bom.id}"
        if hasattr(self.__class__, '_component_assignment_cache'):
            if cache_key in self.__class__._component_assignment_cache:
                del self.__class__._component_assignment_cache[cache_key]

        action = {
            "res_model": "mrp.production",
            "name": "Manufacture Orders",
            "type": "ir.actions.act_window",
            "views": [[False, "form"]],
            "target": "current",
            "context": {"default_bom_id": bom.id, "pos": pos},
        }

        return {"action": action, "messages": messages}