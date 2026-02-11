# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, api


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

        # product = self.env['product.product'].browse(data['product_id'])
        # print('product : ',product)
        # main_vendor = product.seller_ids.filtered(lambda s: s.main_vendor) if product else False
        # print('main_vendor : ', main_vendor)
        # data['has_main_vendor'] = bool(main_vendor)
        # print('has_main_vendor : ', data['has_main_vendor'])
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
            data['componentId'] = component_rec.id
            data['free_to_use'] = component_rec.free_to_use

            # # Collect customer PO lines (exclude cancelled)
            # if component_rec.customer_po_ids:
            #     for po_line in component_rec.customer_po_ids:
            #         if po_line.order_id.state != 'cancel':
            #             po_ids.append(po_line.id)
            #             po_names.append(po_line.order_id.name)
            #
            # # Collect vendor PO lines (exclude cancelled)
            # if component_rec.vendor_po_ids:
            #     for po_line in component_rec.vendor_po_ids:
            #         if po_line.order_id.state != 'cancel':
            #             po_ids.append(po_line.id)
            #             po_names.append(po_line.order_id.name)
            #
            # data['po_line_id'] = po_ids or False
            # data['po_line_name'] = ", ".join(po_names) if po_names else ""
            # # After collecting po_names
            # po_order_ids = list(set([po_line.order_id.id for po_line in
            #                          component_rec.customer_po_ids.filtered(lambda l: l.order_id.state != 'cancel')] +
            #                         [po_line.order_id.id for po_line in
            #                          component_rec.vendor_po_ids.filtered(lambda l: l.order_id.state != 'cancel')]))
            #
            # data['po_order_ids'] = po_order_ids or False

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


        data['purchase_group_editable'] = bom_line.approval_1 and bom_line.approval_2
        is_approval = bom_line.approval_1 and bom_line.approval_2

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


        return data

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

