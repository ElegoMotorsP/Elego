# -*- coding: utf-8 -*-
"""External API for the (separately-built) customer/dealer app: register a
bike's warranty, check status, file a claim, track a claim, and pull a
warranty certificate PDF. Same bearer-token contract as the Bajaj Finance
API (controllers/finance_api.py) — business-logic outcomes return HTTP 200
with an error field in the body; only transport/auth failures use real
HTTP error codes.
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


def _require_bearer_token():
    auth_header = request.httprequest.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, _json_response({'error': 'missing_bearer_token'}, status=401)
    token = auth_header[len('Bearer '):].strip()
    client = request.env['elegomotors.warranty.api.client'].sudo().verify_token(token)
    if not client:
        return None, _json_response({'error': 'invalid_or_expired_token'}, status=401)
    return client, None


def _registration_payload(reg):
    return {
        'component': reg.component,
        'batteryType': reg.battery_type or None,
        'componentSerial': reg.component_serial or None,
        'startDate': reg.start_date.isoformat() if reg.start_date else None,
        'endDate': reg.end_date.isoformat() if reg.end_date else None,
        'durationMonths': reg.duration_months,
        'cycleLimit': reg.cycle_limit or None,
        'daysRemaining': reg.days_remaining,
        'status': reg.warranty_status,
    }


def _log(client_id, endpoint, chassis_number, summary):
    request.env['elegomotors.warranty.api.log'].sudo().create({
        'client_id': client_id,
        'endpoint': endpoint,
        'chassis_number': chassis_number,
        'response_summary': summary,
    })


class WarrantyApiController(http.Controller):

    @http.route(
        '/elegomotors/warranty/token', type='http', auth='public',
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

        Client = request.env['elegomotors.warranty.api.client'].sudo()
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
        '/elegomotors/warranty/register', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def register(self, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        chassis_number = (body.get('chassisNumber') or '').strip()
        dealer_code = (body.get('dealerCode') or '').strip()
        invoice_number = (body.get('invoiceNumber') or '').strip()
        invoice_date = (body.get('invoiceDate') or '').strip()
        customer_name = (body.get('customerName') or '').strip()
        customer_mobile = (body.get('customerMobile') or '').strip()

        missing = [
            name for name, val in [
                ('chassisNumber', chassis_number), ('dealerCode', dealer_code),
                ('invoiceNumber', invoice_number), ('invoiceDate', invoice_date),
                ('customerName', customer_name), ('customerMobile', customer_mobile),
            ] if not val
        ]
        if missing:
            resp = {'error': 'missing_fields', 'fields': missing}
            _log(client.client_id, 'register', chassis_number, 'missing_fields')
            return _json_response(resp, status=400)

        env = request.env
        lot = env['stock.lot'].sudo().search([('name', '=', chassis_number)], limit=1)
        if not lot:
            _log(client.client_id, 'register', chassis_number, 'invalid_chassis_number')
            return _json_response({'error': 'invalid_chassis_number'})

        dealer = env['res.partner'].sudo().search(
            [('x_dealer_code', '=', dealer_code)], limit=1
        )
        if not dealer:
            _log(client.client_id, 'register', chassis_number, 'invalid_dealer_code')
            return _json_response({'error': 'invalid_dealer_code'})

        existing = env['elegomotors.warranty.registration'].sudo().search(
            [('chassis_number', '=', chassis_number)], limit=1
        )
        if existing:
            _log(client.client_id, 'register', chassis_number, 'already_registered')
            return _json_response({'error': 'already_registered'})

        registrations = env['elegomotors.warranty.registration'].sudo()._register_bike(
            lot, dealer, customer_name, customer_mobile, invoice_number, invoice_date,
        )
        _log(client.client_id, 'register', chassis_number, f'{len(registrations)} components registered')
        return _json_response({
            'chassisNumber': chassis_number,
            'registrations': [_registration_payload(r) for r in registrations],
        })

    @http.route(
        '/elegomotors/warranty/status', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def status(self, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        chassis_number = (body.get('chassisNumber') or '').strip()
        if not chassis_number:
            return _json_response({'error': 'chassisNumber is required'}, status=400)

        registrations = request.env['elegomotors.warranty.registration'].sudo().search(
            [('chassis_number', '=', chassis_number)]
        )
        _log(client.client_id, 'status', chassis_number, f'{len(registrations)} found')
        if not registrations:
            return _json_response({'error': 'not_registered'})
        return _json_response({
            'chassisNumber': chassis_number,
            'registrations': [_registration_payload(r) for r in registrations],
        })

    @http.route(
        '/elegomotors/warranty/claims', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def file_claim(self, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        chassis_number = (body.get('chassisNumber') or '').strip()
        component = (body.get('component') or '').strip()
        claim_type = (body.get('claimType') or '').strip()
        repair_location = (body.get('repairLocation') or '').strip()
        reason = (body.get('reason') or '').strip()

        missing = [
            name for name, val in [
                ('chassisNumber', chassis_number), ('component', component),
                ('claimType', claim_type), ('repairLocation', repair_location),
                ('reason', reason),
            ] if not val
        ]
        if missing:
            return _json_response({'error': 'missing_fields', 'fields': missing}, status=400)

        registration = request.env['elegomotors.warranty.registration'].sudo().search([
            ('chassis_number', '=', chassis_number),
            ('component', '=', component),
            ('state', '=', 'active'),
        ], limit=1)
        if not registration:
            _log(client.client_id, 'claims', chassis_number, 'no_active_registration')
            return _json_response({'error': 'no_active_registration_for_component'})

        claim = request.env['elegomotors.warranty.claim'].sudo().create({
            'registration_id': registration.id,
            'faulty_part_name': body.get('faultyPartName') or component,
            'faulty_part_serial': body.get('faultyPartSerial'),
            'faulty_part_photo': body.get('photoBase64'),
            'reason': reason,
            'reported_usage': body.get('reportedUsage') or 0,
            'claim_type': claim_type,
            'repair_location': repair_location,
            'state': 'submitted',
        })
        _log(client.client_id, 'claims', chassis_number, claim.claim_number)
        return _json_response({'claimNumber': claim.claim_number, 'status': claim.state})

    @http.route(
        '/elegomotors/warranty/claims/<string:claim_number>', type='http', auth='public',
        methods=['GET'], csrf=False,
    )
    def claim_status(self, claim_number, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response

        claim = request.env['elegomotors.warranty.claim'].sudo().search(
            [('claim_number', '=', claim_number)], limit=1
        )
        _log(client.client_id, 'claims/status', claim.chassis_number if claim else '', claim_number)
        if not claim:
            return _json_response({'error': 'claim_not_found'})
        return _json_response({
            'claimNumber': claim.claim_number,
            'status': claim.state,
            'claimType': claim.claim_type,
            'faultyPartName': claim.faulty_part_name,
            'reason': claim.reason,
            'rejectionReason': claim.rejection_reason or None,
        })

    @http.route(
        '/elegomotors/warranty/certificate', type='http', auth='public',
        methods=['GET'], csrf=False,
    )
    def certificate(self, chassis_number=None, **kwargs):
        client, error_response = _require_bearer_token()
        if error_response:
            return error_response
        if not chassis_number:
            return _json_response({'error': 'chassis_number is required'}, status=400)

        registrations = request.env['elegomotors.warranty.registration'].sudo().search(
            [('chassis_number', '=', chassis_number), ('state', '=', 'active')]
        )
        _log(client.client_id, 'certificate', chassis_number, f'{len(registrations)} active')
        if not registrations:
            return _json_response({'error': 'no_active_warranty_for_chassis'})

        pdf_content, _ = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'elegomotors_setup.report_warranty_certificate', registrations.ids,
        )
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="Warranty_Certificate_{chassis_number}.pdf"'),
            ('Content-Length', str(len(pdf_content))),
        ]
        return request.make_response(pdf_content, headers=headers)
