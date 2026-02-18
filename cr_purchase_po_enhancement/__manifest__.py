# -*- coding: utf-8 -*-
# Part of Creyox Technologies
{
    'name': 'Purchase Order Enhancement',
    'version': '18.0.0.19',
    'category': 'Purchase',
    'summary': 'Enhanced PO management with types, vendor status, and follow-up',
    'depends': [
        'purchase',
        'purchase_stock',
        'stock',
        'approvals',
        'cr_mrp_bom_customisation',
        'cr_mrp_bom_evr_customisation',
        'cr_mrp_bom_evr_automation',
        "bizzup_product_customisation",
        'cr_mrp_buy_make_customisation',
        "purchase_stock"
    ],
    'data': [
        "views/res_config_settings.xml",
        'views/purchase_order_views.xml',
        'views/res_partner_views.xml',
        'views/po_line_followup_views.xml',
        'views/menu_views.xml',
        'views/product_views.xml',
        'views/approval_product_line.xml',
        'views/purchase_rfq_grouped.xml',
        'views/po_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cr_purchase_po_enhancement/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
}