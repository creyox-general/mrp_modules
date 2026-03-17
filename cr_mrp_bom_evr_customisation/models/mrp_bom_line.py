# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api,fields
import logging

from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    customer_ref = fields.Char(string='Customer ref')
    root_bom_assignment_ids = fields.One2many('mrp.bom.line.branch.assignment', 'bom_line_id', 
                                           string='Root BOM Assignments')

    def write(self, vals):
        quantity_changed = 'product_qty' in vals

        res = super().write(vals)

        if quantity_changed and not self.env.context.get('skip_mo_qty_update'):
            for line in self:
                if line.bom_id.is_evr and line.child_bom_id:
                    self._update_child_mo_quantities(line, line.bom_id.id)


        return res

    def _update_child_mo_quantities(self, line, root_bom_id, parent_qty=1.0):
        """Recursively update MO quantities for this line and all its children"""
        # Find MOs for this line
        mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom_id),
            ('line', '=', line.id),
            ('state', '=', 'draft')
        ])

        for mo in mos:
            # Calculate new quantity
            new_qty = float(line.product_qty or 1.0) * parent_qty

            # Get locations from context or recalculate
            Branch = self.env['mrp.bom.line.branch']
            branches = Branch.search([
                ('bom_id', '=', root_bom_id),
                ('bom_line_id', '=', line.id)
            ], order='sequence', limit=1)

            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            stock_location = warehouse.lot_stock_id if warehouse else False

            current_branch_location = branches.location_id.id if branches and branches.location_id else False
            print('_update_child_mo_quantities :')
            parent_branch_location = mo.parent_mo_id.branch_intermediate_location_id.id if mo.parent_mo_id else False
            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # Update MO with all three locations - USE with_context to skip component recalculation
            mo.with_context(skip_compute_move_raw_ids=True).write({
                'product_qty': new_qty,
                'location_src_id': stock_location.id if stock_location else mo.location_src_id.id,
                'branch_intermediate_location_id': current_branch_location if current_branch_location else mo.branch_intermediate_location_id.id,
                'location_dest_id': final_dest_location if final_dest_location else mo.location_dest_id.id,
            })

            # Update child MOs recursively
            if line.child_bom_id:
                for child_line in line.child_bom_id.bom_line_ids:
                    if child_line.child_bom_id:
                        self._update_child_mo_quantities(child_line, root_bom_id, new_qty)

    def _collect_affected_root_boms(self):
        """
        Find root BOMs that must be recalculated based on line changes.
        Performance optimization: process by unique parent BOM.
        """
        affected_roots = set()
        parent_boms = self.mapped('bom_id')

        for bom in parent_boms:
            _logger.info(f"[SYNC TRACE] _collect_affected_root_boms checking parent BOM '{bom.display_name}' (ID {bom.id})")

            # Method 1: from explicit used_in_root_bom_ids_str tracking
            if bom.used_in_root_bom_ids_str:
                id_strings = [i.strip() for i in bom.used_in_root_bom_ids_str.split(',') if i.strip()]
                for root_id_str in id_strings:
                    try:
                        affected_roots.add(int(root_id_str))
                    except ValueError:
                        pass

            # Method 2: BFS ancestor search via product relationship
            helpers = self.env['cr.mrp.bom.helpers']
            roots = helpers.get_root_boms_for_bom(bom)
            for r in roots:
                affected_roots.add(r.id)

            # Method 3 (most reliable): directly search BOM lines that explicitly
            # reference this BOM as child_bom_id, bypassing product-based lookup.
            direct_parent_lines = self.env['mrp.bom.line'].search([
                ('child_bom_id', '=', bom.id)
            ])
            for pl in direct_parent_lines:
                p_bom = pl.bom_id
                if not p_bom:
                    continue
                if p_bom.is_evr and (p_bom.cfe_project_location_id or getattr(p_bom, 'sale_order_id', False)):
                    affected_roots.add(p_bom.id)
                # Traverse further up from the parent BOM
                for r in helpers.get_root_boms_for_bom(p_bom):
                    affected_roots.add(r.id)

        # Filter for EVR roots with projects/SO
        final_roots = self.env['mrp.bom'].browse(list(affected_roots)).filtered(
            lambda r: r.is_evr and (r.cfe_project_location_id or getattr(r, 'sale_order_id', False))
        )
        _logger.info(f"[SYNC TRACE] Final EVR Roots to reassign: {[r.display_name for r in final_roots]}")
        return final_roots

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"[SYNC TRACE] mrp.bom.line.create triggered for {len(vals_list)} lines. Context: {self.env.context}")
        lines = super(MrpBomLine, self.with_context(skip_branch_recompute=True)).create(vals_list)

        if not self.env.context.get('skip_branch_recompute'):
            _logger.info(f"[SYNC TRACE] skip_branch_recompute is FALSE, checking affected roots...")
            roots = lines._collect_affected_root_boms()
            if roots:
                for root in roots:
                    _logger.info(f"[SYNC TRACE] Triggering _assign_branches_for_bom on Root '{root.display_name}' (ID {root.id})")
                    self.env['bus.bus']._sendone(
                        self.env.user.partner_id, "simple_notification",
                        {"title": "BOM Hierarchy Sync", "message": f"Adding component to '{root.display_name}' hierarchy...", "sticky": False, "type": "info"}
                    )
                    root._assign_branches_for_bom()
            else:
                _logger.info(f"[SYNC TRACE] No affected roots found for these newly created lines.")
        else:
            _logger.info(f"[SYNC TRACE] skip_branch_recompute is TRUE, skipping trigger.")

        return lines

    def get_assignment(self, root_bom, parent_branch=None):
        """
        Get the branch assignment for this line in a given context (Root BOM + Parent Branch).
        This is necessary because a single BOM line can have different assignments 
        depending on its path in the hierarchy.
        """
        Assignment = self.env['mrp.bom.line.branch.assignment']
        parent_branch_id = parent_branch.id if parent_branch and hasattr(parent_branch, 'id') else parent_branch
        
        domain = [
            ('bom_line_id', '=', self.id),
            ('root_bom_id', '=', root_bom.id),
            ('branch_id', '=', parent_branch_id or False)
        ]
        return Assignment.search(domain, limit=1)

    def _delete_child_records_recursive(self, line, root_bom_id):
        """Recursively delete Branch, Component, and Draft MO records for a line's subtree."""
        Component = self.env['mrp.bom.line.branch.components']
        Branch = self.env['mrp.bom.line.branch']
        Production = self.env['mrp.production']

        # Determine child BOM (same logic as branch assignment)
        child_bom = line.child_bom_id
        if not child_bom:
             # Try default BOM for product
             child_bom = self.env['mrp.bom']._get_first_created_bom(line.product_id)

        if child_bom:
            _logger.info("Cleaning up subtree for line %s (Product: %s)", line.id, line.product_id.display_name)
            for child_line in child_bom.bom_line_ids:
                # 1. Delete associated Components
                Component.search([
                    ('cr_bom_line_id', '=', child_line.id),
                    ('root_bom_id', '=', root_bom_id)
                ]).unlink()

                # 2. Delete associated Branches
                branches = Branch.search([
                    ('bom_line_id', '=', child_line.id),
                    ('bom_id', '=', root_bom_id)
                ])
                for branch in branches:
                    branch.unlink() # Cascades to its components via O2M ondelete

                # 3. Delete associated Draft MOs
                Production.search([
                    ('root_bom_id', '=', root_bom_id),
                    ('line', '=', str(child_line.id)),
                    ('state', '=', 'draft')
                ]).unlink()

                # 4. RECURSE: Process the next level down
                self._delete_child_records_recursive(child_line, root_bom_id)

    def unlink(self):
        # 1. Collect affected root BOMs before deleting the lines
        roots = self._collect_affected_root_boms() if not self.env.context.get('skip_branch_recompute') else self.env['mrp.bom']

        # 2. Delete associated tracking records and draft MOs BEFORE the lines are gone
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        Production = self.env['mrp.production']
        
        del_counts = {'branch': 0, 'comp': 0, 'mo': 0}

        for line in self:
            _logger.info("Deleting line %s and its associated records", line.id)
            
            line_roots = self.env['cr.mrp.bom.helpers'].get_root_boms_for_bom(line.bom_id)
            for root in line_roots:
                 # Recursive cleanup (now includes MO)
                 self._delete_child_records_recursive(line, root.id)

            # Cleanup direct records for THIS line
            comps = Component.search([('cr_bom_line_id', '=', line.id)])
            del_counts['comp'] += len(comps)
            comps.unlink()
            
            branches = Branch.search([('bom_line_id', '=', line.id)])
            del_counts['branch'] += len(branches)
            for branch in branches:
                branch.unlink()

            mos = Production.search([('line', '=', str(line.id)), ('state', '=', 'draft')])
            del_counts['mo'] += len(mos)
            mos.unlink()

        # Notify user about deletion start
        if any(del_counts.values()):
            self.env['bus.bus']._sendone(
                self.env.user.partner_id, "simple_notification",
                {"title": "Cleaning Up BOM Hierarchy", 
                 "message": f"Removing {del_counts['branch']} branches, {del_counts['comp']} components, and {del_counts['mo']} draft MOs...", 
                 "sticky": False, "type": "warning"}
            )

        # 3. Perform the actual unlink
        res = super(MrpBomLine, self.with_context(skip_branch_recompute=True)).unlink()

        # 4. Trigger incremental update for roots
        if roots:
             for root in roots:
                 self.env['bus.bus']._sendone(
                     self.env.user.partner_id, "simple_notification",
                     {"title": "BOM Hierarchy Sync", "message": f"Syncing '{root.display_name}' after deletion...", "sticky": False, "type": "info"}
                 )
                 root._assign_branches_for_bom()

        return res

    def _skip_bom_line(self, product, never_attribute_values=False):
        """Override to pass context when exploding child BOMs"""
        result = super()._skip_bom_line(product,never_attribute_values)

        if result and self.bom_id.is_evr:
            # Pass this line's ID in context for child BOM explosion
            return result.with_context(parent_bom_line_id=self.id)

        return result



