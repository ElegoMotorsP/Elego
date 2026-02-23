{
    'name': 'ElegoMotors Workflow Setup',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'ElegoMotors EV 2-wheeler end-to-end manufacturing workflow configuration',
    'description': """
        Configures the full ElegoMotors workflow:
        - CRM pipeline stages (Inquiry → Quotation → Sales Order → Won)
        - Inventory locations (Gate Entry, QC Inward, Store, Production, Quarantine, FG)
        - Stock operation types (Gate Entry Receipt, Inward QC Move, Production Issue, Delivery)
        - Manufacturing work centers (Frame Assembly, Motor, Battery, Electronics, QC, Packaging)
        - Company settings (2-level PO approval)
    """,
    'author': 'ElegoMotors',
    'depends': [
        'crm',
        'stock',
        'mrp',
        'purchase',
        'account',
        'sale_management',
        'sale_order_approval',  # Enterprise: res.company.sale_order_approval, sale_order_approval_min_amount
        'base_automation',      # base.automation — workflow notification rules
        'hr',                   # HR: employee records (Srushti)
        'hr_attendance',        # Attendance: officer/manager tracking (Srushti)
        'hr_holidays',          # Time Off: leave management (Srushti)
        # hr_payroll     — Enterprise-only; install separately if EE license is available
        # quality_control — Enterprise-only; QC handled via MRP work-order steps (Community)
    ],
    'data': [
        'data/crm_stages_data.xml',
        'data/stock_locations_data.xml',
        'data/stock_picking_types_data.xml',
        'data/stock_picking_types_fix.xml',
        'data/mrp_workcenters_data.xml',
        'data/company_config_data.xml',
        'data/bom_data.xml',
        'data/users_data.xml',           # department users (loaded before notification_rules)
        'data/notification_rules.xml',   # automated workflow notifications
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'elegomotors_setup.hooks:post_init_hook',
}
