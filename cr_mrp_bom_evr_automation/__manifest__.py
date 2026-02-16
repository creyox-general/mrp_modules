# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
{
    "name": "MRP BOM EVR Purchase Flow Automation",
    "summary": "Automated purchase and transfer flow for EVR BOMs",
    "version": "18.0.0.13",
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
}