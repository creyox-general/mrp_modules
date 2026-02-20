# -*- coding: utf-8 -*-
{
    'name': 'MRP Buy/Make Customisation',
    'version': '18.0.7.0.0',
    'category': 'Manufacturing',
    'summary': 'Add Buy/Make selection in BOM overview for products',
    'description': """
        This module adds:
        - MECH boolean field in Product Category
        - Manufacture/Purchase field in Product
        - Buy/Make selection in BOM Overview
        - Automatic handling of MO based on selection
    """,
    "author": "Creyox Technologies",
    "website": "https://www.creyox.com",
    'depends': ['mrp', 'purchase', 'stock', "cr_mrp_bom_customisation",
        "cr_mrp_bom_evr_customisation","cr_mrp_bom_evr_automation",'bus','cr_custom_internal_transfer'],
    'data': [
        'views/stock_picking.xml',
        'views/product_category_views.xml',
        'views/product_template_views.xml',
        'views/mrp_bom_views.xml',
        'views/mrp_production_views.xml',
        'views/mrp_bom_line_branch_components_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cr_mrp_buy_make_customisation//static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}