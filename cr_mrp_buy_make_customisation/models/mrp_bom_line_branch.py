# -*- coding: utf-8 -*-
from odoo import models,api,fields


class MrpBomLineBranch(models.Model):
    _inherit = "mrp.bom.line.branch"

    critical = fields.Boolean(
        string='Critical',
        compute='_compute_critical',
        store=True,
        help='Branch is critical if BOM line is critical or MO contains critical components'
    )

    @api.depends(
        'bom_line_id.critical',
        'bom_line_id.approve_to_manufacture',
    )
    def _compute_critical(self):
        """
        Branch is critical if:
        1. The BOM line is marked as critical, OR
        2. approve_to_manufacture is True AND the MO contains critical components
        """
        for branch in self:
            # if branch.bom_line_id.critical:
            #     branch.critical = True
            # elif branch.bom_line_id.approve_to_manufacture and branch.mo_id:
            #     branch.critical = branch.mo_id.critical
            # else:
            #     branch.critical = False
            branch.critical = False

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