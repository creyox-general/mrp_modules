# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models, fields


class ApprovalRequest(models.Model):
    _inherit = 'approval.request'

    def action_create_purchase_orders(self):
        """ Create and/or modify Purchase Orders. """
        self.ensure_one()
        self.product_line_ids._check_products_vendor()

        for line in self.product_line_ids:
            seller = line.seller_id
            vendor = seller.partner_id
            po_domain = line._get_purchase_orders_domain(vendor)
            po_domain.append(('po_type', '=', 'urgt'))

            purchase_orders = self.env['purchase.order'].search(po_domain)

            if purchase_orders:
                purchase_line = self.env['purchase.order.line'].search([
                    ('order_id', 'in', purchase_orders.ids),
                    ('product_id', '=', line.product_id.id),
                    ('product_uom', '=', line.product_id.uom_po_id.id),
                ], limit=1)

                if purchase_line:
                    line.purchase_order_line_id = purchase_line.id
                    purchase_line.product_qty += line.po_uom_qty
                    purchase_order = purchase_line.order_id
                    purchase_order.po_type = 'urgt'

                    # Add custom fields from line
                    if line.cr_component_id:
                        purchase_line.component_branch_id = line.cr_component_id

                        comp = self.env['mrp.bom.line.branch.components'].browse(line.cr_component_id)
                        comp.vendor_po_ids = [(4, purchase_line.id)]
                    if line.cr_root_bom_id:
                        purchase_line.bom_id = line.cr_root_bom_id
                        bom = self.env['mrp.bom'].browse(line.cr_root_bom_id)
                        purchase_line.project_id = bom.project_id.id
                    if line.cr_bom_line_id:
                        purchase_line.bom_line_ids = [(4, line.cr_bom_line_id)]

                    if line.cr_bom_line_id:
                        bom_line = self.env['mrp.bom.line'].browse(line.cr_bom_line_id)
                        if bom_line:
                            bom_line.po_line_id = purchase_line.id

                else:
                    purchase_order = purchase_orders[0]
                    po_line_vals = self.env['purchase.order.line']._prepare_purchase_order_line(
                        line.product_id,
                        line.quantity,
                        line.product_uom_id,
                        line.company_id,
                        seller,
                        purchase_order,
                    )

                    # Add custom fields from line
                    if line.cr_component_id:
                        po_line_vals['component_branch_id'] = line.cr_component_id
                    if line.cr_root_bom_id:
                        po_line_vals['bom_id'] = line.cr_root_bom_id
                        bom = self.env['mrp.bom'].browse(line.cr_root_bom_id)
                        po_line_vals['project_id'] = bom.project_id.id
                    if line.cr_bom_line_id:
                        po_line_vals['bom_line_ids'] = [(6, 0, [line.cr_bom_line_id])]


                    new_po_line = self.env['purchase.order.line'].create(po_line_vals)
                    if line.cr_component_id:
                        comp = self.env['mrp.bom.line.branch.components'].browse(line.cr_component_id)
                        comp.vendor_po_ids = [(4, new_po_line.id)]
                    # line.cr_bom_line_id.po_line_id = new_po_line.id
                    line.purchase_order_line_id = new_po_line.id
                    purchase_order.order_line = [(4, new_po_line.id)]
                    purchase_order.po_type = 'urgt'

                    # Attach PO line to BOM line
                    if line.cr_bom_line_id:
                        bom_line = self.env['mrp.bom.line'].browse(line.cr_bom_line_id)
                        if bom_line:
                            bom_line.po_line_id = new_po_line.id

                # Add origin
                new_origin = set([self.name])
                if purchase_order.origin:
                    missing_origin = new_origin - set(purchase_order.origin.split(', '))
                    if missing_origin:
                        purchase_order.write({'origin': purchase_order.origin + ', ' + ', '.join(missing_origin)})
                else:
                    purchase_order.write({'origin': ', '.join(new_origin)})
            else:
                po_vals = line._get_purchase_order_values(vendor)
                po_vals['po_type'] = 'urgt'

                if line.cr_root_bom_id:
                    root_bom = self.env['mrp.bom'].browse(line.cr_root_bom_id)
                    if root_bom and root_bom.cfe_project_location_id:
                        po_vals['cfe_project_location_id'] = root_bom.cfe_project_location_id.id
                    po_vals['bom_id'] = line.cr_root_bom_id

                new_purchase_order = self.env['purchase.order'].create(po_vals)

                po_line_vals = self.env['purchase.order.line']._prepare_purchase_order_line(
                    line.product_id,
                    line.quantity,
                    line.product_uom_id,
                    line.company_id,
                    seller,
                    new_purchase_order,
                )

                # Add custom fields from line
                if line.cr_component_id:
                    po_line_vals['component_branch_id'] = line.cr_component_id
                if line.cr_root_bom_id:
                    po_line_vals['bom_id'] = line.cr_root_bom_id
                    bom = self.env['mrp.bom'].browse(line.cr_root_bom_id)
                    po_line_vals['project_id'] = bom.project_id.id
                if line.cr_bom_line_id:
                    po_line_vals['bom_line_ids'] = [(6, 0, [line.cr_bom_line_id])]

                new_po_line = self.env['purchase.order.line'].create(po_line_vals)
                if line.cr_component_id:
                    comp = self.env['mrp.bom.line.branch.components'].browse(line.cr_component_id)
                    comp.vendor_po_ids = [(4, new_po_line.id)]
                line.purchase_order_line_id = new_po_line.id
                new_purchase_order.order_line = [(4, new_po_line.id)]

                # Attach PO line to BOM line
                if line.cr_bom_line_id:
                    bom_line = self.env['mrp.bom.line'].browse(line.cr_bom_line_id)
                    if bom_line:
                        bom_line.po_line_id = new_po_line.id