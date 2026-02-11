# -*- coding: utf-8 -*-
# Part of Creyox Technologies.

from odoo import models, fields, api


class MrpBomContext(models.Model):
    _name = 'mrp.bom.context'
    _description = 'BOM Context Data for EVR functionality'
    _rec_name = 'display_name'

    root_bom_id = fields.Many2one('mrp.bom', required=True, ondelete='cascade')
    bom_line_id = fields.Many2one('mrp.bom.line', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)

    # NEW: Add session tracking
    session_id = fields.Char(
        string='Session ID',
        help="Unique identifier for each BOM usage session"
    )
    is_active_session = fields.Boolean(
        string='Active Session',
        default=True,
        help="Whether this context belongs to the current active session"
    )

    cfe_quantity = fields.Char(string='CFE Quantity')
    product_qty = fields.Char(string='CFE Quantity')
    lli = fields.Boolean(string='LLI', default=False)
    approval_1 = fields.Boolean(string='Approval 1', default=False)
    approval_2 = fields.Boolean(string='Approval 2', default=False)
    po_created = fields.Boolean(string='PO Created', default=False)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    # Updated constraint to include session_id
    _sql_constraints = [
        ('unique_root_bom_line_session',
         'unique(root_bom_id, bom_line_id, session_id)',
         'Only one context record per BOM line per session allowed!')
    ]

    related_mo_id = fields.Many2one('mrp.production', string='Related MO', ondelete='set null')
    mo_internal_ref = fields.Many2one(
        'res.partner',
        string='Selected Vendor',
        help="The vendor/manufacturer selected for this BOM line."
    )

    @api.model
    def get_or_create_session_id(self, root_bom_id):
        """Get current active session or create a new one"""
        # Check if there's an active session without related_mo_id
        active_session = self.search([
            ('root_bom_id', '=', root_bom_id),
            ('is_active_session', '=', True),
            ('related_mo_id', '=', False)
        ], limit=1)

        if active_session:
            return active_session.session_id

        # Create new session ID
        import uuid
        new_session_id = str(uuid.uuid4())
        return new_session_id

    @api.model
    def reset_context_values(self, root_bom_id, mo_id):
        """Reset context values ONLY for current active session"""
        # Find contexts that belong to active session (no related_mo_id)
        active_contexts = self.search([
            ('root_bom_id', '=', root_bom_id),
            ('is_active_session', '=', True),
            ('related_mo_id', '=', False)
        ])

        for context in active_contexts:
            context.write({
                'cfe_quantity': '',
                'lli': False,
                'approval_1': False,
                'approval_2': False,
                'mo_internal_ref': False,
                # Keep po_created to prevent duplicate POs
                'related_mo_id': mo_id,
                'is_active_session': False  # Mark as processed
            })


    @api.model
    def reset_for_new_cycle(self, root_bom_id):
        """Reset all values including po_created for a completely new cycle"""
        contexts = self.search([('root_bom_id', '=', root_bom_id)])
        contexts.write({
            'cfe_quantity': '',
            'lli': False,
            'approval_1': False,
            'approval_2': False,
            'po_created': False,
            'related_mo_id': False,
            'is_active_session': True,
            'session_id': self.get_or_create_session_id(root_bom_id)
        })

    @api.model
    def mark_pos_created_for_bom(self, root_bom_id):
        """Mark ONLY active session contexts as having POs created"""
        active_contexts = self.search([
            ('root_bom_id', '=', root_bom_id),
            ('is_active_session', '=', True),
            ('related_mo_id', '=', False)
        ])
        active_contexts.write({'po_created': True})

    @api.depends('root_bom_id', 'bom_line_id', 'product_id', 'session_id')
    def _compute_display_name(self):
        for rec in self:
            session_part = f" (Session: {rec.session_id[:8]}...)" if rec.session_id else ""
            rec.display_name = f"{rec.root_bom_id.display_name} - {rec.product_id.display_name}{session_part}"

    @api.model
    def get_context_data(self, root_bom_id, bom_line_id):
        """Get context data for active session only"""
        # First try to find active session context
        context = self.search([
            ('root_bom_id', '=', root_bom_id),
            ('bom_line_id', '=', bom_line_id),
            ('is_active_session', '=', True),
            ('related_mo_id', '=', False)
        ], limit=1)

        if context:
            return {
                'cfe_quantity': context.cfe_quantity or '',
                'lli': context.lli,
                'approval_1': context.approval_1,
                'approval_2': context.approval_2,
                'po_created': context.po_created,
                'mo_internal_ref': context.mo_internal_ref.id if context.mo_internal_ref else False,
            }

        # Return defaults for new session
        return {
            'cfe_quantity': '',
            'lli': False,
            'approval_1': False,
            'approval_2': False,
            'po_created': False,
            'mo_internal_ref': False,
        }

    @api.model
    def set_context_data(self, root_bom_id, bom_line_id, product_id, field_name, value):
        """Set context data for active session"""
        # Get or create session ID
        session_id = self.get_or_create_session_id(root_bom_id)

        # Look for active session context
        context = self.search([
            ('root_bom_id', '=', root_bom_id),
            ('bom_line_id', '=', bom_line_id),
            ('is_active_session', '=', True),
            ('related_mo_id', '=', False)
        ], limit=1)

        if not context:
            context = self.create({
                'root_bom_id': root_bom_id,
                'bom_line_id': bom_line_id,
                'product_id': product_id,
                'session_id': session_id,
                'is_active_session': True,
                field_name: value
            })
        else:
            if field_name == "mo_internal_ref" and value:
                value = int(value)
                value = self.env['res.partner'].browse(value).id
            context.write({field_name: value})


        return context