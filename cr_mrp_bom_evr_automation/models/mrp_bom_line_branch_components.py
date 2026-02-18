# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class MrpBomLineBranchComponents(models.Model):
    _inherit = "mrp.bom.line.branch.components"

    def _process_purchase_flow(self):
        """Process purchase flow for this component"""
        self.ensure_one()

        bom_line = self.cr_bom_line_id
        if not bom_line:
            return

        # Check if approvals are TRUE
        if not (self.approval_1 and self.approval_2):
            return

        # Process CFE flow
        self._process_cfe_flow()

        # Process regular purchase flow
        self._process_regular_flow()

    def _process_cfe_flow(self):
        """Process CFE (Customer Furnished Equipment) flow"""
        self.ensure_one()
        bom_line = self.cr_bom_line_id
        cfe_qty = float(self.cfe_quantity or 0)

        if cfe_qty <= 0:
            return

        # Check if CFE is already fully used
        if cfe_qty == self.used:
            return

        root_bom = self.root_bom_id
        customer = root_bom.project_id.partner_id if root_bom.project_id else False

        if not customer:
            return

        # 1. Calculate Transferred CFE
        transferred_cfe = self._calculate_transferred_cfe(customer)
        self.transferred_cfe = transferred_cfe

        if self.transferred_cfe >= cfe_qty:
            self.transferred_cfe = cfe_qty
            # 2. Calculate To Transfer CFE
            self.to_transfer_cfe = 0

            # 3. Calculate Ordered CFE
            self.ordered_cfe = 0

            # 4. Calculate To Order CFE
            self.to_order_cfe = 0

            self._adjust_cfe_po_quantity(customer, 0)

        else:
            # 2. Calculate To Transfer CFE
            to_transfer_cfe = self._calculate_to_transfer_cfe(customer, cfe_qty, transferred_cfe)
            self.to_transfer_cfe = to_transfer_cfe

            total = self.transferred_cfe + self.to_transfer_cfe
            if total < cfe_qty :
                needed = cfe_qty - total
                # 3. Calculate Ordered CFE
                ordered_cfe = self._calculate_ordered_cfe(customer)

                ordered_cfe = min(needed,ordered_cfe)

                self.ordered_cfe = ordered_cfe

                # 4. Calculate To Order CFE
                to_order_cfe = cfe_qty - transferred_cfe - to_transfer_cfe - ordered_cfe

                self.to_order_cfe = max(0, to_order_cfe)

                # 5. Create/Update CFE Purchase Order
                if to_order_cfe > 0:
                    self._create_or_update_cfe_po(customer, to_order_cfe)
                else:
                    self._adjust_cfe_po_quantity(customer, to_order_cfe)
            else:
                self.ordered_cfe = 0
                self.to_order_cfe = 0
                self._adjust_cfe_po_quantity(customer, 0)


    def _process_regular_flow(self):
        """Process regular (non-CFE) purchase flow"""
        self.ensure_one()

        bom_line = self.cr_bom_line_id
        cfe_qty = float(self.cfe_quantity or 0)
        # total_qty = self._get_actual_component_quantity()
        total_qty = self.quantity
        x_qty = total_qty - cfe_qty
        if x_qty <= 0:
            return

        # Check if fully used
        if x_qty == self.used:
            return

        # 1. Calculate Transferred
        transferred = self._calculate_transferred()
        self.transferred = transferred

        if self.transferred >= x_qty:
            self.transferred = x_qty
            # 2. Calculate To Transfer CFE
            self.to_transfer = 0

            # 3. Calculate Ordered CFE
            self.ordered = 0

            # 4. Calculate To Order CFE
            self.to_order = 0

            self._adjust_regular_po_quantity(0)

        else:
            # 2. Calculate To Transfer
            to_transfer = self._calculate_to_transfer(x_qty, transferred)
            self.to_transfer = to_transfer

            total = self.transferred + self.to_transfer

            if total < x_qty :
                needed = x_qty - total
                # 3. Calculate Ordered
                ordered = self._calculate_ordered()
                ordered = min(needed,ordered)
                self.ordered = ordered

                # 4. Calculate To Order
                to_order = x_qty - transferred - to_transfer - ordered
                self.to_order = max(0, to_order)

                # 5. Create/Update Purchase Order
                if to_order > 0:
                    self._create_or_update_po(to_order)
                else:
                    self._adjust_regular_po_quantity(0)
            else:
                self.ordered = 0
                self.to_order = 0
                self._adjust_regular_po_quantity(0)



    def _get_actual_component_quantity(self):
        """
        Calculate actual component quantity considering parent BOM hierarchy.
        Traverse from root BOM down to this component, multiplying quantities.
        """
        self.ensure_one()


        bom_line = self.cr_bom_line_id
        if not bom_line:
            return 0.0

        # Start with the line's own quantity
        base_qty = float(bom_line.product_qty or 0)

        # If this is a direct component of root BOM, return as-is
        if self.is_direct_component:
            return base_qty

        root_bom = self.root_bom_id
        target_bom = self.bom_id  # The BOM containing our component


        # Find the path from root to target BOM, collecting quantities
        def find_path_and_multiply(from_bom, to_bom, current_multiplier=1.0, depth=0):
            indent = "  " * depth

            if from_bom.id == to_bom.id:
                return current_multiplier

            # Check all lines in current BOM
            for line in from_bom.bom_line_ids:
                if line.child_bom_id:
                    # Recursively search in child BOM
                    result = find_path_and_multiply(
                        line.child_bom_id,
                        to_bom,
                        current_multiplier * float(line.product_qty or 1.0),
                        depth + 1
                    )

                    if result is not None:
                        return result

            return None

        multiplier = find_path_and_multiply(root_bom, target_bom)

        if multiplier is None:
            total_qty = base_qty
        else:
            total_qty = base_qty * multiplier

        return total_qty

    def _calculate_transferred_cfe(self, customer):
        """Calculate transferred CFE quantity"""
        StockQuant = self.env["stock.quant"]

        quants = StockQuant.sudo().search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("location_id", "=", self.location_id.id),
            ("owner_id", "=", customer.id),
        ])

        return sum(quants.mapped("quantity"))


    def _get_free_stock_owned_by(self, partner):
        """Get free stock quantity owned by specific partner"""
        StockQuant = self.env["stock.quant"]

        quants = StockQuant.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("owner_id", "=", partner.id),
            ("quantity", ">", 0),
        ])

        total = 0.0
        for quant in quants:
            if self._should_consider_location(quant.location_id):
                total += quant.quantity

        return total

    def _should_consider_location(self, location):
        """
        Check if a location should be considered by checking itself and then its parent chain.
        Returns True if the location itself OR any of its ancestors is marked as free.
        Stops checking as soon as a free location is found.
        """
        if not location:
            return False

        cur = location
        while cur:
            is_free = getattr(cur, 'location_category', False) == 'free'

            if is_free:
                return True

            cur = cur.location_id

        return False

    def _calculate_ordered_cfe(self, customer):
        """Calculate ordered CFE quantity from confirmed POs (excluding validated receipts)"""
        POLine = self.env["purchase.order.line"]
        po_lines = POLine.search([
            ("component_branch_id", "=", self.id),
            ("order_id.partner_id", "=", customer.id),
            ("order_id.state", "in", ["purchase", "done"]),
        ])

        # Filter out lines where all stock moves are done
        pending_lines = po_lines.filtered(
            lambda line: any(move.state != 'done' for move in line.move_ids)
        )

        return sum(pending_lines.mapped("product_qty"))

    def _calculate_transferred(self):
        """Calculate transferred quantity (non-CFE)"""
        StockQuant = self.env["stock.quant"]

        quants = StockQuant.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("location_id", "=", self.location_id.id),
            ("owner_id", "=", False),
        ])

        return sum(quants.mapped("quantity"))


    def _get_free_stock_without_owner(self):
        """Get free stock quantity without owner"""
        StockQuant = self.env["stock.quant"]

        quants = StockQuant.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("owner_id", "=", False),
            ("quantity", ">", 0),
        ])

        total = 0.0
        for quant in quants:
            if self._should_consider_location(quant.location_id):
                total += quant.quantity

        return total


    def _calculate_ordered(self):
        """Calculate ordered quantity from confirmed POs (non-CFE, excluding validated receipts)"""
        POLine = self.env["purchase.order.line"]
        vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                  or self.cr_bom_line_id.product_id._select_seller())
        po_lines = POLine.search([
            ("component_branch_id", "=", self.id),
            ("order_id.partner_id", "=", vendor.partner_id.id),
            ("order_id.state", "in", ["purchase", "done"]),
            ("order_id.cfe", "=", False),
        ])

        # Filter out lines where all stock moves are done
        pending_lines = po_lines.filtered(
            lambda line: any(move.state != 'done' for move in line.move_ids)
        )

        return sum(pending_lines.mapped("product_qty"))

    def _create_internal_transfer(self, owner, quantity):
        """Create internal transfer to branch location"""
        StockPicking = self.env["stock.picking"]
        StockLocation = self.env["stock.location"]

        # Find source location (free location with stock)
        free_locations = StockLocation.search([
            ("location_category", "=", "free")
        ])

        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "internal"),
            ("company_id", "=", self.root_bom_id.company_id.id),
        ], limit=1)

        if not picking_type or not free_locations:
            return

        if owner:
            picking_vals = {
                "picking_type_id": picking_type.id,
                "location_dest_id": self.location_id.id,
                "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                "partner_id": owner.id,
                "move_ids": [(0, 0, {
                    "name": self.cr_bom_line_id.product_id.display_name,
                    "product_id": self.cr_bom_line_id.product_id.id,
                    "product_uom_qty": quantity,
                    "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                    "location_dest_id": self.location_id.id,
                    "restrict_partner_id": owner.id if owner else False,
                })],
            }

            StockPicking.create(picking_vals)
        else:
            vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                      or self.cr_bom_line_id.product_id._select_seller())
            picking_vals = {
                "picking_type_id": picking_type.id,
                "location_dest_id": self.location_id.id,
                "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                "partner_id": vendor.partner_id.id,
                "move_ids": [(0, 0, {
                    "name": self.cr_bom_line_id.product_id.display_name,
                    "product_id": self.cr_bom_line_id.product_id.id,
                    "product_uom_qty": quantity,
                    "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                    "location_dest_id": self.location_id.id,
                    "restrict_partner_id": owner.id if owner else False,
                })],
            }

            StockPicking.create(picking_vals)


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
            if existing_line.product_qty != quantity:
                existing_line.product_qty = quantity

            self.cr_bom_line_id.customer_po_line_id = POLine.id

        else:
            # Find or create CFE PO
            po = PO.search([
                ("partner_id", "=", customer.id),
                ("state", "=", "draft"),
                ("bom_id", "=", self.root_bom_id.id),
                ("cfe",'=',True)
            ], limit=1)

            if not po:
                po = PO.create({
                    "partner_id": customer.id,
                    "bom_id": self.root_bom_id.id,
                    "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                    "cfe_project_location_id": self.root_bom_id.cfe_project_location_id.id,
                    "state":'draft',
                    "cfe":True,
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
            })
            find_cpo_line = self.env["purchase.order.line"].search(
                [('product_id', '=', self.cr_bom_line_id.product_id.id), ('order_id', '=', po.id),('component_branch_id','=',self.id)])
            self.cr_bom_line_id.customer_po_line_id = find_cpo_line.id

    def _create_or_update_po(self, quantity):
        """Create or update regular purchase order"""
        POLine = self.env["purchase.order.line"]
        PO = self.env["purchase.order"]

        bom_line = self.cr_bom_line_id
        vendor = (bom_line.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                  or bom_line.product_id._select_seller())

        if not vendor or not vendor.partner_id:
            return

        # Find existing draft PO line for this component
        existing_line = POLine.search([
            ("component_branch_id", "=", self.id),
            ("order_id.partner_id", "=", vendor.partner_id.id),
            ("order_id.state", "=", "draft"),
            ("bom_id", "=", self.root_bom_id.id),
            ("order_id.cfe", "=", False),
        ], limit=1)

        if existing_line:
            # existing_line.product_qty = quantity
            if existing_line.product_qty != quantity:
                existing_line.product_qty = quantity

            self.cr_bom_line_id.po_line_id = POLine.id
        else:
            # Find or create PO
            po = PO.search([
                ("partner_id", "=", vendor.partner_id.id),
                ("state", "=", "draft"),
                ("bom_id", "=", self.root_bom_id.id),
                ("cfe", "=", False),
            ], limit=1)

            if not po:
                po = PO.create({
                    "partner_id": vendor.partner_id.id,
                    "bom_id": self.root_bom_id.id,
                    "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                    "cfe_project_location_id": self.root_bom_id.cfe_project_location_id.id,
                    "state": 'draft',
                })

            price = vendor.price or bom_line.product_id.list_price

            POLine.create({
                "order_id": po.id,
                "product_id": bom_line.product_id.id,
                "product_qty": quantity,
                "product_uom": bom_line.product_id.uom_po_id.id,
                "price_unit": price,
                "date_planned": fields.Datetime.now(),
                "component_branch_id": self.id,
                "bom_line_ids": [(6, 0, [bom_line.id])],
                "bom_id":self.root_bom_id.id,
            })
            find_vpo_line = self.env["purchase.order.line"].search(
                [('product_id', '=', self.cr_bom_line_id.product_id.id), ('order_id', '=', po.id),
                 ('component_branch_id', '=', self.id)])
            self.cr_bom_line_id.po_line_id = find_vpo_line.id

    def _calculate_to_transfer_cfe(self, customer, cfe_qty, transferred_cfe):
        """Calculate to transfer CFE quantity and create/update internal transfers"""
        StockMove = self.env["stock.move"]
        StockQuant = self.env["stock.quant"]


        waiting_pickings = self.env["stock.picking"].search([
            ("partner_id", "=", customer.id),
            ("picking_type_id.code", "=", 'internal'),
            ("owner_id", "=", customer.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "=", "confirmed"),
        ])

        # Filter pickings with free source locations
        if waiting_pickings:
            for picking in waiting_pickings:
                if self._should_consider_location(picking.location_id):
                    # Check if this picking has moves for our product
                    product_moves = picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )

                    if product_moves:
                        picking.action_cancel()
                        self._send_notification(
                            "Internal Transfer Cancelled (CFE)",
                            f"Cancelled waiting transfer {picking.name} for recalculation (Customer: {customer.name})",
                            "warning"
                        )

        # Find pending moves to branch location owned by customer
        pending_moves = StockMove.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "not in", ["done", "cancel"]),
            ("restrict_partner_id", "=", customer.id),
        ])
        # Filter moves from free locations
        pending_moves = pending_moves.filtered(
            lambda m: self._should_consider_location(m.location_id)
        )

        existing_demand = sum(pending_moves.mapped("product_uom_qty"))

        # Calculate needed quantity
        needed = cfe_qty - transferred_cfe - existing_demand

        if needed == 0.0:

            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)

            for move in sorted_moves:
                if move.picking_id.picking_type_id.code == 'internal':

                    source_location = move.picking_id.location_id
                    source_quants = StockQuant.search([
                        ("product_id", "=", self.cr_bom_line_id.product_id.id),
                        ("location_id", "=", source_location.id),
                        ("owner_id", "=", customer.id),
                        ("quantity", ">", 0),
                    ])
                    available_in_source = sum(source_quants.mapped("quantity"))

                    if available_in_source < move.product_uom_qty:
                        move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': available_in_source
                        })

                        needed = cfe_qty - transferred_cfe - available_in_source

                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Updated {move.picking_id.name}: to {available_in_source} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Customer: {customer.name})",
                            "info"
                        )

            return needed

        # ADD THIS NEW CODE BLOCK FOR REDUCTION
        if needed < 0:
            reduction_needed = abs(needed)

            # Sort moves by quantity descending to remove from larger quantities first
            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)

            for move in sorted_moves:
                if reduction_needed <= 0:
                    break

                if move.product_uom_qty <= reduction_needed:
                    # Remove entire move
                    reduction_qty = move.product_uom_qty
                    reduction_needed -= reduction_qty
                    picking = move.picking_id
                    move.unlink()

                    # Remove picking if no moves left
                    if not picking.move_ids_without_package:
                        picking_name = picking.name
                        picking.unlink()
                        self._send_notification(
                            "Internal Transfer Removed (CFE)",
                            f"Removed {picking_name}: CFE quantity reduced to {cfe_qty} (Customer: {customer.name})",
                            "warning"
                        )
                    else:
                        self._send_notification(
                            "Internal Transfer Updated (CFE)",
                            f"Removed {reduction_qty} {self.cr_bom_line_id.product_id.uom_id.name} from {picking.name}: "
                            f"CFE quantity reduced to {cfe_qty} (Customer: {customer.name})",
                            "warning"
                        )
                else:
                    # Reduce move quantity
                    move.product_uom_qty -= reduction_needed
                    self._send_notification(
                        "Internal Transfer Updated (CFE)",
                        f"Reduced {move.picking_id.name}: Decreased by {reduction_needed} {self.cr_bom_line_id.product_id.uom_id.name} "
                        f"of {self.cr_bom_line_id.product_id.display_name}, new CFE quantity: {cfe_qty} (Customer: {customer.name})",
                        "warning"
                    )
                    reduction_needed = 0

            # Recalculate existing demand after reduction
            existing_demand = sum(pending_moves.exists().mapped("product_uom_qty"))
            return existing_demand

        if needed > 0:

            existing_picking = self.env["stock.picking"].search([
                ("partner_id", "=", customer.id),
                ("picking_type_id.code", "=", 'internal'),
                ("owner_id", "=", customer.id),
                ("location_dest_id", "=", self.location_id.id),
                ("state", "not in", ["done", "cancel"]),
            ], limit=1)

            if existing_picking:
                existing_picking = existing_picking.filtered(
                    lambda p: self._should_consider_location(p.location_id)
                )

            if existing_picking:
                # Check stock in existing picking's source location
                source_location = existing_picking.location_id
                source_quants = StockQuant.search([
                    ("product_id", "=", self.cr_bom_line_id.product_id.id),
                    ("location_id", "=", source_location.id),
                    ("owner_id", "=", customer.id),
                    ("quantity", ">", 0),
                ])
                available_in_source = sum(source_quants.mapped("quantity"))

                if available_in_source:
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )
                    available_in_source = available_in_source - existing_move.product_uom_qty


                if available_in_source > 0:
                    transfer_qty = min(needed, available_in_source)

                    # Find existing move for this product
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )

                    if existing_move:
                        # existing_move.product_uom_qty += transfer_qty
                        existing_move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': existing_move.product_uom_qty + transfer_qty
                        })
                        existing_picking.origin = f"EVR Flow - {self.root_bom_id.display_name}"
                        existing_picking.action_confirm()
                        self._send_notification(
                            "Internal Transfer Updated (CFE)",
                            f"Updated {existing_picking.name}: Added {transfer_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Customer: {customer.name})",
                            "info"
                        )
                    else:
                        self.env["stock.move"].with_context(bypass_custom_internal_transfer_restrictions=True).create({
                            "name": self.cr_bom_line_id.product_id.display_name,
                            "product_id": self.cr_bom_line_id.product_id.id,
                            "product_uom_qty": transfer_qty,
                            "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                            "picking_id": existing_picking.id,
                            "location_id": source_location.id,
                            "location_dest_id": self.location_id.id,
                            "restrict_partner_id": customer.id,
                        })
                        existing_picking.origin = f"EVR Flow - {self.root_bom_id.display_name}"
                        existing_picking.action_confirm()
                        self._send_notification(
                            "Internal Transfer Updated (CFE)",
                            f"Added to {existing_picking.name}: {transfer_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Customer: {customer.name})",
                            "info"
                        )

                    existing_demand += transfer_qty
                    needed -= transfer_qty

                else:
                    if available_in_source < 0:
                        existing_move = existing_picking.move_ids_without_package.filtered(
                            lambda m: m.product_id == self.cr_bom_line_id.product_id
                        )
                        cr_available_in_source = sum(source_quants.mapped("quantity"))
                        if existing_move:
                            existing_move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                                'product_uom_qty': cr_available_in_source
                            })

                            self._send_notification(
                                "Internal Transfer Updated",
                                f"Updated {existing_picking.name}: {cr_available_in_source} {self.cr_bom_line_id.product_id.uom_id.name} "
                                f"of {self.cr_bom_line_id.product_id.display_name} (Customer: {customer.name})",
                                "info"
                            )
                            return cr_available_in_source

                if available_in_source < 0:
                    transfer_qty = min(needed, available_in_source)

                    # Find existing move for this product
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )

                    if existing_move:
                        # existing_move.product_uom_qty += transfer_qty
                        existing_move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': transfer_qty
                        })
                        existing_picking.origin = f"EVR Flow - {self.root_bom_id.display_name}"
                        existing_picking.action_confirm()
                        self._send_notification(
                            "Internal Transfer Updated (CFE)",
                            f"Updated {existing_picking.name}: Added {transfer_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Customer: {customer.name})",
                            "info"
                        )

            # If still need more, create new transfer(s)
            if needed > 0:
                total_qty = self._create_multiple_internal_transfers_cfe(customer, needed)
                existing_demand += total_qty

        return existing_demand

    def _create_multiple_internal_transfers_cfe(self, customer, needed_qty):
        """Create one or multiple internal transfers based on stock availability"""
        StockQuant = self.env["stock.quant"]

        # Get all quants owned by customer in free locations
        all_quants = StockQuant.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("owner_id", "=", customer.id),
            ("quantity", ">", 0),
            ("location_id",'!=',self.location_id.id)
        ])

        # Filter by free locations
        valid_quants = []
        for quant in all_quants:
            if self._should_consider_location(quant.location_id):

                existing_picking = self.env["stock.picking"].search([
                    ("partner_id", "=", customer.id),
                    ("picking_type_id.code", "=", 'internal'),
                    ("owner_id", "=", customer.id),
                    ("location_dest_id", "=", self.location_id.id),
                    ("state", "not in", ["done", "cancel"]),
                ], limit=1)

                if existing_picking:
                    existing_picking = existing_picking.filtered(
                        lambda p: self._should_consider_location(p.location_id)
                    )

                if existing_picking:
                    # Check stock in existing picking's source location
                    source_location = existing_picking.location_id
                    source_quants = StockQuant.search([
                        ("product_id", "=", self.cr_bom_line_id.product_id.id),
                        ("location_id", "=", source_location.id),
                        ("owner_id", "=", customer.id),
                        ("quantity", ">", 0),
                    ])
                    available_in_source = sum(source_quants.mapped("quantity"))

                    if available_in_source:
                        existing_move = existing_picking.move_ids_without_package.filtered(
                            lambda m: m.product_id == self.cr_bom_line_id.product_id
                        )
                        available_in_source = available_in_source - existing_move.product_uom_qty

                    if available_in_source > 0:
                        valid_quants.append(quant)
                else:
                    valid_quants.append(quant)



        if not valid_quants:
            return 0

        # Sort by quantity descending to prioritize locations with more stock
        valid_quants.sort(key=lambda q: q.quantity, reverse=True)

        # Try to find single location with full quantity
        for quant in valid_quants:
            if quant.quantity >= needed_qty:
                picking = self._create_single_internal_transfer(
                    customer,
                    False,
                    quant.location_id,
                    needed_qty
                )
                if picking:
                    picking.action_confirm()
                    self._send_notification(
                        "Internal Transfer Created (CFE)",
                        f"Created {picking.name}: {needed_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                        f"of {self.cr_bom_line_id.product_id.display_name} "
                        f"from {quant.location_id.display_name} (Customer: {customer.name})",
                        "success"
                    )
                return needed_qty

        total_qty = 0
        # Create multiple transfers from different locations
        remaining = needed_qty
        for quant in valid_quants:
            if remaining <= 0:
                break

            transfer_qty = min(quant.quantity, remaining)
            picking = self._create_single_internal_transfer(
                customer,
                False,
                quant.location_id,
                transfer_qty
            )
            total_qty = total_qty + transfer_qty
            if picking:
                picking.action_confirm()
                self._send_notification(
                    "Internal Transfer Created (CFE)",
                    f"Created {picking.name}: {transfer_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                    f"of {self.cr_bom_line_id.product_id.display_name} "
                    f"from {quant.location_id.display_name} (Customer: {customer.name})",
                    "success"
                )
            remaining -= transfer_qty

        return total_qty

    def _create_single_internal_transfer(self, owner, vendor_partner,source_location, quantity):
        """Create a single internal transfer from specific source location"""
        _logger.info(f'>>>>>>> quantity {quantity}')
        StockPicking = self.env["stock.picking"]

        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "internal"),
            ("company_id", "=", self.root_bom_id.company_id.id),
        ], limit=1)

        if not picking_type:
            return False

        StockPicking = StockPicking.with_context(bypass_custom_internal_transfer_restrictions=True)

        if vendor_partner:
            picking_vals = {
                "picking_type_id": picking_type.id,
                "location_id": source_location.id,
                "location_dest_id": self.location_id.id,
                "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                "partner_id": vendor_partner.id if vendor_partner else False,
                "move_ids": [(0, 0, {
                    "name": self.cr_bom_line_id.product_id.display_name,
                    "product_id": self.cr_bom_line_id.product_id.id,
                    "product_uom_qty": quantity,
                    "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                    "location_id": source_location.id,
                    "location_dest_id": self.location_id.id,
                    "restrict_partner_id": owner.id if owner else False,
                })],
            }
            return StockPicking.create(picking_vals)
        else:
            picking_vals = {
                "picking_type_id": picking_type.id,
                "location_id": source_location.id,
                "location_dest_id": self.location_id.id,
                "origin": f"EVR Flow - {self.root_bom_id.display_name}",
                "partner_id": owner.id if owner else False,
                "owner_id": owner.id if owner else False,
                "move_ids": [(0, 0, {
                    "name": self.cr_bom_line_id.product_id.display_name,
                    "product_id": self.cr_bom_line_id.product_id.id,
                    "product_uom_qty": quantity,
                    "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                    "location_id": source_location.id,
                    "location_dest_id": self.location_id.id,
                    "restrict_partner_id": owner.id if owner else False,
                })],
            }
            return StockPicking.create(picking_vals)



    def _calculate_to_transfer(self, x_qty, transferred):
        """Calculate to transfer quantity and create/update internal transfers"""
        StockMove = self.env["stock.move"]
        StockQuant = self.env["stock.quant"]


        vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                  or self.cr_bom_line_id.product_id._select_seller())

        if vendor and vendor.partner_id:
            waiting_pickings = self.env["stock.picking"].search([
                ("picking_type_id.code", "=", 'internal'),
                ("partner_id", "=", vendor.partner_id.id),
                ("location_dest_id", "=", self.location_id.id),
                ("state", "=", "confirmed"),
            ])

            # Filter pickings with free source locations
            if waiting_pickings:
                for picking in waiting_pickings:
                    if self._should_consider_location(picking.location_id):
                        # Check if this picking has moves for our product
                        product_moves = picking.move_ids_without_package.filtered(
                            lambda m: m.product_id == self.cr_bom_line_id.product_id
                        )

                        if product_moves:
                            picking.action_cancel()
                            self._send_notification(
                                "Internal Transfer Cancelled",
                                f"Cancelled waiting transfer {picking.name} for recalculation (Vendor: {vendor.partner_id.name})",
                                "warning"
                            )

        # Find pending moves to branch location without owner
        pending_moves = StockMove.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "not in", ["done", "cancel"]),
            ("restrict_partner_id", "=", False),
        ])
        # Filter moves from free locations
        pending_moves = pending_moves.filtered(
            lambda m: self._should_consider_location(m.location_id)
        )

        existing_demand = sum(pending_moves.mapped("product_uom_qty"))

        # Calculate needed quantity
        needed = x_qty - transferred - existing_demand

        if needed == 0.0:
            vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                      or self.cr_bom_line_id.product_id._select_seller())

            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)

            for move in sorted_moves:
                if move.picking_id.picking_type_id.code == 'internal':

                    source_location = move.picking_id.location_id
                    source_quants = StockQuant.search([
                        ("product_id", "=", self.cr_bom_line_id.product_id.id),
                        ("location_id", "=", source_location.id),
                        ("owner_id", "=", False),
                        ("quantity", ">", 0),
                    ])
                    available_in_source = sum(source_quants.mapped("quantity"))

                    if available_in_source < move.product_uom_qty:
                        move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': available_in_source
                        })
                        needed = x_qty - transferred - available_in_source

                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Updated {move.picking_id.name}: to {available_in_source} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Vendor: {vendor.partner_id.name})",
                            "info"
                        )

            return needed


        # ADD THIS NEW CODE BLOCK FOR REDUCTION
        if needed < 0:
            reduction_needed = abs(needed)

            vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                      or self.cr_bom_line_id.product_id._select_seller())

            # Sort moves by quantity descending
            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)

            for move in sorted_moves:
                if reduction_needed <= 0:
                    break

                if move.product_uom_qty <= reduction_needed:
                    # Remove entire move
                    reduction_qty = move.product_uom_qty
                    reduction_needed -= reduction_qty
                    picking = move.picking_id
                    move.unlink()

                    # Remove picking if no moves left
                    if not picking.move_ids_without_package:
                        picking_name = picking.name
                        picking.unlink()
                        self._send_notification(
                            "Internal Transfer Removed",
                            f"Removed {picking_name}: Quantity reduced to {x_qty}" +
                            (f" (Vendor: {vendor.partner_id.name})" if vendor else ""),
                            "warning"
                        )
                    else:
                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Removed {reduction_qty} {self.cr_bom_line_id.product_id.uom_id.name} from {picking.name}: "
                            f"Quantity reduced to {x_qty}" +
                            (f" (Vendor: {vendor.partner_id.name})" if vendor else ""),
                            "warning"
                        )
                else:
                    # Reduce move quantity
                    move.product_uom_qty -= reduction_needed
                    self._send_notification(
                        "Internal Transfer Updated",
                        f"Reduced {move.picking_id.name}: Decreased by {reduction_needed} {self.cr_bom_line_id.product_id.uom_id.name} "
                        f"of {self.cr_bom_line_id.product_id.display_name}, new quantity: {x_qty}" +
                        (f" (Vendor: {vendor.partner_id.name})" if vendor else ""),
                        "warning"
                    )
                    reduction_needed = 0

            # Recalculate existing demand after reduction
            existing_demand = sum(pending_moves.exists().mapped("product_uom_qty"))
            return existing_demand

        if needed > 0:
            # Check if internal transfer exists

            vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                      or self.cr_bom_line_id.product_id._select_seller())


            existing_picking = self.env["stock.picking"].search([
                ("picking_type_id.code", "=", 'internal'),
                ("partner_id", "=", vendor.partner_id.id),
                ("location_dest_id", "=", self.location_id.id),
                ("state", "not in", ["done", "cancel"]),
            ], limit=1)

            if existing_picking:
                existing_picking = existing_picking.filtered(
                    lambda p: self._should_consider_location(p.location_id)
                )

            if existing_picking:
                # Check stock in existing picking's source location
                source_location = existing_picking.location_id
                source_quants = StockQuant.search([
                    ("product_id", "=", self.cr_bom_line_id.product_id.id),
                    ("location_id", "=", source_location.id),
                    ("owner_id", "=", False),
                    ("quantity", ">", 0),
                ])
                available_in_source = sum(source_quants.mapped("quantity"))

                if available_in_source:
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )
                    available_in_source = available_in_source - existing_move.product_uom_qty

                if available_in_source > 0:
                    transfer_qty = min(needed, available_in_source)

                    # Find existing move for this product
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )

                    if existing_move:
                        # existing_move.product_uom_qty += transfer_qty
                        existing_move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': existing_move.product_uom_qty + transfer_qty
                        })
                        existing_picking.origin = f"EVR Flow - {self.root_bom_id.display_name}"

                        existing_picking.action_confirm()

                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Updated {existing_picking.name}: Added {transfer_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Vendor: {vendor.partner_id.name})",
                            "info"
                        )
                    else:
                        self.env["stock.move"].with_context(bypass_custom_internal_transfer_restrictions=True).create({
                            "name": self.cr_bom_line_id.product_id.display_name,
                            "product_id": self.cr_bom_line_id.product_id.id,
                            "product_uom_qty": transfer_qty,
                            "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                            "picking_id": existing_picking.id,
                            "location_id": source_location.id,
                            "location_dest_id": self.location_id.id,
                            "restrict_partner_id": False,
                        })

                        existing_picking.origin = f"EVR Flow - {self.root_bom_id.display_name}"

                        existing_picking.action_confirm()
                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Added to {existing_picking.name}: {transfer_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Vendor: {vendor.partner_id.name})",
                            "info"
                        )


                    existing_demand += transfer_qty
                    needed -= transfer_qty

                if available_in_source < 0:
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )
                    cr_available_in_source = sum(source_quants.mapped("quantity"))
                    if existing_move:
                        existing_move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': cr_available_in_source
                        })

                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Updated {existing_picking.name}: {cr_available_in_source} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Vendor: {vendor.partner_id.name})",
                            "info"
                        )
                        return cr_available_in_source

            # If still need more, create new transfer(s)
            if needed > 0:
                total_qty = self._create_multiple_internal_transfers_regular(vendor.partner_id if vendor else False, needed)
                _logger.info(f'total_qty {total_qty}')
                _logger.info(f'>>existing_demand {existing_demand}')
                existing_demand += total_qty
                _logger.info(f'existing_demand {existing_demand}')

        return existing_demand

    def _create_multiple_internal_transfers_regular(self, vendor_partner, needed_qty):
        """Create one or multiple internal transfers based on stock availability (no owner)"""
        StockQuant = self.env["stock.quant"]

        # Get all quants without owner in free locations
        all_quants = StockQuant.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("owner_id", "=", False),
            ("quantity", ">", 0),
            ("location_id",'!=',self.location_id.id)
        ])

        # Filter by free locations
        valid_quants = []
        for quant in all_quants:
            if self._should_consider_location(quant.location_id):

                vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                          or self.cr_bom_line_id.product_id._select_seller())


                existing_picking = self.env["stock.picking"].search([
                    ("picking_type_id.code", "=", 'internal'),
                    ("partner_id", "=", vendor.partner_id.id),
                    ("location_dest_id", "=", self.location_id.id),
                    ("state", "not in", ["done", "cancel"]),
                ], limit=1)

                if existing_picking:
                    existing_picking = existing_picking.filtered(
                        lambda p: self._should_consider_location(p.location_id)
                    )

                if existing_picking:
                    # Check stock in existing picking's source location
                    source_location = existing_picking.location_id
                    source_quants = StockQuant.search([
                        ("product_id", "=", self.cr_bom_line_id.product_id.id),
                        ("location_id", "=", source_location.id),
                        ("owner_id", "=", False),
                        ("quantity", ">", 0),
                    ])
                    available_in_source = sum(source_quants.mapped("quantity"))

                    if available_in_source:
                        existing_move = existing_picking.move_ids_without_package.filtered(
                            lambda m: m.product_id == self.cr_bom_line_id.product_id
                        )
                        available_in_source = available_in_source - existing_move.product_uom_qty

                    if available_in_source > 0:
                        valid_quants.append(quant)
                else:
                    valid_quants.append(quant)



        if not valid_quants:
            return 0

        # Sort by quantity descending to prioritize locations with more stock
        valid_quants.sort(key=lambda q: q.quantity, reverse=True)

        # Try to find single location with full quantity
        for quant in valid_quants:
            if quant.quantity >= needed_qty:
                picking = self._create_single_internal_transfer(
                    False,
                    vendor_partner,
                    quant.location_id,
                    needed_qty
                )
                if picking:
                    picking.action_confirm()
                    self._send_notification(
                        "Internal Transfer Created",
                        f"Created {picking.name}: {needed_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                        f"of {self.cr_bom_line_id.product_id.display_name} "
                        f"from {quant.location_id.display_name}" +
                        (f" (Vendor: {vendor_partner.name})" if vendor_partner else ""),
                        "success"
                    )

                return needed_qty

        # Create multiple transfers from different locations
        total_qty = 0
        remaining = needed_qty
        for quant in valid_quants:
            if remaining <= 0:
                break

            transfer_qty = min(quant.quantity, remaining)
            picking = self._create_single_internal_transfer(
                False,
                vendor_partner,
                quant.location_id,
                transfer_qty
            )
            total_qty = total_qty + transfer_qty
            if picking:
                picking.action_confirm()
                self._send_notification(
                    "Internal Transfer Created",
                    f"Created {picking.name}: {transfer_qty} {self.cr_bom_line_id.product_id.uom_id.name} "
                    f"of {self.cr_bom_line_id.product_id.display_name} "
                    f"from {quant.location_id.display_name}" +
                    (f" (Vendor: {vendor_partner.name})" if vendor_partner else ""),
                    "success"
                )
            remaining -= transfer_qty

        return total_qty



    def _send_notification(self, title, message, notification_type="info"):
        """Send notification to user"""
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': False,
            }
        )

    def _adjust_cfe_po_quantity(self, customer, required_qty):
        """Adjust or remove CFE PO lines to match required quantity"""
        POLine = self.env["purchase.order.line"]

        po_lines = POLine.search([
            ("component_branch_id", "=", self.id),
            ("order_id.partner_id", "=", customer.id),
            ("order_id.state", "=", "draft"),
            ("bom_id", "=", self.root_bom_id.id),
        ])

        for line in po_lines:
            if required_qty <= 0:
                # Remove entire line
                po = line.order_id
                line.unlink()

                # Remove PO if no lines left
                if not po.order_line:
                    po.button_cancel()
                    po.unlink()
                    self._send_notification(
                        "Purchase Order Removed (CFE)",
                        f"Removed PO: CFE requirement satisfied (Customer: {customer.name})",
                        "info"
                    )
            elif line.product_qty > required_qty:
                # Reduce quantity
                old_qty = line.product_qty
                line.product_qty = required_qty
                self._send_notification(
                    "Purchase Order Updated (CFE)",
                    f"Reduced PO {line.order_id.name}: {old_qty} → {required_qty} {line.product_uom.name} "
                    f"of {line.product_id.display_name} (Customer: {customer.name})",
                    "info"
                )

    def _adjust_regular_po_quantity(self, required_qty):
        """Adjust or remove regular PO lines to match required quantity"""
        POLine = self.env["purchase.order.line"]

        bom_line = self.cr_bom_line_id
        vendor = (bom_line.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                  or bom_line.product_id._select_seller())

        if not vendor or not vendor.partner_id:
            return

        po_lines = POLine.search([
            ("component_branch_id", "=", self.id),
            ("order_id.partner_id", "=", vendor.partner_id.id),
            ("order_id.state", "=", "draft"),
            ("bom_id", "=", self.root_bom_id.id),
        ])

        for line in po_lines:
            if required_qty <= 0:
                # Remove entire line
                po = line.order_id
                line.unlink()

                # Remove PO if no lines left
                if not po.order_line:
                    po.button_cancel()
                    po.unlink()
                    self._send_notification(
                        "Purchase Order Removed",
                        f"Removed PO: Requirement satisfied (Vendor: {vendor.partner_id.name})",
                        "info"
                    )
            elif line.product_qty > required_qty:
                # Reduce quantity
                old_qty = line.product_qty
                line.product_qty = required_qty
                self._send_notification(
                    "Purchase Order Updated",
                    f"Reduced PO {line.order_id.name}: {old_qty} → {required_qty} {line.product_uom.name} "
                    f"of {line.product_id.display_name} (Vendor: {vendor.partner_id.name})",
                    "info"
                )