{
    'name': "Elego Custom Invoice Format",
    'summary': "Customizes the Sales Invoice printout to match the Elego format and displays vehicle serial numbers.",
    'version': '18.0.1.0.0',
    'category': 'Invoicing/Custom',
    'depends': ['base', 'account', 'sale_management', 'stock', 'mrp'],
    'data': [
        'views/report_invoice_templates.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
