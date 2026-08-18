# -*- coding: utf-8 -*-
"""Bajaj Finance (BFL) serial-number validation API.

BFL calls this before approving a two-wheeler loan, to confirm a bike serial
is genuine, matches its model, was billed to the dealer requesting the loan,
and hasn't been validated before — implements the BRD in
"finance api/SerialNumber BRD.docx". Two endpoints:

    POST /elegomotors/finance/token            client_credentials -> bearer token
    POST /elegomotors/finance/validate-serial  the actual BRD contract

This is the first external-facing (non-Odoo-user) API in this codebase —
every other controller here is auth='user' for logged-in staff downloading
reports — so auth is handled explicitly per request rather than via Odoo's
session auth. Business-logic outcomes (valid / invalid / mismatch / already
validated / bad dealer / not billed to dealer) are returned as HTTP 200 with
a responseStatus/responseMessage body, matching the BRD's own sample. Only
transport/auth failures (bad token, malformed JSON, missing fields) use real
HTTP error codes.
"""
import json

from odoo import fields, http
from odoo.http import request


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


def _require_bearer_token():
    """Return (client_record, None) on success, or (None, error_response)."""
    auth_header = request.httprequest.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, _json_response({'error': 'missing_bearer_token'}, status=401)
    token = auth_header[len('Bearer '):].strip()
    client = request.env['elegomotors.finance.api.client'].sudo().verify_token(token)
    if not client:
        return None, _json_response({'error': 'invalid_or_expired_token'}, status=401)
    return client, None


class FinanceApiController(http.Controller):

    @http.route(
        '/elegomotors/finance/token', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def issue_token(self, **kwargs):
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        client_id = body.get('client_id')
        client_secret = body.get('client_secret')
        if not client_id or not client_secret:
            return _json_response(
                {'error': 'client_id and client_secret are required'}, status=400
            )

        Client = request.env['elegomotors.finance.api.client'].sudo()
        client = Client._verify_credentials(client_id, client_secret)
        if not client:
            return _json_response({'error': 'invalid_client'}, status=401)

        token, ttl = Client.issue_token(client_id)
        return _json_response({
            'access_token': token,
            'token_type': 'Bearer',
            'expires_in': ttl,
        })

    @http.route(
        '/elegomotors/finance/validate-serial', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def validate_serial(self, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response

        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        material_code = (body.get('materialCode') or '').strip()
        serial_number = (body.get('serialNumber') or '').strip()
        dealer_code = (body.get('dealerCode') or '').strip()

        status, message = self._validate(material_code, serial_number, dealer_code)

        request.env['elegomotors.finance.api.log'].sudo().create({
            'client_id': client.client_id,
            'material_code': material_code,
            'serial_number': serial_number,
            'dealer_code': dealer_code,
            'response_status': status,
            'response_message': message,
        })
        return _json_response({'responseStatus': status, 'responseMessage': message})

    def _validate(self, material_code, serial_number, dealer_code):
        """Check order (BFL doesn't mandate one — see the plan doc for the
        reasoning): serial exists -> material code known/matches -> not
        already validated -> dealer code known -> serial billed to that
        dealer -> valid."""
        env = request.env
        Lot = env['stock.lot'].sudo()

        lot = Lot.search([('name', '=', serial_number)], limit=1)
        if not lot:
            return '-1', 'Invalid Serial Number'

        template = env['product.template'].sudo().search(
            [('x_material_code', '=', material_code)], limit=1
        )
        if not template:
            return '-4', 'Invalid Material code'
        if lot.product_id.product_tmpl_id != template:
            return '-2', 'Mismatch in model and serial number.'

        if lot.x_bfl_validated:
            return '-3', 'Serial Number Already Validated'

        dealer = env['res.partner'].sudo().search(
            [('x_dealer_code', '=', dealer_code)], limit=1
        )
        if not dealer:
            return '-5', 'Dealer Code INVALID'

        if not lot.x_dealer_id or lot.x_dealer_id != dealer:
            return '-6', 'Serial Number is not billed to this Dealer'

        lot.write({
            'x_bfl_validated': True,
            'x_bfl_validated_date': fields.Datetime.now(),
        })
        return '0', 'Valid Serial Number'
