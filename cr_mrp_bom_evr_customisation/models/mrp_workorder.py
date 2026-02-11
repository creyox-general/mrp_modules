# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def button_start(self):
        self.production_id._check_approve_to_manufacture()
        return super().button_start()

    def button_finish(self):
        self.production_id._check_approve_to_manufacture()
        return super().button_finish()
