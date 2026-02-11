# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    cfe_quantity = fields.Char(
        string='CFE Quantity',
        help="Customer Furnished Equipment quantity - supplied by customer at zero cost"
    )
    lli = fields.Boolean(string='LLI', default=False)
    approval_1 = fields.Boolean(string='Approval 1', default=False)
    approval_2 = fields.Boolean(string='Approval 2', default=False)
    po_created = fields.Boolean(string='PO Created', default=False)
    mo_internal_ref = fields.Many2one(
        comodel_name="product.supplierinfo",
        string="Preferred Manufacturer",
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        help="Select the manufacturer/vendor defined on the product card."
    )
    customer_po_created = fields.Boolean(string='Customer PO Created', default=False)
    vendor_po_created = fields.Boolean(string='Vendor PO Created', default=False)
    product_manufacturer_id = fields.Many2one(comodel_name="product.manufacturer.detail",string='')
    can_edit_approval_2 = fields.Boolean(
        string='Can Edit Approval 2',
        compute='_compute_can_edit_approval_2',
        help="Technical field to check if user can edit Approval 2"
    )
    product_default_code = fields.Char(
        string='Internal Reference',
        related='product_id.default_code',
        readonly=True,
        store=True
    )

    product_old_everest_pn = fields.Char(
        string='Old Everest PN',
        related='product_id.old_everest_pn',
        readonly=True,
        store=True
    )

    @api.depends_context('uid')
    def _compute_can_edit_approval_2(self):
        """Check if current user can edit Approval 2 (only Manufacture/Admin or Purchase/Admin)"""
        user = self.env.user
        can_edit = user.has_group('mrp.group_mrp_manager') or user.has_group('purchase.group_purchase_manager')
        for line in self:
            line.can_edit_approval_2 = can_edit

    def set_product_manufacturer_id(self,data):
        for line in self:
            pmd = self.env['product.manufacturer.detail'].browse(data)
            if pmd:
                line.product_manufacturer_id = pmd.id



    @api.depends('bom_id.is_evr')
    def _compute_show_cfe_quantity(self):
        """Compute whether CFE quantity and new fields should be shown"""
        for line in self:
            show = line.bom_id.is_evr
            line.show_cfe_quantity = show
            line.show_lli = show
            line.show_approval_1 = show
            line.show_approval_2 = show
            line.show_mo_internal_ref = show

    show_cfe_quantity = fields.Boolean(
        string='Show CFE Quantity',
        compute='_compute_show_cfe_quantity',
        store=True,
        help="Technical field to control CFE quantity visibility"
    )
    show_lli = fields.Boolean(compute='_compute_show_cfe_quantity', store=True)
    show_approval_1 = fields.Boolean(compute='_compute_show_cfe_quantity', store=True)
    show_approval_2 = fields.Boolean(compute='_compute_show_cfe_quantity', store=True)
    show_mo_internal_ref = fields.Boolean(compute='_compute_show_cfe_quantity', store=True)
    po_line_id = fields.Many2one(string='Related PO line',comodel_name='purchase.order.line')
    customer_po_line_id = fields.Many2one(string='Related Customer PO line',comodel_name='purchase.order.line')


    def validate_third_boolean(self):
        """
        Check rules before allowing the 3rd boolean to be ticked.
        Now uses context data for validation and returns PO result.
        """
        root_bom_id = self.env.context.get('root_bom_id') or self.bom_id.id
        results = []
        qty = self.env.context.get('qty')

        for line in self:
            # Get context data for validation
            # context_data = self.env['mrp.bom.context'].get_context_data(root_bom_id, line.id)

            lli = line.lli
            a1 = line.approval_1
            a2 = line.approval_2
            cfe_quantity = line.cfe_quantity


            # Only if all three would become True
            if lli and a1 and a2:

                if not cfe_quantity or float(cfe_quantity or 0) <= 0:
                    raise ValidationError("⚠️ CFE Quantity must be > 0 before enabling all 3 flags.")

                if float(cfe_quantity) >= qty:
                    raise ValidationError("⚠️ CFE Quantity must be smaller then the Quantity.")

                # Get root BOM for project validation
                root_bom = self.env['mrp.bom'].browse(root_bom_id)
                if not root_bom.project_id or not root_bom.project_id.partner_id:
                    raise ValidationError("⚠️ Project Partner must be set on root BOM before enabling all 3 flags.")

                # Vendor check
                diff = qty - int(cfe_quantity)
                if diff >= 1:
                    main_vendor = line.product_id.seller_ids.filtered(lambda s: s.main_vendor)
                    vendor = main_vendor[0] if main_vendor else line.product_id._select_seller()

                    if not vendor:
                        raise ValidationError(
                            f"⚠️ No vendor defined for {line.product_id.display_name}. Please configure at least one vendor."
                        )

                # If validation passes, create POs immediately
                po_result = self._create_instant_pos_with_context(root_bom_id, line,qty)
                results.append({
                    "bom_line_id": line.id,
                    **po_result
                })
            else:
                print("⏩ Not all three flags are TRUE → no validation triggered")

        return results if results else True


    def _create_instant_pos_with_context(self, root_bom_id, bom_line, qty):
        """Create instant POs respecting independent rules for customer/vendor with detailed messages."""
        result = {
            "customer_po": False,
            "vendor_po": False,
            "customer_po_id": False,
            "vendor_po_id": False,
            "customer_po_name": False,
            "vendor_po_name": False,
            "messages": [],  # detailed messages
        }

        cfe_qty = float(bom_line.cfe_quantity or 0)
        required_qty = float(qty or 0)
        remaining_qty = required_qty - cfe_qty

        root_bom = self.env['mrp.bom'].browse(root_bom_id)
        project_partner = root_bom.project_id.partner_id if root_bom.project_id else None
        product_code = root_bom.product_id.default_code or root_bom.product_tmpl_id.default_code or ''
        product_name = root_bom.product_id.name or root_bom.product_tmpl_id.name or ''
        cfe_project_location_id = root_bom.cfe_project_location_id

        # ----------------------------
        # CUSTOMER PO (with bom_line_id)
        # ----------------------------
        create_customer_po = False
        existing_customer_po_line = self.env['purchase.order.line'].search([
            ('bom_id','=',root_bom_id),
            ('product_id', '=', bom_line.product_id.id),
            ('order_id.partner_id', '=', project_partner.id),
            ('bom_line_ids', 'in', [bom_line.id]),
            ("order_id.state", "=", "draft"),
        ], order="id desc",limit=1)

        existing_customer_po = existing_customer_po_line.order_id if existing_customer_po_line else False

        if existing_customer_po:
            if existing_customer_po_line.order_id.state == 'draft':
                existing_customer_po.cfe_project_location_id = cfe_project_location_id.id


        if not bom_line.customer_po_created:
            create_customer_po = True
        elif existing_customer_po and existing_customer_po.state != 'draft':
            # ✅ if PO exists but not in draft, create new
            create_customer_po = True
        elif not existing_customer_po:
            create_customer_po = True
        else:
            result['messages'].append(
                f"Customer PO not created for {bom_line.product_id.display_name}: "
                f"already exists ({existing_customer_po.name if existing_customer_po else 'N/A'}) "
            )

        if create_customer_po:
            if not project_partner:
                result['messages'].append(
                    f"Customer PO not created for {bom_line.product_id.display_name}: Project partner missing."
                )
            elif cfe_qty <= 0:
                result['messages'].append(
                    f"Customer PO not created for {bom_line.product_id.display_name}: CFE Quantity <= 0."
                )
            else:
                po_exist = self.env['purchase.order'].search([('bom_id','=',root_bom_id),('state','=','draft'),("partner_id", "=", project_partner.id),])

                if po_exist:
                    if po_exist:
                        po_exist.cfe_project_location_id = cfe_project_location_id.id
                        po_line = po_exist.order_line.filtered(lambda l: l.product_id.id == bom_line.product_id.id)
                        if po_line:
                            po_line.product_qty += cfe_qty
                            bom_line.customer_po_line_id = po_line.id
                            if bom_line.id not in po_line.bom_line_ids.ids:
                                po_line.bom_line_ids = [(4, bom_line.id)]

                            result['messages'].append(
                                f"🔄 Updated Customer PO {po_exist.name}: added {cfe_qty} to {bom_line.product_id.display_name}"
                            )
                        else:
                            cpo_line_vals = {
                                "order_id": po_exist.id,
                                "product_id": bom_line.product_id.id,
                                "product_qty": cfe_qty,
                                "product_uom": bom_line.product_id.uom_po_id.id,
                                "price_unit": 0.0,
                                "date_planned": fields.Datetime.now(),
                                "name": f"CFE - {bom_line.product_id.display_name}",
                                "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
                                'bom_id':root_bom_id,
                            }

                            if bom_line.product_manufacturer_id:
                                cpo_line_vals["manufacturer_id"] = bom_line.product_manufacturer_id.id
                            cr_cpo = self.env["purchase.order.line"].create(cpo_line_vals)
                            bom_line.customer_po_line_id = cr_cpo.id
                            result['messages'].append(
                                f"➕ Added {bom_line.product_id.display_name} ({cfe_qty}) to Customer PO {po_exist.name}"
                            )

                        bom_line.customer_po_created = True

                else:
                    customer_po_vals = {
                        'partner_id': project_partner.id,
                        'cfe_project_location_id': cfe_project_location_id.id if cfe_project_location_id else False,
                        'origin': f"EVR-Manufacture - [{product_code}] {product_name}",
                        'state': 'draft',
                        'bom_id':root_bom_id,
                        'order_line': [(0, 0, {
                            'product_id': bom_line.product_id.id,
                            'product_qty': cfe_qty,
                            'product_uom': bom_line.product_id.uom_po_id.id,
                            'price_unit': 0.0,
                            'date_planned': fields.Datetime.now(),
                            'name': f"CFE - {bom_line.product_id.display_name}",
                            'manufacturer_id': bom_line.product_manufacturer_id.id if bom_line.product_manufacturer_id else False,
                            'bom_line_ids': [(6, 0, [bom_line.id])],
                            'bom_id':root_bom_id,
                        })]
                    }

                    customer_po = self.env['purchase.order'].create(customer_po_vals)
                    find_cpo_line = self.env["purchase.order.line"].search(
                        [('product_id', '=', bom_line.product_id.id), ('order_id', '=', customer_po.id)])
                    bom_line.customer_po_line_id = find_cpo_line.id
                    bom_line.customer_po_created = True
                    result.update({
                        'customer_po': True,
                        'customer_po_id': customer_po.id,
                        'customer_po_name': customer_po.name
                    })
                    result['messages'].append(f"✅ Customer PO created: {customer_po.name} ({cfe_qty})")

        # ----------------------------
        # VENDOR PO (Check draft first, then follow full flow)
        # ----------------------------
        if remaining_qty > 0:
            vendor = (bom_line.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                      or bom_line.product_id._select_seller())

            if not vendor or not vendor.partner_id:
                result['messages'].append(
                    f"⚠️ Vendor PO not created for {bom_line.product_id.display_name} ({remaining_qty}): Vendor not configured properly."
                )
                return result

            price = vendor.price or bom_line.product_id.list_price
            if not price:
                result['messages'].append(
                    f"⚠️ Vendor PO not created for {bom_line.product_id.display_name} ({remaining_qty}): No price found."
                )
                return result

            manufacturer_id = bom_line.product_manufacturer_id.id if bom_line.product_manufacturer_id else False
            mo_internal_ref = getattr(bom_line.bom_id, 'mo_internal_ref', False)
            bom = bom_line.bom_id

            # 1️⃣ Check if draft Vendor PO exists
            draft_po_line = self.env["purchase.order.line"].search([
                ("order_id.partner_id", "=", vendor.partner_id.id),
                ("product_id", "=", bom_line.product_id.id),
                ("bom_line_ids", "in", [bom_line.id]),
                ("order_id.state", "=", "draft")
            ], order="id desc",limit=1)

            if draft_po_line:
                draft_po_line.order_id.cfe_project_location_id = cfe_project_location_id.id
                # Draft exists → do nothing
                result['messages'].append(
                    f"ℹ️ Vendor PO {draft_po_line.order_id.name} already exists in draft for {bom_line.product_id.display_name}, no action needed."
                )
                bom_line.vendor_po_created = True
                result.update({
                    "vendor_po": True,
                    "vendor_po_id": draft_po_line.order_id.id,
                    "vendor_po_name": draft_po_line.order_id.name
                })
                return result

            # 2️⃣ No draft Vendor PO → check non-draft Vendor PO (log warning)
            existing_vpo_line = self.env["purchase.order.line"].search([
                ("order_id.partner_id", "=", vendor.partner_id.id),
                ("product_id", "=", bom_line.product_id.id),
                ("bom_line_ids", "in", [bom_line.id]),
                ("order_id.state", "!=", "draft")
            ],order="id desc", limit=1)

            if existing_vpo_line:
                existing_vpo_line.order_id.cfe_project_location_id = cfe_project_location_id.id
                result['messages'].append(
                    f"⚠️ Vendor PO {existing_vpo_line.order_id.name} exists but not in draft, creating new PO."
                )

            # 3️⃣ No Vendor PO exists → check draft Customer PO for this product
            draft_cpo = self.env["purchase.order"].search([
                ("partner_id", "=", vendor.partner_id.id),
                ("state", "=", "draft")
            ], order="id desc", limit=1)

            if draft_cpo:
                draft_cpo.cfe_project_location_id = cfe_project_location_id.id
                cpo_line = draft_cpo.order_line.filtered(lambda l: l.product_id.id == bom_line.product_id.id)
                if cpo_line:
                    cpo_line.product_qty += remaining_qty
                    # cpo_line.bom_line_id = bom_line.id
                    bom_line.po_line_id = cpo_line.id

                    if bom_line.id not in cpo_line.bom_line_ids.ids:
                        cpo_line.bom_line_ids = [(4, bom_line.id)]
                    cpo_line.manufacturer_id = manufacturer_id
                    result['messages'].append(
                        f"🔄 Updated Vendor PO {draft_cpo.name}: added {remaining_qty} to {bom_line.product_id.display_name}"
                    )
                else:
                    po_line_vals = {
                        "order_id": draft_cpo.id,
                        "product_id": bom_line.product_id.id,
                        "product_qty": remaining_qty,
                        "product_uom": bom_line.product_id.uom_po_id.id,
                        "price_unit": 0.0,
                        "date_planned": fields.Datetime.now(),
                        "name": f"CFE - {bom_line.product_id.display_name}",
                        "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
                    }
                    if manufacturer_id:
                        po_line_vals["manufacturer_id"] = manufacturer_id
                    new_po_line = self.env["purchase.order.line"].create(po_line_vals)
                    bom_line.po_line_id = new_po_line.id

                    result['messages'].append(
                        f"➕ Added {bom_line.product_id.display_name} ({remaining_qty}) to Vendor PO {draft_cpo.name}"
                    )
                bom_line.vendor_po_created = True
                result.update({
                    "vendor_po": True,
                    "vendor_po_id": draft_cpo.id,
                    "vendor_po_name": draft_cpo.name
                })
                return result

            # 4️⃣ No draft Customer PO → create new Vendor PO
            po_line_vals = {
                "product_id": bom_line.product_id.id,
                "product_qty": remaining_qty,
                "product_uom": bom_line.product_id.uom_po_id.id,
                "price_unit": price,
                "date_planned": fields.Datetime.now(),
                "name": f"Vendor - {bom_line.product_id.display_name}",
                "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
            }
            if manufacturer_id:
                po_line_vals["manufacturer_id"] = manufacturer_id

            vendor_po_vals = {
                "partner_id": vendor.partner_id.id,
                "origin": f"BOM {bom.display_name}",
                "order_line": [(0, 0, po_line_vals)],
                'cfe_project_location_id':cfe_project_location_id.id
            }
            if bom.is_evr and cfe_project_location_id:
                vendor_po_vals.update({"cfe_project_location_id": cfe_project_location_id.id})
            if mo_internal_ref:
                vendor_po_vals["mo_internal_ref"] = mo_internal_ref

            vpo = self.env["purchase.order"].create(vendor_po_vals)
            find_po_line = self.env["purchase.order.line"].search([('product_id','=',bom_line.product_id.id),('order_id','=',vpo.id)])
            bom_line.po_line_id = find_po_line.id

            bom_line.vendor_po_created = True
            result.update({
                "vendor_po": True,
                "vendor_po_id": vpo.id,
                "vendor_po_name": vpo.name
            })
            result['messages'].append(
                f"✅ Vendor PO {vpo.name} created for {bom_line.product_id.display_name} ({remaining_qty})"
            )
            return result

        return result






