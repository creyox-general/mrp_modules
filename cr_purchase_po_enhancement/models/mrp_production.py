# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import models,api,fields
from odoo.exceptions import ValidationError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    @api.model_create_multi
    def create(self, vals_list):
        # PART 1: Handle validation for EVR BOMs
        for vals in vals_list:
            if vals.get('bom_id'):
                bom = self.env['mrp.bom'].browse(vals['bom_id'])
                if bom.is_evr:
                    unapproved_lines = []

                    if bom.project_id:
                        vals['project_id'] = bom.project_id.id

                    for line in bom.bom_line_ids:
                        if not bom._check_all_children_approved(line):
                            unapproved_lines.append(line.product_id.display_name)

                    if unapproved_lines:
                        raise ValidationError(
                            "Cannot create MO. The following BOM lines or their sub-components are not approved for manufacture:\n" +
                            "\n".join([f"- {name}" for name in unapproved_lines])
                        )

            branch_intermediate_location = self.env.context.get('branch_intermediate_location')

            # Store intermediate location
            if branch_intermediate_location:
                print('>>>branch_intermediate_location : ',branch_intermediate_location)
                vals['branch_intermediate_location_id'] = branch_intermediate_location

        # PART 2: Create MOs WITHOUT skipping component moves when called from write
        skip_moves = self.env.context.get('skip_component_moves', False)
        from_write = self.env.context.get('from_bom_write', False)

        if skip_moves and not from_write:
            mos = super(MrpProduction, self.with_context(skip_compute_move_raw_ids=True)).create(vals_list)
        else:
            mos = super().create(vals_list)

        return mos

