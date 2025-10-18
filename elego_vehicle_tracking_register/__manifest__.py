{
    'name': 'Vehicle Tracking Register',
    'version': '18.0.0.0',
    'summary': 'Vehicle Tracking Register',
    'description': 'Customized excel report for elego',
    'category': 'Reporting',
    'author': 'Prakash Gatade',
    'company': 'LNSInfusion',
    'depends': [
        'sale_management',
        'stock',
        'purchase',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/vehicle_tracking_report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'elego_vehicle_tracking_register/static/src/js/action_manager.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
