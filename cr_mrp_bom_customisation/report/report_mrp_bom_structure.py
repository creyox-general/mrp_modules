# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models
import base64


class ReportBomStructure(models.AbstractModel):
    _inherit = 'report.mrp.report_bom_structure'

    def _get_bom_data(self, bom, warehouse, product=False, line_qty=False, bom_line=False, level=0, parent_bom=False,
                      parent_product=False, index=0, product_info=False, ignore_stock=False,
                      simulated_leaves_per_workcenter=False):

        data = super()._get_bom_data(
            bom, warehouse, product, line_qty, bom_line, level,
            parent_bom, parent_product, index, product_info, ignore_stock, simulated_leaves_per_workcenter
        )

        # Get root BOM from context or current BOM
        root_bom_id = self.env.context.get("root_bom_id")
        if not root_bom_id:
            root_bom_id = bom.id if bom else (parent_bom.id if parent_bom else False)

        root_bom = self.env['mrp.bom'].browse(root_bom_id) if root_bom_id else False

        data['is_evr'] = bool(root_bom and root_bom.is_evr)
        data['bom_id'] = bom.id if bom else False
        data['root_bom_id'] = root_bom_id
        data['root_is_evr'] = data['is_evr']
        product = data['product']
        data['default_code'] = product.default_code or ''
        data['old_everest_pn'] = product.old_everest_pn or ''
        return data

    def _get_component_data(self, parent_bom, parent_product, warehouse, bom_line,
                            line_quantity, level, index, product_info, ignore_stock=False):

        data = super()._get_component_data(
            parent_bom, parent_product, warehouse, bom_line,
            line_quantity, level, index, product_info, ignore_stock
        )

        root_bom_id = self.env.context.get("root_bom_id")
        root_bom = self.env['mrp.bom'].browse(root_bom_id) if root_bom_id else False

        # Debug image handling in _get_component_data method
        if bom_line and bom_line.product_id:
            data['product_id'] = bom_line.product_id.id
            data['product_name'] = bom_line.product_id.display_name
            data['default_code'] = bom_line.product_id.default_code or ''
            data['old_everest_pn'] = bom_line.product_id.old_everest_pn or ''

            # Debug image field
            image_field = bom_line.product_id.image_128

            if image_field:
                try:
                    # Method 1: Direct assignment (if it's already base64 string)
                    if isinstance(image_field, str):
                        data['product_image'] = image_field
                    # Method 2: Binary to base64 conversion
                    elif isinstance(image_field, bytes):
                        data['product_image'] = base64.b64encode(image_field).decode('utf-8')
                    else:
                        # Method 3: For other field types
                        data['product_image'] = str(image_field)
                except Exception as e:
                    data['product_image'] = False
            else:
                data['product_image'] = False

        if bom_line and root_bom_id:
            data['cfe_quantity'] = bom_line.cfe_quantity
            data['has_cfe_quantity'] = bool(bom_line.cfe_quantity)
            data['bom_line_id'] = bom_line.id
            data['lli'] = bom_line.lli
            data['approval_1'] = bom_line.approval_1
            data['approval_2'] = bom_line.approval_2

            child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')
            data['cfe_editable'] = not bool(child_bom)
            data['lli_editable'] = not bool(child_bom)
            data['approval_1_editable'] = not bool(child_bom)
            data['approval_2_editable'] = not bool(child_bom)
            data['mo_internal_ref_editable'] = not bool(child_bom)

            # Check user permissions for Approval 2
            user = self.env.user
            can_edit_approval_2 = user.has_group('mrp.group_mrp_manager') or user.has_group(
                'purchase.group_purchase_manager')
            data['can_edit_approval_2'] = can_edit_approval_2


            # Available manufacturers from main vendor
            main_vendor_line = bom_line.product_id.product_tmpl_id.seller_ids.filtered(lambda s: s.main_vendor)

            available_manufacturers = []
            for vendor in main_vendor_line:
                for manufacturer in vendor.manufacturer_ids:
                    available_manufacturers.append({
                        'id': manufacturer.id,
                        'ref': manufacturer.manufacture_internal_ref,  # or name if you want
                        'name': manufacturer.manufacture_internal_ref,
                    })

            data['available_manufacturers'] = available_manufacturers

            # Selected manufacturer
            if bom_line.product_manufacturer_id:
                data['product_manufacturer_id'] = bom_line.product_manufacturer_id.id
            else:
                data['product_manufacturer_id'] = False

            # Editable flag
            child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')
            data['product_manufacturer_editable'] = not bool(child_bom)

        else:
            # Defaults
            data.update({
                'cfe_quantity': '',
                'has_cfe_quantity': False,
                'cfe_editable': False,
                'bom_line_id': False,
                'lli': False,
                'approval_1': False,
                'approval_2': False,
                'lli_editable': False,
                'approval_1_editable': False,
                'approval_2_editable': False,
                'available_vendors': [],
                'mo_internal_ref': False,
                'can_edit_approval_2': False,
            })

        data['is_evr'] = bool(root_bom and root_bom.is_evr)
        data['root_bom_id'] = root_bom_id

        return data


    def _get_report_data(self, bom_id, searchQty=0, searchVariant=False):
        # Set root BOM context for the entire report
        self = self.with_context(root_bom_id=bom_id)
        result = super()._get_report_data(bom_id, searchQty, searchVariant)
        bom = self.env['mrp.bom'].browse(bom_id)
        result['is_evr'] = bom.is_evr
        return result
