{
    'name': 'Filter Selector',
    'version': '19.0.1.0.0',
    'category': 'Web',
    'summary': 'Add filters and search to One2many fields',
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'filter_selector/static/src/components/filter_toolbar.js',
            'filter_selector/static/src/components/filter_toolbar.xml',
            'filter_selector/static/src/fields/x2many_field_with_selectors.js',
            'filter_selector/static/src/hooks/use_bulk_action_on_selection.js',
            'filter_selector/static/src/fields/filter_selector_field.js',
            'filter_selector/static/src/fields/filter_selector_field.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
