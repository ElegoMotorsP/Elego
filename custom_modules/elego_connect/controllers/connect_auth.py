# -*- coding: utf-8 -*-
"""Token issuance for the Elego Connect app's own backend — same
bearer-token contract as the Warranty/Finance APIs (see
controllers/warranty_api.py in elegomotors_setup for the pattern this
mirrors exactly): business-logic outcomes return HTTP 200 with an error
field in the body; only transport/auth failures use real HTTP error codes.
"""
import json

from odoo import http
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


def require_connect_bearer_token():
    """Shared by every controller in this module — returns (client, None)
    on success, or (None, error_response)."""
    auth_header = request.httprequest.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, _json_response({'error': 'missing_bearer_token'}, status=401)
    token = auth_header[len('Bearer '):].strip()
    client = request.env['elegomotors.connect.api.client'].sudo().verify_token(token)
    if not client:
        return None, _json_response({'error': 'invalid_or_expired_token'}, status=401)
    return client, None


def log_connect_call(client_id, endpoint, entity_ref, summary):
    request.env['elegomotors.connect.api.log'].sudo().create({
        'client_id': client_id,
        'endpoint': endpoint,
        'entity_ref': entity_ref,
        'response_summary': summary,
    })


class ConnectAuthController(http.Controller):

    @http.route(
        '/elegomotors/connect/token', type='http', auth='public',
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

        Client = request.env['elegomotors.connect.api.client'].sudo()
        client = Client._verify_credentials(client_id, client_secret)
        if not client:
            return _json_response({'error': 'invalid_client'}, status=401)

        token, ttl = Client.issue_token(client_id)
        return _json_response({
            'access_token': token,
            'token_type': 'Bearer',
            'expires_in': ttl,
        })
