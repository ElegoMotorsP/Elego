{
    "name": "Elego Vehicle Tracking Report",
    "version": "1.0",
    "category": "Reporting",
    "summary": "Vehicle tracking report with filters (customer, invoice, item, location)",
    "author": "LNSInfusion",
    "depends": [
        "account",
        "stock",
        "mrp",
        "sale"
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/vehicle_tracking_wizard_view.xml",
        "reports/report_action.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}
