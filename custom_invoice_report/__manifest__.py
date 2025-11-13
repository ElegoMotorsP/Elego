{
    'name': "Custom Invoice Report (Odoo 18)",
    'version': '18.0.1.0.0',
    'summary': "Custom QWeb Report for Sales Invoice with specific formatting.",
    'depends': ['account'],
    'data': [
        'reports/reports.xml',
        'reports/report_invoice_document_format.xml',
        'reports/report_invoice_document.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
