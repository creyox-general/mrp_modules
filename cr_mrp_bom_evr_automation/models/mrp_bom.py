# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    last_flow_run = fields.Datetime(string="Last Flow Run", readonly=True)

    @api.model
    def _cron_run_evr_purchase_flow(self):
        """Cron job to run purchase flow every 10 minutes for all EVR BOMs"""
        evr_boms = self.search([("is_evr", "=", True)])

        for bom in evr_boms:
            try:
                bom._run_purchase_flow()
                bom.last_flow_run = fields.Datetime.now()
            except Exception as e:
                _logger.exception(f"Error running purchase flow for BOM {bom.id}: {str(e)}")

    def _run_purchase_flow(self):
        """Main purchase flow logic for EVR BOM"""
        self.ensure_one()

        if not self.is_evr:
            return

        # Get all components for this root BOM
        Component = self.env["mrp.bom.line.branch.components"]
        components = Component.search([("root_bom_id", "=", self.id)])

        for component in components:
            try:
                component._process_purchase_flow()
            except Exception as e:
                _logger.exception(
                    f"Error processing component {component.id} for BOM {self.id}: {str(e)}"
                )

    def action_run_purchase_flow_now(self):
        """Manual button to run purchase flow immediately"""
        self.ensure_one()
        self._run_purchase_flow()
        # self.last_flow_run = fields.Datetime.now()
        self.sudo().write({
            'last_flow_run': fields.Datetime.now()
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Purchase Flow Executed",
                "message": "The purchase flow has been executed successfully.",
                "type": "success",
                "sticky": False,
            },
        }
