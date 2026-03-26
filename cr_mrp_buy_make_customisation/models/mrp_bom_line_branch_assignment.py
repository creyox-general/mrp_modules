# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpBomLineBranchAssignment(models.Model):
    _inherit = "mrp.bom.line.branch.assignment"

    # Fields for Mechanical Parts Management
    project_name = fields.Char(string='Project', compute='_compute_mechanical_data')
    root_product_code = fields.Char(string='Root Everest PN', compute='_compute_mechanical_data')
    
    mo_ids = fields.Many2many('mrp.production', compute='_compute_mechanical_data', string='MOs')
    all_mos_draft = fields.Boolean(string='All MOs Draft', compute='_compute_mechanical_data', search='_search_all_mos_draft')
    
    buy_make_selection = fields.Selection([
        ('buy', 'BUY'),
        ('make', 'MAKE'),
    ], string='Buy/Make', compute='_compute_buy_make_selection', inverse='_inverse_buy_make_selection')
    
    is_buy_make_product = fields.Boolean(compute='_compute_is_buy_make_product')

    @api.depends('bom_line_id.product_id')
    def _compute_is_buy_make_product(self):
        for rec in self:
            rec.is_buy_make_product = rec.bom_line_id.product_id.manufacture_purchase == 'buy_make'

    def _compute_mechanical_data(self):
        Production = self.env['mrp.production']
        for rec in self:
            # 1. Project & Root Product Info
            rec.project_name = rec.root_bom_id.project_id.name if rec.root_bom_id.project_id else ''
            rec.root_product_code = rec.root_bom_id.product_tmpl_id.default_code if rec.root_bom_id.product_tmpl_id else ''
            
            # 2. MO IDs
            domain = [('root_bom_id', '=', rec.root_bom_id.id), ('state', '!=', 'cancel')]
            if rec.own_branch_id:
                domain.append(('branch_mapping_id', '=', rec.own_branch_id.id))
            elif rec.component_id:
                 # Search for components by line ID in the Produiction model if we track them there
                 domain.append(('line', '=', str(rec.bom_line_id.id)))
            else:
                 rec.mo_ids = False
                 rec.all_mos_draft = True
                 continue
                 
            mos = Production.search(domain)
            rec.mo_ids = mos
            
            # 3. All MOs Draft Filter
            if not mos:
                rec.all_mos_draft = True
            else:
                rec.all_mos_draft = all(mo.state == 'draft' for mo in mos)

    def _search_all_mos_draft(self, operator, value):
        all_assignments = self.search([])
        target_ids = []
        for assign in all_assignments:
            assign._compute_mechanical_data()
            if (assign.all_mos_draft == value):
                target_ids.append(assign.id)
        return [('id', 'in', target_ids)]

    @api.depends('own_branch_id', 'component_id')
    def _compute_buy_make_selection(self):
        for rec in self:
            if rec.own_branch_id:
                rec.buy_make_selection = 'make'
            elif rec.component_id:
                rec.buy_make_selection = 'buy'
            else:
                rec.buy_make_selection = False

    def _inverse_buy_make_selection(self):
        for rec in self:
            if rec.buy_make_selection in ('buy', 'make'):
                rec.root_bom_id.action_transition_bom_line(
                    line_id=rec.bom_line_id.id,
                    record_model='mrp.bom.line.branch.assignment',
                    record_id=rec.id,
                    new_value=rec.buy_make_selection
                )
