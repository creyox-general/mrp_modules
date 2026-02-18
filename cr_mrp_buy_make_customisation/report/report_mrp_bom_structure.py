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

            # Check if this should be treated as component
            treat_as_component = (
                    (bom_line.child_bom_id and
                     bom_line.product_id.manufacture_purchase == 'buy_make' and
                     bom_line.buy_make_selection == 'buy') or
                    bom_line.product_id.manufacture_purchase == 'buy'
            )

            if treat_as_component:
                # Treat as component - show component fields instead of branch
                Component = self.env["mrp.bom.line.branch.components"]

                component_rec = self._get_component_for_line(root_bom_id, bom_line, parent_bom, index)

                data['type'] = 'component'
                data['components'] = []
                data['operations'] = []
                data['branch'] = ""

                # Show component fields
                if component_rec:
                    component_rec.quantity = data['quantity']
                    data['componentId'] = component_rec.id
                    data['free_to_use'] = component_rec.free_to_use
                    data['display_free_to_use'] = True

                    # Enable component editing fields
                    data['cfe_editable'] = True
                    data['lli_editable'] = True
                    data['approval_1_editable'] = True
                    data['approval_2_editable'] = True
                    data['customer_ref_editable'] = True
                    data['mo_internal_ref_editable'] = True

                    # Show component data from bom_line
                    data['cfe_quantity'] = component_rec.cfe_quantity
                    data['has_cfe_quantity'] = bool(component_rec.cfe_quantity)
                    data['approval_1'] = component_rec.approval_1
                    data['approval_2'] = component_rec.approval_2

                    user = self.env.user
                    can_edit_approval_2 = user.has_group('mrp.group_mrp_manager') or user.has_group(
                        'purchase.group_purchase_manager')

                    data['can_edit_approval_2'] = can_edit_approval_2

                    # Show manufacturer data
                    available_manufacturers = []
                    main_vendor_line = bom_line.product_id.product_tmpl_id.seller_ids.filtered(lambda s: s.main_vendor)
                    for vendor in main_vendor_line:
                        for manufacturer in vendor.manufacturer_ids:
                            available_manufacturers.append({
                                'id': manufacturer.id,
                                'ref': manufacturer.manufacture_internal_ref,
                                'name': manufacturer.manufacture_internal_ref,
                            })

                    data['available_manufacturers'] = available_manufacturers
                    data[
                        'product_manufacturer_id'] = component_rec.product_manufacturer_id.id if component_rec.product_manufacturer_id else False
                    data['product_manufacturer_editable'] = True

                    # Customer ref
                    data['customer_ref'] = bom_line.customer_ref or ''
                    data['customer_ref_editable'] = True

                    # PO data
                    po_data = []
                    if component_rec.customer_po_ids:
                        for po_line in component_rec.customer_po_ids:
                            if po_line.order_id.state != 'cancel':
                                po_data.append({
                                    'id': po_line.order_id.id,
                                    'name': po_line.order_id.name
                                })

                    if component_rec.vendor_po_ids:
                        for po_line in component_rec.vendor_po_ids:
                            if po_line.order_id.state != 'cancel':
                                po_data.append({
                                    'id': po_line.order_id.id,
                                    'name': po_line.order_id.name
                                })

                    seen_ids = set()
                    unique_po_data = []
                    for po in po_data:
                        if po['id'] not in seen_ids:
                            seen_ids.add(po['id'])
                            unique_po_data.append(po)

                    data['po_data'] = unique_po_data
                    data['po_line_name'] = ", ".join([po['name'] for po in unique_po_data]) if unique_po_data else ""

                    # Purchase group data
                    data['purchase_group_editable'] = component_rec.approval_1 and component_rec.approval_2
                    if component_rec.approval_1 and component_rec.approval_2:
                        data['to_order'] = component_rec.to_order
                        data['to_order_cfe'] = component_rec.to_order_cfe
                        data['ordered'] = component_rec.ordered
                        data['ordered_cfe'] = component_rec.ordered_cfe
                        data['to_transfer'] = component_rec.to_transfer
                        data['to_transfer_cfe'] = component_rec.to_transfer_cfe
                        data['transferred'] = component_rec.transferred
                        data['transferred_cfe'] = component_rec.transferred_cfe
                        data['used'] = component_rec.used
                        data['lost'] = component_rec.lost

                    product = self.env['product.product'].browse(data['product_id'])
                    main_vendor = product.seller_ids.filtered(lambda s: s.main_vendor) if product else False
                    data['has_main_vendor'] = bool(main_vendor)

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

                    data['product_manufacturer_editable'] = True


                else:
                    # No component record - show defaults
                    data['cfe_editable'] = True
                    data['lli_editable'] = True
                    data['approval_1_editable'] = True
                    data['approval_2_editable'] = True
                    data['customer_ref_editable'] = True

                data['approve_to_manufacture_editable'] = False
                data['bom_line_id'] = bom_line.id

            else:
                # Normal BOM line - show branch
                Branch = self.env["mrp.bom.line.branch"]

                branches = Branch.search([
                    ("bom_id", "=", root_bom_id),
                    ("bom_line_id", "=", bom_line.id),
                ], order='sequence')

                branch = False
                if branches:
                    if len(branches) == 1:
                        branch = branches[0]
                    else:
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
                    data['has_main_vendor'] = True
                    data['used'] = branch.used
                    data['transferred'] = branch.transferred
                    data['used_editable'] = True
                    data['transferred_editable'] = True
                else:
                    data['approve_to_manufacture_editable'] = False

                data['bom_line_id'] = bom_line.id if bom_line else False

            # Add buy_make selection data for all cases
            data['buy_make_selection'] = bom_line.buy_make_selection or False
            data['is_buy_make_product'] = bom_line.product_id.manufacture_purchase == 'buy_make'
            data['manufacture_purchase'] = bom_line.product_id.manufacture_purchase or False

        else:
            data["branch"] = ""
            data['bom_line_id'] = bom_line.id if bom_line else False
            data['has_main_vendor'] = True


        if bom_line:
            data['critical'] = bom_line.critical or False

        else:
            data['critical'] = False

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
        child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')
        data['customer_ref_editable'] = not bool(child_bom)

        component_rec = self._get_component_for_line(root_bom_id, bom_line, parent_bom, index)

        data['display_free_to_use'] = True
        if component_rec:
            component_rec.quantity = data['quantity']
            data['componentId'] = component_rec.id
            data['free_to_use'] = component_rec.free_to_use

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

            # Check if product has a main vendor
            product = bom_line.product_id if bom_line else parent_product
            main_vendor = product.seller_ids.filtered(lambda s: s.main_vendor) if product else False
            data['has_main_vendor'] = bool(main_vendor)

            # ============= BUY/MAKE FUNCTIONALITY =============
            # Add buy_make selection data
            data['buy_make_selection'] = bom_line.buy_make_selection or False
            data['is_buy_make_product'] = bom_line.product_id.manufacture_purchase == 'buy_make'
            data['manufacture_purchase'] = bom_line.product_id.manufacture_purchase or False
            data['show_buy_make_column'] = True  # Show column in overview

            # If BUY is selected, treat as regular component
            if bom_line.buy_make_selection == 'buy':
                data['type'] = 'component'
            # ============= END BUY/MAKE FUNCTIONALITY =============

            data['critical'] = bom_line.critical or False

            if component_rec:
                data['lost'] = component_rec.lost
            else:
                data['lost'] = 0.0

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

    # def _get_component_for_line(self, root_bom_id, bom_line, parent_bom, index):
    #     """Get component record for line - handles BUY-selected BOM lines"""
    #
    #     Component = self.env["mrp.bom.line.branch.components"]
    #
    #     # Check if line has child BOM but BUY selected (treat as component)
    #     has_child_bom = bool(self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal'))
    #     is_buy_make = bom_line.product_id.manufacture_purchase == 'buy_make'
    #     is_buy_selected = bom_line.buy_make_selection == 'buy'
    #     is_buy = bom_line.product_id.manufacture_purchase == 'buy'
    #
    #     treat_as_component = not has_child_bom or (has_child_bom and is_buy_make and is_buy_selected) or is_buy
    #
    #     if not treat_as_component:
    #         return False
    #
    #     # Search for component record
    #     # For root level
    #     if not parent_bom or parent_bom.id == root_bom_id:
    #         component = Component.search([
    #             ('root_bom_id', '=', root_bom_id),
    #             ('bom_id', '=', parent_bom.id),
    #             ('cr_bom_line_id', '=', bom_line.id),
    #             ('is_direct_component', '=', True),
    #         ], limit=1)
    #
    #         return component if component else False
    #
    #     # For child level
    #     component = Component.search([
    #         ('root_bom_id', '=', root_bom_id),
    #         ('bom_id', '=', parent_bom.id),
    #         ('cr_bom_line_id', '=', bom_line.id),
    #         ('is_direct_component', '=', False),
    #     ], limit=1)
    #
    #     return component if component else False


    def _get_component_for_line(self, root_bom_id, bom_line, parent_bom, index):
        Component = self.env["mrp.bom.line.branch.components"]

        # Check if line has child BOM but BUY selected (treat as component)
        has_child_bom = bool(self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal'))
        is_buy_make = bom_line.product_id.manufacture_purchase == 'buy_make'
        is_buy_selected = bom_line.buy_make_selection == 'buy'
        is_buy = bom_line.product_id.manufacture_purchase == 'buy'

        treat_as_component = not has_child_bom or (has_child_bom and is_buy_make and is_buy_selected) or is_buy

        if not treat_as_component:
            return False

        # # Check for child BOM
        # child_bom = self.env['mrp.bom']._bom_find(bom_line.product_id, bom_type='normal')
        #
        # if child_bom:
        #     return False

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


