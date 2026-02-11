# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line.branch.components'

    critical = fields.Boolean(
        string='Critical',
        related='cr_bom_line_id.critical',
        store=True,
        help='This component is critical'
    )

    lost = fields.Float(
        string='Lost',
        compute='_compute_lost',
        store=True,
        help='Quantity lost/damaged'
    )

    @api.depends('used', 'to_transfer')
    def _compute_lost(self):
        """
        Calculate lost quantity based on transfers and usage
        Lost = quantities that were transferred but not used and not available
        """
        for component in self:
            # Get all done pickings to this location
            # done_pickings = self.env['stock.picking'].search([
            #     ('location_dest_id', '=', component.location_id.id),
            #     ('state', '=', 'done'),
            #     ('move_ids_without_package.product_id', '=', component.cr_bom_line_id.product_id.id)
            # ])
            #
            # total_transferred = sum(
            #     done_pickings.mapped('move_ids_without_package').filtered(
            #         lambda m: m.product_id == component.cr_bom_line_id.product_id
            #     ).mapped('quantity_done')
            # )
            #
            # # Lost = transferred - used - available_in_location
            # available_in_location = self.env['stock.quant']._get_available_quantity(
            #     component.cr_bom_line_id.product_id,
            #     component.location_id
            # )
            #
            # lost_qty = total_transferred - component.used - available_in_location
            # component.lost = max(0, lost_qty)  # Can't be negative
            component.lost = 0


    def _should_consider_location(self, location, bom_line=None):
        """
        Override to include TAPY locations when buy_make_selection is 'buy'.
        - If line has buy_make_selection = 'buy': Include FREE + TAPY locations
        - Otherwise: Include only FREE locations

        Args:
            location: stock.location record to check
            bom_line: optional mrp.bom.line record (to avoid recordset issues)
        """
        product = bom_line.product_id if bom_line else False
        is_mech_product = product and product.categ_id and product.categ_id.mech

        location_fields = self.env['stock.location']._fields
        use_boolean_field = 'free_to_use' in location_fields

        cur = location
        while cur:
            # Check if current location is free
            is_free = False
            is_tapy = False

            if use_boolean_field:
                try:
                    is_free = bool(cur.free_to_use)
                except Exception:
                    pass
            else:
                try:
                    location_cat = getattr(cur, 'location_category', False)
                    is_free = location_cat == 'free'
                    is_tapy = location_cat == 'tapy'
                except Exception:
                    pass

            # If free location found, always consider it
            if is_free:
                return True

            # If TAPY location and product is MECH category, consider it
            if is_tapy and is_mech_product:
                return True

            # Move to parent and continue checking
            cur = cur.location_id

        # No matching location found in the entire parent chain
        return False

    @api.depends(
        'cr_bom_line_id.product_id',
        'cr_bom_line_id.product_id.stock_quant_ids',
        'cr_bom_line_id.product_id.stock_quant_ids.quantity',
        'cr_bom_line_id.product_id.stock_quant_ids.reserved_quantity',
        'cr_bom_line_id.product_id.stock_quant_ids.location_id',
        'cr_bom_line_id.product_id.stock_quant_ids.location_id.location_category',
        'cr_bom_line_id.product_id.stock_quant_ids.location_id.location_id.location_category'
    )
    def _compute_free_to_use(self):
        """Override to pass bom_line explicitly to avoid singleton issues"""
        StockQuant = self.env['stock.quant']

        for rec in self:
            rec.free_to_use = 0.0
            if not rec.cr_bom_line_id or not rec.cr_bom_line_id.product_id:
                continue

            product = rec.cr_bom_line_id.product_id
            bom_line = rec.cr_bom_line_id  # Store for this specific record

            # Search for quants with positive quantity
            quants = StockQuant.search([
                ('product_id', '=', product.id),
                ('quantity', '>', 0),
                ('owner_id', '=', False),
            ])

            total_qty = 0.0

            # Check each location that has stock and calculate available quantity
            for quant in quants:
                # Calculate available quantity (quantity - reserved_quantity)
                available_qty = quant.quantity - quant.reserved_quantity
                if available_qty > 0 and rec._should_consider_location(quant.location_id, bom_line):
                    total_qty += available_qty

            rec.free_to_use = float(total_qty)

    def _process_purchase_flow(self):
        """Process purchase flow for this component"""
        self.ensure_one()

        bom_line = self.cr_bom_line_id
        if not bom_line:
            return

        # Skip if BUY/MAKE product without selection
        if (bom_line.product_id.manufacture_purchase == 'buy_make' and
                not bom_line.buy_make_selection):
            return

        # # Skip if MAKE is selected (treat as sub-BOM, not component)
        # if bom_line.buy_make_selection == 'make':
        #     return

        # Check if approvals are TRUE
        if not (bom_line.approval_1 and bom_line.approval_2):
            return

        # Process CFE flow
        self._process_cfe_flow()

        # Process regular purchase flow
        self._process_regular_flow()

    def _is_tapy_location(self, location):
        """Check if location or any parent is TAPY"""
        cur = location
        while cur:
            try:
                if getattr(cur, 'location_category', False) == 'tapy':
                    return True
            except Exception:
                pass
            cur = cur.location_id
        return False

    def _is_free_location(self, location):
        """Check if location or any parent is FREE"""
        cur = location
        while cur:
            try:
                if getattr(cur, 'location_category', False) == 'free':
                    return True
            except Exception:
                pass
            cur = cur.location_id
        return False


    def _calculate_to_transfer_cfe(self, customer, cfe_qty, transferred_cfe):
        """Calculate to transfer CFE quantity and create/update internal transfers"""
        _logger.info(
            "START _calculate_to_transfer_cfe | component=%s customer=%s cfe_qty=%s transferred_cfe=%s",
            self.id, customer.id if customer else None, cfe_qty, transferred_cfe
        )

        StockMove = self.env["stock.move"]
        StockQuant = self.env["stock.quant"]

        bom_line = self.cr_bom_line_id
        _logger.info("BOM line=%s product=%s", bom_line.id if bom_line else None,
                     bom_line.product_id.id if bom_line else None)

        waiting_pickings = self.env["stock.picking"].search([
            ("partner_id", "=", customer.id),
            ("picking_type_id.code", "=", 'internal'),
            ("owner_id", "=", customer.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "=", "confirmed"),
        ])
        _logger.info("Found waiting_pickings=%s", waiting_pickings.ids)

        if waiting_pickings:
            for picking in waiting_pickings:
                _logger.info("Checking waiting picking=%s source_location=%s", picking.name, picking.location_id.id)
                if self._should_consider_location(picking.location_id, bom_line):
                    _logger.info("Picking %s source location allowed", picking.name)

                    product_moves = picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )
                    _logger.info("Product moves in picking %s: %s", picking.name, product_moves.ids)

                    if product_moves:
                        _logger.info("Cancelling picking %s due to recalculation", picking.name)
                        picking.action_cancel()
                        self._send_notification(
                            "Internal Transfer Cancelled (CFE)",
                            f"Cancelled waiting transfer {picking.name} for recalculation (Customer: {customer.name})",
                            "warning"
                        )

        pending_moves = StockMove.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "not in", ["done", "cancel"]),
            ("restrict_partner_id", "=", customer.id),
        ])
        _logger.info("Initial pending_moves=%s", pending_moves.ids)

        pending_moves = pending_moves.filtered(
            lambda m: self._should_consider_location(m.location_id, bom_line)
        )
        _logger.info("Filtered pending_moves=%s", pending_moves.ids)

        existing_demand = sum(pending_moves.mapped("product_uom_qty"))
        _logger.info("Existing demand=%s", existing_demand)

        needed = cfe_qty - transferred_cfe - existing_demand
        _logger.info("Calculated needed=%s", needed)

        if needed == 0.0:
            _logger.info("Needed is zero, validating existing moves")

            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)
            return_qty = 0
            for move in sorted_moves:
                _logger.info("Checking move=%s qty=%s", move.id, move.product_uom_qty)
                if move.picking_id.picking_type_id.code == 'internal':
                    source_location = move.picking_id.location_id
                    _logger.info("Source location=%s", source_location.id)

                    source_quants = StockQuant.search([
                        ("product_id", "=", self.cr_bom_line_id.product_id.id),
                        ("location_id", "=", source_location.id),
                        ("owner_id", "=", customer.id),
                        ("quantity", ">", 0),
                    ])
                    available_in_source = sum(source_quants.mapped("quantity"))
                    _logger.info("Available in source=%s", available_in_source)

                    if available_in_source < move.product_uom_qty:
                        _logger.info(
                            "Reducing move %s qty from %s to %s",
                            move.id, move.product_uom_qty, available_in_source
                        )
                        move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': available_in_source,
                            "mrp_bom_line_id": self.cr_bom_line_id.id,
                        })

                        needed = cfe_qty - transferred_cfe - available_in_source
                        _logger.info("Recalculated needed=%s", needed)

                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Updated {move.picking_id.name}: to {available_in_source} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Customer: {customer.name})",
                            "info"
                        )

                    return_qty = return_qty + move.product_uom_qty


            _logger.info("RETURN needed=%s", return_qty)
            return return_qty

        if needed < 0:
            _logger.info("Needed < 0, starting reduction flow | needed=%s", needed)
            reduction_needed = abs(needed)

            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)

            for move in sorted_moves:
                if reduction_needed <= 0:
                    break

                _logger.info(
                    "Reducing move=%s qty=%s reduction_needed=%s",
                    move.id, move.product_uom_qty, reduction_needed
                )

                if move.product_uom_qty <= reduction_needed:
                    reduction_qty = move.product_uom_qty
                    reduction_needed -= reduction_qty
                    picking = move.picking_id
                    _logger.info("Removing move=%s from picking=%s", move.id, picking.name)
                    move.unlink()

                    if not picking.move_ids_without_package:
                        _logger.info("Removing empty picking=%s", picking.name)
                        picking.unlink()
                        self._send_notification(
                            "Internal Transfer Removed (CFE)",
                            f"Removed {picking.name}: CFE quantity reduced to {cfe_qty} (Customer: {customer.name})",
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
                    move.product_uom_qty -= reduction_needed
                    move.mrp_bom_line_id = self.cr_bom_line_id.id
                    _logger.info(
                        "Reduced move=%s new_qty=%s",
                        move.id, move.product_uom_qty
                    )
                    self._send_notification(
                        "Internal Transfer Updated (CFE)",
                        f"Reduced {move.picking_id.name}: Decreased by {reduction_needed} {self.cr_bom_line_id.product_id.uom_id.name} "
                        f"of {self.cr_bom_line_id.product_id.display_name}, new CFE quantity: {cfe_qty} (Customer: {customer.name})",
                        "warning"
                    )
                    reduction_needed = 0

            existing_demand = sum(pending_moves.exists().mapped("product_uom_qty"))
            _logger.info("RETURN existing_demand after reduction=%s", existing_demand)
            return existing_demand

        if needed > 0:
            _logger.info("Needed > 0, creating/updating internal transfers | needed=%s", needed)

            existing_picking = self.env["stock.picking"].search([
                ("partner_id", "=", customer.id),
                ("picking_type_id.code", "=", 'internal'),
                ("owner_id", "=", customer.id),
                ("location_dest_id", "=", self.location_id.id),
                ("state", "not in", ["done", "cancel"]),
            ], limit=1)
            _logger.info("Existing picking=%s", existing_picking.name if existing_picking else None)

            if existing_picking:
                existing_picking = existing_picking.filtered(
                    lambda p: self._should_consider_location(p.location_id, bom_line)
                )

            if existing_picking:
                source_location = existing_picking.location_id
                _logger.info("Using source_location=%s", source_location.id)

                source_quants = StockQuant.search([
                    ("product_id", "=", self.cr_bom_line_id.product_id.id),
                    ("location_id", "=", source_location.id),
                    ("owner_id", "=", customer.id),
                    ("quantity", ">", 0),
                ])
                available_in_source = sum(source_quants.mapped("quantity"))
                _logger.info("Available in source=%s", available_in_source)

                if available_in_source:
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )
                    available_in_source -= existing_move.product_uom_qty
                    _logger.info("Adjusted available_in_source=%s", available_in_source)

                if available_in_source > 0:
                    transfer_qty = min(needed, available_in_source)
                    _logger.info("Transfer qty=%s", transfer_qty)

                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )

                    if existing_move:
                        existing_move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': existing_move.product_uom_qty + transfer_qty,
                            "mrp_bom_line_id": self.cr_bom_line_id.id,
                        })
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
                            "mrp_bom_line_id": self.cr_bom_line_id.id,
                        })

                    existing_picking.origin = f"EVR Flow - {self.root_bom_id.display_name}"
                    existing_picking.root_bom_id = self.roott_bom_id.id
                    existing_picking.action_confirm()

                    existing_demand += transfer_qty
                    needed -= transfer_qty
                    _logger.info("Updated existing_demand=%s remaining_needed=%s", existing_demand, needed)

            if needed > 0:
                _logger.info("Creating multiple internal transfers | needed=%s", needed)
                total_qty = self._create_multiple_internal_transfers_cfe(customer, needed)
                existing_demand += total_qty
                _logger.info("Added total_qty=%s new_existing_demand=%s", total_qty, existing_demand)

        _logger.info("END _calculate_to_transfer_cfe | return=%s", existing_demand)
        return existing_demand


    def _create_multiple_internal_transfers_cfe(self, customer, needed_qty):
        """Override to prioritize TAPY locations for MECH products"""
        _logger.info(
            "START _create_multiple_internal_transfers_cfe | component=%s customer=%s needed_qty=%s",
            self.id, customer.id if customer else None, needed_qty
        )

        StockQuant = self.env["stock.quant"]

        bom_line = self.cr_bom_line_id
        is_mech_product = bom_line and bom_line.product_id.categ_id and bom_line.product_id.categ_id.mech
        _logger.info(
            "BOM line=%s product=%s is_mech_product=%s",
            bom_line.id if bom_line else None,
            bom_line.product_id.id if bom_line else None,
            is_mech_product
        )

        all_quants = StockQuant.search([
            ("product_id", "=", bom_line.product_id.id),
            ("owner_id", "=", customer.id),
            ("quantity", ">", 0),
            ("location_id", '!=', self.location_id.id)
        ])
        _logger.info("Found all_quants=%s", all_quants.ids)

        tapy_quants = []
        free_quants = []

        for quant in all_quants:
            _logger.info(
                "Evaluating quant=%s location=%s qty=%s",
                quant.id, quant.location_id.id, quant.quantity
            )

            if is_mech_product and self._is_tapy_location(quant.location_id):
                _logger.info("Quant %s is TAPY location", quant.id)
                if not self._has_pending_transfer_from_location(quant.location_id, customer):
                    tapy_quants.append(quant)
                    _logger.info("Added quant %s to tapy_quants", quant.id)
            elif self._is_free_location(quant.location_id):
                _logger.info("Quant %s is FREE location", quant.id)
                if not self._has_pending_transfer_from_location(quant.location_id, customer):
                    free_quants.append(quant)
                    _logger.info("Added quant %s to free_quants", quant.id)

        # Sort each list by quantity descending
        tapy_quants.sort(key=lambda q: q.quantity, reverse=True)
        free_quants.sort(key=lambda q: q.quantity, reverse=True)

        _logger.info(
            "TAPY quants (sorted)=%s FREE quants (sorted)=%s",
            [(q.id, q.quantity) for q in tapy_quants],
            [(q.id, q.quantity) for q in free_quants]
        )

        total_qty = 0
        remaining = needed_qty

        # STEP 1: Try to fulfill completely from TAPY locations
        if is_mech_product and tapy_quants:
            _logger.info("STEP 1: Attempting to fulfill from TAPY locations | remaining=%s", remaining)

            for quant in tapy_quants:
                if remaining <= 0:
                    break

                transfer_qty = min(quant.quantity, remaining)
                _logger.info(
                    "Creating TAPY transfer | quant=%s qty=%s transfer_qty=%s",
                    quant.id, quant.quantity, transfer_qty
                )

                picking = self._create_single_internal_transfer(customer, False, quant.location_id, transfer_qty)

                if picking:
                    picking.action_confirm()
                    total_qty += transfer_qty
                    remaining -= transfer_qty

                    _logger.info(
                        "Created TAPY picking=%s qty=%s | total_qty=%s remaining=%s",
                        picking.name, transfer_qty, total_qty, remaining
                    )

                    self._send_notification(
                        "Internal Transfer Created (CFE)",
                        f"Created {picking.name}: {transfer_qty} {bom_line.product_id.uom_id.name} "
                        f"from TAPY location {quant.location_id.display_name} (Customer: {customer.name})",
                        "success"
                    )

        # STEP 2: If still needed, fulfill from FREE locations
        if remaining > 0 and free_quants:
            _logger.info("STEP 2: Attempting to fulfill remaining from FREE locations | remaining=%s", remaining)

            for quant in free_quants:
                if remaining <= 0:
                    break

                transfer_qty = min(quant.quantity, remaining)
                _logger.info(
                    "Creating FREE transfer | quant=%s qty=%s transfer_qty=%s",
                    quant.id, quant.quantity, transfer_qty
                )

                picking = self._create_single_internal_transfer(customer, False, quant.location_id, transfer_qty)

                if picking:
                    picking.action_confirm()
                    total_qty += transfer_qty
                    remaining -= transfer_qty

                    _logger.info(
                        "Created FREE picking=%s qty=%s | total_qty=%s remaining=%s",
                        picking.name, transfer_qty, total_qty, remaining
                    )

                    self._send_notification(
                        "Internal Transfer Created (CFE)",
                        f"Created {picking.name}: {transfer_qty} {bom_line.product_id.uom_id.name} "
                        f"from FREE location {quant.location_id.display_name} (Customer: {customer.name})",
                        "success"
                    )

        _logger.info(
            "END _create_multiple_internal_transfers_cfe | return total_qty=%s",
            total_qty
        )
        return total_qty


    def _has_pending_transfer_from_location(self, source_location, customer):
        """Check if there's already a pending transfer from this location"""
        _logger.info(
            "START _has_pending_transfer_from_location | component=%s source_location=%s customer=%s",
            self.id,
            source_location.id if source_location else None,
            customer.id if customer else None
        )

        existing_picking = self.env["stock.picking"].search([
            ("partner_id", "=", customer.id),
            ("picking_type_id.code", "=", 'internal'),
            ("owner_id", "=", customer.id),
            ("location_id", "=", source_location.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "not in", ["done", "cancel"]),
        ], limit=1)

        _logger.info(
            "Existing picking found=%s",
            existing_picking.name if existing_picking else None
        )

        if existing_picking:
            existing_move = existing_picking.move_ids_without_package.filtered(
                lambda m: m.product_id == self.cr_bom_line_id.product_id
            )
            _logger.info(
                "Existing move found=%s move_ids=%s",
                bool(existing_move),
                existing_move.ids
            )

            result = bool(existing_move)
            _logger.info("RETURN %s", result)
            return result

        _logger.info("RETURN False (no existing picking)")
        return False


    def _calculate_to_transfer(self, x_qty, transferred):
        """Calculate to transfer quantity and create/update internal transfers"""
        _logger.info(
            "START _calculate_to_transfer | component=%s x_qty=%s transferred=%s",
            self.id, x_qty, transferred
        )

        StockMove = self.env["stock.move"]
        StockQuant = self.env["stock.quant"]

        bom_line = self.cr_bom_line_id
        _logger.info("BOM line=%s product=%s", bom_line.id if bom_line else None,
                     bom_line.product_id.id if bom_line else None)

        vendor = (self.cr_bom_line_id.product_id.seller_ids.filtered(lambda s: s.main_vendor)[:1]
                  or self.cr_bom_line_id.product_id._select_seller())
        _logger.info("Vendor=%s", vendor.partner_id.id if vendor and vendor.partner_id else None)

        if vendor and vendor.partner_id:
            waiting_pickings = self.env["stock.picking"].search([
                ("picking_type_id.code", "=", 'internal'),
                ("partner_id", "=", vendor.partner_id.id),
                ("location_dest_id", "=", self.location_id.id),
                ("state", "=", "confirmed"),
            ])
            _logger.info("Waiting pickings=%s", waiting_pickings.ids)

            if waiting_pickings:
                for picking in waiting_pickings:
                    _logger.info("Evaluating waiting picking=%s", picking.name)
                    if self._should_consider_location(picking.location_id, bom_line):
                        _logger.info("Picking %s source location allowed", picking.name)
                        product_moves = picking.move_ids_without_package.filtered(
                            lambda m: m.product_id == self.cr_bom_line_id.product_id
                        )
                        _logger.info(
                            "Picking %s product moves=%s",
                            picking.name, product_moves.ids
                        )

                        if product_moves:
                            picking.action_cancel()
                            _logger.info("Cancelled picking=%s", picking.name)
                            self._send_notification(
                                "Internal Transfer Cancelled",
                                f"Cancelled waiting transfer {picking.name} for recalculation (Vendor: {vendor.partner_id.name})",
                                "warning"
                            )

        pending_moves = StockMove.search([
            ("product_id", "=", self.cr_bom_line_id.product_id.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "not in", ["done", "cancel"]),
            ("restrict_partner_id", "=", False),
        ])
        _logger.info("Pending moves (raw)=%s", pending_moves.ids)

        pending_moves = pending_moves.filtered(
            lambda m: self._should_consider_location(m.location_id, bom_line)
        )
        _logger.info("Pending moves (filtered)=%s", pending_moves.ids)

        existing_demand = sum(pending_moves.mapped("product_uom_qty"))
        _logger.info("Existing demand=%s", existing_demand)

        needed = x_qty - transferred - existing_demand
        _logger.info("Calculated needed=%s", needed)

        if needed == 0.0:
            _logger.info("Needed == 0, validating existing transfers")

            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)
            return_qty = 0
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
                    _logger.info(
                        "Move=%s available_in_source=%s move_qty=%s",
                        move.id, available_in_source, move.product_uom_qty
                    )

                    if available_in_source < move.product_uom_qty:
                        move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': available_in_source,
                            "mrp_bom_line_id": self.cr_bom_line_id.id,
                        })
                        needed = x_qty - transferred - available_in_source
                        _logger.info("Adjusted move=%s new_needed=%s", move.id, needed)

                        self._send_notification(
                            "Internal Transfer Updated",
                            f"Updated {move.picking_id.name}: to {available_in_source} {self.cr_bom_line_id.product_id.uom_id.name} "
                            f"of {self.cr_bom_line_id.product_id.display_name} (Vendor: {vendor.partner_id.name})",
                            "info"
                        )

                    return_qty = return_qty + move.product_uom_qty

            _logger.info("RETURN needed=%s", needed)
            return return_qty

        if needed < 0:
            _logger.info("Needed < 0, reduction flow started | needed=%s", needed)
            reduction_needed = abs(needed)

            sorted_moves = pending_moves.sorted(key=lambda m: m.product_uom_qty, reverse=True)
            for move in sorted_moves:
                if reduction_needed <= 0:
                    break

                _logger.info(
                    "Reducing move=%s qty=%s reduction_needed=%s",
                    move.id, move.product_uom_qty, reduction_needed
                )

                if move.product_uom_qty <= reduction_needed:
                    reduction_qty = move.product_uom_qty
                    reduction_needed -= reduction_qty
                    picking = move.picking_id
                    move.unlink()
                    _logger.info("Removed move=%s reduction_qty=%s", move.id, reduction_qty)

                    if not picking.move_ids_without_package:
                        picking_name = picking.name
                        picking.unlink()
                        _logger.info("Removed empty picking=%s", picking_name)
                    self._send_notification(
                        "Internal Transfer Updated",
                        f"Quantity reduced to {x_qty}",
                        "warning"
                    )
                else:
                    move.product_uom_qty -= reduction_needed
                    move.mrp_bom_line_id = self.cr_bom_line_id.id
                    _logger.info(
                        "Reduced move=%s by=%s",
                        move.id, reduction_needed
                    )
                    reduction_needed = 0

            existing_demand = sum(pending_moves.exists().mapped("product_uom_qty"))
            _logger.info("RETURN existing_demand=%s", existing_demand)
            return existing_demand

        if needed > 0:
            _logger.info("Needed > 0, creation/update flow started | needed=%s", needed)

            existing_picking = self.env["stock.picking"].search([
                ("picking_type_id.code", "=", 'internal'),
                ("partner_id", "=", vendor.partner_id.id),
                ("owner_id", "=", False),
                ("location_dest_id", "=", self.location_id.id),
                ("state", "not in", ["done", "cancel"]),
            ], limit=1)
            _logger.info("Existing picking=%s", existing_picking.name if existing_picking else None)

            if existing_picking:
                existing_picking = existing_picking.filtered(
                    lambda p: self._should_consider_location(p.location_id, bom_line)
                )

            if existing_picking:
                source_location = existing_picking.location_id
                source_quants = StockQuant.search([
                    ("product_id", "=", self.cr_bom_line_id.product_id.id),
                    ("location_id", "=", source_location.id),
                    ("owner_id", "=", False),
                    ("quantity", ">", 0),
                ])
                available_in_source = sum(source_quants.mapped("quantity"))
                _logger.info("Available in source=%s", available_in_source)

                if available_in_source:
                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )
                    available_in_source -= existing_move.product_uom_qty
                    _logger.info("Adjusted available_in_source=%s", available_in_source)

                if available_in_source > 0:
                    transfer_qty = min(needed, available_in_source)
                    _logger.info("Transfer qty=%s", transfer_qty)

                    existing_move = existing_picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == self.cr_bom_line_id.product_id
                    )

                    if existing_move:
                        existing_move.with_context(bypass_custom_internal_transfer_restrictions=True).write({
                            'product_uom_qty': existing_move.product_uom_qty + transfer_qty,
                            "mrp_bom_line_id": self.cr_bom_line_id.id,
                        })
                        _logger.info("Updated existing move=%s", existing_move.id)
                    else:
                        self.env["stock.move"].with_context(
                            bypass_custom_internal_transfer_restrictions=True
                        ).create({
                            "name": self.cr_bom_line_id.product_id.display_name,
                            "product_id": self.cr_bom_line_id.product_id.id,
                            "product_uom_qty": transfer_qty,
                            "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                            "picking_id": existing_picking.id,
                            "location_id": source_location.id,
                            "location_dest_id": self.location_id.id,
                            "restrict_partner_id": False,
                            "mrp_bom_line_id": self.cr_bom_line_id.id,
                        })
                        _logger.info("Created new move in picking=%s", existing_picking.name)

                    existing_picking.action_confirm()
                    existing_picking.root_bom_id = self.root_bom_id.id
                    existing_demand += transfer_qty
                    needed -= transfer_qty
                    _logger.info(
                        "Updated totals | existing_demand=%s needed=%s",
                        existing_demand, needed
                    )

            if needed > 0:
                total_qty = self._create_multiple_internal_transfers_regular(
                    vendor.partner_id if vendor else False, needed
                )
                _logger.info("total_qty=%s", total_qty)
                _logger.info("existing_demand(before)=%s", existing_demand)
                existing_demand += total_qty
                _logger.info("existing_demand(after)=%s", existing_demand)

        _logger.info("END _calculate_to_transfer | return=%s", existing_demand)
        return existing_demand


    def _create_multiple_internal_transfers_regular(self, vendor_partner, needed_qty):
        """Override to prioritize TAPY locations for MECH products"""
        _logger.info(
            "START _create_multiple_internal_transfers_regular | component=%s vendor=%s needed_qty=%s",
            self.id,
            vendor_partner.id if vendor_partner else None,
            needed_qty
        )

        StockQuant = self.env["stock.quant"]

        bom_line = self.cr_bom_line_id
        is_mech_product = bom_line and bom_line.product_id.categ_id and bom_line.product_id.categ_id.mech
        _logger.info(
            "BOM line=%s product=%s is_mech_product=%s",
            bom_line.id if bom_line else None,
            bom_line.product_id.id if bom_line else None,
            is_mech_product
        )

        all_quants = StockQuant.search([
            ("product_id", "=", bom_line.product_id.id),
            ("owner_id", "=", False),
            ("quantity", ">", 0),
            ("location_id", '!=', self.location_id.id)
        ])
        _logger.info("Found all_quants=%s", all_quants.ids)

        tapy_quants = []
        free_quants = []

        for quant in all_quants:
            _logger.info(
                "Evaluating quant=%s location=%s qty=%s",
                quant.id, quant.location_id.id, quant.quantity
            )

            if is_mech_product and self._is_tapy_location(quant.location_id):
                _logger.info("Quant %s is TAPY location", quant.id)
                if not self._has_pending_vendor_transfer_from_location(quant.location_id, vendor_partner):
                    tapy_quants.append(quant)
                    _logger.info("Added quant %s to tapy_quants", quant.id)

            elif self._is_free_location(quant.location_id):
                _logger.info("Quant %s is FREE location", quant.id)
                if not self._has_pending_vendor_transfer_from_location(quant.location_id, vendor_partner):
                    free_quants.append(quant)
                    _logger.info("Added quant %s to free_quants", quant.id)

        # Sort each list by quantity descending
        tapy_quants.sort(key=lambda q: q.quantity, reverse=True)
        free_quants.sort(key=lambda q: q.quantity, reverse=True)

        _logger.info(
            "TAPY quants (sorted)=%s FREE quants (sorted)=%s",
            [(q.id, q.quantity) for q in tapy_quants],
            [(q.id, q.quantity) for q in free_quants]
        )

        total_qty = 0
        remaining = needed_qty

        # STEP 1: Try to fulfill completely from TAPY locations
        if is_mech_product and tapy_quants:
            _logger.info("STEP 1: Attempting to fulfill from TAPY locations | remaining=%s", remaining)

            for quant in tapy_quants:
                if remaining <= 0:
                    break

                transfer_qty = min(quant.quantity, remaining)
                _logger.info(
                    "Creating TAPY transfer | quant=%s qty=%s transfer_qty=%s",
                    quant.id, quant.quantity, transfer_qty
                )

                picking = self._create_single_internal_transfer(
                    False, vendor_partner, quant.location_id, transfer_qty
                )

                if picking:
                    picking.action_confirm()
                    total_qty += transfer_qty
                    remaining -= transfer_qty

                    _logger.info(
                        "Created TAPY picking=%s qty=%s | total_qty=%s remaining=%s",
                        picking.name, transfer_qty, total_qty, remaining
                    )

                    self._send_notification(
                        "Internal Transfer Created",
                        f"Created {picking.name}: {transfer_qty} {bom_line.product_id.uom_id.name} "
                        f"from TAPY location {quant.location_id.display_name}" +
                        (f" (Vendor: {vendor_partner.name})" if vendor_partner else ""),
                        "success"
                    )

        # STEP 2: If still needed, fulfill from FREE locations
        if remaining > 0 and free_quants:
            _logger.info("STEP 2: Attempting to fulfill remaining from FREE locations | remaining=%s", remaining)

            for quant in free_quants:
                if remaining <= 0:
                    break

                transfer_qty = min(quant.quantity, remaining)
                _logger.info(
                    "Creating FREE transfer | quant=%s qty=%s transfer_qty=%s",
                    quant.id, quant.quantity, transfer_qty
                )

                picking = self._create_single_internal_transfer(
                    False, vendor_partner, quant.location_id, transfer_qty
                )

                if picking:
                    picking.action_confirm()
                    total_qty += transfer_qty
                    remaining -= transfer_qty

                    _logger.info(
                        "Created FREE picking=%s qty=%s | total_qty=%s remaining=%s",
                        picking.name, transfer_qty, total_qty, remaining
                    )

                    self._send_notification(
                        "Internal Transfer Created",
                        f"Created {picking.name}: {transfer_qty} {bom_line.product_id.uom_id.name} "
                        f"from FREE location {quant.location_id.display_name}" +
                        (f" (Vendor: {vendor_partner.name})" if vendor_partner else ""),
                        "success"
                    )

        _logger.info(
            "END _create_multiple_internal_transfers_regular | return total_qty=%s",
            total_qty
        )
        return total_qty


    def _has_pending_vendor_transfer_from_location(self, source_location, vendor_partner):
        """Check if there's already a pending vendor transfer from this location"""
        _logger.info(
            "START _has_pending_vendor_transfer_from_location | component=%s source_location=%s vendor=%s",
            self.id,
            source_location.id if source_location else None,
            vendor_partner.id if vendor_partner else None
        )

        existing_picking = self.env["stock.picking"].search([
            ("picking_type_id.code", "=", 'internal'),
            ("partner_id", "=", vendor_partner.id if vendor_partner else False),
            ("location_id", "=", source_location.id),
            ("location_dest_id", "=", self.location_id.id),
            ("state", "not in", ["done", "cancel"]),
        ], limit=1)

        _logger.info(
            "Existing picking found=%s",
            existing_picking.name if existing_picking else None
        )

        if existing_picking:
            existing_move = existing_picking.move_ids_without_package.filtered(
                lambda m: m.product_id == self.cr_bom_line_id.product_id
            )
            _logger.info(
                "Existing move found=%s move_ids=%s",
                bool(existing_move),
                existing_move.ids
            )

            result = bool(existing_move)
            _logger.info("RETURN %s", result)
            return result

        _logger.info("RETURN False (no existing picking)")
        return False

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
                "root_bom_id": self.root_bom_id.id,
                "move_ids": [(0, 0, {
                    "name": self.cr_bom_line_id.product_id.display_name,
                    "product_id": self.cr_bom_line_id.product_id.id,
                    "product_uom_qty": quantity,
                    "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                    "location_id": source_location.id,
                    "location_dest_id": self.location_id.id,
                    "restrict_partner_id": owner.id if owner else False,
                    "mrp_bom_line_id": self.cr_bom_line_id.id,
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
                "root_bom_id": self.root_bom_id.id,
                "move_ids": [(0, 0, {
                    "name": self.cr_bom_line_id.product_id.display_name,
                    "product_id": self.cr_bom_line_id.product_id.id,
                    "product_uom_qty": quantity,
                    "product_uom": self.cr_bom_line_id.product_id.uom_id.id,
                    "location_id": source_location.id,
                    "location_dest_id": self.location_id.id,
                    "restrict_partner_id": owner.id if owner else False,
                    "mrp_bom_line_id": self.cr_bom_line_id.id,
                })],
            }
            return StockPicking.create(picking_vals)

