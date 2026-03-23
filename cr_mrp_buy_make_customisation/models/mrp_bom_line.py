# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'


    is_buy_make_product = fields.Boolean(
        compute='_compute_is_buy_make_product',
        store=True
    )

    @api.depends('product_id', 'product_id.manufacture_purchase')
    def _compute_is_buy_make_product(self):
        for line in self:
            line.is_buy_make_product = line.product_id.manufacture_purchase == 'buy_make'


    def _find_actual_root_bom(self, line):
        """Find root by traversing upward through parent BOMs"""

        _logger.info(f"Finding root for line {line.product_id.display_name} in BOM {line.bom_id.display_name}")

        # Start from line's BOM and traverse upward
        current_bom = line.bom_id
        visited = set()

        while True:
            if current_bom.id in visited:
                _logger.error(f"Circular reference detected at {current_bom.display_name}")
                break
            visited.add(current_bom.id)

            # Check if this BOM is EVR with project location
            if current_bom.is_evr and current_bom.cfe_project_location_id:
                _logger.info(f"  Found EVR BOM: {current_bom.display_name}")

                # Check if this BOM is used as a component in another EVR BOM
                parent_found = False

                # Search for any BOM line that uses this BOM's product
                parent_lines = self.env['mrp.bom.line'].search([
                    ('product_id', '=', current_bom.product_id.id if current_bom.product_id else False)
                ])

                if not parent_lines and current_bom.product_tmpl_id:
                    # Try with product variants
                    variant_ids = current_bom.product_tmpl_id.product_variant_ids.ids
                    parent_lines = self.env['mrp.bom.line'].search([
                        ('product_id', 'in', variant_ids)
                    ])

                for parent_line in parent_lines:
                    parent_bom = parent_line.bom_id

                    # Check if parent is EVR with project location
                    if parent_bom.is_evr and parent_bom.cfe_project_location_id:
                        _logger.info(f"    {current_bom.display_name} is used in EVR BOM: {parent_bom.display_name}")
                        current_bom = parent_bom
                        parent_found = True
                        break

                if not parent_found:
                    # No parent EVR BOM found, this is the root
                    _logger.info(f"  ✓ ROOT BOM (no parent): {current_bom.display_name}")
                    return current_bom
            else:
                # Not EVR, find which BOM uses this as component
                parent_lines = self.env['mrp.bom.line'].search([
                    ('child_bom_id', '=', current_bom.id)
                ], limit=1)

                if parent_lines:
                    _logger.info(f"  {current_bom.display_name} used in {parent_lines[0].bom_id.display_name}")
                    current_bom = parent_lines[0].bom_id
                else:
                    _logger.error(f"  No parent found for {current_bom.display_name}")
                    return current_bom

        return current_bom

    def _bom_uses_product_in_hierarchy(self, bom, product):
        """Check if BOM uses this product anywhere in hierarchy"""
        visited = set()

        def check_recursive(check_bom):
            if check_bom.id in visited:
                return False
            visited.add(check_bom.id)

            for line in check_bom.bom_line_ids:
                if line.product_id.id == product.id:
                    return True
                if line.child_bom_id and check_recursive(line.child_bom_id):
                    return True

            return False

        return check_recursive(bom)

    def _bom_contains_line_in_hierarchy(self, bom, target_line):
        """Check if BOM contains specific line anywhere in hierarchy"""
        visited = set()

        def check_recursive(check_bom):
            if check_bom.id in visited:
                return False
            visited.add(check_bom.id)

            if target_line.id in check_bom.bom_line_ids.ids:
                return True

            for line in check_bom.bom_line_ids:
                if line.child_bom_id and check_recursive(line.child_bom_id):
                    return True

            return False

        return check_recursive(bom)

    def _cleanup_related_mos(self, line, root_bom):
        """Cancel and delete all MOs related to this line and its children recursively"""
        MO = self.env['mrp.production']

        def recursive_mo_cleanup(bom_line):
            """Recursively find and delete MOs"""
            # Find MOs for this line
            mos = MO.search([
                ('root_bom_id', '=', root_bom.id),
                ('line', '=', str(bom_line.id)),
                ('state', '=', 'draft')
            ])

            if mos:
                mos.action_cancel()
                mos.unlink()

            # Recurse into child BOM
            if bom_line.child_bom_id:
                for child_line in bom_line.child_bom_id.bom_line_ids:
                    recursive_mo_cleanup(child_line)

        # Start recursive cleanup
        recursive_mo_cleanup(line)

    def _find_child_mos_recursive(self, bom, root_bom):
        """Recursively find all child MOs"""
        MO = self.env['mrp.production']
        all_mos = self.env['mrp.production']

        for line in bom.bom_line_ids:
            line_mos = MO.search([
                ('root_bom_id', '=', root_bom.id),
                ('line', '=', str(line.id)),
                ('state', '=', 'draft')
            ])
            all_mos |= line_mos

            if line.child_bom_id:
                all_mos |= self._find_child_mos_recursive(line.child_bom_id, root_bom)

        return all_mos

    def _cleanup_branch_records(self, line, root_bom):
        """Delete branch and component records for this line and all descendants recursively"""
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        Location = self.env['stock.location']

        def recursive_cleanup(bom_line):
            """Recursively clean up branches and components"""
            _logger.info(f"Cleaning up line {bom_line.product_id.display_name}")

            # Delete ALL component records for this line (both direct and branch-linked)
            all_components = Component.search([
                ('root_bom_id', '=', root_bom.id),
                ('cr_bom_line_id', '=', bom_line.id)
            ])

            if all_components:
                _logger.info(f"Deleting {len(all_components)} component records")
                all_components.unlink()

            # Delete branches for this line
            branches = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', bom_line.id)
            ])

            if branches:
                _logger.info(f"Deleting {len(branches)} branch records")

                # Store locations to delete later
                locations_to_delete = branches.mapped('location_id')

                # Delete branches first
                branches.unlink()

                # Delete unused locations
                for loc in locations_to_delete:
                    if loc and loc.exists():
                        # Check if location is still referenced
                        other_branches = Branch.search([('location_id', '=', loc.id)], limit=1)
                        other_components = Component.search([('location_id', '=', loc.id)], limit=1)

                        if not other_branches and not other_components:
                            quants = self.env['stock.quant'].search([('location_id', '=', loc.id)], limit=1)
                            moves = self.env['stock.move'].search([
                                '|',
                                ('location_id', '=', loc.id),
                                ('location_dest_id', '=', loc.id)
                            ], limit=1)

                            if not quants and not moves:
                                _logger.info(f"Deleting unused location {loc.display_name}")
                                loc.unlink()

            # Recurse into child BOM
            if bom_line.child_bom_id:
                for child_line in bom_line.child_bom_id.bom_line_ids:
                    recursive_cleanup(child_line)

        recursive_cleanup(line)

    def _delete_child_components_recursive(self, bom, root_bom):
        """Recursively delete components for child BOMs"""
        Component = self.env['mrp.bom.line.branch.components']

        for line in bom.bom_line_ids:
            Component.search([
                ('root_bom_id', '=', root_bom.id),
                ('cr_bom_line_id', '=', line.id)
            ]).unlink()

            if line.child_bom_id:
                self._delete_child_components_recursive(line.child_bom_id, root_bom)

    def _get_all_components_for_line(self, line, root_bom):
        """Get all component records for this line and its children"""
        Component = self.env['mrp.bom.line.branch.components']
        all_components = self.env['mrp.bom.line.branch.components']

        # Get components for this line
        components = Component.search([
            ('root_bom_id', '=', root_bom.id),
            ('cr_bom_line_id', '=', line.id)
        ])
        all_components |= components

        # Get components for children if BOM exists
        if line.child_bom_id:
            for child_line in line.child_bom_id.bom_line_ids:
                all_components |= self._get_all_components_for_line(child_line, root_bom)

        return all_components

    def _cleanup_manufacturing_orders(self, line, root_bom):
        """Cancel and delete manufacturing orders - returns list of deleted MOs"""
        deleted_mos = []

        def recursive_cleanup_mos(bom_line):
            nonlocal deleted_mos
            line = bom_line.id
            mos = self.env['mrp.production'].search([
                ('line', '=', line),
                ('product_id', '=', bom_line.product_id.id),
                ('root_bom_id', '=', root_bom.id),
                ('state', 'in', ['draft', 'confirmed', 'progress']),
            ])

            if mos:
                for mo in mos:
                    deleted_mos.append({
                        'name': mo.name,
                        'product': mo.product_id.display_name
                    })
                    _logger.info(f"  ✗ Deleting MO: {mo.name} for {mo.product_id.display_name}")

                mos.action_cancel()
                mos.unlink()

            if bom_line.child_bom_id:
                for child_line in bom_line.child_bom_id.bom_line_ids:
                    recursive_cleanup_mos(child_line)

        recursive_cleanup_mos(line)
        return deleted_mos

    def _cleanup_purchase_orders(self, line, root_bom):
        """Cancel purchase orders - returns list of deleted PO lines"""
        deleted_pos = []

        def recursive_cleanup_pos(bom_line):
            nonlocal deleted_pos

            po_lines = self.env['purchase.order.line'].search([
                ('product_id', '=', bom_line.product_id.id),
                ('order_id.state', 'in', ['draft', 'sent', 'to approve']),
                ('bom_id','=',root_bom.id)
            ])

            for po_line in po_lines:
                pickings = po_line.order_id.picking_ids

                if pickings:
                    deleted_pos.append({
                        'po_name': po_line.order_id.name,
                        'product': bom_line.product_id.display_name
                    })
                    _logger.info(f"  ✗ Deleting PO line from {po_line.order_id.name}")
                    po_line.unlink()

            if bom_line.child_bom_id:
                for child_line in bom_line.child_bom_id.bom_line_ids:
                    recursive_cleanup_pos(child_line)

        recursive_cleanup_pos(line)
        return deleted_pos


    def _cleanup_branch_records(self, line, root_bom):
        """Delete branch and component records - returns counts"""
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']

        total_branches = 0
        total_components = 0

        def recursive_cleanup(bom_line):
            nonlocal total_branches, total_components

            components = Component.search([
                ('root_bom_id', '=', root_bom.id),
                ('cr_bom_line_id', '=', bom_line.id)
            ])

            if components:
                total_components += len(components)
                _logger.info(f"  ✗ Deleting {len(components)} component(s)")
                components.unlink()

            branches = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', bom_line.id)
            ])

            if branches:
                total_branches += len(branches)
                _logger.info(f"  ✗ Deleting {len(branches)} branch(es)")

                locations = branches.mapped('location_id')
                branches.unlink()

                for loc in locations:
                    if loc and loc.exists():
                        if not Branch.search([('location_id', '=', loc.id)], limit=1) and \
                                not Component.search([('location_id', '=', loc.id)], limit=1):
                            if not self.env['stock.quant'].search([('location_id', '=', loc.id)], limit=1) and \
                                    not self.env['stock.move'].search(
                                        ['|', ('location_id', '=', loc.id), ('location_dest_id', '=', loc.id)],
                                        limit=1):
                                _logger.info(f"  ✗ Deleting location: {loc.complete_name}")
                                loc.unlink()

            if bom_line.child_bom_id:
                for child_line in bom_line.child_bom_id.bom_line_ids:
                    recursive_cleanup(child_line)

        recursive_cleanup(line)
        return total_branches, total_components


    def _cleanup_stock_pickings(self, line, root_bom):
        """Override to handle transfer reversal for MAKE to BUY"""
        cancelled_transfers = []
        reversed_transfers = []

        def recursive_cleanup_pickings(bom_line):
            nonlocal cancelled_transfers, reversed_transfers

            origin = f"EVR Flow - {root_bom.display_name}"
            pickings = self.env['stock.picking'].search([
                ('root_bom_id', '=', root_bom.id),
                ('state', 'in', ['draft', 'waiting', 'confirmed', 'assigned']),
                ('location_dest_id', 'child_of', root_bom.cfe_project_location_id.id),
                ('origin', '=', origin)
            ])

            for picking in pickings:
                moves = picking.move_ids.filtered(lambda m: m.product_id.id == bom_line.product_id.id
                                                            and m.mrp_bom_line_id.id == bom_line.id
                                                  )
                if moves:
                    cancelled_transfers.append({
                        'transfer_name': picking.name,
                        'product': bom_line.product_id.display_name
                    })
                    _logger.info(f"  ✗ Cancelling transfer: {picking.name}")
                    picking.action_cancel()

            # Find done pickings that transferred to branch - create reverse
            origin = f"EVR Flow - {root_bom.display_name}"
            done_pickings = self.env['stock.picking'].search([
                ('root_bom_id', '=', root_bom.id),
                ('state', '=', 'done'),
                ('location_dest_id', 'child_of', root_bom.cfe_project_location_id.id),
                ('origin', '=', origin)
            ])

            for picking in done_pickings:
                moves = picking.move_ids.filtered(lambda m: m.product_id.id == bom_line.product_id.id
                                                            and m.mrp_bom_line_id.id == bom_line.id
                                                  )
                if moves:
                    for move in moves:
                        if move.quantity > 0:
                            reversed = self._create_reverse_transfer_to_free(move, root_bom)
                            if reversed:
                                reversed_transfers.append({
                                    'transfer_name': reversed.name,
                                    'product': bom_line.product_id.display_name,
                                    'qty': move.quantity
                                })

            if bom_line.child_bom_id:
                for child_line in bom_line.child_bom_id.bom_line_ids:
                    recursive_cleanup_pickings(child_line)

        recursive_cleanup_pickings(line)

        # Combine results
        all_transfers = cancelled_transfers + [{
            'transfer_name': t['transfer_name'],
            'product': t['product'],
            'reversed': True,
            'qty': t.get('qty', 0)
        } for t in reversed_transfers]

        return all_transfers

    def _create_reverse_transfer_to_free(self, original_move, root_bom):
        """Create reverse transfer from branch to FREE location"""
        # Find FREE location
        free_location = self.env['stock.location'].search([
            ('location_category', '=', 'free'),
            ('usage', '=', 'internal')
        ], limit=1)

        if not free_location:
            _logger.warning("No FREE location found for reverse transfer")
            return False

        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', root_bom.company_id.id)
        ], limit=1)

        if not picking_type:
            return False


        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': original_move.location_dest_id.id,
            'location_dest_id': original_move.location_id.id,
            'origin': "reverse transfer of evr",
            'move_ids': [(0, 0, {
                'name': original_move.product_id.display_name,
                'product_id': original_move.product_id.id,
                'product_uom_qty': original_move.quantity,
                'product_uom': original_move.product_uom.id,
                'location_id': original_move.location_dest_id.id,
                'location_dest_id': free_location.id,
            })]
        })

        picking.action_confirm()
        picking.action_assign()
        picking.button_validate()

        _logger.info(f"  ↩ Created reverse transfer: {picking.name}")
        return picking


    def _cleanup_purchase_orders(self, line, root_bom):
        """Override to cancel POs created for this BOM line and its children"""
        deleted_pos = []
        confirmed_pos = []

        _logger.info("START _cleanup_purchase_orders | line=%s root_bom=%s", line.id, root_bom.id)

        def recursive_cleanup_pos(bom_line):
            nonlocal deleted_pos, confirmed_pos

            # Find ALL component branches for this BOM line
            component_branches = self.env['mrp.bom.line.branch.components'].search([
                ('cr_bom_line_id', '=', bom_line.id),
                ('root_bom_id', '=', root_bom.id)
            ])

            _logger.info(
                "Found %s component branches for BOM line %s",
                len(component_branches), bom_line.id
            )

            for component in component_branches:
                # Find CFE PO lines (customer POs)
                cfe_po_lines = self.env['purchase.order.line'].search([
                    ('component_branch_id', '=', component.id),
                    ('bom_id', '=', root_bom.id),
                    ('order_id.cfe', '=', True),
                ])

                _logger.info(
                    "Component %s: Found %s CFE PO lines",
                    component.id, len(cfe_po_lines)
                )

                for po_line in cfe_po_lines:
                    po = po_line.order_id
                    _logger.info(
                        "Processing CFE PO line %s in %s (state=%s)",
                        po_line.id, po.name, po.state
                    )

                    if po.state in ['draft', 'sent', 'to approve']:
                        deleted_pos.append({
                            'po_name': po.name,
                            'product': bom_line.product_id.display_name,
                            'type': 'CFE'
                        })
                        _logger.info("  ✗ Deleting CFE PO line %s from %s", po_line.id, po.name)

                        # Remove the line
                        po_line.unlink()

                        # If PO has no more lines, delete the PO
                        if not po.order_line:
                            po_name = po.name
                            po.button_cancel()
                            po.unlink()
                            _logger.info("  ✗ Deleted empty PO %s", po_name)

                    elif po.state in ['purchase', 'done']:
                        confirmed_pos.append({
                            'po_name': po.name,
                            'product': bom_line.product_id.display_name,
                            'vendor': po.partner_id.name,
                            'type': 'CFE'
                        })
                        _logger.info(
                            "  ✓ Confirmed CFE PO line %s in %s (vendor: %s)",
                            po_line.id, po.name, po.partner_id.name
                        )

                # Find regular PO lines (vendor POs)
                vendor_po_lines = self.env['purchase.order.line'].search([
                    ('component_branch_id', '=', component.id),
                    ('bom_id', '=', root_bom.id),
                    ('order_id.cfe', '=', False),
                ])

                _logger.info(
                    "Component %s: Found %s vendor PO lines",
                    component.id, len(vendor_po_lines)
                )

                for po_line in vendor_po_lines:
                    po = po_line.order_id
                    _logger.info(
                        "Processing vendor PO line %s in %s (state=%s)",
                        po_line.id, po.name, po.state
                    )

                    if po.state in ['draft', 'sent', 'to approve']:
                        deleted_pos.append({
                            'po_name': po.name,
                            'product': bom_line.product_id.display_name,
                            'type': 'Vendor'
                        })
                        _logger.info("  ✗ Deleting vendor PO line %s from %s", po_line.id, po.name)

                        # Remove the line
                        po_line.unlink()

                        # If PO has no more lines, delete the PO
                        if not po.order_line:
                            po_name = po.name
                            po.button_cancel()
                            po.unlink()
                            _logger.info("  ✗ Deleted empty PO %s", po_name)

                    elif po.state in ['purchase', 'done']:
                        confirmed_pos.append({
                            'po_name': po.name,
                            'product': bom_line.product_id.display_name,
                            'vendor': po.partner_id.name,
                            'type': 'Vendor'
                        })
                        _logger.info(
                            "  ✓ Confirmed vendor PO line %s in %s (vendor: %s)",
                            po_line.id, po.name, po.partner_id.name
                        )

            # Recurse into child BOM if exists
            if bom_line.child_bom_id:
                _logger.info(
                    "Recursing into child BOM %s for line %s",
                    bom_line.child_bom_id.id, bom_line.id
                )
                for child_line in bom_line.child_bom_id.bom_line_ids:
                    recursive_cleanup_pos(child_line)

        # Start recursion from the line being changed
        recursive_cleanup_pos(line)

        # Notify purchase admin if confirmed POs exist
        if confirmed_pos:
            _logger.info("Notifying purchase admin about %s confirmed POs", len(confirmed_pos))
            self._notify_purchase_admin(confirmed_pos, line.product_id.display_name)

        _logger.info(
            "END _cleanup_purchase_orders | deleted=%s confirmed=%s",
            len(deleted_pos), len(confirmed_pos)
        )
        return deleted_pos

    def _notify_purchase_admin(self, confirmed_pos, product_name):
        """Notify purchase admin users about confirmed POs"""
        purchase_admin_group = self.env.ref('purchase.group_purchase_manager', raise_if_not_found=False)

        if not purchase_admin_group:
            return

        message = f"⚠️ Product '{product_name}' changed from MAKE to BUY\n\n"
        message += f"The following confirmed Purchase Orders need manual review:\n\n"

        for po in confirmed_pos[:10]:
            message += f"  • PO: {po['po_name']}\n"
            message += f"    Product: {po['product']}\n"
            message += f"    Vendor: {po['vendor']}\n\n"

        if len(confirmed_pos) > 10:
            message += f"  ... and {len(confirmed_pos) - 10} more\n"

        for user in purchase_admin_group.users:
            self.env['bus.bus']._sendone(
                user.partner_id,
                'simple_notification',
                {
                    'title': 'MAKE → BUY: Confirmed POs Require Review',
                    'message': message,
                    'type': 'warning',
                    'sticky': True,
                }
            )

    def action_change_buy_make_selection(self, new_value):
        """
        Delegation method for backward compatibility with frontend calls to mrp.bom.line.
        Redirects the call to the appropriate mrp.bom.line.branch record.
        """
        self.ensure_one()
        _logger.info(f"Delegating BUY/MAKE change for BOM line {self.id} to branch...")
        
        root_bom_id = self.env.context.get('root_bom_id')
        if not root_bom_id:
             # Try to find root BOM if not in context
             root_bom = self._find_actual_root_bom(self)
             root_bom_id = root_bom.id if root_bom else False

        if not root_bom_id:
            return {'success': False, 'message': 'Root BOM not found for delegation'}

        # 1. Try to find a branch record
        branch = self.env['mrp.bom.line.branch'].search([
            ('bom_id', '=', root_bom_id),
            ('bom_line_id', '=', self.id)
        ], limit=1)

        if branch:
            _logger.info(f"Redirecting call to branch {branch.id}")
            return branch.action_change_buy_make_selection(new_value)

        # 2. Try to find a component record (since BUY selections are now components)
        component = self.env['mrp.bom.line.branch.components'].search([
            ('root_bom_id', '=', root_bom_id),
            ('cr_bom_line_id', '=', self.id)
        ], limit=1)

        if component:
            _logger.info(f"Redirecting call to component {component.id}")
            return component.action_change_buy_make_selection(new_value)

        _logger.warning(f"No branch or component record found for BOM line {self.id} under root BOM {root_bom_id}")
        return {'success': False, 'message': 'No structural record found for this line'}
