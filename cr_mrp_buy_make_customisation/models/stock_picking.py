from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    root_bom_id = fields.Many2one('mrp.bom', string='Bom')

    def button_validate(self):

        res = super(StockPicking, self).button_validate()

        for picking in self:

            if (
                picking.picking_type_id.code == 'internal'
                and picking.picking_type_id.name == 'Pick Components'
                and picking.origin
            ):
                mo = self.env['mrp.production'].search(
                    [('name', '=', picking.origin)],
                    limit=1
                )

                if mo and mo.branch_mapping_id:

                    for move in picking.move_ids_without_package:

                        if move.state == 'done' and move.quantity > 0:
                            component = self.env['mrp.bom.line.branch.components'].search([
                                ('bom_line_branch_id', '=', mo.branch_mapping_id.id),
                                ('cr_bom_line_id.product_id', '=', move.product_id.id)
                            ], limit=1)


                            if component:
                                # component.write({
                                #     'used': component.used + move.quantity
                                # })
                                component.write({
                                    'used': move.quantity
                                })

                            child_mrp = self.env['mrp.production'].search([('parent_mo_id','=',mo.id)])
                            if child_mrp and child_mrp.branch_mapping_id:
                                if child_mrp.branch_mapping_id.bom_line_id.product_id.id == move.product_id.id:
                                    child_mrp.branch_mapping_id.sudo().write({'used':move.quantity})


            if (
                picking.picking_type_id.code == 'internal'
                and picking.picking_type_id.name == 'Store Finished Product'
                and picking.origin
            ):
                mo = self.env['mrp.production'].search(
                    [('name', '=', picking.origin)],
                    limit=1
                )

                if mo and mo.branch_mapping_id:

                    for move in picking.move_ids_without_package:

                        if move.state == 'done' and move.quantity > 0:
                            mo.branch_mapping_id.write({
                                'transferred': move.quantity
                            })

        return res



    @api.model
    def create(self, vals):
        picking = super(StockPicking, self).create(vals)

        if (
                picking.picking_type_id.code == 'internal'
                and picking.picking_type_id.name == 'Pick Components'
                and picking.origin
        ):
            mo = self.env['mrp.production'].search(
                [('name', '=', picking.origin)],
                limit=1
            )

            if mo and mo.branch_intermediate_location_id:

                picking.write({
                    'location_id': mo.branch_intermediate_location_id.id
                })
                vals['location_id'] = mo.branch_intermediate_location_id.id

                for move in picking.move_ids_without_package:
                    move.write({
                        'location_dest_id': mo.branch_intermediate_location_id.id
                    })

        if (
                picking.picking_type_id.code == 'internal'
                and picking.picking_type_id.name == 'Store Finished Product'
                and picking.origin
        ):
            mo = self.env['mrp.production'].search(
                [('name', '=', picking.origin)],
                limit=1
            )

            if mo and mo.cr_final_location_id:
                picking.write({
                    'location_dest_id': mo.cr_final_location_id.id
                })

                for move in picking.move_ids_without_package:
                    move.write({
                        'location_dest_id': mo.cr_final_location_id.id
                    })


        return picking
