# -*- coding: utf-8 -*-
# Part of Creyox Technologies.

from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    evr_purchase_interval_number = fields.Integer(
        string="EVR Purchase Flow Interval Number",
        config_parameter="evr.purchase.interval.number",
        default=1,
        help="Number of minutes/days/hours for the scheduled action."
    )

    evr_purchase_interval_type = fields.Selection(
        [
            ('minutes', 'Minutes'),
            ('hours', 'Hours'),
            ('days', 'Days'),
            ('weeks', 'Weeks'),
            ('months', 'Months'),
        ],
        string="EVR Purchase Flow Interval Type",
        config_parameter="evr.purchase.interval.type",
        default="days",
        help="The interval type for the scheduled action."
    )

    @api.model
    def set_values(self):
        super(ResConfigSettings, self).set_values()

        number = self.evr_purchase_interval_number
        interval_type = self.evr_purchase_interval_type

        cron = self.env.ref("cr_mrp_bom_evr_automation.ir_cron_evr_purchase_flow", raise_if_not_found=False)

        if cron:
            cron.write({
                "interval_number": number,
                "interval_type": interval_type,
            })

    def action_open_evr_cron(self):
        cron = self.env.ref("cr_mrp_bom_evr_automation.ir_cron_evr_purchase_flow", raise_if_not_found=False)
        if cron:
            return {
                'type': 'ir.actions.act_window',
                'name': "EVR: Purchase Flow Cron",
                'view_mode': 'form',
                'res_model': 'ir.cron',
                'res_id': cron.id,
                'target': 'current',
            }
        return True
