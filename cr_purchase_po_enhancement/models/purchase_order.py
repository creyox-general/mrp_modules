# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import date, timedelta
from odoo.osv import expression

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    display_date_po = fields.Date(string="Display Date", compute='_compute_display_date', inverse='_inverse_display_date',
                               store=True)
    po_type = fields.Selection([
        ('mrp', 'MRP'),
        ('urgt', 'URGT'),
        ('min', 'MIN'),
    ], string='PO Type')

    vendor_status = fields.Selection([
        ('confirmed', 'Confirmed'),
        ('delayed', 'Delayed'),
        ('pending', 'PENDING RESPONSE'),
    ], string='Vendor Status', compute='_compute_vendor_status', store=True)

    partner_tag_ids = fields.Many2many(
        'res.partner.category',
        string='Tags',
        compute='_compute_partner_tags',
        domain=[('website_vendor','=',True)],
        store=True,
        readonly=False
    )


    @api.depends('partner_id', 'partner_id.category_id')
    def _compute_partner_tags(self):
        for po in self:
            if po.partner_id and po.partner_id.category_id:
                website_tags = po.partner_id.category_id.filtered(lambda t: t.website_vendor)
                po.partner_tag_ids = [(6, 0, website_tags.ids)]
            else:
                po.partner_tag_ids = False

    @api.model
    def create(self, vals):
        if vals.get('po_type') == 'urgt':
            vals['date_order'] = fields.Datetime.now()
        return super().create(vals)

    def write(self, vals):
        if vals.get('po_type') == 'urgt':
            for po in self:
                if not vals.get('date_order'):
                    vals['date_order'] = fields.Datetime.now()

        # Restrict URGT change to Purchase Manager
        if 'po_type' in vals:
            for po in self:
                if not self.env.user.has_group('purchase.group_purchase_manager'):
                    vals.pop('po_type')
                    raise UserError("Only Purchase Manager can change PO Type.")

        return super().write(vals)

    @api.constrains('po_type')
    def _check_po_type_change(self):
        for record in self:
            if record._origin.po_type == 'urgt' and record.po_type != 'urgt':
                if not self.env.user.has_group('purchase.group_purchase_manager'):
                    raise UserError("Only Purchase Manager can change PO Type from URGT.")

    @api.depends('po_type')
    def _compute_display_date(self):
        Param = self.env['ir.config_parameter'].sudo()
        weekday_str = Param.get_param('cr_purchase_po_enhancement.display_date_days', default='0')
        target_weekday = int(weekday_str)

        for order in self:
            today = fields.Date.context_today(order)
            if order.po_type in ['mrp', 'min']:
                today_wd = today.weekday()
                days_ahead = target_weekday - today_wd
                if days_ahead <= 0:
                    days_ahead += 7
                order.display_date_po = today + timedelta(days=days_ahead)

            elif order.po_type == 'urgt':
                order.display_date_po = today

    def _inverse_display_date(self):
        for order in self:
            if not self.env.user.has_group('purchase.group_purchase_manager'):
                raise AccessError(_("Only administrators can modify Display Date."))

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields, attributes)
        user = self.env.user
        if not user.has_group('purchase.group_purchase_manager'):
            if 'display_date_po' in res:
                res['display_date_po']['readonly'] = True
        return res

    def create_purchase_order(self):
        for order in self:
            li = []
            for line in order.order_line:
                if line.split_order == True:
                    li.append((0, 0, {'product_id': line.product_id.id,
                                      'name': line.name,
                                      'product_qty': line.product_qty,
                                      'product_uom': line.product_uom.id,

                                      'price_unit': line.price_unit,
                                      'discount': line.discount,
                                      'taxes_id': [(6, 0, line.taxes_id.ids)], }))
                    line.unlink()

            custom_record = {
                'display_date_po': order.display_date_po,
                'partner_id': order.partner_id.id,
                'partner_ref': order.partner_ref,
                'po_type': order.po_type,

                'order_line': li
            }
            self.env['purchase.order'].create(custom_record)

    def _search(self, domain, offset=0, limit=None, order=None):
        user = self.env.user
        today = date.today()
        if not user.has_group("purchase.group_purchase_manager"):
            visibility_domain = [
                '|', '|',
                ('po_type', '=', False),
                ('display_date_po', '=', False),
                ('display_date_po', '<=', today),
            ]
            domain = expression.AND([domain, visibility_domain])


        if self.env.user.has_group('purchase.group_purchase_user') and \
                not self.env.user.has_group('purchase.group_purchase_manager'):

            domain = domain or []
            domain = ['&'] + domain + [('user_id', '=', self.env.user.id)]

        return super()._search(domain, offset=offset, limit=limit, order=order)

    def get_grouped_lines_for_report(self):
        result = []
        seen_products = set()
        for line in self.order_line:
            if line.display_type:
                result.append({
                    'line': line,
                    'is_grouped': False,
                    'total_qty': 0,
                    'total_subtotal': 0.0,
                })
                continue
            if line.product_id.id in seen_products:
                continue
            seen_products.add(line.product_id.id)
            grouped_lines = self.order_line.filtered(
                lambda l: l.product_id == line.product_id and not l.display_type
            )
            total_qty = sum(grouped_lines.mapped('product_qty'))
            total_subtotal = sum(grouped_lines.mapped('price_subtotal'))
            result.append({
                'line': line,
                'is_grouped': True,
                'total_qty': total_qty,
                'total_subtotal': total_subtotal,
            })
        return result

    @api.depends('order_line.vendor_status_line')
    def _compute_vendor_status(self):
        for order in self:
            statuses = order.order_line.mapped('vendor_status_line')
            if 'delayed' in statuses:
                order.vendor_status = 'delayed'
            elif 'pending' in statuses:
                order.vendor_status = 'pending'
            elif statuses:
                order.vendor_status = 'confirmed'
            else:
                order.vendor_status = False