# -*- coding: utf-8 -*-
{
    "name": "vehicle_stock_report",
    "version": "1.0.0",
    "summary": "Dynamic SQL vehicle stock report with component mappings, domain-export and PDF/XLSX/CSV exports",
    "description": "Vehicle tracking dynamic report: BOM component serial extraction, export current domain, PDF template, and admin mapping UI.",
    "author": "LNSInfusion",
    "license": "LGPL-3",
    "category": "Inventory/Reporting",
    "depends": ["base", "stock", "sale_management", "account", "product", "mrp", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/sample_component_roles.xml",
        "views/vehicle_stock_views.xml",
        "views/vehicle_stock_search.xml",
        "views/vehicle_stock_menu.xml",
        "views/vehicle_stock_wizard_views.xml",
        "views/vehicle_component_role_views.xml",
        "reports/vehicle_stock_report_templates.xml",
        "reports/vehicle_stock_report_actions.xml"
        # "views/templates_assets.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "vehicle_stock_report/static/src/js/export_current_domain.js"
        ]
    },
    "installable": True,
    "application": False,
    "auto_install": False
}
