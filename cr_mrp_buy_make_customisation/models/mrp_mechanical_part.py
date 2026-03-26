# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpMechanicalPart(models.Model):
    _name = "mrp.mechanical.part"
    _description = "Stable Interface for Mechanical Parts Management"
    _order = "project_name, root_product_code, path_key"

    path_key = fields.Char(string='Path Key', index=True, copy=False)
    root_bom_id = fields.Many2one('mrp.bom', string='Root BOM', ondelete='cascade', required=True)
    bom_id = fields.Many2one('mrp.bom', string='BOM', ondelete='cascade')
    bom_line_id = fields.Many2one('mrp.bom.line', string='Product', ondelete='cascade', required=True)
    parent_branch_name = fields.Char(string='Parent Branch Name')
    
    project_name = fields.Char(string='Project')
    root_product_code = fields.Char(string='Root Everest PN')
    
    mo_ids = fields.Many2many('mrp.production', string='MOs')
    all_mos_draft = fields.Boolean(
        string='All MOs Draft',
        compute='_compute_all_mos_draft',
        store=True,
        default=True
    )
    is_buy_make_product = fields.Boolean(string='Is Buy/Make Product')
    
    buy_make_selection = fields.Selection([
        ('buy', 'BUY'),
        ('make', 'MAKE'),
    ], string='Buy/Make', inverse='_inverse_buy_make_selection')
    
    part_type = fields.Selection([
        ('branch', 'Branch'),
        ('component', 'Component')
    ], string='Part Type', default='branch', index=True)

    @api.depends('mo_ids', 'mo_ids.state')
    def _compute_all_mos_draft(self):
        for rec in self:
            if not rec.mo_ids:
                rec.all_mos_draft = True
            else:
                # Check all non-cancelled MOs
                active_mos = rec.mo_ids.filtered(lambda m: m.state != 'cancel')
                if not active_mos:
                    rec.all_mos_draft = True
                else:
                    rec.all_mos_draft = all(m.state == 'draft' for m in active_mos)

    def _inverse_buy_make_selection(self):
        # Recursion Guard: Skip if triggered by the sync logic itself
        if self.env.context.get('skip_mechanical_sync'):
            return

        for rec in self:
            if not rec.buy_make_selection:
                continue
                
            # Trigger the standard dynamic transition logic
            # This will unlink/rebuild structural records, but THIS mechanical.part record remains stable.
            rec.root_bom_id.action_transition_bom_line(
                line_id=rec.bom_line_id.id,
                record_model='mrp.mechanical.part',
                record_id=rec.id,
                new_value=rec.buy_make_selection,
                parent_branch_name=rec.parent_branch_name
            )

    @api.model
    def sync_mechanical_parts(self, root_bom, structural_data):
        """
        Synchronize mechanical.part records with structural data.
        'structural_data' is a list of dicts: [
            {'path_key': '...', 'bom_line_id': ID, 'parent_branch_name': '...', 
             'selection': 'buy/make', 'mo_ids': [IDs]},
            ...
        ]
        """
        # 1. Map existing records for this root BoM
        existing_parts = self.search([('root_bom_id', '=', root_bom.id)])
        path_map = {p.path_key: p for p in existing_parts}
        
        seen_keys = set()
        project_name = root_bom.project_id.name if root_bom.project_id else ''
        root_product_code = root_bom.product_tmpl_id.default_code if root_bom.product_tmpl_id else ''

        # Use context guard to prevent inverse methods from triggering rebuilds during sync
        SelfSync = self.with_context(skip_mechanical_sync=True)

        for data in structural_data:
            key = data['path_key']
            seen_keys.add(key)
            
            vals = {
                'root_bom_id': root_bom.id,
                'bom_id': data['bom_id'],
                'bom_line_id': data['bom_line_id'],
                'parent_branch_name': data['parent_branch_name'],
                'project_name': project_name,
                'root_product_code': root_product_code,
                'mo_ids': [(6, 0, data.get('mo_ids', []))],
                'all_mos_draft': data.get('all_mos_draft', True),
                'is_buy_make_product': data.get('is_buy_make_product', False),
                'buy_make_selection': data.get('selection'),
                'part_type': data.get('part_type', 'branch'),
            }
            
            if key in path_map:
                path_map[key].with_context(skip_mechanical_sync=True).write(vals)
            else:
                vals['path_key'] = key
                SelfSync.create(vals)
        
        # 3. Purge those not in the current structure
        to_unlink = existing_parts.filtered(lambda p: p.path_key not in seen_keys)
        to_unlink.unlink()
