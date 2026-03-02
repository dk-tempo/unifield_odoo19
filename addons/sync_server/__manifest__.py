# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Sync Server Module',
    'version': '1.0',
    'category': '',
    'depends': ['base'],
    'description': """
This is the base module for managing Units of measure.
========================================================================
    """,
    'data': [
       'security/ir.model.access.csv',
       'views/sync_server_view.xml',
    ],
    'author': 'MSF, TeMPO Consulting',
    'installable': True,
    'license': 'LGPL-3',
}
