# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
import logging

from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    branch_mapping_id = fields.Many2one('mrp.bom.line.branch', string='Branch Mapping', help="Branch mapping for this MO (if set, finished goods will go to this branch location)")
    root_bom_id = fields.Many2one("mrp.bom", string="Root BOM", help="Top-level BOM where the chain started.")
    parent_mo_id = fields.Many2one("mrp.production", string="Parent Manufacturing Order")
    can_manufacture = fields.Boolean(
        string="Approved to Manufacture",
        compute="_compute_can_manufacture",
        store=True,
    )
    line = fields.Char(string='Line')
    branch_intermediate_location_id = fields.Many2one(
        'stock.location',
        string='Branch Intermediate Location',
        help='Intermediate branch location before moving to parent'
    )
    cr_final_location_id = fields.Many2one(
        'stock.location',
        string='Parent Location',
    )


    def _compute_can_manufacture(self):
        for mo in self:
            # A MO is linked to bom_line via product / child BOM → so:
            line = self.env['mrp.bom.line'].search([
                ('child_bom_id', '=', mo.bom_id.id),
                ('bom_id', '=', mo.root_bom_id.id),
            ], limit=1)

            mo.can_manufacture = line.approve_to_manufacture if line else False

    def button_unreserve(self):
        self._check_approve_to_manufacture()
        return super().button_unreserve()

    def action_scrap(self):
        self._check_approve_to_manufacture()
        return super().action_scrap()


    def _check_approve_to_manufacture(self):
        for mo in self:
            if mo.root_bom_id and self.line:
                bom = mo.bom_id


                line = self.env['mrp.bom.line'].search([
                                ('product_id', '=', self.product_id.id),
                                ('id','=',int(self.line))
                            ], limit=1)

                is_main_allowed = line.approve_to_manufacture if line else False

                if is_main_allowed:
                    allowed = self._check_descendant_approval(bom)

                    if not allowed:
                        raise UserError(
                            "You cannot perform this operation because not all BOM lines "
                            "below this MO are approved for manufacture.\n\n"
                            "Please enable 'Approve to Manufacture' on all child BOM lines."
                        )
                else:
                    raise UserError(
                        "You cannot perform this operation because not all BOM lines "
                        "below this MO are approved for manufacture.\n\n"
                        "Please enable 'Approve to Manufacture' on all child BOM lines."
                    )

    def _check_descendant_approval(self, bom):
        """
        Check approval ONLY for lines that have a child BOM.
        """

        lines = self.env['mrp.bom.line'].search([
            ('bom_id', '=', bom.id),
        ])

        for line in lines:

            # Skip lines that do NOT have child BOM
            if not line.child_bom_id:
                continue


            # If this line with child BOM is NOT approved → FAIL
            if not line.approve_to_manufacture:
                return False

            # If approved and has child BOM → go deeper
            if not self._check_descendant_approval(line.child_bom_id):
                return False

        return True

    # def move_finished_to_branch(self):
    #     """Move finished product quantity from production output location to branch location."""
    #     for prod in self:
    #         if not prod.branch_mapping_id or not prod.branch_mapping_id.location_id:
    #             _logger.info("No branch mapping/location set for production %s", prod.name)
    #             continue
    #
    #         dest_location = prod.branch_mapping_id.location_id
    #         # Find final moves (finished moves) for this production
    #         finished_moves = prod.move_finished_ids.filtered(lambda m: m.state in ('draft','confirmed','waiting') or m.state == 'done')
    #         if not finished_moves:
    #             # sometimes finished moves are in move_raw_work or move_finished_ids, try move_raw_ids_by_finished or stock pickings
    #             finished_moves = prod.move_finished_ids
    #
    #         if not finished_moves:
    #             _logger.warning("No finished moves found for production %s", prod.name)
    #             continue
    #
    #         # For safety, create a transfer of the produced qty from current destination to branch location
    #         for mv in finished_moves:
    #             # Skip if already at desired location
    #             if mv.location_dest_id.id == dest_location.id:
    #                 _logger.info("Move %s already has destination %s", mv.id, dest_location.name)
    #                 continue
    #
    #             # Best practice: create a new stock.picking or move to move the quantity
    #             # Here we will create a new internal move that moves product from current dest to branch location.
    #             try:
    #                 move_vals = {
    #                     'name': f"Move to branch {prod.branch_mapping_id.branch_name} for {prod.name}",
    #                     'product_id': mv.product_id.id,
    #                     'product_uom_qty': mv.product_uom_qty,
    #                     'product_uom': mv.product_uom.id,
    #                     'location_id': mv.location_dest_id.id,
    #                     'location_dest_id': dest_location.id,
    #                     'company_id': prod.company_id.id,
    #                     'origin': prod.name,
    #                 }
    #                 new_move = self.env['stock.move'].create(move_vals)
    #                 # Confirm & assign & done quickly (depends on your workflow)
    #                 new_move._action_confirm()
    #                 new_move._action_assign()
    #                 new_move._action_done()
    #             except Exception as e:
    #                 _logger.exception("Failed to create branch move for production %s: %s", prod.name, e)


    # def _get_approved_bom_lines(self, bom):
    #     """
    #     Get only approved BOM lines (where all children are approved)
    #     """
    #     approved_lines = self.env['mrp.bom.line']
    #
    #     for line in bom.bom_line_ids:
    #         if bom._check_all_children_approved(line):
    #             approved_lines |= line
    #
    #     return approved_lines

    @api.model_create_multi
    def create(self, vals_list):
        # PART 1: Handle validation for EVR BOMs
        for vals in vals_list:
            if vals.get('bom_id'):
                bom = self.env['mrp.bom'].browse(vals['bom_id'])
                if bom.is_evr:
                    unapproved_lines = []

                    if bom.project_id:
                        vals['project_id'] = bom.project_id.id

                    for line in bom.bom_line_ids:
                        if not bom._check_all_children_approved(line):
                            unapproved_lines.append(line.product_id.display_name)

                    if unapproved_lines:
                        raise ValidationError(
                            "Cannot create MO. The following BOM lines or their sub-components are not approved for manufacture:\n" +
                            "\n".join([f"- {name}" for name in unapproved_lines])
                        )

            # branch_intermediate_location = self.env.context.get('branch_intermediate_location')
            #
            # # Store intermediate location
            # if branch_intermediate_location:
            #     vals['branch_intermediate_location_id'] = branch_intermediate_location

        # PART 2: Create MOs with skip context to prevent component computation
        skip_moves = self.env.context.get('skip_component_moves')

        if skip_moves:
            mos = super(MrpProduction, self.with_context(skip_compute_move_raw_ids=True)).create(vals_list)
        else:
            mos = super().create(vals_list)

        return mos

    def action_confirm(self):
        """Override to compute moves when confirming"""
        # Force recompute of raw and finished moves for draft MOs without moves
        for mo in self:
            if mo.state == 'draft' and not mo.move_raw_ids:
                # Trigger computation of component moves
                mo._compute_move_raw_ids()

        # Call original confirmation
        self._check_approve_to_manufacture()
        res = super().action_confirm()

        # for mo in self:
        #
        #     own_branch = mo.branch_intermediate_location_id
        #     parent_branch = mo.location_dest_id
        #
        #     if own_branch and parent_branch:
        #         # Update finished product move lines: Own branch → Parent branch
        #         for move in mo.all_move_raw_ids:
        #             print('move : ',mo)
        #             move.write({
        #                 'location_id': own_branch.id,
        #                 # 'location_dest_id': parent_branch.id,
        #             })
        #
        #             if move.move_line_ids:
        #                 move.move_line_ids.write({
        #                     'location_id': own_branch.id,
        #                     # 'location_dest_id': parent_branch.id,
        #                 })

        for mo in self:
            # Get all child MOs
            child_mos = self.env['mrp.production'].search([
                ('parent_mo_id', '=', mo.id)
            ])

            if child_mos:
                # Check if any child MO is not confirmed
                unconfirmed_children = child_mos.filtered(lambda m: m.state in ['draft', 'cancel'])

                if unconfirmed_children:
                    child_names = ', '.join(unconfirmed_children.mapped('name'))
                    raise ValidationError(
                        f"Cannot confirm MO {mo.name}. "
                        f"Please confirm all child Manufacturing Orders first:\n{child_names}"
                    )


        return res

    def _generate_raw_moves(self):
        """Override to skip component moves on creation if context flag is set"""
        if self.env.context.get('skip_component_moves'):
            return self.env['stock.move']
        return super()._generate_raw_moves()


    # def _get_component_id_for_line(self, root_bom_id, bom_line, parent_bom, index=0):
    #     """
    #     Get the component branch ID for a BOM line using the same logic as report.
    #     """
    #     Component = self.env["mrp.bom.line.branch.components"]
    #
    #     # Check for child BOM
    #     child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')
    #     if child_bom:
    #         return False
    #
    #     # ROOT LEVEL COMPONENT
    #     if not parent_bom or parent_bom.id == root_bom_id:
    #         components = Component.search([
    #             ('root_bom_id', '=', root_bom_id),
    #             ('bom_id', '=', parent_bom.id),
    #             ('cr_bom_line_id', '=', bom_line.id),
    #             ('is_direct_component', '=', True),
    #         ])
    #
    #         if not components:
    #             return False
    #
    #         if len(components) == 1:
    #             return components[0].id
    #
    #         try:
    #             comp = components[int(index)]
    #             return comp.id
    #         except (IndexError, ValueError):
    #             return components[0].id if components else False
    #
    #     # CHILD LEVEL COMPONENT
    #     components = Component.search([
    #         ('root_bom_id', '=', root_bom_id),
    #         ('bom_id', '=', parent_bom.id),
    #         ('cr_bom_line_id', '=', bom_line.id),
    #         ('is_direct_component', '=', False),
    #     ], order='id')
    #
    #     if not components:
    #         return False
    #
    #     if len(components) == 1:
    #         return components[0].id
    #
    #     # Multiple components - use cache logic
    #     index_str = str(index)
    #     path_key = f"{root_bom_id}_{bom_line.id}_{index_str}"
    #
    #     if not hasattr(self.__class__, '_component_assignment_cache'):
    #         self.__class__._component_assignment_cache = {}
    #
    #     cache = self.__class__._component_assignment_cache
    #     cache_key = f"bom_{root_bom_id}"
    #
    #     if cache_key not in cache:
    #         cache[cache_key] = {
    #             'assignments': {},
    #             'seen_paths': []
    #         }
    #
    #     bom_cache = cache[cache_key]
    #
    #     if path_key not in bom_cache['seen_paths']:
    #         existing_count = len([p for p in bom_cache['seen_paths']
    #                               if p.startswith(f"{root_bom_id}_{bom_line.id}_")])
    #
    #         if existing_count < len(components):
    #             component = components[existing_count]
    #         else:
    #             component = components[-1]
    #
    #         bom_cache['assignments'][path_key] = component.id
    #         bom_cache['seen_paths'].append(path_key)
    #         return component.id
    #     else:
    #         component_id = bom_cache['assignments'].get(path_key)
    #         return component_id if component_id else components[0].id

    # def _generate_raw_moves(self):
    #     """Override to set branch location instead of Pre-Production"""
    #     moves = super()._generate_raw_moves()
    #
    #     if self.branch_intermediate_location_id:
    #         for move in moves:
    #             # Find the move going to Pre-Production
    #             if move.location_dest_id.is_subcontracting_location or \
    #                     'Pre-Production' in move.location_dest_id.complete_name:
    #                 move.location_dest_id = self.branch_intermediate_location_id
    #
    #     return moves

    # def _get_consumption_issues(self):
    #     """Override to use branch location instead of Pre-Production"""
    #     issues = super()._get_consumption_issues()
    #
    #     if self.branch_intermediate_location_id:
    #         # Update location references in issues
    #         for issue in issues:
    #             if 'Pre-Production' in str(issue.get('location', '')):
    #                 issue['location'] = self.branch_intermediate_location_id.display_name
    #
    #     return issues

    @api.model
    def _prepare_procurement_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id,
                                    values):
        """Override to pass branch location context"""
        res = super()._prepare_procurement_values(product_id, product_qty, product_uom, location_id, name, origin,
                                                  company_id, values)

        if self.branch_intermediate_location_id:
            print('in _prepare_procurement_values')
            res['branch_intermediate_location'] = self.branch_intermediate_location_id.id

        return res


