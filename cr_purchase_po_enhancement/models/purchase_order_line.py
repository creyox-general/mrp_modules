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
    
    po_type = fields.Selection([
        ('mrp', 'MRP'),
        ('urgt', 'URGT'),
        ('min', 'MIN'),
        ('mixed', 'Mixed'),
    ], string='PO Type', store=True)
    
    extra_qty = fields.Float(string='Extra Qty')
    manufacture_internal_ref = fields.Char(
        related='manufacturer_id.manufacture_internal_ref',
        string='INTERNAL REF of selected MFG',
        store=True
    )

    display_date_po = fields.Date(string='Display Date', related='order_id.display_date_po', store=True)
    categ_id = fields.Many2one('product.category', related='product_id.categ_id', store=True, string='Product Category')
    product_document_count = fields.Integer(compute='_compute_product_document_count', string='Document Count')
    
    product_description_variant = fields.Char(
        string='Description(product name)',
        compute='_compute_product_description_variant',
        store=True
    )

    @api.depends('product_id.default_code', 'product_id.name')
    def _compute_product_description_variant(self):
        """
        Compute formatted description: '[default_code] product_name'
        """
        for line in self:
            product = line.product_id
            code = product.default_code
            name = product.name or ''
            if code:
                line.product_description_variant = '%s [%s]' % (code, name)
            else:
                line.product_description_variant = name

    def action_open_product(self):
        """
        Action to open the product form view.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _compute_product_document_count(self):
        for line in self:
            line.product_document_count = len(line.product_id.product_document_ids) if line.product_id else 0

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
        """Override create to ensure Free Location is set for replenishment lines and po_type is inherited"""
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

            # Set po_type from order if not explicitly set
            if not vals.get('po_type') and vals.get('order_id'):
                order = self.env['purchase.order'].browse(vals.get('order_id'))
                if order.exists():
                    vals['po_type'] = order.po_type

        lines = super(PurchaseOrderLine, self).create(vals_list)
        for line, vals in zip(lines, vals_list):
            if 'branch_id' in vals or line.branch_id:
                print(f">>> DEBUG PO LINE CREATE: ID={line.id} Product={line.product_id.name} Branch={line.branch_id.display_name if line.branch_id else 'None'} PO Type={line.po_type}")
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

    def action_merge_lines(self):
        """
        Merge selected PO lines into a new Purchase Order.
        - Create exactly ONE new PO using the vendor and currency of the first selected line.
        - Move ALL selected lines to this single PO.
        - If any line is MRP, set WH/Project Location and disable summing.
        - Cancel source POs if they become empty.
        """
        if not self:
            return False

        if any(line.state not in ['draft', 'sent'] for line in self):
            raise models.ValidationError(_("Only lines in RFQ or Sent state can be merged."))

        lines = self
        source_pos = lines.mapped('order_id')
        
        # Determine if MRP is involved (using MTO Bom name pattern as a proxy if field exists, plus po_type)
        is_mrp_involved = any(line.po_type == 'mrp' or line.order_id.po_type == 'mrp' for line in lines)
        # Check if EVR components are present
        if not is_mrp_involved:
             is_mrp_involved = any(hasattr(line, 'name_mto_bom') and line.name_mto_bom and 'EVR' in line.name_mto_bom for line in lines)

        base_line = lines[0]
        base_order = base_line.order_id

        po_vals = {
            'partner_id': base_line.partner_id.id,
            'currency_id': base_line.currency_id.id,
            'company_id': base_order.company_id.id,
            'picking_type_id': base_order.picking_type_id.id,
            'origin': ', '.join(filter(None, set(source_pos.mapped('origin')))),
            'is_merged': True,
            'mrp_involved': is_mrp_involved,
        }

        # Set PO Type for the new header
        types = set(lines.mapped('po_type')) - {False}
        if len(types) == 1:
            po_vals['po_type'] = list(types)[0]
        elif len(types) > 1:
            po_vals['po_type'] = 'mixed'

        if is_mrp_involved:
            project_loc = self.env['stock.location'].search([
                ('complete_name', '=', 'WH/Project Location')
            ], limit=1)
            if project_loc:
                po_vals['cfe_project_location_id'] = project_loc.id

        new_po = self.env['purchase.order'].create(po_vals)

        for line in lines:
            merge_allowed = not is_mrp_involved
            source_po_type = line.po_type or line.order_id.po_type
            
            existing_line = False
            if merge_allowed:
                existing_line = new_po.order_line.filtered(
                    lambda l: l.display_type not in ['line_note', 'line_section'] and
                    l.product_id == line.product_id and
                    l.product_uom == line.product_uom and
                    l.price_unit == line.price_unit and
                    l.component_branch_id == line.component_branch_id and
                    l.po_type == source_po_type
                )
            
            if existing_line:
                existing_line.product_qty += line.product_qty
                line.unlink()
            else:
                line.po_type = source_po_type
                line.order_id = new_po.id

        # Post messages and handle source POs
        for po in source_pos:
            if not po.exists():
                continue
            if not po.order_line:
                po.button_cancel()
            else:
                po.message_post(body=_("Some lines moved to merged RFQ %s", new_po._get_html_link()))
        
        new_po.message_post(body=_("RFQ created by merging lines from %s", ", ".join(source_pos.mapped('name'))))

        return {
            'name': _('Merged Purchase Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': new_po.id,
            'view_mode': 'form',
            'target': 'current',
        }

