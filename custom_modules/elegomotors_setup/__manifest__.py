{
    'name': 'ElegoMotors Workflow Setup',
    'version': '18.0.6.0.0',
    'category': 'Manufacturing',
    'summary': 'ElegoMotors EV 2-wheeler end-to-end manufacturing workflow configuration',
    'description': """
        Configures the full ElegoMotors workflow:
        - CRM pipeline stages (Inquiry → Quotation → Sales Order → Won)
        - Inventory locations (Gate Entry, QC Inward, Store, Production, Quarantine, FG)
        - Stock operation types (Gate Entry Receipt, Inward QC Move, Production Issue, Delivery)
        - Manufacturing: single-assembly-point MO (no work-order routing steps)
        - QC control points: inward material inspection + post-production quality check
        - Company settings (INR currency, 2-level PO approval)
        - Security: Produce button restricted to Manufacturing Operator group
        - Security: Amit (Store) restricted to customer invoices only, prices read-only
        - India localization (l10n_in) for GST + INR chart of accounts
    """,
    'author': 'ElegoMotors',
    'depends': [
        'crm',
        'stock',
        'mrp',
        'purchase',
        'account',
        'sale_management',
        'base_automation',      # base.automation — workflow notification rules
        'hr',                   # HR: employee records (Srushti)
        'hr_attendance',        # Attendance: officer/manager tracking (Srushti)
        'hr_holidays',          # Time Off: leave management (Srushti)
        'quality',              # Community QC: quality.point / quality.check / quality.alert
        'l10n_in',              # India localization: GST taxes, INR chart of accounts
        # hr_payroll     — Enterprise-only; install separately if EE license is available
        # quality_control — Enterprise-only; Community quality module used instead
    ],
    'data': [
        # Security groups must load before users_data (groups referenced in user records)
        'security/groups.xml',
        'security/record_rules.xml',
        'security/ir.model.access.csv',
        # store_billing_access.csv is kept on disk as a fallback reference but NOT loaded:
        # Amit retains account.group_account_invoice for model-level access (needed for
        # "Create Invoice" button on SO/Delivery). The ir.rule in record_rules.xml
        # restricts account.move records to out_invoice/out_refund at the ORM level.
        # Master data
        'data/crm_stages_data.xml',
        'data/stock_locations_data.xml',
        'data/stock_picking_types_data.xml',
        'data/stock_picking_types_fix.xml',
        'data/mrp_workcenters_data.xml',
        'data/company_config_data.xml',
        'data/bom_data.xml',
        'data/bom_data_fix.xml',         # deletes routing ops (noupdate=0, runs on upgrade)
        'data/users_data.xml',           # department users (loaded after groups)
        'data/quality_data.xml',         # QC control points: gate entry + FG receipt
        'data/qc_check_sheets_data.xml', # Charger + Battery QC check sheet templates
        'data/notification_rules.xml',   # automated workflow notifications
        # View overrides (loaded last so base views exist)
        'views/account_move_views.xml',
        'views/mrp_production_views.xml',   # Post-production QC buttons on MO form; Issue 7+8
        'views/purchase_order_views.xml',   # Receive Products button restriction; Issues 2+3
        'views/sale_order_views.xml',
        'views/stock_lot_views.xml',        # Component Traceability tab + serial list columns; Issue 7
        'views/stock_picking_views.xml',    # Gate Entry QC flow + vendor invoice + QC columns; Issues 5/6/12/13
        'views/product_template_views.xml', # x_qc_required checkbox + QC parameters list
        'views/stock_picking_qc_wizard_views.xml',  # QC routing wizard form + action
    ],
    'assets': {
        'web.assets_backend': [
            'elegomotors_setup/static/src/js/barcode_beep_widget.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
