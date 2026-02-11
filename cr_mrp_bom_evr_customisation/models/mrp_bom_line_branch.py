# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import api, fields, models
from odoo.addons import decimal_precision as dp

class MrpBomLineBranch(models.Model):
    _name = "mrp.bom.line.branch"
    _description = "Branch mapping per BOM per path"
    _rec_name = 'branch_name'

    bom_id = fields.Many2one('mrp.bom', string='BOM', required=True, ondelete='cascade', index=True)
    bom_line_id = fields.Many2one('mrp.bom.line', string='BOM Line', ondelete='cascade', index=True)
    branch_name = fields.Char(string='Branch', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=0)
    path_uid = fields.Char(string='Path UID', index=True)
    location_id = fields.Many2one('stock.location', string='Branch Location', ondelete='set null')
    mrp_bom_line_branch_component_ids = fields.One2many(
        'mrp.bom.line.branch.components',
        inverse_name='bom_line_branch_id',
        string='Branch components',
        ondelete='cascade'
    )
    free_to_use = fields.Float(
        string='Free To Use',
        compute='_compute_free_to_use',
        store=True,
        digits=dp.get_precision('Product Unit of Measure'),
        help="Total free quantity from all branch components whose locations are marked free"
    )
    transferred = fields.Float(string='Transferred', default=0.0)
    used = fields.Float(string='Used', default=0.0)

    _sql_constraints = [
        ('bom_branch_unique', 'unique(bom_id, branch_name)', 'Branch name must be unique per BOM.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """Override to prevent recursive branch assignment"""
        return super(MrpBomLineBranch, self.with_context(skip_branch_recompute=True)).create(vals_list)

    def write(self, vals):
        """Override to prevent recursive branch assignment"""
        return super(MrpBomLineBranch, self.with_context(skip_branch_recompute=True)).write(vals)

    def unlink(self):
        """Override to prevent recursive branch assignment"""
        return super(MrpBomLineBranch, self.with_context(skip_branch_recompute=True)).unlink()

    # -----------------------------
    # NAME GET
    # -----------------------------

    def name_get(self):
        res = []
        for r in self:
            name = f"{r.bom_id.display_name}/{r.branch_name}"
            if r.bom_line_id and r.bom_line_id.product_id:
                name += f" - {r.bom_line_id.product_id.display_name}"
            res.append((r.id, name))
        return res

    # -----------------------------
    # OPEN COMPONENTS
    # -----------------------------

    def action_view_branch_components(self):
        self.ensure_one()
        action = self.env.ref(
            'cr_mrp_bom_evr_customisation.action_mrp_bom_line_branch_components'
        ).read()[0]
        action['domain'] = [('bom_line_branch_id', '=', self.id)]
        return action


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


