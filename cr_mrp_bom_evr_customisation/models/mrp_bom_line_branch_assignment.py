# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields

class MrpBomLineBranchAssignment(models.Model):
    _name = "mrp.bom.line.branch.assignment"
    _description = "Context-aware branch assignment for BOM lines"
    _order = "root_bom_id, bom_line_id"

    root_bom_id = fields.Many2one('mrp.bom', string='Root BOM', index=True, ondelete='cascade', required=True)
    bom_id = fields.Many2one('mrp.bom', string='BOM', index=True, ondelete='cascade', required=True)
    bom_line_id = fields.Many2one('mrp.bom.line', string='BOM Line', index=True, ondelete='cascade', required=True)
    
    branch_id = fields.Many2one('mrp.bom.line.branch', string='Parent Branch', index=True, ondelete='cascade',
                                help="The branch this line belongs to as a component.")
    
    own_branch_id = fields.Many2one('mrp.bom.line.branch', string='Own Branch', index=True, ondelete='cascade',
                                   help="The branch formed by this line (if it has a child BOM).")
    
    component_id = fields.Many2one('mrp.bom.line.branch.components', string='Component', index=True, ondelete='cascade',
                                   help="The tracking component record (if leaf).")
    
    root_line_id = fields.Many2one('mrp.bom.line', string='Root Component Line', index=True, ondelete='cascade',
                                  help="The direct component of the absolute root BOM that leads to this path.")

    _sql_constraints = [
        ('path_assignment_unique', 'unique(root_bom_id, bom_line_id, branch_id)', 
         'A line can only have one assignment per branch context in a root BOM.')
    ]
