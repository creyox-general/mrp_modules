# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api
import base64

class ReportBomStructureBranch(models.AbstractModel):
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

        if root_bom_id and bom_line:
            Branch = self.env["mrp.bom.line.branch"]

            # Get all branches for this bom_id and bom_line_id combination, ordered by sequence
            branches = Branch.search([
                ("bom_id", "=", root_bom_id),
                ("bom_line_id", "=", bom_line.id),
            ], order='sequence')

            branch = False
            if branches:
                if len(branches) == 1:
                    # Only one branch for this bom_line, use it
                    branch = branches[0]
                else:
                    # Multiple branches exist for this bom_line_id
                    index_str = str(index)
                    path_key = f"{root_bom_id}_{bom_line.id}_{index_str}"

                    # Use a class variable or cache to persist across all calls
                    if not hasattr(self.__class__, '_branch_assignment_cache'):
                        self.__class__._branch_assignment_cache = {}

                    cache = self.__class__._branch_assignment_cache
                    cache_key = f"bom_{root_bom_id}"
                    if cache_key not in cache:
                        cache[cache_key] = {
                            'assignments': {},
                            'seen_paths': []
                        }

                    bom_cache = cache[cache_key]

                    if path_key not in bom_cache['seen_paths']:
                        existing_count = len([p for p in bom_cache['seen_paths']
                                              if p.startswith(f"{root_bom_id}_{bom_line.id}_")])

                        if existing_count < len(branches):
                            branch = branches[existing_count]
                        else:
                            branch = branches[-1]

                        bom_cache['assignments'][path_key] = branch.id
                        bom_cache['seen_paths'].append(path_key)
                    else:
                        branch_id = bom_cache['assignments'].get(path_key)
                        branch = Branch.browse(branch_id) if branch_id else False

                    if level == 0 and not bom_line:
                        if cache_key in cache:
                            del cache[cache_key]

            data["branch"] = branch.branch_name if branch else ""

            if branch and branch.branch_name:
                data['approve_to_manufacture_editable'] = True
                data['approve_to_manufacture'] = bom_line.approve_to_manufacture
                data['display_free_to_use'] = True
                data['customer_ref_editable'] = True
                data["free_to_use"] = branch.free_to_use
            else:
                data['approve_to_manufacture_editable'] = False

            data['bom_line_id'] = bom_line.id if bom_line else False

        else:
            data["branch"] = ""
            data['bom_line_id'] = bom_line.id if bom_line else False

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

        data['purchase_group_editable'] = False

        if not bom_line:
            return data

        root_bom_id = self.env.context.get("root_bom_id")

        root_bom = self.env['mrp.bom'].browse(root_bom_id) if root_bom_id else False

        if not root_bom:
            return data


        if not root_bom.is_evr:
            return data


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

            data['customer_ref'] = bom_line.customer_ref or ''


        # -------------------------------
        # PURCHASE ORDER HANDLING (MERGED SINGLE FIELD)
        # -------------------------------
        po_ids = []
        po_names = []

        child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')

        data['customer_ref_editable'] = not bool(child_bom)

        component_rec = self._get_component_for_line(root_bom_id, bom_line, parent_bom, index)

        data['display_free_to_use'] = True
        if component_rec:
            data['cfe_quantity'] = component_rec.cfe_quantity
            data['has_cfe_quantity'] = bool(component_rec.cfe_quantity)
            data['bom_line_id'] = component_rec.id
            data['approval_1'] = component_rec.approval_1
            data['approval_2'] = component_rec.approval_2
            child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')
            data['cfe_editable'] = True
            data['approval_1_editable'] = True
            data['approval_2_editable'] = True
            data['mo_internal_ref_editable'] = True
            user = self.env.user
            can_edit_approval_2 = user.has_group('mrp.group_mrp_manager') or user.has_group(
                'purchase.group_purchase_manager')
            data['can_edit_approval_2'] = can_edit_approval_2


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
            if component_rec.product_manufacturer_id:
                data['product_manufacturer_id'] = component_rec.product_manufacturer_id.id
            else:
                data['product_manufacturer_id'] = False

            # Editable flag
            child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')
            data['product_manufacturer_editable'] = not bool(child_bom)
            data['componentId'] = component_rec.id
            data['free_to_use'] = component_rec.free_to_use


            # In _get_component_data method, replace the PO handling section:

            po_data = []  # List of {id, name} dictionaries

            # Collect customer PO lines (exclude cancelled)
            if component_rec.customer_po_ids:
                for po_line in component_rec.customer_po_ids:
                    if po_line.order_id.state != 'cancel':
                        po_data.append({
                            'id': po_line.order_id.id,
                            'name': po_line.order_id.name
                        })

            # Collect vendor PO lines (exclude cancelled)
            if component_rec.vendor_po_ids:
                for po_line in component_rec.vendor_po_ids:
                    if po_line.order_id.state != 'cancel':
                        po_data.append({
                            'id': po_line.order_id.id,
                            'name': po_line.order_id.name
                        })

            # Remove duplicates based on PO id
            seen_ids = set()
            unique_po_data = []
            for po in po_data:
                if po['id'] not in seen_ids:
                    seen_ids.add(po['id'])
                    unique_po_data.append(po)

            data['po_data'] = unique_po_data
            data['po_line_name'] = ", ".join([po['name'] for po in unique_po_data]) if unique_po_data else ""


            data['purchase_group_editable'] = component_rec.approval_1 and component_rec.approval_2
            is_approval = component_rec.approval_1 and component_rec.approval_2

            # After: if not root_bom.is_evr: return data

            # Check if product has a main vendor
            product = bom_line.product_id if bom_line else parent_product
            main_vendor = product.seller_ids.filtered(lambda s: s.main_vendor) if product else False
            # data['has_main_vendor'] = bool(main_vendor)

            if is_approval and component_rec:
                data['to_order'] = component_rec.to_order
                data['to_order_cfe'] = component_rec.to_order_cfe
                data['ordered'] = component_rec.ordered
                data['ordered_cfe'] = component_rec.ordered_cfe
                data['to_transfer'] = component_rec.to_transfer
                data['to_transfer_cfe'] = component_rec.to_transfer_cfe
                data['transferred'] = component_rec.transferred
                data['transferred_cfe'] = component_rec.transferred_cfe
                data['used'] = component_rec.used

            else:
                data['to_order'] = None
                data['to_order_cfe'] = None
                data['ordered'] = None
                data['ordered_cfe'] = None
                data['to_transfer'] = None
                data['to_transfer_cfe'] = None
                data['transferred'] = None
                data['transferred_cfe'] = None
                data['used'] = None
        else:
            data.update({
                'cfe_quantity': '',
                'has_cfe_quantity': False,
                'cfe_editable': False,
                'bom_line_id': False,
                'approval_1': False,
                'approval_2': False,
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

    def _get_component_for_line(self, root_bom_id, bom_line, parent_bom, index):
        Component = self.env["mrp.bom.line.branch.components"]

        # Check for child BOM
        child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')

        if child_bom:
            return False

        # ROOT LEVEL COMPONENT
        if not parent_bom or parent_bom.id == root_bom_id:

            components = Component.search([
                ('root_bom_id', '=', root_bom_id),
                ('bom_id', '=', parent_bom.id),
                ('cr_bom_line_id', '=', bom_line.id),
                ('is_direct_component', '=', True),
            ])

            if not components:
                return False

            if len(components) == 1:
                return components[0]

            try:
                comp = components[int(index)]
                return comp
            except (IndexError, ValueError):
                return components[0]

        # CHILD LEVEL COMPONENT
        components = Component.search([
            ('root_bom_id', '=', root_bom_id),
            ('bom_id', '=', parent_bom.id),
            ('cr_bom_line_id', '=', bom_line.id),
            ('is_direct_component', '=', False),
        ], order='id')

        if not components:
            return False

        if len(components) == 1:
            return components[0]

        # Multiple components - use cache logic
        index_str = str(index)
        path_key = f"{root_bom_id}_{bom_line.id}_{index_str}"

        if not hasattr(self.__class__, '_branch_assignment_cache'):
            self.__class__._branch_assignment_cache = {}

        cache = self.__class__._branch_assignment_cache
        cache_key = f"bom_{root_bom_id}"

        if cache_key not in cache:
            cache[cache_key] = {
                'assignments': {},
                'seen_paths': []
            }

        bom_cache = cache[cache_key]

        if path_key not in bom_cache['seen_paths']:
            # First time seeing this path
            existing_count = len([p for p in bom_cache['seen_paths']
                                  if p.startswith(f"{root_bom_id}_{bom_line.id}_")])

            if existing_count < len(components):
                component = components[existing_count]
            else:
                component = components[-1]

            bom_cache['assignments'][path_key] = component.id
            bom_cache['seen_paths'].append(path_key)
            return component
        else:
            # Path already seen, reuse assignment
            component_id = bom_cache['assignments'].get(path_key)
            return Component.browse(component_id) if component_id else components[0]

    def _get_branch_for_parent(self, root_bom_id, parent_bom_line, index):
        """
        Get the branch record for a parent BOM line.
        Uses the same cache logic as _get_bom_data to ensure consistency.
        """
        Branch = self.env["mrp.bom.line.branch"]

        # Get branches for parent BOM line
        branches = Branch.search([
            ("bom_id", "=", root_bom_id),
            ("bom_line_id", "=", parent_bom_line.id),
        ], order='sequence')

        if not branches:
            return False

        if len(branches) == 1:
            return branches[0]

        # Multiple branches - use cache logic
        index_str = str(index)
        path_key = f"{root_bom_id}_{parent_bom_line.id}_{index_str}"

        if not hasattr(self.__class__, '_branch_assignment_cache'):
            return branches[0]

        cache = self.__class__._branch_assignment_cache
        cache_key = f"bom_{root_bom_id}"

        if cache_key not in cache:
            return branches[0]

        bom_cache = cache[cache_key]

        if path_key in bom_cache['assignments']:
            branch_id = bom_cache['assignments'].get(path_key)
            return Branch.browse(branch_id) if branch_id else branches[0]

        return branches[0]

