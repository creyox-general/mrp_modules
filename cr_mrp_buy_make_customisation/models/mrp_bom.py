# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
import uuid

from odoo import models, api, _
import logging

from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


def _generate_branch_codes():
    codes = []
    for c in range(ord('A'), ord('Z') + 1):
        codes.append(chr(c))
    for c in range(ord('A'), ord('Z') + 1):
        for d in range(1, 10):
            codes.append(f"{chr(c)}{d}")
    for c1 in range(ord('A'), ord('Z') + 1):
        for c2 in range(ord('A'), ord('Z') + 1):
            codes.append(chr(c1) + chr(c2))
    return codes


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)
        if not self.env.context.get('skip_branch_recompute'):
            for bom in boms:
                bom._assign_branches_for_bom()
        return boms

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_branch_recompute'):
            # Only rebuild if structure-affecting fields changed
            if any(f in vals for f in ['bom_line_ids', 'product_qty', 'product_uom_id']):
                for bom in self:
                    bom._assign_branches_for_bom()
        return res

    @api.model
    def _auto_sync_mechanical_parts(self):
        """Helper for XML function tag to sync all BoMs on upgrade. Uses UI-Only mode to avoid touching structure."""
        boms = self.search([])
        boms.with_context(sync_ui_only=True).action_force_rebuild_mechanical_parts()
        return True

    def action_force_rebuild_mechanical_parts(self):
        """Force a full structural rebuild and sync for selected BoMs."""
        for bom in self:
            bom._assign_branches_for_bom()
        return True

    def _should_treat_as_component(self, bom_line, parent_branch_id=None, root_bom=None):
        """
        Smart path-aware check if BOM line should be treated as a component.
        Considers context overrides, existing branch selections, and global defaults.
        """
        if not bom_line:
            return False

        # If not provided, assume self is root (for simple cases)
        root_bom = root_bom or self

        has_child = bool(bom_line.child_bom_id)
        if not has_child:
            # Check if other BOMs exist if this line has no child_bom_id
            possible_bom = self._get_first_created_bom(bom_line.product_id)
            if possible_bom:
                has_child = True

        is_mech_categ = bom_line.product_id.categ_id.mech
        is_buy_make = bom_line.product_id.manufacture_purchase == 'buy_make'
        is_buy_product = bom_line.product_id.manufacture_purchase == 'buy'

        # Component if: (no child BOM AND not mechanical) OR type is strictly BUY
        if not (has_child or is_mech_categ) or is_buy_product:
            return True

        # Non-BUY assembly: Handle BUY/MAKE logic
        if not is_buy_make:
            # Normal assembly (MAKE path)
            return False

        # BUY/MAKE assembly path resolution
        is_buy = False
        
        # Priority 1: Context Overrides (Path-specific)
        changed_line_id = self.env.context.get('changed_line_id')
        changed_branch_id = self.env.context.get('changed_branch_id')
        new_buy_make_value = self.env.context.get('new_buy_make_value')
        target_parent_id = self.env.context.get('parent_branch_id')

        matches_context_path = (changed_line_id and bom_line.id == changed_line_id and 
                               ((target_parent_id == parent_branch_id) or (not target_parent_id and not parent_branch_id)))

        if matches_context_path:
            is_buy = (new_buy_make_value == 'buy')
        else:
            # Priority 2: Look for existing branch and its selection
            Branch = self.env['mrp.bom.line.branch']
            existing_branch = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', bom_line.id),
                ('parent_branch_id', '=', parent_branch_id)
            ], limit=1)
            
            if existing_branch:
                # If this IS the explicitly changed branch record, use the context value
                if changed_branch_id and existing_branch.id == changed_branch_id:
                    is_buy = (new_buy_make_value == 'buy')
                elif existing_branch.buy_make_selection:
                    is_buy = (existing_branch.buy_make_selection == 'buy')
                else:
                    # Fallback to line selection for branch with no selection
                    is_buy = getattr(bom_line, 'buy_make_selection', False) == 'buy'
            else:
                # Priority 3: Global Default (Line selection)
                is_buy = getattr(bom_line, 'buy_make_selection', False) == 'buy'

        # Final decision: Component if assembly but BUY is selected
        return is_buy


    def _get_first_created_bom(self, product):
        """Find the oldest BOM for a product."""
        domain = [
            '|',
            ('product_id', '=', product.id),
            '&',
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False),
        ]
        return self.env['mrp.bom'].search(domain, order='create_date asc, id asc', limit=1)


    def action_transition_bom_line(self, line_id, record_model, record_id, new_value, parent_branch_name=None):
        """
        ATOMIC TRANSITION PROXY:
        This is the STABLE entry point for BUY/MAKE transitions.
        """
        self.ensure_one()
        _logger.info(f"### ATOMIC TRANSITION START: Line {line_id} -> {new_value} ###")

        # 1. IDENTIFY LINE & ROOT
        line = self.env['mrp.bom.line'].browse(line_id)
        if not line.exists():
            return {'success': False, 'message': 'BOM Line not found'}

        # Determine parent_branch_name for the context check
        target_parent_name = parent_branch_name or "ROOT"
        if record_model == 'mrp.bom.line.branch' and record_id:
            branch_rec = self.env['mrp.bom.line.branch'].browse(record_id)
            if branch_rec.parent_branch_id:
                target_parent_name = branch_rec.parent_branch_id.branch_name
        elif record_model == 'mrp.bom.line.branch.components' and record_id:
            comp_rec = self.env['mrp.bom.line.branch.components'].browse(record_id)
            if comp_rec.bom_line_branch_id:
                target_parent_name = comp_rec.bom_line_branch_id.branch_name
        elif record_model == 'mrp.mechanical.part' and record_id:
            mech_rec = self.env['mrp.mechanical.part'].browse(record_id)
            if mech_rec.exists():
                target_parent_name = mech_rec.parent_branch_name

        # 2. CAPTURE DATA BEFORE PURGE
        old_value = getattr(line, 'buy_make_selection', 'buy')

        # Snapshot only MOs tied to currently active branches (not orphaned historical ones)
        active_branch_ids = self.env['mrp.bom.line.branch'].search([
            ('bom_id', '=', self.id)
        ]).ids
        mos_before = {
            mo.name: mo.product_id.display_name
            for mo in self.env['mrp.production'].search([
                ('root_bom_id', '=', self.id),
                ('branch_mapping_id', 'in', active_branch_ids),
                ('state', 'not in', ['done', 'cancel']),
            ])
        }

        # 3. SURGICAL & AGGRESSIVE LEGACY CLEANUP (MOs, POs, Transfers)
        # We do this FIRST while structural records still exist for path lookup
        cleanup_results = self._cleanup_transition_legacy_data(line, self, parent_branch_name=target_parent_name)

        # AGGRESSIVE GLOBAL MO CLEANUP: Delete ALL draft/confirmed/progress MOs for this project (ROOT BOM)
        # USER REQUEST: Search using ONLY root_bom_id, nothing else.
        extra_mos = self.env['mrp.production'].search([
            ('root_bom_id', '=', self.id),
            ('state', 'in', ['draft', 'confirmed', 'progress', 'to_close'])
        ])
        for xmo in extra_mos:
            # Check if already handled in cleanup_results
            if xmo.name not in [m.get('name') for m in cleanup_results.get('mos', [])]:
                cleanup_results['mos'].append({
                    'name': xmo.name, 
                    'product': xmo.product_id.display_name,
                    'state': xmo.state
                })
                _logger.info(f"  ✗ Deleting PROJECT-WIDE MO: {xmo.name} (State: {xmo.state})")
                xmo.action_cancel()
                xmo.unlink()


        # 4. FRESH REBUILD (Purge happens safely inside after caching)
        _logger.info(f"  ✓ TRIGGERING FRESH REBUILD")
        self.with_context(
            changed_line_id=line_id,
            new_buy_make_value=new_value,
            parent_branch_name=target_parent_name,
        )._assign_branches_for_bom()

        _logger.info(f"  ✓ GENERATING NEW MOs for all remaining MAKE branches")
        create_results = []
        self.with_context(created_mos_list=create_results).action_create_child_mos_recursive()
        
        # FINAL SYNC: picking up new MOs without unlinking structure again
        self.with_context(skip_structural_recompute=True)._assign_branches_for_bom()

        # After full transition: show all MOs that existed before (all branches' old MOs)
        all_deleted_mos = [{'name': name, 'product': product} for name, product in mos_before.items()]

        # 7. REAL-TIME NOTIFICATIONS (WOW EFFECT)
        _logger.info(f"  ✓ SENDING TRANSITION NOTIFICATION")
        self._notify_transition_summary(line, old_value, new_value, cleanup_results, create_results)

        _logger.info(f"### ATOMIC TRANSITION COMPLETE ###")
        transfers_cancelled = [t for t in cleanup_results.get('transfers', []) if not t.get('reversed')]
        transfers_reversed = [t for t in cleanup_results.get('transfers', []) if t.get('reversed')]

        return {
            'success': True,
            'product_name': line.product_id.display_name,
            'old_value': old_value,
            'mos_deleted': all_deleted_mos,
            'pos_deleted': cleanup_results.get('pos', []),
            'transfers_cancelled': transfers_cancelled,
            'transfers_reversed': transfers_reversed,
            'mos_created': create_results,
            'branches_deleted': 0, # They are always all deleted/reassigned now
            'components_deleted': 0
        }

    def _cleanup_transition_legacy_data(self, line, root_bom, parent_branch_name=None):
        """
        Surgical cleanup of MOs, POs, and Transfers for a specific BOM line path.
        """
        self.ensure_one()
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        Assignment = self.env['mrp.bom.line.branch.assignment']
        
        # Find the parent branch ID from existing assignments for this line
        assign_domain = [('root_bom_id', '=', root_bom.id), ('bom_line_id', '=', line.id)]
        if parent_branch_name:
            if parent_branch_name == "ROOT":
                assign_domain.append(('branch_id', '=', False))
            else:
                assign_domain.append(('branch_id.branch_name', '=', parent_branch_name))
        
        assign = Assignment.search(assign_domain, limit=1)
        # Guard against stale references to already-deleted branch records
        parent_branch_id = assign.branch_id.id if (assign and assign.branch_id.exists()) else False

        results = {'mos': [], 'pos': [], 'transfers': []}

        # 1. CLEANUP AS BRANCH
        branch_domain = [
            ('bom_id', '=', root_bom.id),
            ('bom_line_id', '=', line.id),
            ('parent_branch_id', '=', parent_branch_id)
        ]
        branch_rec = Branch.search(branch_domain, limit=1)
        
        if branch_rec:
            _logger.info(f"  ✗ Cleaning up BRANCH legacy data for line {line.id} (Branch {branch_rec.branch_name})")
            results['mos'].extend(branch_rec._cleanup_branch_manufacturing_orders(root_bom))
            res_pos, res_confirmed = branch_rec._cleanup_branch_purchase_orders_recursive_data(root_bom)
            results['pos'].extend(res_pos)
            results['transfers'].extend(branch_rec._cleanup_branch_stock_pickings(root_bom))

        # 2. CLEANUP AS COMPONENT
        comp_rec = Component.search([
            ('root_bom_id', '=', root_bom.id),
            ('cr_bom_line_id', '=', line.id),
        ], limit=1)
        
        if comp_rec:
            _logger.info(f"  ✗ Cleaning up COMPONENT legacy data for line {line.id}")
            po_lines = self.env['purchase.order.line'].search([
                ('component_branch_id', '=', comp_rec.id),
                ('bom_id', '=', root_bom.id),
            ])
            for po_line in po_lines:
                if po_line.order_id.state in ['draft', 'sent', 'to approve']:
                    results['pos'].append({'po_name': po_line.order_id.name, 'product': po_line.product_id.display_name})
                    po_line.unlink()

            origin = f"EVR Flow - {root_bom.display_name}"
            pickings = self.env['stock.picking'].search([
                ('root_bom_id', '=', root_bom.id),
                ('origin', '=', origin),
                ('state', 'not in', ['cancel', 'done']),
            ])
            for picking in pickings:
                moves = picking.move_ids.filtered(lambda m: m.mrp_bom_line_id.id == line.id)
                if moves:
                    results['transfers'].append({'transfer_name': picking.name, 'product': line.product_id.display_name})
                    picking.action_cancel()

            # Reverse DONE transfers for this Component when switching to MAKE
            done_pickings = self.env['stock.picking'].search([
                ('root_bom_id', '=', root_bom.id),
                ('state', '=', 'done'),
                ('origin', '=', origin),
                ('location_dest_id', 'child_of', root_bom.cfe_project_location_id.id),
            ])
            for picking in done_pickings:
                for move in picking.move_ids:
                    if move.quantity > 0:
                        reversed_trans = self.env['mrp.bom.line']._create_reverse_transfer_to_free(move, root_bom)
                        if reversed_trans:
                            _logger.info(f"  ↩ Created reverse transfer for component: {reversed_trans.name}")
                            results['transfers'].append({'transfer_name': reversed_trans.name, 'product': line.product_id.display_name, 'reversed': True})
                # Remove root_bom_id link as requested by user to prevent duplicate reversal
                picking.write({'root_bom_id': False})

        return results

    def _notify_transition_summary(self, line, old_value, new_value, cleanup, created):
        """Send detailed real-time notification about the transition summary."""
        title = f"Transition: {old_value.upper()} → {new_value.upper()}"
        product = line.product_id.display_name
        
        msg_parts = [f"Product: {product}", ""]
        
        mos_del = cleanup.get('mos', [])
        if mos_del:
            states_map = {
                'draft': 'draft',
                'confirmed': 'confirmed',
                'progress': 'in-progress',
                'to_close': 'closing'
            }
            summary_by_state = {}
            for m in mos_del:
                s = states_map.get(m.get('state'), 'other')
                summary_by_state.setdefault(s, []).append(f"{m['name']} ({m.get('product', 'Unknown')})")
            
            if len(summary_by_state) == 1:
                state_label, mo_list = list(summary_by_state.items())[0]
                msg_parts.append(f"• Deleted {len(mos_del)} {state_label} MOs: {', '.join([m['name'] for m in mos_del])}")
            else:
                msg_parts.append(f"• Deleted {len(mos_del)} Project MOs:")
                for state_label, mo_details in summary_by_state.items():
                    msg_parts.append(f"  - {state_label.capitalize()}: {', '.join(mo_details)}")
            
        pos_del = cleanup.get('pos', [])
        if pos_del:
            msg_parts.append(f"• Cancelled {len(pos_del)} PO lines/orders.")
            
        trans_cancelled = [t for t in cleanup.get('transfers', []) if not t.get('reversed')]
        if trans_cancelled:
            msg_parts.append(f"• Cancelled {len(trans_cancelled)} pending transfers.")
            
        trans_reversed = [t for t in cleanup.get('transfers', []) if t.get('reversed')]
        if trans_reversed:
            msg_parts.append(f"• Created {len(trans_reversed)} reverse transfers to WH/Free.")
            
        if created:
            msg_parts.append(f"• Created {len(created)} new Manufacturing Orders.")
            
        if not (mos_del or pos_del or trans_cancelled or trans_reversed or created):
            msg_parts.append("• Structure updated (no secondary actions required).")
            
        message = "\n".join(msg_parts)
        
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            "simple_notification",
            {
                "title": title,
                "message": message,
                "sticky": False,
                "type": "success" if new_value == 'make' else "info",
            }
        )



    def _assign_branches_for_bom(self):
        """
        Global Structural Rebuild: Reassigns all structural records for the Root BOM from scratch.
        Caches manual selections for path consistency.
        """
        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']
        Assignment = self.env['mrp.bom.line.branch.assignment']
        codes = _generate_branch_codes()
        
        # Check for UI-Only mode (Refresh Management UI without touching backend structure)
        ui_only = self.env.context.get('sync_ui_only')
        skip_structural = self.env.context.get('skip_structural_recompute') or ui_only

        PartObj = self.env['mrp.mechanical.part']
        
        for root_bom in self:
            if self.env.context.get('skip_branch_recompute'):
                continue
                
            # selection_cache should pull from STABLE Management UI records
            selection_cache = {}
            existing_parts = PartObj.search([('root_bom_id', '=', root_bom.id)])
            for part in existing_parts:
                if part.buy_make_selection:
                    selection_cache[(part.parent_branch_name, part.bom_line_id.id)] = part.buy_make_selection

            if not skip_structural:
                # PURGE STRUCTURE (Backend models only)
                _logger.info(f"Rebuilding Structure for ROOT BOM: {root_bom.display_name}")
                Assignment.search([('root_bom_id', '=', root_bom.id)]).unlink()
                Component.search([('root_bom_id', '=', root_bom.id)]).unlink()
                Branch.search([('bom_id', '=', root_bom.id)]).unlink()

            # 3. REBUILD DFS (with Mechanical Sync)
            current_idx_ptr = 0
            root_location_id = root_bom.cfe_project_location_id.id if root_bom.cfe_project_location_id else False
            mechanical_sync_data = []

            # Extract context for targeted selection overrides
            changed_line_id = self.env.context.get('changed_line_id')
            new_buy_make_value = self.env.context.get('new_buy_make_value')
            target_parent_name = self.env.context.get('parent_branch_name', "ROOT")

            def dfs(current_bom, parent_branch_id, depth, current_root_line_id=None, parent_branch_name="ROOT"):
                nonlocal current_idx_ptr

                for line in current_bom.bom_line_ids:
                    if not line.product_id: continue

                    is_buy_prod = line.product_id.manufacture_purchase == 'buy'
                    child_bom = line.child_bom_id or root_bom._get_first_created_bom(line.product_id)
                    matches_context = (changed_line_id and line.id == changed_line_id and target_parent_name == parent_branch_name)

                    if matches_context:
                        current_selection = new_buy_make_value
                    elif (parent_branch_name, line.id) in selection_cache:
                        current_selection = selection_cache[(parent_branch_name, line.id)]
                    else:
                        if child_bom and not is_buy_prod:
                            current_selection = getattr(line, 'buy_make_selection', False)
                        else:
                            current_selection = getattr(line, 'buy_make_selection', 'buy')

                    is_mech_categ = line.product_id.categ_id.mech
                    is_component = (current_selection == 'buy' or not (child_bom or is_mech_categ) or is_buy_prod)
                    
                    if depth == 0: current_root_line_id = line.id

                    path_key = f"{root_bom.id}_{line.id}_{parent_branch_name}"
                    sync_vals = {
                        'path_key': path_key,
                        'bom_id': current_bom.id,
                        'bom_line_id': line.id,
                        'parent_branch_name': parent_branch_name,
                        'selection': current_selection or '',
                        'is_buy_make_product': True, # We already filtered for buy_make
                    }

                    if is_component:
                        # 1. LEGACY COMPONENT RECORD
                        if not skip_structural:
                            comp = Component.create({
                                'root_bom_id': root_bom.id,
                                'bom_id': current_bom.id,
                                'cr_bom_line_id': line.id,
                                'bom_line_branch_id': parent_branch_id,
                                'buy_make_selection': current_selection,
                                'root_line_id': current_root_line_id,
                                'is_direct_component': not bool(parent_branch_id),
                                'location_id': root_location_id, # Always use root loc
                            })

                            Assignment.create({
                                'root_bom_id': root_bom.id, 'bom_id': current_bom.id, 'bom_line_id': line.id,
                                'branch_id': parent_branch_id, 'own_branch_id': False, 'component_id': comp.id,
                                'root_line_id': current_root_line_id,
                            })
                        
                        sync_vals.update({
                            'part_type': 'component',
                            'branch_name': False,
                        })
                    else:
                        # 2. LEGACY BRANCH RECORD
                        code = codes[current_idx_ptr]
                        current_idx_ptr += 1

                        if not skip_structural:
                            loc = self.env['stock.location'].create({
                                'name': code, 'location_id': root_location_id, 'usage': 'internal',
                            })
                            branch_vals = {
                                'bom_id': root_bom.id, 'bom_line_id': line.id, 'branch_name': code,
                                'sequence': current_idx_ptr, 'path_uid': uuid.uuid4().hex, 'location_id': loc.id,
                                'parent_branch_id': parent_branch_id, 'root_line_id': current_root_line_id,
                            }
                            if current_selection == 'make':
                                branch_vals['buy_make_selection'] = 'make'
                            branch = Branch.create(branch_vals)

                            Assignment.create({
                                'root_bom_id': root_bom.id, 'bom_id': current_bom.id, 'bom_line_id': line.id,
                                'branch_id': parent_branch_id, 'own_branch_id': branch.id, 'component_id': False,
                                'root_line_id': current_root_line_id,
                            })
                        else:
                            # In Read-Only / UI-Only mode, we don't create or search for branches in the backend
                            branch = False 
                        
                        sync_vals.update({
                            'part_type': 'branch',
                            'branch_name': code,
                        })

                    # 3. MO SYNC DATA (Strict UI Filter)
                    # USER REQUEST: ONLY sync to Management UI if is 'buy_make'
                    if line.product_id.manufacture_purchase == 'buy_make':
                        mos = self.env['mrp.production'].search([
                            ('root_bom_id', '=', root_bom.id),
                            ('line', '=', str(line.id)),
                            ('state', '!=', 'cancel')
                        ])
                        # Link MOs to branch if we are in structural mode
                        if not is_component and branch:
                             mos.write({'branch_mapping_id': branch.id})
                             
                        sync_vals['mo_ids'] = mos.ids
                        mechanical_sync_data.append(sync_vals)
                    else:
                        # Link MOs to branch if they happen to exist but aren't buy_make (and we have a branch)
                        if not is_component and branch:
                            self.env['mrp.production'].search([
                                ('root_bom_id', '=', root_bom.id),
                                ('line', '=', str(line.id)),
                                ('state', '!=', 'cancel')
                            ]).write({'branch_mapping_id': branch.id})

                    # 4. RECURSION (Always recurse through sub-boms if they are set to MAKE)
                    if not is_component and child_bom:
                        dfs(child_bom, branch.id if branch else False, depth + 1, current_root_line_id, code)

            dfs(root_bom, None, 0)
            
            # 4. Synchronize Mechanical Parts
            self.env['mrp.mechanical.part'].sync_mechanical_parts(root_bom, mechanical_sync_data)
        return True

    def action_create_child_mos_recursive(self, root_bom=None, parent_mo=None, index="0", level=0, parent_qty=1.0,
                                          parent_branch_location=None, parent_branch_id=None):
        """
        Create MOs ONLY for BOM lines that have a child BOM and are NOT set to BUY.
        Modified to correctly handle branch path contexts including parent_branch_id.
        """
        Branch = self.env['mrp.bom.line.branch']

        # Get specific branch to start from (if called recursively from a branch change)
        start_from_branch = self.env.context.get('changed_branch_id')

        # Get created MOs list from context
        created_mos_list = self.env.context.get('created_mos_list')
        if created_mos_list is None:
            created_mos_list = []

        if root_bom is None:
            root_bom = self

        _logger.info(f"{index}  >>> action_create_child_mos_recursive START: parent_branch={parent_branch_id}, root_bom={root_bom.id}")

        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        stock_location = warehouse.lot_stock_id if warehouse else False

        mo = False
        for line_idx, line in enumerate(self.bom_line_ids):
            # Check if this line is a component in the context of the current parent branch
            is_comp = self._should_treat_as_component(line, parent_branch_id=parent_branch_id, root_bom=root_bom)
            _logger.info(f"{index}      Line Check: {line.id} | is_component={is_comp}")
            if is_comp:
                continue

            if not line.child_bom_id:
                # Still check if it has a first created BOM as fallback
                possible_bom = root_bom._get_first_created_bom(line.product_id)
                if not possible_bom:
                     continue
                child_bom = possible_bom
            else:
                child_bom = line.child_bom_id

            child_qty = float(line.product_qty or 1.0) * parent_qty
            line_index = f"{index}{line_idx}"

            # Find the branch record for this specific path
            branch_rec = Branch.search([
                ('bom_id', '=', root_bom.id),
                ('bom_line_id', '=', line.id),
                ('parent_branch_id', '=', parent_branch_id)
            ], limit=1)

            _logger.info(f"{index}      Branch Lookup: line={line.id}, parent={parent_branch_id} => Found={bool(branch_rec)}")

            if not branch_rec:
                continue

            current_branch_location = branch_rec.location_id.id if branch_rec.location_id else False
            branch_name = branch_rec.branch_name

            # Determine final destination (parent's branch location or project location)
            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # CHECK: Does MO already exist for this branch-line?
            existing_mo = self.env['mrp.production'].search([
                ('root_bom_id', '=', root_bom.id),
                ('line', '=', str(line.id)),
                ('branch_mapping_id', '=', branch_rec.id),
                ('state', '=', 'draft')
            ], limit=1)

            if existing_mo:
                _logger.info(f"{index}      Updating EXISTING MO: {existing_mo.name} (ID: {existing_mo.id})")
                existing_mo.write({
                    'product_qty': child_qty,
                    'parent_mo_id': parent_mo.id if parent_mo else False,
                    'cr_final_location_id': final_dest_location if final_dest_location else False,
                    'branch_intermediate_location_id': current_branch_location
                })
                mo = existing_mo
                if created_mos_list is not None:
                    created_mos_list.append({
                        'name': mo.display_name,
                        'product': mo.product_id.display_name,
                        'qty': mo.product_qty
                    })
            else:
                mo_vals = {
                    'product_id': child_bom.product_id.id or child_bom.product_tmpl_id.product_variant_id.id,
                    'product_uom_id': child_bom.product_uom_id.id,
                    'product_qty': child_qty,
                    'bom_id': child_bom.id,
                    'root_bom_id': root_bom.id,
                    'parent_mo_id': parent_mo.id if parent_mo else False,
                    'project_id': root_bom.project_id.id,
                    'line': str(line.id),
                    'cr_final_location_id': final_dest_location if final_dest_location else False,
                    'state': 'draft',
                    'branch_mapping_id': branch_rec.id,
                    'branch_intermediate_location_id': current_branch_location
                }

                _logger.info(f"{index}      Creating NEW MO for branch {branch_rec.id} (BOM: {child_bom.id}) | Qty: {child_qty}")
                mo = self.env['mrp.production'].with_context(
                    branch_intermediate_location=current_branch_location,
                    branch_final_location=final_dest_location,
                    skip_component_moves=True,
                    force_skip_component_moves=True,
                    created_mos_list=created_mos_list
                ).create(mo_vals)

            # RECURSE: Create MOs for this child's sub-BOMs
            child_bom.action_create_child_mos_recursive(
                parent_mo=mo,
                parent_branch_id=branch_rec.id,
                level=level + 1,
                index=f"{line_index}.",
                parent_qty=child_qty,
                parent_branch_location=current_branch_location,
                root_bom=root_bom
            )

            if hasattr(self.__class__, '_branch_assignment_cache'):
                if cache_key in self.__class__._branch_assignment_cache:
                    del self.__class__._branch_assignment_cache[cache_key]


        # Return list at root level, single MO object for recursion
        if level == 0:
            # Always return as list format
            return created_mos_list

        # For recursive calls, return the single MO object (last one created in this level)
        return mo



    def action_verify_branch_assignment(self):
        """Debug action to verify branch assignment"""
        self.ensure_one()

        Branch = self.env['mrp.bom.line.branch']
        Component = self.env['mrp.bom.line.branch.components']

        branches = Branch.search([('bom_id', '=', self.id)])
        components = Component.search([('root_bom_id', '=', self.id)])

        message = f"BOM: {self.display_name}\n\n"
        message += f"Branches ({len(branches)}):\n"
        for branch in branches:
            message += f"  - {branch.branch_name}: {branch.bom_line_id.product_id.display_name}\n"

        message += f"\nComponents ({len(components)}):\n"
        for comp in components:
            branch_name = comp.bom_line_branch_id.branch_name if comp.bom_line_branch_id else "ROOT"
            message += f"  - {comp.cr_bom_line_id.product_id.display_name} (branch: {branch_name}, direct: {comp.is_direct_component})\n"

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Branch Assignment Verification',
                'message': message,
                'type': 'info',
                'sticky': True,
            }
        }

    def _check_all_children_approved(self, line):
        """
        Override to handle BUY/MAKE selection:
        - If line has buy_make_selection = 'buy': Return True (no child MO needed)
        - If line has buy_make_selection = 'make': Check child BOMs normally
        """
        # If BUY selected, treat as component (always approved)
        if (line.product_id.manufacture_purchase == 'buy_make' and
                getattr(line, 'buy_make_selection', None) == 'buy'):
            _logger.info(
                "BOM line %s has BUY selected, treating as approved component",
                line.id
            )
            return True

        # Normal flow
        return super(MrpBom, self)._check_all_children_approved(line)

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)

        for bom in boms:
            product = bom.product_tmpl_id
            categ = product.categ_id if product else False

            if not categ or not categ.demo_bom_id:
                continue

            demo_bom = categ.demo_bom_id

            # Avoid copying onto the demo BOM itself
            if bom.id == demo_bom.id:
                continue

            result = self._copy_operations_from_demo_bom(bom, demo_bom)

            if result:
                self._send_demo_bom_notification(bom, result)

        return boms

    def _copy_operations_from_demo_bom(self, target_bom, demo_bom):
        operations_copied = 0

        for operation in demo_bom.operation_ids:
            vals = {
                'name': operation.name,
                'workcenter_id': operation.workcenter_id.id,
                'bom_id': target_bom.id,
                'sequence': operation.sequence,
                'time_cycle_manual': operation.time_cycle_manual,
                'time_mode': operation.time_mode,
            }

            self.env['mrp.routing.workcenter'].create(vals)
            operations_copied += 1

        return {
            'bom': target_bom,
            'operations_copied': operations_copied,
            'demo_bom': demo_bom,
        }

    def _send_demo_bom_notification(self, bom, result):
        product = bom.product_tmpl_id
        product.message_post(
            body=(
                f"BOM '{bom.display_name}' created. "
                f"Copied {result['operations_copied']} operations "
                f"from demo BOM '{result['demo_bom'].display_name}'."
            ),
            subject="Demo BOM Operations Copied",
            message_type='notification',
        )


    def _get_branch_location_for_line(self, line, root_bom):
        """
        Get branch location for a BOM line.
        This ensures consistent location retrieval whether MO exists or not.
        """
        Branch = self.env['mrp.bom.line.branch']
        branches = Branch.search([
            ('bom_id', '=', root_bom.id),
            ('bom_line_id', '=', line.id)
        ], order='sequence', limit=1)

        if branches and branches.location_id:
            return branches.location_id.id, branches
        return None, None


    def _get_branch_location_for_line(self, line, root_bom):
        """
        Get branch location for a BOM line.
        This ensures consistent location retrieval whether MO exists or not.
        """
        Branch = self.env['mrp.bom.line.branch']
        branches = Branch.search([
            ('bom_id', '=', root_bom.id),
            ('bom_line_id', '=', line.id)
        ], order='sequence', limit=1)

        if branches and branches.location_id:
            return branches.location_id.id, branches
        return None, None


    def _check_and_create_missing_mos(self, line, root_bom, parent_mo=None, parent_qty=1.0,
                                      parent_branch_location=None):
        """
        Recursively check if MOs exist for a line and all its children.
        Create missing MOs for entire hierarchy.
        """
        if not line.child_bom_id:
            return

        child_bom = line.child_bom_id
        child_qty = float(line.product_qty or 1.0) * parent_qty

        product_variant = child_bom.product_tmpl_id.product_variant_id
        if product_variant.manufacture_purchase == 'buy':
            return

        # Check if MO exists for this line
        existing_mo = self.env['mrp.production'].search([
            ('root_bom_id', '=', root_bom.id),
            ('line', '=', str(line.id)),
            ('bom_id', '=', child_bom.id),
            ('state', '=', 'draft')
        ], limit=1)

        current_mo = existing_mo
        current_branch_location = parent_branch_location

        if not existing_mo:
            # Get branch for this line to determine locations
            branch_location_id, branches = self._get_branch_location_for_line(line, root_bom)

            if branch_location_id:
                current_branch_location = branch_location_id

            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            # Get warehouse location
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            stock_location = warehouse.lot_stock_id if warehouse else False

            # Create MO for this line
            _logger.info(f"Creating missing MO for line {line.id} (product: {line.product_id.display_name})")

            mo_vals = {
                'product_id': child_bom.product_tmpl_id.product_variant_id.id,
                'product_uom_id': child_bom.product_uom_id.id,
                'product_qty': child_qty,
                'bom_id': child_bom.id,
                'root_bom_id': root_bom.id,
                'parent_mo_id': parent_mo.id if parent_mo else False,
                'project_id': root_bom.project_id.id,
                'line': line.id,
                'cr_final_location_id': final_dest_location if final_dest_location else False,
                'branch_mapping_id': branches.id if branches else False,
                'state': 'draft',
            }

            _logger.info(
                f"Creating MO with root_bom_id={root_bom.id} ({root_bom.display_name}), bom_id={child_bom.id} ({child_bom.display_name})")

            current_mo = self.env['mrp.production'].with_context(
                branch_intermediate_location=current_branch_location,
                branch_final_location=final_dest_location,
                skip_component_moves=True
            ).create(mo_vals)

            if current_mo.root_bom_id.id != root_bom.id:
                current_mo.root_bom_id = root_bom.id

            # Send notification
            branch_name = branches.branch_name if branches else "N/A"
            src_name = stock_location.display_name if stock_location else "WH/Stock"
            intermediate_name = self.env['stock.location'].browse(
                current_branch_location).display_name if current_branch_location else "N/A"
            final_name = self.env['stock.location'].browse(
                final_dest_location).display_name if final_dest_location else "N/A"

            self.env['bus.bus']._sendone(
                self.env.user.partner_id,
                "simple_notification",
                {
                    "title": "Manufacturing Order Created",
                    "message": (
                        f"MO {current_mo.name} created for {child_bom.display_name}\n"
                        f"Branch: {branch_name}\n"
                        f"Quantity: {child_qty}\n"
                        f"Flow: {src_name} → {intermediate_name} → {final_name}"
                    ),
                    "sticky": False,
                    "type": "info",
                }
            )
        else:
            _logger.info(f"MO already exists for line {line.id}: {existing_mo.name}")
            _logger.info(
                f"Existing MO has root_bom_id={existing_mo.root_bom_id.id if existing_mo.root_bom_id else 'None'}, expected={root_bom.id}")

            branch_location_id, branches = self._get_branch_location_for_line(line, root_bom)

            update_vals = {}

            if not existing_mo.root_bom_id or existing_mo.root_bom_id.id != root_bom.id:
                update_vals['root_bom_id'] = root_bom.id
                _logger.warning(
                    f"CORRECTING root_bom_id for MO {existing_mo.name} from {existing_mo.root_bom_id.id if existing_mo.root_bom_id else 'None'} to {root_bom.id}")

            if branches:
                if not existing_mo.branch_mapping_id or existing_mo.branch_mapping_id.id != branches.id:
                    update_vals['branch_mapping_id'] = branches.id
                    update_vals['branch_intermediate_location_id'] = branches.location_id.id
                    _logger.info(f"Updating branch_mapping_id for MO {existing_mo.name}")

            parent_mo_id = parent_mo.id if parent_mo else False
            if existing_mo.parent_mo_id.id if existing_mo.parent_mo_id else False != parent_mo_id:
                update_vals['parent_mo_id'] = parent_mo_id
                _logger.info(f"Updating parent_mo_id for MO {existing_mo.name}: {parent_mo_id}")

            final_dest_location = parent_branch_location if parent_branch_location else root_bom.cfe_project_location_id.id

            if not existing_mo.cr_final_location_id or existing_mo.cr_final_location_id != final_dest_location:
                update_vals['cr_final_location_id'] = final_dest_location
                _logger.info(f"Updating cr_final_location_id for MO {existing_mo.name}: {final_dest_location}")

            if update_vals:
                existing_mo.write(update_vals)
                _logger.info(f"Updated existing MO {existing_mo.name} with: {update_vals}")

            if existing_mo.branch_mapping_id and existing_mo.branch_mapping_id.location_id:
                current_branch_location = existing_mo.branch_mapping_id.location_id.id
            elif branch_location_id:
                current_branch_location = branch_location_id
            elif hasattr(existing_mo, 'cr_final_location_id') and existing_mo.cr_final_location_id:
                current_branch_location = existing_mo.cr_final_location_id

        # Recursively check ALL child lines
        for child_line in child_bom.bom_line_ids:
            if child_line.child_bom_id:
                self._check_and_create_missing_mos(
                    child_line,
                    root_bom,
                    current_mo,
                    child_qty,
                    current_branch_location
                )



