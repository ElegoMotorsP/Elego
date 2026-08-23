# -*- coding: utf-8 -*-
"""The two new warranty endpoints Elego Connect's claim-detail screen needs
(docs/09-module-warranty.md §9.2 in the app's own design repo) — dispatch
tracking and failed-part disposition. Added here rather than editing
elegomotors_setup/controllers/warranty_api.py directly, so that already-
shipped file stays untouched; this reuses its exact bearer-token helpers
(same elegomotors.warranty.api.client credential — no new credential needed
for these two, since they're just filling out the existing Warranty API's
own surface, not a new integration).
"""
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.elegomotors_setup.controllers.warranty_api import (
    _json_response,
    _parse_json_body,
    _require_bearer_token,
    _log,
)


class ConnectWarrantyApiExtension(http.Controller):

    @http.route(
        '/elegomotors/warranty/claims/<string:claim_number>/dispatch', type='http',
        auth='public', methods=['POST'], csrf=False,
    )
    def dispatch_claim(self, claim_number, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        claim = request.env['elegomotors.warranty.claim'].sudo().search(
            [('claim_number', '=', claim_number)], limit=1
        )
        if not claim:
            _log(client.client_id, 'claims/dispatch', '', 'claim_not_found')
            return _json_response({'error': 'claim_not_found'})

        try:
            claim.action_mark_dispatched({
                'item': body.get('item'),
                'serial': body.get('serial'),
                'qty': body.get('qty'),
                'challan_number': body.get('challanNumber'),
                'transporter': body.get('transporter'),
                'lr_awb_number': body.get('lrAwbNumber'),
                'dispatch_date': body.get('dispatchDate'),
                'expected_delivery_date': body.get('expectedDeliveryDate'),
            })
        except UserError as e:
            _log(client.client_id, 'claims/dispatch', claim.chassis_number, f'invalid_state: {e}')
            return _json_response({'error': 'invalid_state', 'message': str(e)})

        _log(client.client_id, 'claims/dispatch', claim.chassis_number, claim.state)
        return _json_response({'claimNumber': claim.claim_number, 'status': claim.state})

    @http.route(
        '/elegomotors/warranty/claims/<string:claim_number>/acknowledge-receipt', type='http',
        auth='public', methods=['POST'], csrf=False,
    )
    def acknowledge_receipt(self, claim_number, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response

        claim = request.env['elegomotors.warranty.claim'].sudo().search(
            [('claim_number', '=', claim_number)], limit=1
        )
        if not claim:
            _log(client.client_id, 'claims/acknowledge-receipt', '', 'claim_not_found')
            return _json_response({'error': 'claim_not_found'})

        try:
            claim.action_confirm_delivery()
        except UserError as e:
            _log(client.client_id, 'claims/acknowledge-receipt', claim.chassis_number, f'invalid_state: {e}')
            return _json_response({'error': 'invalid_state', 'message': str(e)})

        _log(client.client_id, 'claims/acknowledge-receipt', claim.chassis_number, claim.state)
        return _json_response({'claimNumber': claim.claim_number, 'status': claim.state})

    @http.route(
        '/elegomotors/warranty/claims/<string:claim_number>/failed-part-action', type='http',
        auth='public', methods=['POST'], csrf=False,
    )
    def failed_part_action(self, claim_number, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        action = (body.get('action') or '').strip()
        if action not in ('return', 'scrap', 'retain'):
            return _json_response(
                {'error': 'missing_or_invalid_fields', 'fields': ['action']}, status=400
            )

        claim = request.env['elegomotors.warranty.claim'].sudo().search(
            [('claim_number', '=', claim_number)], limit=1
        )
        if not claim:
            _log(client.client_id, 'claims/failed-part-action', '', 'claim_not_found')
            return _json_response({'error': 'claim_not_found'})

        try:
            claim.action_record_failed_part_action(action, body.get('evidencePhotoBase64'))
        except UserError as e:
            _log(client.client_id, 'claims/failed-part-action', claim.chassis_number, f'invalid_state: {e}')
            return _json_response({'error': 'invalid_state', 'message': str(e)})

        _log(client.client_id, 'claims/failed-part-action', claim.chassis_number, claim.state)
        return _json_response({'claimNumber': claim.claim_number, 'status': claim.state})
