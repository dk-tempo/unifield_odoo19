{
    "name": "MSF Purchase Order",
    "version": "19.0.1.0.0",
    "category": "",
    "summary": "Port of purchase modules from Unifield",
    "author": "TeMPO Consulting",
    "website": "https://tempo-consulting.fr",
    "license": "LGPL-3",
    "depends": ["msf_product"],
    # 'depends': ['base', 'account', 'stock', 'process', 'procurement'],
    "data": [
        "security/ir.model.access.csv",

        # "data/purchase_data.xml",

        "views/purchase_order_views.xml",

        "menus/purchase_menus.xml",
    ],
    "assets": {
        "web.report_assets_common": [
        ],
    },
    "installable": True,
    "auto_install": False,
}
