{
    "name": "MSF Product",
    "version": "19.0.1.0.0",
    "category": "",
    "summary": "Port of product modules from Unifield",
    "author": "TeMPO Consulting",
    "website": "https://tempo-consulting.fr",
    "license": "LGPL-3",
    "depends": ["msf_uom", "mail"],
    "data": [
        "security/ir.model.access.csv",

        "data/product_status_data.xml",
        "data/product_international_status_data.xml",
        "data/product_heat_sensitive_data.xml",
        "data/product_cold_chain_data.xml",
        "data/product_justification_code_data.xml",
        "data/product_section_code_data.xml",
        "data/product_supply_source_data.xml",

        "views/product_cold_chain_views.xml",
        "views/product_heat_sensitive_views.xml",
        "views/product_international_status_views.xml",
        "views/product_justification_code_views.xml",
        "views/product_list_views.xml",
        "views/product_nomenclature_views.xml",
        "views/product_product_views.xml",
        "views/product_purchase_views.xml",
        "views/product_status_views.xml",
        "views/product_supply_source_views.xml",
        "views/uom_views.xml",

        "menus/supply_configuration_menus.xml",
        "menus/product_menus.xml",

        "reports/product_reports.xml",
        "reports/product_labels_templates.xml",
        "reports/product_list_templates.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "msf_product/static/css/product_labels_report_styles.css",
            "msf_product/static/css/product_list_report_styles.css",
        ],
    },
    "installable": True,
    "auto_install": False,
}
