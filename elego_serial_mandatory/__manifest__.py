{
    'name': 'Serial Mandatory (Odoo 18) - with Invoice Serial Storage',
    'version': '1.1.0',
    'summary': 'Make serial/lot mandatory for marked products and store serials on invoice lines for exact reporting (Odoo 18)',
    'category': 'Warehouse',
    'author': 'LNSInfusion',
    'license': 'AGPL-3',
    'depends': ['stock', 'sale', 'account', 'mrp'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/report_invoice_inherit.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
