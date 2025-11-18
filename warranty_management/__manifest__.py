# -*- coding: utf-8 -*-
{
    "name": "Warranty Management - Complete",
    "version": "1.0.0",
    "summary": "Full warranty management: product warranties, claims, auto-generation from deliveries, reports and smart buttons",
    "author": "LNSInfusion",
    "license": "LGPL-3",
    "category": "Sales",
    "depends": ["base", "sale_management", "stock", "mrp", "account", "product"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence_data.xml",
        "views/product_template_views.xml",
        "views/product_warranty_views.xml",
        "views/warranty_claim_views.xml",
        "views/sale_order_views.xml",
        "views/stock_picking_inherit_views.xml",
        "views/menu.xml",
        "reports/warranty_report_templates.xml",
        "reports/warranty_report_actions.xml"
        # ,
        # "views/res_config_settings_views.xml"
    ],
    "installable": True,
    "application": False,
    "auto_install": False
}
