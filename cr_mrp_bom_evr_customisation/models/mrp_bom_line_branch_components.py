# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp

class MrpBomLineBranchComponents(models.Model):
    _name = "mrp.bom.line.branch.components"
    _description = "Branch components per BOM per path"

    quantity = fields.Float(
        string='Quantity',
    )
    cfe_quantity = fields.Char(
        string='CFE Quantity',
        help="Customer Furnished Equipment quantity - supplied by customer at zero cost"
    )
    approval_1 = fields.Boolean(string='Approval 1', default=False)
    approval_2 = fields.Boolean(string='Approval 2', default=False)
    mo_internal_ref = fields.Many2one(
        comodel_name="product.supplierinfo",
        string="Preferred Manufacturer",
        help="Select the manufacturer/vendor defined on the product card."
    )
    product_manufacturer_id = fields.Many2one(comodel_name="product.manufacturer.detail", string='')
    can_edit_approval_2 = fields.Boolean(
        string='Can Edit Approval 2',
        compute='_compute_can_edit_approval_2',
        help="Technical field to check if user can edit Approval 2"
    )
    show_cfe_quantity = fields.Boolean(
        string='Show CFE Quantity',
        compute='_compute_show_cfe_quantity',
        store=True,
        help="Technical field to control CFE quantity visibility"
    )
    show_approval_1 = fields.Boolean(compute='_compute_show_cfe_quantity', store=True)
    show_approval_2 = fields.Boolean(compute='_compute_show_cfe_quantity', store=True)
    show_mo_internal_ref = fields.Boolean(compute='_compute_show_cfe_quantity', store=True)

    bom_line_branch_id = fields.Many2one('mrp.bom.line.branch', string='BOM Line Branch', ondelete='cascade')
    root_bom_id = fields.Many2one('mrp.bom', string='Root BOM', ondelete='cascade')
    bom_id = fields.Many2one('mrp.bom', string='Just Child BOM', ondelete='cascade')
    cr_bom_line_id = fields.Many2one('mrp.bom.line', string='BOM Line', ondelete='cascade', index=True)
    to_order = fields.Float(string='To Order', default=0.0)
    to_order_cfe = fields.Float(string='To Order CFE', default=0.0)
    ordered = fields.Float(string='Ordered', default=0.0)
    ordered_cfe = fields.Float(string='Ordered CFE', default=0.0)
    to_transfer = fields.Float(string='To Transfer', default=0.0)
    to_transfer_cfe = fields.Float(string='To Transfer CFE', default=0.0)
    transferred = fields.Float(string='Transferred', default=0.0)
    transferred_cfe = fields.Float(string='Transferred CFE', default=0.0)
    used = fields.Float(string='Used', default=0.0)
    is_direct_component = fields.Boolean(string='Is Direct Component', default=False)
    location_id = fields.Many2one('stock.location', string='Location')
    free_to_use = fields.Float(
        string='Free to Use',
        compute='_compute_free_to_use',
        store=True,
        digits=dp.get_precision('Product Unit of Measure'),
        help="Quantity available to use from assigned location if that location (or any ancestor) is marked free."
    )
    customer_po_ids = fields.One2many('purchase.order.line',inverse_name='component_customer_po_id',string='Customer PO Line')
    vendor_po_ids = fields.One2many('purchase.order.line',inverse_name='component_vendor_po_id', string='Vendor PO Line')

    @api.depends('bom_id.is_evr')
    def _compute_show_cfe_quantity(self):
        """Compute whether CFE quantity and new fields should be shown"""
        for line in self:
            show = line.bom_id.is_evr
            line.show_cfe_quantity = show
            line.show_approval_1 = show
            line.show_approval_2 = show
            line.show_mo_internal_ref = show

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
            print('pmd : ',pmd)
            if pmd:
                line.product_manufacturer_id = pmd.id


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
        StockQuant = self.env['stock.quant']
        for rec in self:
            rec.free_to_use = 0.0
            if not rec.cr_bom_line_id or not rec.cr_bom_line_id.product_id:
                continue

            product = rec.cr_bom_line_id.product_id

            # Search for quants with positive quantity (stored field)
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
                if available_qty > 0 and self._should_consider_location(quant.location_id):
                    total_qty += available_qty

            rec.free_to_use = float(total_qty)

    def _should_consider_location(self, location):
        """
        Check if a location should be considered by checking itself and then its parent chain.
        Returns True if the location itself OR any of its ancestors is marked as free.
        Stops checking as soon as a free location is found.
        """
        if not location:
            return False

        location_fields = self.env['stock.location']._fields
        use_boolean_field = 'free_to_use' in location_fields

        cur = location
        while cur:
            # Check if current location is free
            is_free = False
            if use_boolean_field:
                try:
                    is_free = bool(cur.free_to_use)
                except Exception:
                    pass
            else:
                try:
                    is_free = getattr(cur, 'location_category', False) == 'free'
                except Exception:
                    pass

            if is_free:
                # Found a free location in the chain, so this location should be considered
                return True

            # Move to parent and continue checking
            cur = cur.location_id

        # No free location found in the entire parent chain
        return False

    @api.model_create_multi
    def create(self, vals_list):
        """Override to prevent recursive branch assignment"""
        return super(MrpBomLineBranchComponents, self.with_context(skip_branch_recompute=True)).create(vals_list)

    def write(self, vals):
        """Override to prevent recursive branch assignment"""
        return super(MrpBomLineBranchComponents, self.with_context(skip_branch_recompute=True)).write(vals)

    def unlink(self):
        """Override to prevent recursive branch assignment"""
        return super(MrpBomLineBranchComponents, self.with_context(skip_branch_recompute=True)).unlink()



