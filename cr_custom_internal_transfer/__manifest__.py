# -*- coding: utf-8 -*-
# Part of Creyox Technologies
{
    'name': 'Custom Internal Transfer',
    'version': '18.0.0.7',
    'category': 'Inventory',
    'author': 'Creyox Technologies',
    'website': 'https://www.creyox.com',
    'support': 'support@creyox.com',
    'summary': 'Restrict internal transfers to single product with auto location selection',
    'description': """
        Custom Internal Transfer Module
        ================================
        This module adds the following features for internal transfers:
        - Restricts internal transfers to contain only one product
        - Automatically selects source location with highest available stock
        - Filters location dropdown to show only locations with sufficient stock
        - Validates quantity against available stock
    """,
    'depends': [
        'stock',
    ],
    'data': ['views/stock_move.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
