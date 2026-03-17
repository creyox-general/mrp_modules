# -*- coding: utf-8 -*-
# Part of Creyox Technologies
{
    'name': 'Sale Order MTO Multi MO BOM',
    'version': '18.0.0.12',
    'category': 'Sales',
    'summary': 'Create hierarchical BOMs on SO confirmation for RE orders',
    "author": "Creyox Technologies",
    "website": "https://www.creyox.com",
    "support": "support@creyox.com",
    'depends': [
        'sale_stock', 'mrp', 'cr_sale_order_re_nre', 'project_mrp',
        'cr_mrp_bom_customisation', 'cr_mrp_bom_evr_customisation',
        'cr_mrp_bom_evr_automation', 'cr_mrp_buy_make_customisation',
        'cr_purchase_po_enhancement',
    ],
    'data': [
        'views/mrp_production.xml',
        'views/mrp_bom.xml',
        'views/sale_order.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}