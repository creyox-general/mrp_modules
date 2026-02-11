# -*- coding: utf-8 -*-
# Part of Creyox Technologies
{
    "name": "MRP BOM EVR Customisation",
    "summary": "Custom enhancements for MRP BOM and EVR processes",
    "version": "18.0.0.13",
    "category": "Manufacturing",
    "license": "LGPL-3",
    'author': 'Creyox Technologies',
    'website': 'https://www.creyox.com',
    "depends": [
        'mrp', 'project', 'purchase', 'stock', 'purchase_stock', 'purchase_mrp', 'bizzup_product_customisation',
        'mrp_plm',
        "cr_mrp_bom_customisation",
    ],
    "data": [
        "security/ir.model.access.csv",
        'views/mrp_bom_line_branch_views.xml',
        'views/mrp_bom_line_branch_components_views.xml',
        "views/stock_location_views.xml",
        "data/stock_location_data.xml",
        "views/purchase_order_view.xml",
        "views/mrp_bom_line_view.xml",
        "views/mrp_production.xml",
        "views/purchase_order_line.xml",
    ],
    'assets': {
        'web.assets_backend': [
            'cr_mrp_bom_evr_customisation/static/src/**/*',
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
