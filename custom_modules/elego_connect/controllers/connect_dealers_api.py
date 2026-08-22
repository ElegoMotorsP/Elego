# -*- coding: utf-8 -*-
"""Dealer provisioning — called by Elego Connect API's DealersService.approve()
right after Elego HQ approves a pending dealer registration, so the dealer's
Odoo contact exists without anyone re-typing it into Odoo by hand.

Idempotent on x_dealer_code: calling this twice for the same dealer code
updates the existing partner rather than creating a duplicate — required
per Elego Connect's own idempotency design (docs/02.5 in the app's design
repo) since a retried HTTP call must be safe to repeat.
"""
import json

from odoo import http
from odoo.http import request

from .connect_auth import require_connect_bearer_token, log_connect_call


def _json_response(payload, status=200):
    return request.make_response(
        json.dumps(payload),
        status=status,
        headers=[('Content-Type', 'application/json')],
    )


def _parse_json_body():
    try:
        return json.loads(request.httprequest.data or b'{}'), None
    except ValueError:
        return None, _json_response({'error': 'invalid_json'}, status=400)


class ConnectDealersApiController(http.Controller):

    @http.route(
        '/elegomotors/connect/dealers', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def provision_dealer(self, **kwargs):
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        dealer_code = (body.get('dealerCode') or '').strip()
        legal_name = (body.get('legalName') or '').strip()
        owner_name = (body.get('ownerName') or '').strip()
        mobile = (body.get('mobile') or '').strip()
        gstin = (body.get('gstin') or '').strip()
        territory = (body.get('territory') or '').strip()

        missing = [
            name for name, val in [
                ('dealerCode', dealer_code), ('legalName', legal_name), ('mobile', mobile),
            ] if not val
        ]
        if missing:
            log_connect_call(client.client_id, 'connect/dealers', dealer_code, 'missing_fields')
            return _json_response({'error': 'missing_fields', 'fields': missing}, status=400)

        Partner = request.env['res.partner'].sudo()
        partner_vals = {
            'name': legal_name,
            'x_dealer_code': dealer_code,
            'is_company': True,
            'company_type': 'company',
            'mobile': mobile,
        }
        if gstin:
            partner_vals['vat'] = gstin
        if territory:
            partner_vals['x_dealer_territory'] = territory

        partner = Partner.search([('x_dealer_code', '=', dealer_code)], limit=1)
        if partner:
            partner.write(partner_vals)
            created = False
        else:
            partner = Partner.create(partner_vals)
            created = True

        # Owner as a linked contact person under the dealer company — the
        # standard Odoo pattern for "company + the person you actually
        # deal with" — upserted the same way, by (parent_id, type=contact).
        if owner_name:
            owner_contact = Partner.search([
                ('parent_id', '=', partner.id), ('type', '=', 'contact'),
            ], limit=1)
            owner_vals = {'name': owner_name, 'parent_id': partner.id, 'type': 'contact'}
            if owner_contact:
                owner_contact.write(owner_vals)
            else:
                Partner.create(owner_vals)

        log_connect_call(
            client.client_id, 'connect/dealers', dealer_code,
            f'{"created" if created else "updated"} partner #{partner.id}',
        )
        return _json_response({'odooPartnerId': partner.id, 'created': created})
