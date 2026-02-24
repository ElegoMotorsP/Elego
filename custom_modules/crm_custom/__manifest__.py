{
    'name': 'CRM Customizations',
    'version': '18.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Custom CRM functionality extensions',
    'description': """
        This module extends the standard Odoo CRM functionality with custom features:
        * Custom lead scoring
        * Enhanced pipeline views
        * Additional reporting capabilities
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': [
        'base',
        'crm',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
} 