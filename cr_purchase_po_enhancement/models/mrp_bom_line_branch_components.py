# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpBomLineBranchComponents(models.Model):
    _inherit = "mrp.bom.line.branch.components"


    def _create_or_update_cfe_po(self, customer, quantity):
        """Create or update CFE purchase order"""
        POLine = self.env["purchase.order.line"]
        PO = self.env["purchase.order"]

        # Find existing draft CFE PO line for this component
        existing_line = POLine.search([
            ("component_branch_id", "=", self.id),
            ("order_id.partner_id", "=", customer.id),
            ("order_id.state", "=", "draft"),
            ("bom_id", "=", self.root_bom_id.id),
        ], limit=1)

        if existing_line:
            existing_line.order_id.po_type = 'mrp'

            if existing_line.product_qty != quantity:
                existing_line.product_qty = quantity
                self.customer_po_ids = [(4, existing_line.id)]

            self.cr_bom_line_id.customer_po_line_id = POLine.id

            self._send_notification(
                "Purchase Order Updated (CFE)",
                f"Updated Qty to {existing_line.product_qty} for {existing_line.order_id.name}",
                "success"
            )

        else:
            company = self.env.company

            # Find or create CFE PO
            po = PO.search([
                ("partner_id", "=", customer.id),
                ("state", "=", "draft"),
                ("bom_id", "=", self.root_bom_id.id),
                ("po_type", "=", "mrp"),
                ("cfe", '=', True),
            ], limit=1)


            if not po:
                po = PO.create({
                    "partner_id": customer.id,
                    "bom_id": self.root_bom_id.id,
                    "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                    "cfe_project_location_id": self.root_bom_id.cfe_project_location_id.id,
                    "state":'draft',
                    "po_type":"mrp",
                    "cfe": True,
                })


            POLine.create({
                "order_id": po.id,
                "product_id": self.cr_bom_line_id.product_id.id,
                "product_qty": quantity,
                "product_uom": self.cr_bom_line_id.product_id.uom_po_id.id,
                "price_unit": 0.0,
                "date_planned": fields.Datetime.now(),
                "component_branch_id": self.id,
                "bom_line_ids": [(6, 0, [self.cr_bom_line_id.id])],
                "bom_id":self.root_bom_id.id,
                "project_id":self.root_bom_id.project_id.id,
            })

            find_cpo_line = self.env["purchase.order.line"].sudo().search(
                [('product_id', '=', self.cr_bom_line_id.product_id.id), ('order_id', '=', po.id),('component_branch_id','=',self.id)])
            self.cr_bom_line_id.customer_po_line_id = find_cpo_line.id
            self.customer_po_ids = [(4, find_cpo_line.id)]
            find_cpo_line.order_id.po_type = 'mrp'

            self._send_notification(
                "Purchase Order Created",
                f"Created PO {find_cpo_line.order_id.name} for {self.cr_bom_line_id.product_id.display_name} ({quantity})",
                "success"
            )



    def _create_or_update_po(self, quantity):
        """Create or update regular purchase order"""
        _logger.info("START _create_or_update_po | component=%s quantity=%s", self.id, quantity)

        POLine = self.env["purchase.order.line"]
        PO = self.env["purchase.order"]

        bom_line = self.cr_bom_line_id
        vendor = (bom_line.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                  or bom_line.product_id._select_seller())

        _logger.info("Vendor found: %s", vendor.partner_id.name if vendor and vendor.partner_id else None)

        if not vendor or not vendor.partner_id:
            _logger.info("No vendor or partner, EXIT")
            return

        # Find existing draft PO line for this component
        existing_line = POLine.search([
            ("component_branch_id", "=", self.id),
            ("order_id.partner_id", "=", vendor.partner_id.id),
            ("order_id.state", "=", "draft"),
            ("bom_id", "=", self.root_bom_id.id),
        ], limit=1)

        _logger.info("Existing PO line found: %s", existing_line.id if existing_line else None)

        if existing_line:
            # Update existing line
            existing_line.order_id.po_type = 'mrp'
            existing_line.manufacturer_id = bom_line.product_manufacturer_id.id
            self.vendor_po_ids = [(4, existing_line.id)]
            if existing_line.product_qty != quantity:
                existing_line.product_qty = quantity
                _logger.info("Updated existing PO line qty to %s", quantity)

            self.cr_bom_line_id.po_line_id = POLine.id
            self._send_notification(
                "Purchase Order Updated (Non - CFE)",
                f"Updated Qty to {existing_line.product_qty} for {existing_line.order_id.name}",
                "success"
            )
        else:
            # Find or create PO
            po = PO.search([
                ("partner_id", "=", vendor.partner_id.id),
                ("state", "=", "draft"),
                ("bom_id", "=", self.root_bom_id.id),
                ("po_type", "=", "mrp"),
                ("cfe", '=', False)
            ], limit=1)

            company = self.env.company


            if not po:
                po = PO.create({
                    "partner_id": vendor.partner_id.id,
                    "bom_id": self.root_bom_id.id,
                    "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                    "cfe_project_location_id": self.root_bom_id.cfe_project_location_id.id,
                    "state": 'draft',
                    "po_type": "mrp",
                })
                _logger.info("Created new PO: %s", po.id)

            price = vendor.price or bom_line.product_id.list_price

            new_line = POLine.create({
                "order_id": po.id,
                "product_id": bom_line.product_id.id,
                "product_qty": quantity,
                "product_uom": bom_line.product_id.uom_po_id.id,
                "price_unit": price,
                "date_planned": fields.Datetime.now(),
                "component_branch_id": self.id,
                "bom_line_ids": [(6, 0, [bom_line.id])],
                "bom_id": self.root_bom_id.id,
                "project_id": self.root_bom_id.project_id.id,
                "manufacturer_id": bom_line.product_manufacturer_id.id,
            })
            _logger.info("Created new PO line: %s qty=%s", new_line.id, quantity)



            find_vpo_line = self.env["purchase.order.line"].search([
                ('product_id', '=', self.cr_bom_line_id.product_id.id),
                ('order_id', '=', po.id),
                ('component_branch_id', '=', self.id)
            ])
            find_vpo_line.order_id.po_type = 'mrp'
            self.cr_bom_line_id.po_line_id = find_vpo_line.id
            self.vendor_po_ids = [(4, find_vpo_line.id)]
            _logger.info("Linked new PO line %s to component branch %s", find_vpo_line.id, self.id)

            self._send_notification(
                "Purchase Order Created",
                f"Created PO {find_vpo_line.order_id.name} for {self.cr_bom_line_id.product_id.display_name} ({quantity})",
                "success"
            )

        _logger.info("END _create_or_update_po")





