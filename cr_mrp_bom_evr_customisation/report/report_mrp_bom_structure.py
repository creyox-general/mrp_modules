# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api
import base64

class ReportBomStructureBranch(models.AbstractModel):
    _inherit = 'report.mrp.report_bom_structure'

    def _get_bom_data(self, bom, warehouse, product=False, line_qty=False, bom_line=False, level=0, parent_bom=False,
                      parent_product=False, index=0, product_info=False, ignore_stock=False,
                      simulated_leaves_per_workcenter=False):
        # Context-aware branch assignment MUST be calculated before super() 
        # so that self.with_context() can be passed down to recursive child iterations inside super()
        root_bom_id = self.env.context.get("root_bom_id") or (bom.id if bom else False)
        parent_branch_id = self.env.context.get("parent_branch_id")
        
        branch_name = ""
        branch_id = False
        approve_to_manufacture = False
        free_to_use = 0.0

        if bom_line and root_bom_id:
            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            assignment = bom_line.get_assignment(root_bom, parent_branch_id)
            branch = assignment.own_branch_id if assignment else False
            if branch:
                branch_name = branch.branch_name
                branch_id = branch.id
                approve_to_manufacture = branch.approve_to_manufacture
                free_to_use = branch.free_to_use
                # Propagate this branch as the new parent for any child lines processed by super()
                self = self.with_context(parent_branch_id=branch_id)

        # MO handling for Branch
        mo_data = []
        if branch_id and root_bom_id:
            related_mos = self.env['mrp.production'].search([
                ('branch_mapping_id', '=', branch_id),
                ('root_bom_id', '=', root_bom_id),
                ('state', '!=', 'cancel')
            ])
            for mo in related_mos:
                mo_data.append({
                    'id': mo.id,
                    'name': mo.name,
                    'state': mo.state
                })

        # Propagate the root BOM down 
        if root_bom_id:
            self = self.with_context(root_bom_id=root_bom_id)

        data = super()._get_bom_data(
            bom, warehouse, product, line_qty, bom_line, level,
            parent_bom, parent_product, index, product_info, ignore_stock, simulated_leaves_per_workcenter
        )

        data.update({
            "branch": branch_name,
            "branch_id": branch_id,
            "approve_to_manufacture": approve_to_manufacture,
            "approve_to_manufacture_editable": bool(branch_id),
            "free_to_use": free_to_use,
            "display_free_to_use": True,
            "customer_ref_editable": True,
            "bom_line_id": bom_line.id if bom_line else False,
            "is_evr": bool(root_bom_id and self.env['mrp.bom'].browse(root_bom_id).is_evr),
            "root_bom_id": root_bom_id,
            "root_is_evr": bool(root_bom_id and self.env['mrp.bom'].browse(root_bom_id).is_evr),
            "mo_data": mo_data,
        })

        product_obj = data.get('product')
        if product_obj:
            data['default_code'] = product_obj.default_code or ''
            data['old_everest_pn'] = product_obj.old_everest_pn or ''

        return data

    def _get_component_data(self, parent_bom, parent_product, warehouse, bom_line,
                            line_quantity, level, index, product_info, ignore_stock=False):

        root_bom_id = self.env.context.get("root_bom_id")
        parent_branch_id = self.env.context.get("parent_branch_id")
        
        assignment = False
        if bom_line and root_bom_id:
            root_bom = self.env['mrp.bom'].browse(root_bom_id)
            assignment = bom_line.get_assignment(root_bom, parent_branch_id)

        # Remove useless context swap from here since _get_component_data doesn't initiate tree recursion
        if assignment and assignment.own_branch_id:
            pass

        data = super()._get_component_data(
            parent_bom, parent_product, warehouse, bom_line,
            line_quantity, level, index, product_info, ignore_stock
        )

        data.update({
            'purchase_group_editable': False,
            'is_evr': bool(root_bom_id and self.env['mrp.bom'].browse(root_bom_id).is_evr),
            'root_bom_id': root_bom_id,
        })

        if assignment:
            branch_rec = assignment.own_branch_id or (assignment.component_id.bom_line_branch_id if assignment.component_id else False)
            data['branch'] = branch_rec.branch_name if branch_rec else ""
            
            if assignment.component_id:
                comp = assignment.component_id
                data.update({
                    'componentId': comp.id,
                    'cfe_quantity': comp.cfe_quantity,
                    'has_cfe_quantity': bool(comp.cfe_quantity),
                    'approval_1': comp.approval_1,
                    'approval_2': comp.approval_2,
                    'cfe_editable': True,
                    'approval_1_editable': True,
                    'approval_2_editable': True,
                    'has_main_vendor': bool(bom_line.product_id.product_main_vendor_id),
                    'mo_internal_ref_editable': True,
                    'free_to_use': comp.free_to_use,
                    'display_free_to_use': True,
                })
                
                # Manufacturer handling
                available_manufacturers = []
                main_vendor_lines = bom_line.product_id.product_tmpl_id.seller_ids.filtered(lambda s: s.main_vendor)
                for vendor in main_vendor_lines:
                    for manufacturer in vendor.manufacturer_ids:
                        available_manufacturers.append({
                            'id': manufacturer.id,
                            'ref': manufacturer.manufacture_internal_ref,
                            'name': manufacturer.manufacture_internal_ref,
                        })
                data['available_manufacturers'] = available_manufacturers
                data['product_manufacturer_id'] = comp.product_manufacturer_id.id if comp.product_manufacturer_id else False
                data['product_manufacturer_editable'] = not bool(bom_line.child_bom_id)

                # PO handling (merged logic)
                po_data = []
                for po_line in (comp.customer_po_ids | comp.vendor_po_ids):
                    if po_line.order_id.state != 'cancel':
                        po_data.append({
                            'id': po_line.order_id.id,
                            'name': po_line.order_id.name,
                            'state': po_line.order_id.state
                        })
                
                # Uniquify POs
                unique_po_data = []
                seen_ids = set()
                for po in po_data:
                    if po['id'] not in seen_ids:
                        seen_ids.add(po['id'])
                        unique_po_data.append(po)
                
                data['po_data'] = unique_po_data
                data['po_line_name'] = ", ".join([f"({po['name']})" if po['state'] in ['draft', 'sent', 'to approve'] else po['name'] for po in unique_po_data]) if unique_po_data else ""
                
                # MO handling (EVR only)
                # mo_data = []
                # print('branch_rec : ',branch_rec,'  root_bom_id : ',root_bom_id,' bom_line.product_id : ',bom_line.product_id.name)
                # if branch_rec and root_bom_id:
                #     related_mos = self.env['mrp.production'].search([
                #         ('branch_mapping_id', '=', branch_rec.id),
                #         ('root_bom_id', '=', root_bom_id),
                #         ('state', '!=', 'cancel')
                #     ])
                #     for mo in related_mos:
                #         mo_data.append({
                #             'id': mo.id,
                #             'name': mo.name,
                #             'state': mo.state
                #         })
                # data['mo_data'] = mo_data
                # print('mo_data : ',mo_data)
                
                data['purchase_group_editable'] = comp.approval_1 and comp.approval_2
                if comp.approval_1 and comp.approval_2:
                    data.update({
                        'to_order': comp.to_order, 'to_order_cfe': comp.to_order_cfe,
                        'ordered': comp.ordered, 'ordered_cfe': comp.ordered_cfe,
                        'to_transfer': comp.to_transfer, 'to_transfer_cfe': comp.to_transfer_cfe,
                        'transferred': comp.transferred, 'transferred_cfe': comp.transferred_cfe,
                        'used': comp.used,
                    })

            user = self.env.user
            data['can_edit_approval_2'] = user.has_group('mrp.group_mrp_manager') or user.has_group('purchase.group_purchase_manager')
        
        if bom_line and bom_line.product_id:
            data.update({
                'product_id': bom_line.product_id.id,
                'product_name': bom_line.product_id.display_name,
                'default_code': bom_line.product_id.default_code or '',
                'old_everest_pn': bom_line.product_id.old_everest_pn or '',
                'customer_ref': bom_line.customer_ref or '',
                'customer_ref_editable': not bool(bom_line.child_bom_id),
            })
            
            if bom_line.product_id.image_128:
                try:
                    img = bom_line.product_id.image_128
                    data['product_image'] = base64.b64encode(img).decode('utf-8') if isinstance(img, bytes) else str(img)
                except Exception:
                    data['product_image'] = False

        return data


    def _get_report_data(self, bom_id, searchQty=0, searchVariant=False):
        # Clear the per-BOM branch assignment cache before every render.
        # This prevents stale component IDs (deleted during buy/make transitions)
        # from surviving in-process and causing "Record does not exist" errors.
        if hasattr(self.__class__, '_branch_assignment_cache'):
            self.__class__._branch_assignment_cache.pop(f"bom_{bom_id}", None)

        # Set root BOM and initial parent branch context for the entire report
        self = self.with_context(root_bom_id=bom_id, parent_branch_id=False)
        result = super()._get_report_data(bom_id, searchQty, searchVariant)
        bom = self.env['mrp.bom'].browse(bom_id)
        result['is_evr'] = bom.is_evr
        return result


