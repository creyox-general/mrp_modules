# -*- coding: utf-8 -*-
from odoo import models,api,fields
import logging
_logger = logging.getLogger(__name__)

class MrpBomLineBranch(models.Model):
    _inherit = "mrp.bom.line.branch"

    def _should_consider_location(self, location, bom_line=None):
        """
        Override to include TAPY locations for MECH category products.
        Check if a location should be considered by checking itself and then its parent chain.
        Returns True if:
        1. The location (or ancestor) is marked as 'free', OR
        2. Product has MECH category AND location (or ancestor) is marked as 'tapy'
        """
        if not location:
            return False

            # Check if product has MECH category
        product = bom_line.product_id if bom_line else False
        is_mech_product = product and product.categ_id and product.categ_id.mech

        location_fields = self.env['stock.location']._fields
        use_boolean_field = 'free_to_use' in location_fields

        cur = location
        while cur:
            # Check if current location is free or tapy
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
        'bom_line_id.product_id',
        'bom_line_id.product_id.stock_quant_ids',
        'bom_line_id.product_id.stock_quant_ids.quantity',
        'bom_line_id.product_id.stock_quant_ids.reserved_quantity',
        'bom_line_id.product_id.stock_quant_ids.location_id',
        'bom_line_id.product_id.stock_quant_ids.location_id.location_category',
        'bom_line_id.product_id.stock_quant_ids.location_id.location_id.location_category'
    )
    def _compute_free_to_use(self):
        StockQuant = self.env['stock.quant']

        for rec in self:
            rec.free_to_use = 0.0
            if not rec.bom_line_id or not rec.bom_line_id.product_id:
                continue

            product = rec.bom_line_id.product_id
            bom_line = rec.bom_line_id  # Store for this specific record

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

    buy_make_selection = fields.Selection([
        ('buy', 'BUY'),
        ('make', 'MAKE'),
    ], string='BUY/MAKE Selection', tracking=True,)

    critical = fields.Boolean(string='Critical', default=False, store=True,
                               help='Mark this branch as a critical component')

    is_buy_make_product = fields.Boolean(
        compute='_compute_is_buy_make_product',
        store=True
    )


    @api.depends('bom_line_id.product_id', 'bom_line_id.product_id.manufacture_purchase')
    def _compute_is_buy_make_product(self):
        for rec in self:
            rec.is_buy_make_product = rec.bom_line_id.product_id.manufacture_purchase == 'buy_make'

    def action_change_buy_make_selection(self, new_value):
        """
        Delegate to the stable Atomic Transition Proxy on the BOM model.
        This avoids the "Record does not exist" error when unlinking self.
        """
        self.ensure_one()
        _logger.info(f"Delegating branch transition for {self.branch_name} (ID: {self.id}) to BOM proxy")
        
        root_bom = self.bom_id
        if not root_bom:
            return {'success': False, 'message': 'Root BOM not found'}

        return root_bom.action_transition_bom_line(
            line_id=self.bom_line_id.id,
            record_model=self._name,
            record_id=self.id,
            new_value=new_value
        )

    def _cleanup_branch_manufacturing_orders(self, root_bom):
        """Cancel and delete MOs linked to this branch and its descendants (Recursive)"""
        deleted_mos = []
        
        # Find MOs for this specific branch
        mos = self.env['mrp.production'].search([
            ('branch_mapping_id', '=', self.id),
            ('root_bom_id', '=', root_bom.id),
            ('state', 'in', ['draft', 'confirmed', 'progress']),
        ])
        
        for mo in mos:
            deleted_mos.append({'name': mo.name, 'product': mo.product_id.display_name})
            _logger.info(f"  ✗ Deleting branch MO: {mo.name}")
            mo.action_cancel()
            mo.unlink()

        # Recurse into child branches
        child_branches = self.env['mrp.bom.line.branch'].search([('parent_branch_id', '=', self.id)])
        for child in child_branches:
            deleted_mos.extend(child._cleanup_branch_manufacturing_orders(root_bom))
            
        return deleted_mos

    def _cleanup_branch_purchase_orders(self, root_bom):
        """Cancel PO lines linked to component branches under this branch hierarchy (Recursive)"""
        deleted_pos = []
        confirmed_pos = []
        
        # Component branches directly under this branch
        components = self.env['mrp.bom.line.branch.components'].search([
            ('bom_line_branch_id', '=', self.id),
            ('root_bom_id', '=', root_bom.id)
        ])
        
        for comp in components:
            # Handle both CFE and regular Vendor POs
            po_lines = self.env['purchase.order.line'].search([
                ('component_branch_id', '=', comp.id),
                ('bom_id', '=', root_bom.id),
            ])
            for po_line in po_lines:
                po = po_line.order_id
                if po.state in ['draft', 'sent', 'to approve']:
                    deleted_pos.append({
                        'po_name': po.name, 
                        'product': po_line.product_id.display_name,
                        'type': 'CFE' if po.cfe else 'Vendor'
                    })
                    _logger.info(f"  ✗ Deleting branch PO line from {po.name}")
                    po_line.unlink()
                    if not po.order_line:
                        po.button_cancel()
                        po.unlink()
                elif po.state in ['purchase', 'done']:
                    confirmed_pos.append({
                        'po_name': po.name,
                        'product': po_line.product_id.display_name,
                        'vendor': po.partner_id.name,
                        'type': 'CFE' if po.cfe else 'Vendor'
                    })

        # Recurse into descendant branches
        child_branches = self.env['mrp.bom.line.branch'].search([('parent_branch_id', '=', self.id)])
        for child in child_branches:
            res_deleted, res_confirmed = child._cleanup_branch_purchase_orders_recursive_data(root_bom)
            deleted_pos.extend(res_deleted)
            confirmed_pos.extend(res_confirmed)

        # Notify purchase admin about confirmed POs if switching to BUY
        if confirmed_pos and self.buy_make_selection == 'buy':
             self._notify_purchase_admin_for_branch(confirmed_pos)
            
        return deleted_pos

    def _cleanup_branch_purchase_orders_recursive_data(self, root_bom):
        """Helper for recursive PO data collection without immediate notification"""
        deleted_pos = []
        confirmed_pos = []
        components = self.env['mrp.bom.line.branch.components'].search([
            ('bom_line_branch_id', '=', self.id),
            ('root_bom_id', '=', root_bom.id)
        ])
        for comp in components:
            po_lines = self.env['purchase.order.line'].search([
                ('component_branch_id', '=', comp.id),
                ('bom_id', '=', root_bom.id),
            ])
            for po_line in po_lines:
                po = po_line.order_id
                if po.state in ['draft', 'sent', 'to approve']:
                    deleted_pos.append({
                        'po_name': po.name, 
                        'product': po_line.product_id.display_name,
                        'type': 'CFE' if po.cfe else 'Vendor'
                    })
                    po_line.unlink()
                    if not po.order_line:
                        po.button_cancel()
                        po.unlink()
                elif po.state in ['purchase', 'done']:
                    confirmed_pos.append({
                        'po_name': po.name,
                        'product': po_line.product_id.display_name,
                        'vendor': po.partner_id.name,
                        'type': 'CFE' if po.cfe else 'Vendor'
                    })
        child_branches = self.env['mrp.bom.line.branch'].search([('parent_branch_id', '=', self.id)])
        for child in child_branches:
            res_deleted, res_confirmed = child._cleanup_branch_purchase_orders_recursive_data(root_bom)
            deleted_pos.extend(res_deleted)
            confirmed_pos.extend(res_confirmed)
        return deleted_pos, confirmed_pos

    def _notify_purchase_admin_for_branch(self, confirmed_pos):
        """Notify purchase admin about confirmed POs in branch hierarchy"""
        purchase_admin_group = self.env.ref('purchase.group_purchase_manager', raise_if_not_found=False)
        if not purchase_admin_group:
            return

        product_name = self.bom_line_id.product_id.display_name
        message = f"⚠️ Product '{product_name}' (Branch: {self.branch_name}) changed from MAKE to BUY\n\n"
        message += f"The following confirmed Purchase Orders in this hierarchy need manual review:\n\n"

        for po in confirmed_pos[:10]:
            message += f"  • PO: {po['po_name']} ({po['type']})\n"
            message += f"    Product: {po['product']}\n"
            message += f"    Vendor: {po['vendor']}\n\n"

        if len(confirmed_pos) > 10:
            message += f"  ... and {len(confirmed_pos) - 10} more\n"

        for user in purchase_admin_group.users:
            self.env['bus.bus']._sendone(
                user.partner_id,
                'simple_notification',
                {
                    'title': 'MAKE → BUY: Branch Hierarchy Review Required',
                    'message': message,
                    'type': 'warning',
                    'sticky': True,
                }
            )

    def _cleanup_branch_stock_pickings(self, root_bom):
        """Cancel and reverse transfers for this branch hierarchy (Recursive)"""
        results = []
        origin = f"EVR Flow - {root_bom.display_name}"
        
        # Gather all descendant component lines
        def get_all_descendant_lines(branch):
            lines = []
            components = self.env['mrp.bom.line.branch.components'].search([
                ('bom_line_branch_id', '=', branch.id),
                ('root_bom_id', '=', root_bom.id)
            ])
            lines.extend(components.mapped('cr_bom_line_id.id'))
            
            child_branches = self.env['mrp.bom.line.branch'].search([('parent_branch_id', '=', branch.id)])
            for child in child_branches:
                lines.extend(get_all_descendant_lines(child))
            return lines

        descendant_line_ids = get_all_descendant_lines(self)

        # 1. Cancel pending transfers related to any descendant component
        pickings = self.env['stock.picking'].search([
            ('root_bom_id', '=', root_bom.id),
            ('origin', '=', origin),
            ('state', 'not in', ['cancel', 'done']),
        ])
        for picking in pickings:
            if picking.move_ids:
                results.append({'transfer_name': picking.name, 'product': picking.move_ids[0].product_id.display_name})
                _logger.info(f"  ✗ Cancelling descendant transfer: {picking.name}")
                picking.action_cancel()

        # 2. Reverse DONE transfers if switching to BUY
        done_pickings = self.env['stock.picking'].search([
            ('root_bom_id', '=', root_bom.id),
            ('state', '=', 'done'),
            ('location_dest_id', 'child_of', root_bom.cfe_project_location_id.id),
            ('origin', '=', origin)
        ])

        for picking in done_pickings:
            for move in picking.move_ids:
                if move.quantity > 0:
                    reversed_trans = self.env['mrp.bom.line']._create_reverse_transfer_to_free(move, root_bom)
                    if reversed_trans:
                        _logger.info(f"  ↩ Created reverse transfer for branch descendant: {reversed_trans.name}")
                        results.append({
                            'transfer_name': reversed_trans.name,
                            'product': move.product_id.display_name,
                            'qty': move.quantity,
                            'reversed': True
                        })
            # Remove link to prevent double-reversal as requested by user
            picking.write({'root_bom_id': False})

        return results

    def _cleanup_descendant_branch_records(self, root_bom):
        """Delete descendant branch and component records (Recursive)"""
        total_branches = 0
        total_components = 0
        
        # Clean up components directly under this branch
        components = self.env['mrp.bom.line.branch.components'].search([
            ('bom_line_branch_id', '=', self.id),
            ('root_bom_id', '=', root_bom.id)
        ])
        if components:
            total_components += len(components)
            _logger.info(f"  ✗ Deleting {len(components)} descendant components")
            components.unlink()
            
        # Recurse into child branches
        child_branches = self.env['mrp.bom.line.branch'].search([('parent_branch_id', '=', self.id)])
        for child in child_branches:
            b, c = child._cleanup_descendant_branch_records(root_bom)
            total_branches += b + 1
            total_components += c
            _logger.info(f"  ✗ Deleting descendant branch: {child.branch_name}")
            child.unlink()
            
        return total_branches, total_components
