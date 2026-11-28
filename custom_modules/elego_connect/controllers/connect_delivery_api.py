# -*- coding: utf-8 -*-
"""Delivery-time estimates for the Elego Connect PO builder
(doc/delivery-estimate-api-plan.md §4).

  GET  /elegomotors/connect/delivery-estimates                 one row per bike model
  POST /elegomotors/connect/delivery-estimates/quote           a whole cart
  GET  /elegomotors/connect/orders/<id>/delivery-estimate      an existing SO

Same bearer-token contract as the rest of this module. Dealers get dates plus
a coarse limitingFactor only — never component, supplier, PO or SO names.

Debug trace (§4.3): returned only when the system parameter
elego_connect.delivery_estimate_debug is on AND the request asks for it
(?debug=1 on a GET, "debug": true in the POST body). With the parameter
off, the debug flag is ignored and the response is the normal one.

Every call logs its compute time (ms) in the request-log summary, so
response time can be watched without extra tooling.
"""
import time

from odoo import http
from odoo.http import request

from .connect_auth import (
    _json_response, _parse_json_body, log_connect_call, require_connect_bearer_token,
)

_TRUE = ('1', 'true', 'yes', 'on')


def _flag(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in _TRUE


def _query_debug():
    # Read from the raw query string: Odoo also interprets ?debug= (web debug
    # mode), so don't rely on it reaching the route kwargs.
    return _flag(request.httprequest.args.get('debug'))


def _summary(result, debug, started):
    rate = result.get('rate') or {}
    used = rate.get('used')
    text = f"rate {used if used is not None else 'none'}/day ({rate.get('source')}"
    if rate.get('anomaly'):
        text += f", anomaly={rate['anomaly']}"
    text += f'); {int((time.monotonic() - started) * 1000)} ms'
    if debug:
        text += ' debug=1'
    return text


def _estimator():
    return request.env['elegomotors.delivery.estimator'].sudo()


class ConnectDeliveryApiController(http.Controller):

    @http.route(
        '/elegomotors/connect/delivery-estimates', type='http', auth='public',
        methods=['GET'], csrf=False,
    )
    def delivery_estimates(self, **kwargs):
        started = time.monotonic()
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response

        Estimator = _estimator()
        debug = _query_debug() and Estimator.debug_enabled()
        result, tracer = Estimator.estimate_catalogue(debug=debug)

        payload = {
            'asOf': Estimator.now_local().isoformat(timespec='seconds'),
            'items': result['items'],
        }
        if tracer:
            payload['debug'] = tracer.as_dict()
        log_connect_call(client.client_id, 'delivery-estimates', '',
                         f"{len(result['items'])} models; " + _summary(result, debug, started))
        return _json_response(payload)

    @http.route(
        '/elegomotors/connect/delivery-estimates/quote', type='http', auth='public',
        methods=['POST'], csrf=False,
    )
    def delivery_quote(self, **kwargs):
        started = time.monotonic()
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response
        body, error_response = _parse_json_body()
        if error_response:
            return error_response

        raw_lines = body.get('lines') if isinstance(body, dict) else None
        if not isinstance(raw_lines, list) or not raw_lines:
            return _json_response(
                {'error': 'invalid_request', 'error_description': 'lines must be a non-empty list'},
                status=400)
        lines = []
        for raw in raw_lines:
            try:
                lines.append((int(raw['odooProductId']), float(raw['quantity'])))
            except (KeyError, TypeError, ValueError):
                return _json_response(
                    {'error': 'invalid_request',
                     'error_description': 'each line needs integer odooProductId and numeric quantity'},
                    status=400)

        Estimator = _estimator()
        debug = _flag(body.get('debug')) and Estimator.debug_enabled()
        result, tracer = Estimator.estimate_cart(lines, debug=debug)

        payload = {
            'asOf': Estimator.now_local().isoformat(timespec='seconds'),
            'models': result['models'],
            'lines': result['lines'],
            'orderCompleteDate': result['orderCompleteDate'],
        }
        if result['errors']:
            payload['errors'] = result['errors']
        if tracer:
            payload['debug'] = tracer.as_dict()
        ref = ','.join(f'{pid}x{int(qty)}' for pid, qty in lines)[:200]
        log_connect_call(client.client_id, 'delivery-estimates/quote', ref,
                         f"{len(result['models'])} models; " + _summary(result, debug, started))
        return _json_response(payload)

    @http.route(
        '/elegomotors/connect/orders/<int:odoo_sale_order_id>/delivery-estimate', type='http',
        auth='public', methods=['GET'], csrf=False,
    )
    def order_delivery_estimate(self, odoo_sale_order_id, **kwargs):
        """Live estimate for an existing SO. Approved orders (inQueue true) get
        the dates of their own place in the production queue; orders still
        waiting for approval are quoted at the back of the queue."""
        started = time.monotonic()
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response

        order = request.env['sale.order'].sudo().browse(odoo_sale_order_id)
        if not order.exists():
            log_connect_call(client.client_id, 'orders/delivery-estimate',
                             str(odoo_sale_order_id), 'order_not_found')
            return _json_response({'error': 'order_not_found'})
        if order.state == 'cancel':
            log_connect_call(client.client_id, 'orders/delivery-estimate', order.name, 'order_cancelled')
            return _json_response({'error': 'order_cancelled'})

        Estimator = _estimator()
        debug = _query_debug() and Estimator.debug_enabled()
        result, tracer = Estimator.estimate_order(order, debug=debug)
        status = order.connect_status_payload()

        payload = {
            'asOf': Estimator.now_local().isoformat(timespec='seconds'),
            'odooSaleOrderId': order.id,
            'odooSaleOrderName': order.name,
            'inQueue': result['inQueue'],
            'outstanding': result['outstanding'],
            'commitmentDate': status['commitmentDate'],
            'models': result['models'],
            'lines': result['lines'],
            'orderCompleteDate': result['orderCompleteDate'],
        }
        if tracer:
            payload['debug'] = tracer.as_dict()
        log_connect_call(client.client_id, 'orders/delivery-estimate', order.name,
                         f"inQueue={result['inQueue']}; " + _summary(result, debug, started))
        return _json_response(payload)
