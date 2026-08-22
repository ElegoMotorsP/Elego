{
    'name': 'Elego Connect',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'API integration layer for the Elego Connect app (Dealer/Customer/HQ)',
    'description': """
        Odoo-side integration for Elego Connect — the single Dealer/Customer/
        Elego HQ app (separate repo). Depends on elegomotors_setup for the
        dealer (res.partner.x_dealer_code), stock (stock.lot serials), and
        warranty (elegomotors.warranty.*) data it builds on.

        - A single shared, scoped API credential (elegomotors.connect.api.client)
          for everything Elego Connect writes to Odoo, separate from the
          existing Finance and Warranty API clients (each stays scoped to its
          own integration partner).
        - POST /elegomotors/connect/token — issues a bearer token for that
          credential (same stateless HMAC design as the Warranty/Finance APIs).
        - POST /elegomotors/connect/dealers — creates/updates the res.partner
          dealer contact when Elego HQ approves a new dealer registration in
          Elego Connect. Idempotent on x_dealer_code.
        - Extends elegomotors.warranty.claim with the additional status states
          and dispatch/failed-part-action fields the Elego Connect app's
          warranty screens need (docs/09-module-warranty.md in the app's own
          design repo), plus the two new endpoints that drive them — added by
          subclassing the existing WarrantyApiController rather than editing
          elegomotors_setup's warranty_api.py directly.
    """,
    'author': 'ElegoMotors',
    'depends': ['elegomotors_setup'],
    'data': [
        'security/ir.model.access.csv',
        'views/connect_api_client_views.xml',
        'views/connect_menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
