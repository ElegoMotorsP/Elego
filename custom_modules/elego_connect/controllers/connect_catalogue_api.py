# -*- coding: utf-8 -*-
"""Read-only bike-model catalogue for the Elego Connect app's dealer
catalogue screen (docs/07-module-dealer-catalogue-po-payments.md §7.1 in
the app's own design repo). One row per sellable variant (colour), not per
template — a dealer adds a specific colour to cart, not a bare model.

Pricing: flat `list_price` for every dealer for now (2026-08-31 decision,
recorded in the app repo's docs/20-project-status.md) — no per-dealer/
territory pricelist exists in Odoo yet. ATP: Odoo's on-hand `qty_available`
per variant, not a true reserved-aware available-to-promise figure (no
custom field for that exists either) — good enough for the "never show
total physical stock across colours combined" requirement in the interim,
revisit once a real ATP/pricelist model exists.
"""
from odoo import http
from odoo.http import request

from .connect_auth import _json_response, log_connect_call, require_connect_bearer_token


class ConnectCatalogueApiController(http.Controller):

    @http.route(
        '/elegomotors/connect/catalogue', type='http', auth='public',
        methods=['GET'], csrf=False,
    )
    def catalogue(self, **kwargs):
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response

        variants = request.env['product.product'].sudo().search([
            ('product_tmpl_id.x_is_ego_bike', '=', True),
            ('active', '=', True),
            ('sale_ok', '=', True),
        ])

        items = []
        for v in variants:
            colour = ', '.join(
                v.product_template_attribute_value_ids.mapped('name')
            ) or None
            items.append({
                'odooProductId': v.id,
                'model': v.product_tmpl_id.name,
                'variant': colour,
                'sku': v.default_code or str(v.id),
                'dealerPrice': v.list_price,
                'atpQty': int(v.qty_available),
            })

        log_connect_call(client.client_id, 'catalogue', '', f'{len(items)} variants')
        return _json_response({'items': items})
