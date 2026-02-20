from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    root_bom_id = fields.Many2one('mrp.bom', string='Bom')


    def button_validate(self):
        res = super().button_validate()

        for picking in self:
            if picking.picking_type_id.code != 'internal' or not picking.origin:
                continue

            mo = self._get_related_mo(picking.origin)
            if not mo:
                continue

            if picking.picking_type_id.name == 'Pick Components':
                self._handle_pick_components(picking, mo)

            elif picking.picking_type_id.name == 'Store Finished Product':
                self._handle_store_finished_product(picking, mo)
                self.reset_values(picking,mo)

        return res

    # ---------------------------------------------------------
    # Helper Methods
    # ---------------------------------------------------------


    def _get_related_mo(self, origin):
        return self.env['mrp.production'].search(
            [('name', '=', origin)],
            limit=1
        )

    def _handle_pick_components(self, picking, mo):
        # if not mo.branch_mapping_id:
        #     return

        ComponentModel = self.env['mrp.bom.line.branch.components']
        BranchModel = self.env['mrp.bom.line.branch']
        MrpModel = self.env['mrp.production']

        for move in picking.move_ids_without_package.filtered(
                lambda m: m.state == 'done' and m.quantity > 0
        ):
            # 1️⃣ Update Component
            component = ComponentModel.search([
                ('is_direct_component', '=', False),
                ('bom_line_branch_id', '=', mo.branch_mapping_id.id),
                ('cr_bom_line_id.product_id', '=', move.product_id.id),
                ('root_bom_id','=',mo.root_bom_id.id)
            ], limit=1)

            if component:
                component.write({'used': move.quantity, 'transferred': 0,
                'transferred_cfe': 0,})
                self._update_child_mo_usage(mo, move, MrpModel)
                continue

            # 2️⃣ Fallback Branch Update
            if mo.branch_intermediate_location_id:
                if  mo.bom_id.id == mo.root_bom_id.id:
                    branches = BranchModel.search([
                        ('bom_id', '=', mo.root_bom_id.id),
                        ('used', '=',0)
                    ])

                    matching_branch = branches.filtered(
                        lambda b: b.bom_line_id.product_id == move.product_id
                    )

                    if matching_branch:
                        matching_branch.write({'used': move.quantity,'transferred': 0,})
                else:
                    self._update_child_mo_usage(mo, move, MrpModel)

            if not mo.branch_mapping_id:
                component = ComponentModel.search([
                    ('is_direct_component', '=', True),
                    ('root_bom_id','=',mo.root_bom_id.id),
                    ('cr_bom_line_id.product_id', '=', move.product_id.id)
                ], limit=1)

                if component:
                    component.write({'used': move.quantity, 'transferred': 0,
                                     'transferred_cfe': 0, })


    def _update_child_mo_usage(self, mo, move, MrpModel):
        child_mo = MrpModel.search(
            [('parent_mo_id', '=', mo.id)],
            limit=1
        )

        if (
                child_mo
                and child_mo.branch_mapping_id
                and child_mo.branch_mapping_id.bom_line_id.product_id == move.product_id
        ):
            child_mo.branch_mapping_id.sudo().write({
                'transferred': 0,
                'used': move.quantity
            })

    def _handle_store_finished_product(self, picking, mo):
        if not mo.branch_mapping_id:
            return

        for move in picking.move_ids_without_package.filtered(
                lambda m: m.state == 'done' and m.quantity > 0
        ):
            # Update transferred qty
            mo.branch_mapping_id.write({
                'transferred': move.quantity
            })

            # Reset all component counters in single write
            mo.branch_mapping_id.mrp_bom_line_branch_component_ids.write({
                'to_order': 0,
                'to_order_cfe': 0,
                'ordered': 0,
                'ordered_cfe': 0,
                'to_transfer': 0,
                'to_transfer_cfe': 0,
                'transferred': 0,
                'transferred_cfe': 0,
            })

    def reset_values(self, picking, mo):
        # Run logic only for root MO
        if (
                mo.bom_id
                and mo.root_bom_id
                and mo.bom_id.id == mo.root_bom_id.id
        ):
            branches = self.env['mrp.bom.line.branch'].search([
                ('bom_id', '=', mo.bom_id.id)
            ])

            for branch in branches:
                branch.write({
                    'transferred': 0,
                    'used': 0,
                    'approve_to_manufacture':False,
                })

            components = self.env['mrp.bom.line.branch.components'].search([
                ('root_bom_id', '=', mo.root_bom_id.id),
            ])

            for component in components:
                component.write({
                    'used': 0,
                    'transferred': 0,
                    'transferred_cfe': 0,
                })



    @api.model
    def create(self, vals):

        # Execute custom logic BEFORE super()

        if vals.get('picking_type_id') and vals.get('origin'):

            picking_type = self.env['stock.picking.type'].browse(vals['picking_type_id'])

            # Case 1: Pick Components
            if (
                    picking_type.code == 'internal'
                    and picking_type.name == 'Pick Components'
                    and vals.get('origin')
            ):
                mo = self.env['mrp.production'].search(
                    [('name', '=', vals.get('origin'))],
                    limit=1
                )

                if mo and mo.branch_intermediate_location_id:
                    vals['location_id'] = mo.branch_intermediate_location_id.id

            # Case 2: Store Finished Product
            if (
                    picking_type.code == 'internal'
                    and picking_type.name == 'Store Finished Product'
                    and vals.get('origin')
            ):
                mo = self.env['mrp.production'].search(
                    [('name', '=', vals.get('origin'))],
                    limit=1
                )

                if mo and mo.cr_final_location_id:
                    vals['location_dest_id'] = mo.cr_final_location_id.id

        # Now call super AFTER custom logic
        picking = super(StockPicking, self.with_context(
            bypass_custom_internal_transfer_restrictions=True
        )).create(vals)

        return picking


