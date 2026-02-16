# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api,fields
import logging

from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"


    approve_to_manufacture = fields.Boolean(
        string='Approve to Manufacture',
        default=False,
        help="If checked, MO will be created for this BOM line"
    )

    customer_ref = fields.Char(string='Customer ref')

    def write(self, vals):
        quantity_changed = 'product_qty' in vals

        res = super().write(vals)

        if quantity_changed and not self.env.context.get('skip_mo_qty_update'):
            for line in self:
                if line.bom_id.is_evr and line.child_bom_id:
                    self._update_child_mo_quantities(line, line.bom_id.id)


        return res

    def _update_child_mo_quantities(self, line, root_bom_id, parent_qty=1.0):
        """Recursively update MO quantities for this line and all its children"""
        # Find MOs for this line
        mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom_id),
            ('line', '=', line.id),
            ('state', '=', 'draft')
        ])

        for mo in mos:
            # Calculate new quantity
            new_qty = float(line.product_qty or 1.0) * parent_qty

            # Get locations from context or recalculate
            Branch = self.env['mrp.bom.line.branch']
            branches = Branch.search([
                ('bom_id', '=', root_bom_id),
                ('bom_line_id', '=', line.id)
            ], order='sequence', limit=1)

            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            stock_location = warehouse.lot_stock_id if warehouse else False

            current_branch_location = branches.location_id.id if branches and branches.location_id else False
            print('_update_child_mo_quantities :')
            parent_branch_location = mo.parent_mo_id.branch_intermediate_location_id.id if mo.parent_mo_id else False
            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # Update MO with all three locations - USE with_context to skip component recalculation
            mo.with_context(skip_compute_move_raw_ids=True).write({
                'product_qty': new_qty,
                'location_src_id': stock_location.id if stock_location else mo.location_src_id.id,
                'branch_intermediate_location_id': current_branch_location if current_branch_location else mo.branch_intermediate_location_id.id,
                'location_dest_id': final_dest_location if final_dest_location else mo.location_dest_id.id,
            })

            # Update child MOs recursively
            if line.child_bom_id:
                for child_line in line.child_bom_id.bom_line_ids:
                    if child_line.child_bom_id:
                        self._update_child_mo_quantities(child_line, root_bom_id, new_qty)

    def _collect_affected_root_boms(self):
        """
        For this recordset of bom.lines return a set of root BOMs that must be
        recalculated. Only returns BOMs that are EVR and have project location.
        """
        helpers = self.env['cr.mrp.bom.helpers']
        affected_roots = set()

        for line in self:
            # 1) roots for the containing BOM of this line
            if line.bom_id:
                roots = helpers.get_root_boms_for_bom(line.bom_id)
                for r in roots:
                    if r.is_evr and r.cfe_project_location_id:
                        affected_roots.add(r.id)

            # 2) if this line itself points to a child BOM, include roots for that child
            if line.child_bom_id:
                roots_child = helpers.get_root_boms_for_bom(line.child_bom_id)
                for r in roots_child:
                    if r.is_evr and r.cfe_project_location_id:
                        affected_roots.add(r.id)

        # return browse recordset of root BOMs
        return self.env['mrp.bom'].browse(list(affected_roots))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super(MrpBomLine, self.with_context(skip_branch_recompute=True)).create(vals_list)

        if not self.env.context.get('skip_branch_recompute'):
            roots = lines._collect_affected_root_boms()
            if roots:
                for root in roots:
                    try:
                        root._assign_branches_for_bom()
                    except Exception:
                        _logger.exception(f"Error assigning branches for root BOM {root.id} after create")

        return lines

    def unlink(self):
        roots = self._collect_affected_root_boms() if not self.env.context.get('skip_branch_recompute') else self.env[
            'mrp.bom']

        res = super(MrpBomLine, self.with_context(skip_branch_recompute=True)).unlink()

        if roots:
            for root in roots:
                try:
                    root._assign_branches_for_bom()
                except Exception:
                    _logger.exception(f"Error assigning branches for root BOM {root.id} after unlink")

        return res



    def _skip_bom_line(self, product, never_attribute_values=False):
        """Override to pass context when exploding child BOMs"""
        result = super()._skip_bom_line(product,never_attribute_values)

        if result and self.bom_id.is_evr:
            # Pass this line's ID in context for child BOM explosion
            return result.with_context(parent_bom_line_id=self.id)

        return result

    def _get_branch_component_for_po(self, root_bom_id):
        """
        Find the correct branch component for this BOM line.
        Uses the same cache logic as the report to ensure consistency.
        """
        Component = self.env["mrp.bom.line.branch.components"]

        # Check for child BOM - if it has one, it's not a component
        child_bom = self.env['mrp.bom']._bom_find(self.product_id, bom_type='normal')
        if child_bom:
            return False

        parent_bom = self.bom_id

        # ROOT LEVEL COMPONENT
        if not parent_bom.parent_id or parent_bom.id == root_bom_id:
            components = Component.search([
                ('root_bom_id', '=', root_bom_id),
                ('bom_id', '=', parent_bom.id),
                ('cr_bom_line_id', '=', self.id),
                ('is_direct_component', '=', True),
            ])

            if not components:
                return False

            if len(components) == 1:
                return components[0]

            # Multiple components - return first one for PO creation
            return components[0]

        # CHILD LEVEL COMPONENT
        components = Component.search([
            ('root_bom_id', '=', root_bom_id),
            ('bom_id', '=', parent_bom.id),
            ('cr_bom_line_id', '=', self.id),
            ('is_direct_component', '=', False),
        ], order='id')

        if not components:
            return False

        return components[0]

    def validate_third_boolean(self):
        """
        Check rules before allowing the 3rd boolean to be ticked.
        Now uses context data for validation and returns PO result.
        """
        root_bom_id = self.env.context.get('root_bom_id') or self.bom_id.id
        results = []
        qty = self.env.context.get('qty')
        componentId = self.env.context.get('componentId')

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
                po_result = self._create_instant_pos_with_context(root_bom_id, line,qty,componentId)
                results.append({
                    "bom_line_id": line.id,
                    **po_result
                })
            else:
                print("⏩ Not all three flags are TRUE → no validation triggered")

        return results if results else True


    def _create_instant_pos_with_context(self, root_bom_id, bom_line, qty,componentId):
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
            ("component_branch_id",'=',componentId)
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

                        cpo_line_vals = {
                            "order_id": po_exist.id,
                            "product_id": bom_line.product_id.id,
                            "product_qty": cfe_qty,
                            "product_uom": bom_line.product_id.uom_po_id.id,
                            "price_unit": 0.0,
                            "date_planned": fields.Datetime.now(),
                            "name": f"CFE - {bom_line.product_id.display_name}",
                            "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
                            'bom_id': root_bom_id,
                            'component_branch_id':componentId,
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
                            'component_branch_id': componentId,
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
                ("order_id.state", "=", "draft"),
                ("component_branch_id", '=', componentId)
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
                ("order_id.state", "!=", "draft"),
                ("component_branch_id", '=', componentId)
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

                po_line_vals = {
                    "order_id": draft_cpo.id,
                    "product_id": bom_line.product_id.id,
                    "product_qty": remaining_qty,
                    "product_uom": bom_line.product_id.uom_po_id.id,
                    "price_unit": 0.0,
                    "date_planned": fields.Datetime.now(),
                    "name": f"CFE - {bom_line.product_id.display_name}",
                    "bom_line_ids": [(6, 0, [bom_line.id])],  # 🔹 updated
                    "component_branch_id":componentId
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
                "component_branch_id": componentId
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

    def action_toggle_approve_to_manufacture(self, approve):
        self.ensure_one()
        root_bom = self.env.context.get('root_bom_id')

        if not approve:
            self.approve_to_manufacture = False
            return {
                "success": True,
                "message": "Approval removed."
            }

        if not root_bom:
            return {
                "success": False,
                "message": "Root BOM not found in context."
            }

        # Find Parent MO
        print('root_bom : ',root_bom)
        print('self.id : ', self.id)
        parent_mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom),
            ('line', '=', self.id),
            ('state', '=', 'draft')
        ])

        if not parent_mos:
            return {
                "success": False,
                "message": "No parent MO found for this BOM line."
            }

        for parent_mo in parent_mos:
            child_mos = self.env['mrp.production'].search([
                ('parent_mo_id', '=', parent_mo.id)
            ])

            # If no child MOs → allow confirm
            if not child_mos:
                if approve:
                    self.approve_to_manufacture = True
                    print('parent_mo : ',parent_mo)
                    parent_mo.action_confirm()
                    return {
                        "success": True,
                        "message": f"Parent MO {parent_mo.name} confirmed (no child MOs)."
                    }

            # Validate children approval
            not_ready = child_mos.filtered(lambda mo: mo.state == 'draft')

            if not_ready:
                return {
                    "success": False,
                    "message": "Some child Manufacturing Orders are not approved yet."
                }

            # ✅ All Approved
            if approve:
                self.approve_to_manufacture = True
                parent_mo.action_confirm()

                return {
                    "success": True,
                    "message": f"Parent MO {parent_mo.name} auto-confirmed."
                }

        return {
            "success": False,
            "message": "Unexpected condition reached."
        }