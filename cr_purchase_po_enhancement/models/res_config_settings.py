# -*- coding: utf-8 -*-
# Part of Creyox Technologies
from odoo import api, fields, models
from datetime import date, timedelta


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    display_date_days =  fields.Selection(
        selection=[
            ("0", "Monday"),
            ("1", "Tuesday"),
            ("2", "Wednesday"),
            ("3", "Thursday"),
            ("4", "Friday"),
            ("5", "Saturday"),
            ("6", "Sunday"),
                    ],
                default="0",  config_parameter="cr_purchase_po_enhancement.display_date_days"
    )

