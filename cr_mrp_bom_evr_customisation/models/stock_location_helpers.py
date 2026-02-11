# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)


class BranchLocationHelper(models.AbstractModel):
    _name = "cr.mrp.bom.branch.location.helper"
    _description = "Helper to create or find branch stock locations"

    @api.model
    def get_project_parent_location(self):
        """
        Always use parent location:
            name = 'Project Location'
            usage = 'internal'
        If not exist → create it.
        """
        StockLocation = self.env['stock.location']

        parent = StockLocation.search([
            ('name', '=', 'Project Location'),
            ('usage', '=', 'internal'),
        ], limit=1)

        if parent:
            return parent

        # Create parent Project Location
        vals = {
            'name': 'Project Location',
            'usage': 'internal',
            'location_id': False,  # root-level
        }
        parent = StockLocation.create(vals)
        return parent


    @api.model
    def create_or_get_branch_location(self, bom, branch_code):
        StockLocation = self.env['stock.location']
        parent = self.get_project_parent_location()

        loc_name = f"{bom.display_name or bom.product_tmpl_id.name} - {branch_code}"
        # loc_name = f"{branch_code}"

        existing = StockLocation.search([
            ('name', '=', loc_name),
            ('location_id', '=', parent.id),
        ], limit=1)
        if existing:
            return existing

        vals = {
            'name': loc_name,
            'location_id': parent.id,
            'usage': 'internal',
        }
        loc = StockLocation.create(vals)
        return loc

