# -*- coding: utf-8 -*-
from odoo import models, fields, _
from collections import defaultdict

from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_merge(self):
        """
        Custom merge logic:
        - For POs with po_type == 'mrp', prevent line merging (summing) even for same products.
        - Set cfe_project_location_id to base 'Project Location'.
        """
        # Identify MRP POs in the selection
        mrp_pos = self.filtered(lambda p: p.po_type == 'mrp')
        
        # If no MRP POs, use standard logic (or we can just wrap the whole thing)
        # Actually, the user wants this customisation for the MRP flow.
        # I will override the whole method to ensure control over the merging loop.

        all_origin = []
        all_vendor_references = []
        rfq_to_merge = self.filtered(lambda r: r.state in ['draft', 'sent'])

        if len(rfq_to_merge) < 2:
            raise UserError(_("Please select at least two purchase orders with state RFQ and RFQ sent to merge."))

        rfqs_grouped = defaultdict(lambda: self.env['purchase.order'])
        for rfq in rfq_to_merge:
            key = self._prepare_grouped_data(rfq)
            rfqs_grouped[key] += rfq

        bunches_of_rfq_to_be_merge = list(rfqs_grouped.values())
        if all(len(rfq_bunch) == 1 for rfq_bunch in list(bunches_of_rfq_to_be_merge)):
            raise UserError(_("In selected purchase order to merge these details must be same\nVendor, currency, destination, dropship address and agreement"))
        bunches_of_rfq_to_be_merge = [rfqs for rfqs in bunches_of_rfq_to_be_merge if len(rfqs) > 1]

        for rfqs in bunches_of_rfq_to_be_merge:
            if len(rfqs) <= 1:
                continue
            
            oldest_rfq = min(rfqs, key=lambda r: r.date_order)
            is_mrp_merge = any(r.po_type == 'mrp' for r in rfqs)

            if oldest_rfq:
                # Merge RFQs into the oldest purchase order
                rfqs -= oldest_rfq
                
                # Assign PO Type for Merge
                # Get types of all orders involved (including the oldest one)
                all_types = set(rfqs.mapped('po_type')) | set(oldest_rfq.mapped('po_type'))
                # Filter out False if any
                all_types = [t for t in all_types if t]
                
                if len(all_types) > 1:
                    oldest_rfq.po_type = 'mixed'
                # Else stays as it was (if all same or only one type exists)
                
                oldest_rfq.is_merged = True
                oldest_rfq.mrp_involved = is_mrp_merge

                # Custom Location Logic for MRP
                if is_mrp_merge:
                    # Set to base 'Project Location'
                    # We look for a location named 'Project Location' or similar parent of existing locations
                    # User said: "location in po cfe_lproject_location_id should be WH/Project Location"
                    project_loc = self.env['stock.location'].search([
                        ('complete_name', '=', 'WH/Project Location')
                    ], limit=1)
                    if project_loc:
                        oldest_rfq.cfe_project_location_id = project_loc.id

                for rfq_line in rfqs.order_line:
                    merge_allowed = True
                    if is_mrp_merge or oldest_rfq.po_type == 'mrp':
                        # User: "in both po product is same then also when merge po then line should not merge"
                        merge_allowed = False

                    existing_line = False
                    if merge_allowed:
                        existing_line = oldest_rfq.order_line.filtered(lambda l: l.display_type not in ['line_note', 'line_section'] and
                                                                                    l.product_id == rfq_line.product_id and
                                                                                    l.product_uom == rfq_line.product_uom and
                                                                                    l.product_packaging_id == rfq_line.product_packaging_id and
                                                                                    l.product_packaging_qty == rfq_line.product_packaging_qty and
                                                                                    l.distribution_analytic_account_ids == rfq_line.distribution_analytic_account_ids and
                                                                                    l.discount == rfq_line.discount and
                                                                                    abs(l.date_planned - rfq_line.date_planned).total_seconds() <= 86400
                                                                            )
                    
                    if existing_line:
                        if len(existing_line) > 1:
                            existing_line[0].product_qty += sum(existing_line[1:].mapped('product_qty'))
                            existing_line[1:].unlink()
                            existing_line = existing_line[0]
                        existing_line._merge_po_line(rfq_line)
                    else:
                        # Move the line to the oldest RFQ
                        # Set line po_type to its current header's type before moving
                        rfq_line.po_type = rfq_line.order_id.po_type
                        rfq_line.order_id = oldest_rfq
                        # Branch IDs are preserved because the line object is kept

                # Merge source documents and vendor references
                all_origin = rfqs.mapped('origin')
                all_vendor_references = rfqs.mapped('partner_ref')

                oldest_rfq.origin = ', '.join(filter(None, [oldest_rfq.origin, *all_origin]))
                oldest_rfq.partner_ref = ', '.join(filter(None, [oldest_rfq.partner_ref, *all_vendor_references]))

                rfq_names = rfqs.mapped('name')
                merged_names = ", ".join(rfq_names)
                oldest_rfq_message = _("RFQ merged with %(oldest_rfq_name)s and %(cancelled_rfq)s", oldest_rfq_name=oldest_rfq.name, cancelled_rfq=merged_names)

                for rfq in rfqs:
                    cancelled_rfq_message = _("RFQ merged with %s", oldest_rfq._get_html_link())
                    rfq.message_post(body=cancelled_rfq_message)
                oldest_rfq.message_post(body=oldest_rfq_message)

                rfqs.filtered(lambda r: r.state != 'cancel').button_cancel()
                # Use sudo if necessary or ensure permissions
                oldest_rfq._merge_alternative_po(rfqs)

    def _prepare_grouped_data(self, rfq):
        """
        Simplify grouping: only split by vendor and currency.
        Ignore dest_address_id to prevent redundant PO creation.
        """
        return (rfq.partner_id.id, rfq.currency_id.id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('purchase orders merged'),
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
