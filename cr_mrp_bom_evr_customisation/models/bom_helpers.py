# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api

class MrpBomHelpers(models.AbstractModel):
    _name = "cr.mrp.bom.helpers"
    _description = "Helper: find ancestor/root BOMs"

    @api.model
    def _get_parent_bom_lines(self, bom):
        """
        Find bom.line records whose child_bom_id == bom.id.
        Cannot search child_bom_id directly → filter in Python.
        """
        BomLine = self.env["mrp.bom.line"]

        # Step 1: Get all BOM lines whose product might trigger this BOM
        possible_lines = BomLine.search([
            ("product_id.product_tmpl_id", "=", bom.product_tmpl_id.id)
        ])

        # Step 2: Filter by actual child_bom_id relation
        parent_lines = possible_lines.filtered(
            lambda l: l.child_bom_id and l.child_bom_id.id == bom.id
        )

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

            if not parent_lines:
                # No parents ⇒ this is a root BOM
                roots.add(bom)
                continue

            # Add all parent BOMs to queue
            for line in parent_lines:
                parent_bom = line.bom_id
                if parent_bom and parent_bom.id not in visited:
                    queue.append(parent_bom)

        return list(roots)
