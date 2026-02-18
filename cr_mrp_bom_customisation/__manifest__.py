# -*- coding: utf-8 -*-
# Part of Creyox Technologies.
{
    'name': 'MRP BOM EVR Customization',
    'version': '18.0.9.0',
    'summary': 'Add EVR field customization to BOM overview',
    'description': """
        This module adds EVR customization to BOM:
        - Adds is_evr boolean field to BOM
        - Auto-sets is_evr to True when product internal ref starts with 'EVR'
        - Hides project_id field when is_evr is False
        - Displays EVR badge in BOM overview report
    """,
    'category': 'Manufacturing',
    'depends': ['mrp', 'project','purchase','stock','purchase_stock','purchase_mrp','bizzup_product_customisation','mrp_plm'],
    'data': [
        'views/mrp_bom_view.xml',
        'views/purchase_order.xml',
        'views/purchase_order_line.xml'
    ],
    "license": "OPL-1",
    "installable": True,
    "application": False,
}