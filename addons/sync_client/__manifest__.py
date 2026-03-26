# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Sync client Module',
    'version': '1.0',
    'category': 'Tools',
    'depends': ['base_setup', 'sync_common', 'mail'],
    'description': "Synchronization Engine - Client Module",
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence.xml'
    ],
    'author': 'OpenERP SA, MSF, TeMPO Consulting',
    'installable': True,
    'license': 'LGPL-3',
}
