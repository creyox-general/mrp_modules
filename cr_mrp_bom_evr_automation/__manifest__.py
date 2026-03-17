# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
{
    "name": "MRP BOM EVR Purchase Flow Automation",
    "summary": "Automated purchase and transfer flow for EVR BOMs",
    "version": "18.0.0.15",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "author": "Creyox Technologies",
    "website": "https://www.creyox.com",
    "depends": [
        "cr_mrp_bom_customisation",
        "cr_mrp_bom_evr_customisation",
    ],
    "data": [
        "data/ir_cron_data.xml",
        "views/mrp_bom_views.xml",
        "views/res_config_settings.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "assets": {
        "web.assets_backend": [
            "cr_mrp_bom_evr_automation/static/src/scss/bom_overview_scroll.scss",
            "cr_mrp_bom_evr_automation/static/src/components/bom_overview_control_panel/evr_bom_overview_control_panel.js",
            "cr_mrp_bom_evr_automation/static/src/components/bom_overview_control_panel/evr_bom_overview_control_panel.xml",
            "cr_mrp_bom_evr_automation/static/src/components/bom_overview_table/evr_bom_overview_table.xml",
            "cr_mrp_bom_evr_automation/static/src/components/bom_overview_line/evr_bom_overview_line.xml",
        ],
    },
}