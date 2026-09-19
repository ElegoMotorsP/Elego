# -*- coding: utf-8 -*-
"""New warranty endpoints Elego Connect needs (docs/09-module-warranty.md
§9.2 in the app's own design repo) — dispatch tracking, failed-part
disposition, and chassis-number resolution. Added here rather than editing
elegomotors_setup/controllers/warranty_api.py directly, so that already-
shipped file stays untouched; this reuses its exact bearer-token helpers
(same elegomotors.warranty.api.client credential — no new credential needed
for these, since they're just filling out the existing Warranty API's own
surface, not a new integration).
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

    # elegomotors_setup's register/status/claims/certificate all key
    # "chassis number" off stock.lot.name — an internal auto-generated
    # bike serial (e.g. "EGO-S1-2503-0001"), NOT x_chassis_serial, the
    # field literally labeled "Chassis No. (Frame Plate)" that a dealer/
    # customer actually reads off the bike and types in (bike_traceability.py
    # uses x_chassis_serial for exactly that reason). Found live 2026-09-01:
    # a real VIN a dealer typed in correctly returned invalid_chassis_number
    # because it was being matched against the wrong field. Rather than
    # change what elegomotors_setup stores/searches (real risk to whatever
    # already depends on chassis_number = lot.name — BFL finance validation,
    # existing registrations, reports), this resolves either identifier to
    # the canonical lot.name *before* any existing endpoint ever sees it —
    # every one of them keeps working exactly as before, on the identifier
    # they've always expected.
    @http.route(
        '/elegomotors/warranty/resolve-chassis', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def resolve_chassis(self, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        identifier = (body.get('chassisNumber') or '').strip()
        if not identifier:
            return _json_response({'error': 'chassisNumber is required'}, status=400)

        Lot = request.env['stock.lot'].sudo()
        lot = Lot.search([('name', '=', identifier)], limit=1)
        if not lot:
            lot = Lot.search([('x_chassis_serial', '=', identifier)], limit=1)
        if not lot:
            _log(client.client_id, 'resolve-chassis', identifier, 'not_found')
            return _json_response({'error': 'not_found'})

        _log(client.client_id, 'resolve-chassis', identifier, lot.name)
        return _json_response({'chassisNumber': lot.name})

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

    # --- Approve / Reject — Elego Connect HQ app, 2026-09-08 -------------
    # Previously deliberately manual-only (needs a real Warranty Manager
    # user — see _get_warranty_approver's comment for exactly why `sudo()`
    # alone was never enough). `actorLabel` is the real HQ user who
    # actually clicked Approve/Reject in the app — posted as a chatter
    # note so Odoo's own audit trail stays honest about who really
    # requested it, even though the state change itself is attributed to
    # the dedicated Elego Connect approver identity. Elego Connect's own
    # backend additionally writes its own AuditLog row for this (see
    # api/src/warranty/warranty.service.ts) — the real human-accountable
    # record now lives on both sides, not lost.
    @http.route(
        '/elegomotors/warranty/claims/<string:claim_number>/approve', type='http',
        auth='public', methods=['POST'], csrf=False,
    )
    def approve_claim(self, claim_number, **kwargs):
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
            _log(client.client_id, 'claims/approve', '', 'claim_not_found')
            return _json_response({'error': 'claim_not_found'})

        actor_label = (body.get('actorLabel') or '').strip()
        try:
            claim.with_context(elego_connect_trusted_api=True).action_approve()
            if actor_label:
                claim.message_post(
                    body=f'(Requested via Elego Connect by {actor_label})',
                    message_type='comment', subtype_xmlid='mail.mt_comment',
                )
        except UserError as e:
            _log(client.client_id, 'claims/approve', claim.chassis_number, f'invalid_state: {e}')
            return _json_response({'error': 'invalid_state', 'message': str(e)})

        _log(client.client_id, 'claims/approve', claim.chassis_number, claim.state)
        return _json_response({'claimNumber': claim.claim_number, 'status': claim.state})

    @http.route(
        '/elegomotors/warranty/claims/<string:claim_number>/reject', type='http',
        auth='public', methods=['POST'], csrf=False,
    )
    def reject_claim(self, claim_number, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        reason = (body.get('reason') or '').strip()
        if not reason:
            return _json_response(
                {'error': 'missing_or_invalid_fields', 'fields': ['reason']}, status=400
            )

        claim = request.env['elegomotors.warranty.claim'].sudo().search(
            [('claim_number', '=', claim_number)], limit=1
        )
        if not claim:
            _log(client.client_id, 'claims/reject', '', 'claim_not_found')
            return _json_response({'error': 'claim_not_found'})

        actor_label = (body.get('actorLabel') or '').strip()
        try:
            wizard = request.env['elegomotors.warranty.claim.reject.wizard'].sudo().with_context(
                elego_connect_trusted_api=True
            ).create({
                'claim_id': claim.id,
                'reason': reason,
            })
            wizard.with_context(elego_connect_trusted_api=True).action_confirm()
            if actor_label:
                claim.message_post(
                    body=f'(Requested via Elego Connect by {actor_label})',
                    message_type='comment', subtype_xmlid='mail.mt_comment',
                )
        except UserError as e:
            _log(client.client_id, 'claims/reject', claim.chassis_number, f'invalid_state: {e}')
            return _json_response({'error': 'invalid_state', 'message': str(e)})

        _log(client.client_id, 'claims/reject', claim.chassis_number, claim.state)
        return _json_response({'claimNumber': claim.claim_number, 'status': claim.state})
