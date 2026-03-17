# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api

class MrpBomHelpers(models.AbstractModel):
    _name = "cr.mrp.bom.helpers"
    _description = "Helper: find ancestor/root BOMs"

    @api.model
    def _get_parent_bom_lines(self, bom):
        """
        Find bom.line records that lead to this 'bom'.
        Includes lines with explicit child_bom_id, AND lines where child_bom_id 
        is NULL but this is the default BOM for the product.
        """
        BomLine = self.env["mrp.bom.line"]
        
        # Determine if this is the default BOM for its own product
        product = bom.product_id or bom.product_tmpl_id.product_variant_id
        # Use existing method in mrp.bom to find default/first BOM
        first_bom = self.env['mrp.bom']._get_first_created_bom(product)
        is_default_bom = (first_bom and first_bom.id == bom.id)

        # Step 1: Get all BOM lines whose product might trigger this BOM
        possible_lines = BomLine.search([
            '|',
            ("product_id.product_tmpl_id", "=", bom.product_tmpl_id.id),
            ("product_tmpl_id", "=", bom.product_tmpl_id.id)
        ])

        # Step 2: Filter by actual child_bom_id relation OR evaluate first created BOM
        def is_parent(l):
            if l.child_bom_id and l.child_bom_id.id == bom.id:
                return True
            if not l.child_bom_id and hasattr(l.bom_id, '_get_first_created_bom'):
                first_bom = l.bom_id._get_first_created_bom(l.product_id)
                if first_bom and first_bom.id == bom.id:
                    return True
            return False

        parent_lines = possible_lines.filtered(is_parent)

        return parent_lines

    @api.model
    def get_root_boms_for_bom(self, start_bom):
        """
        BFS upwards until we reach BOMs with no parents.
        """
        visited = set()
        roots = set()
        queue = [start_bom]

        while queue:
            bom = queue.pop(0)
            if not bom or bom.id in visited:
                continue

            visited.add(bom.id)

            # Use the SAFE parent finder (no search on child_bom_id)
            parent_lines = self._get_parent_bom_lines(bom)

            # If it has no parents OR it has its own Project/Sale Order, it is a Root BOM
            if not parent_lines or bom.cfe_project_location_id or getattr(bom, 'sale_order_id', False):
                roots.add(bom)

            # If it has no parents, we can stop traversing this branch
            if not parent_lines:
                continue

            # Add all parent BOMs to queue
            for line in parent_lines:
                parent_bom = line.bom_id
                if parent_bom and parent_bom.id not in visited:
                    queue.append(parent_bom)

        return list(roots)
