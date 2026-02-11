# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import api, fields, models,_
from datetime import date


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    number_line_in_report = fields.Integer(
        string='Number Line in Report',
        compute='_compute_number_line_in_report',
        store=True
    )

    vendor_status_line = fields.Selection([
        ('confirmed', 'Confirmed'),
        ('delayed', 'Delayed'),
        ('pending', 'PENDING RESPONSE'),
    ], string='Vendor Status')

    vendor_status_manual = fields.Boolean(
        string="Manual Vendor Status",
        default=False
    )

    following_status = fields.Selection([
        ('no_followup', 'No Follow-Up Yet'),
        ('followup_done', 'Follow-Up Done'),
        ('escalation', 'Escalation Needed'),
    ], string='Following Status', default='no_followup')

    days_late = fields.Integer(
        string='Days Late',
        compute='_compute_days_late',
        store=True
    )

    following_note = fields.Text(string='Following Note')

    project_id = fields.Many2one(
        'project.project',
        string='Project',
    )

    split_order = fields.Boolean(string="Split RFQ?")
    buyer_po = fields.Many2one('res.users','Buyer PO',compute='_compute_buyer_po',
        store=True)

    date_approve = fields.Datetime(string='Confirmation Date',related='order_id.date_approve')

    @api.depends('order_id.user_id')
    def _compute_buyer_po(self):
        for line in self:
            order = line.order_id
            if order:
                line.buyer_po = order.user_id
            else:
                line.buyer_po = False


    @api.depends('order_id.order_line', 'product_id', 'order_id.order_line.product_id')
    def _compute_number_line_in_report(self):
        for line in self:
            order = line.order_id
            if not order:
                line.number_line_in_report = 0
                continue
            sequence_map = {}
            current_seq = 1
            for l in order.order_line:
                product = l.product_id.id
                if product not in sequence_map:
                    sequence_map[product] = current_seq
                    current_seq += 1
            line.number_line_in_report = sequence_map.get(line.product_id.id, 0)


    def _find_candidate(self, product_id, product_qty, product_uom, location_id, name, origin, company_id, values):
        """Override to prevent merging lines - always create new line for replenishment"""
        # Always return False to force creation of new line instead of merging
        return False

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to ensure Free Location is set for replenishment lines"""
        for vals in vals_list:
            # Check if this is from replenishment (has move_dest_ids or specific origin)
            if 'move_dest_ids' in vals or vals.get('origin_returned_move_id'):
                # Find free location if not already set
                if not vals.get('location_dest_id'):
                    order = self.env['purchase.order'].browse(vals.get('order_id'))
                    company_id = order.company_id.id if order else self.env.company.id

                    free_location = self.env['stock.location'].search([
                        ('location_category', '=', 'free'),
                        ('company_id', 'in', [False, company_id])
                    ], limit=1)

                    if free_location:
                        vals['location_final_id'] = free_location.id

        lines = super(PurchaseOrderLine, self).create(vals_list)
        for line in lines:
            line._auto_update_vendor_status()
        return lines


    def _auto_update_vendor_status(self):
        self.ensure_one()
        if self.vendor_status_manual:
            return
        today = date.today()
        new_status = None
        if not self.date_planned:
            new_status = 'pending'
        else:
            planned_date = self.date_planned.date()

            if self.qty_received > 0:
                receipt_date = None
                for move in self.move_ids.filtered(lambda m: m.state == 'done' and m.quantity > 0):
                    move_date = move.date.date() if move.date else today
                    if not receipt_date or move_date > receipt_date:
                        receipt_date = move_date
                if not receipt_date:
                    receipt_date = today
                if receipt_date > planned_date:
                    new_status = 'delayed'
                else:
                    new_status = 'confirmed'
            else:
                if planned_date < today:
                    new_status = 'delayed'
                else:
                    new_status = 'pending'
        if new_status and self.vendor_status_line != new_status:
            self.vendor_status_line = new_status

    @api.onchange('date_planned')
    def _onchange_date_planned(self):
        if self.date_planned and not self.vendor_status_manual:
            self._auto_update_vendor_status()

    @api.onchange('qty_received')
    def _onchange_qty_received(self):
        if self.qty_received > 0:
            self.vendor_status_manual = False
            self._auto_update_vendor_status()

    @api.onchange('vendor_status_line')
    def _onchange_vendor_status_line(self):
        if self.env.context.get('skip_manual_flag'):
            return
        if self._origin.id:
            origin_status = self._origin.vendor_status_line
            current_status = self.vendor_status_line
            if origin_status != current_status and not self.env.context.get('from_auto_update'):
                self.vendor_status_manual = True

    def action_refresh_vendor_status(self):
        for line in self:
            # Reset manual flag
            if line.vendor_status_manual:
                super(PurchaseOrderLine, line).write({'vendor_status_manual': False})
            line._auto_update_vendor_status()
        return True

    def write(self, vals):
        result = super(PurchaseOrderLine, self).write(vals)
        if 'date_planned' in vals or 'qty_received' in vals:
            for line in self:
                if line.qty_received > 0 and line.vendor_status_manual:
                    super(PurchaseOrderLine, line).write({'vendor_status_manual': False})
                line._auto_update_vendor_status()
        return result

    @api.depends('qty_received', 'date_planned')
    def _compute_days_late(self):
        today = date.today()
        for line in self:
            line.days_late = 0
            if line.date_planned:
                planned_date = line.date_planned.date()
                if planned_date < today:
                    diff = (today - planned_date).days
                    line.days_late = -diff
                if line.qty_received > 0 and line.days_late == 0:
                    line.vendor_status_line = 'confirmed'

