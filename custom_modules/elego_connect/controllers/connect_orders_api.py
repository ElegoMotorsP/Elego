# -*- coding: utf-8 -*-
"""Dealer-PO → Odoo Sales Order sync — called by Elego Connect API's
OrdersService once an HQ-approved PO needs to land in Odoo
(docs/07-module-dealer-catalogue-po-payments.md §7.5 in the app's own
design repo). Reuses the existing elegomotors.connect.api.client
credential — no new credential needed for this.
"""
from odoo import http
from odoo.http import request

from .connect_auth import _json_response, _parse_json_body, log_connect_call, require_connect_bearer_token


class ConnectOrdersApiController(http.Controller):

    @http.route(
        '/elegomotors/connect/orders/confirm', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def confirm_order(self, **kwargs):
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        po_number = (body.get('poNumber') or '').strip()
        odoo_partner_id = body.get('odooPartnerId')
        lines = body.get('lines') or []
        missing = [
            name for name, val in [
                ('poNumber', po_number), ('odooPartnerId', odoo_partner_id), ('lines', lines),
            ] if not val
        ]
        if missing:
            log_connect_call(client.client_id, 'orders/confirm', po_number, 'missing_fields')
            return _json_response({'error': 'missing_fields', 'fields': missing}, status=400)

        partner = request.env['res.partner'].sudo().browse(int(odoo_partner_id))
        if not partner.exists():
            log_connect_call(client.client_id, 'orders/confirm', po_number, 'odoo_partner_not_found')
            return _json_response({'error': 'odoo_partner_not_found'})

        try:
            order, created = request.env['sale.order'].sudo().create_from_connect_po({
                'poNumber': po_number,
                'odooPartnerId': int(odoo_partner_id),
                'deliveryAddress': body.get('deliveryAddress'),
                'remarks': body.get('remarks'),
                'lines': lines,
            })
        except Exception as e:  # noqa: BLE001 — surfaced to the caller, not swallowed
            log_connect_call(client.client_id, 'orders/confirm', po_number, f'error: {e}')
            return _json_response({'error': 'sales_order_creation_failed', 'message': str(e)}, status=500)

        log_connect_call(
            client.client_id, 'orders/confirm', po_number,
            f'{"created" if created else "already existed"} SO #{order.id} ({order.name})',
        )
        payload = order.connect_status_payload()
        payload['created'] = created
        return _json_response(payload)

    @http.route(
        '/elegomotors/connect/orders/<int:odoo_sale_order_id>/status', type='http',
        auth='public', methods=['GET'], csrf=False,
    )
    def order_status(self, odoo_sale_order_id, **kwargs):
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response

        order = request.env['sale.order'].sudo().browse(odoo_sale_order_id)
        if not order.exists():
            log_connect_call(client.client_id, 'orders/status', str(odoo_sale_order_id), 'order_not_found')
            return _json_response({'error': 'order_not_found'})

        log_connect_call(client.client_id, 'orders/status', order.name, order.state)
        return _json_response(order.connect_status_payload())
