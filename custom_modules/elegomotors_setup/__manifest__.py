{
    'name': 'ElegoMotors Workflow Setup',
    'version': '18.0.26.0.0',
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
        'data/bom_data_fix.xml',            # deletes routing ops (noupdate=0, runs on upgrade)
        'data/product_variants_data.xml', # EGO-S1 color + side guards attribute setup; Req 2
        'data/product_models_data.xml',   # Elego 1.1, 1.2, 2.0+ templates + Battery Type variants
        'data/bom_data_new_models.xml',   # BOMs for the 3 new bike templates
        'data/bom_data_elego_11_by_color.xml', # Color-specific BOMs for Elego 1.1 (Red/White/Gray/Black)
        'data/bom_data_elego_12_by_color.xml', # Color-specific BOMs for Elego 1.2 (Red/White/Gray/Black)
        'data/bom_data_elego_20p_by_color.xml', # Color-specific BOMs for Elego 2.0+ (Red/White/Gray/Black)
        'data/pi_utils_data.xml',          # PI Section Header placeholder product
        'data/product_elego_30_data.xml',  # Elego 3.0 product template + serial sequence
        'data/gst_tax_data.xml',          # GST 5%/18% taxes + fiscal positions (MH intra/other inter)
        'data/sale_products_data.xml',    # Battery Pack + Side Guard accessory sale products
        'data/users_data.xml',            # department users (loaded after groups)
        'data/quality_data.xml',         # QC control points: gate entry + FG receipt
        'data/qc_check_sheets_data.xml', # Charger + Battery QC check sheet templates
        'data/notification_rules.xml',   # automated workflow notifications
        'data/cron_daily_pi.xml',        # Daily consolidated PI generation cron job
        # View overrides (loaded last so base views exist)
        'views/account_move_views.xml',
        'views/mrp_production_views.xml',   # Post-production QC buttons on MO form; Issue 7+8
        'views/purchase_order_views.xml',   # Receive Products button restriction; Issues 2+3
        'views/purchase_bom_wizard_views.xml', # Load BOM Components wizard on PO form
        'views/sale_order_reject_wizard_views.xml', # Reject Sales Order wizard (mandatory reason)
        'views/sale_order_views.xml',
        'views/stock_lot_views.xml',        # Component Traceability tab + serial list columns; Issue 7
        'views/stock_picking_views.xml',    # Gate Entry QC flow + vendor invoice + QC columns; Issues 5/6/12/13
        'views/product_template_views.xml', # x_qc_required checkbox + QC parameters list
        'views/stock_picking_qc_wizard_views.xml',  # QC routing wizard form + action
        'views/batch_mo_wizard_views.xml',          # Batch MO creation wizard + menu entry; Req 2
        'views/bulk_barcode_wizard_views.xml',      # Bulk barcode scan wizard for multi-unit MO
        'views/invoice_bike_scan_wizard_views.xml', # Bike serial scan wizard for invoice assignment
        'views/bike_traceability_views.xml',        # Bike Traceability search window + menu
        'views/generate_pi_wizard_views.xml',       # Generate Daily PI wizard + menu entry
        'views/report_invoice.xml',                 # ElegoMotors custom TAX INVOICE QWeb report
    ],
    'assets': {
        'web.assets_backend': [
            'elegomotors_setup/static/src/js/barcode_beep_widget.js',
            'elegomotors_setup/static/src/js/product_configurator_layout.js',
            'elegomotors_setup/static/src/css/product_configurator.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
