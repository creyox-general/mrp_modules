# -*- coding: utf-8 -*-
# Part of Creyox Technologies

from odoo import models, api

class ReportBomStructure(models.AbstractModel):
    _inherit = 'report.mrp.report_bom_structure'

    def _get_bom_data(self, bom, warehouse, product=False, line_qty=False, bom_line=False, level=0, parent_bom=False, parent_product=False, index=0, product_info=False, ignore_stock=False, simulated_leaves_per_workcenter=False):
        res = super()._get_bom_data(bom, warehouse, product, line_qty, bom_line, level, parent_bom, parent_product, index, product_info, ignore_stock, simulated_leaves_per_workcenter)
        
        # Only inject header data for the root level (level 0)
        if level == 0:
            # Project and Customer
            project = bom.project_id
            if not project and bom.sale_order_id:
                project = getattr(bom.sale_order_id, 'project_id', False)
                
            res.update({
                'project_id': getattr(project, 'id', False),
                'project_name': project.name if project else '',
                'customer_name': project.partner_id.name if project and project.partner_id else '',
            })



            # Related Sales Orders
            so_ids = bom.sale_order_id.ids
            if project and not so_ids:
                so_ids = self.env['sale.order'].search([('project_id', '=', project.id)]).ids
                
            res.update({
                'so_ids': so_ids,
                'so_count': len(so_ids),
            })

            # Related Purchase Orders (via Project)
            po_ids = []
            if project:
                po_lines = self.env['purchase.order.line'].search([('project_id', '=', project.id)])
                po_ids = list(set(po_lines.mapped('order_id').ids))
            res.update({
                'po_ids': po_ids,
                'po_count': len(po_ids),
            })

            # Related Manufacturing Orders (via Project or Root BOM)
            if project:
                mo_domain = ['|', ('project_id', '=', project.id), ('root_bom_id', '=', bom.id)]
            else:
                mo_domain = [('root_bom_id', '=', bom.id)]
            
            mo_ids = self.env['mrp.production'].search(mo_domain).ids
            res.update({
                'mo_ids': mo_ids,
                'mo_count': len(mo_ids),
            })
            
        return res
