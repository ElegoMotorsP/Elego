# -*- coding: utf-8 -*-
"""Elego Connect API client — one shared, scoped bearer-token credential for
everything the Elego Connect app's own backend (a separate Node/NestJS
service, not Odoo) writes to Odoo: dealer provisioning on HQ approval, and
(in the future) order/payment/dealer-stock writes as those modules land.

Deliberately a SEPARATE credential from elegomotors.warranty.api.client and
elegomotors.finance.api.client — see the Elego Connect app's own
docs/02-odoo-integration.md §2.2: those two are scoped to unrelated external
partners (a warranty app, Bajaj Finance); this one is scoped to Elego
Connect's own backend, which is one calling service across many domains, so
one shared credential per environment (dev/staging/prod) is enough — not one
per new feature.

Same stateless HMAC bearer-token design as the Warranty/Finance APIs
(models/warranty.py, models/finance_api.py in elegomotors_setup) —
intentionally NOT importing/reusing that code across modules (same reasoning
warranty.py itself gives for not sharing with finance_api.py: avoids coupling
unrelated integrations through shared internals for ~60 lines of crypto glue).
"""
import hashlib
import hmac
import secrets
import time
import base64
import json

from odoo import api, fields, models

TOKEN_TTL_SECONDS = 3600
_PBKDF2_ITERATIONS = 100_000
_TOKEN_SECRET_PARAM = 'elego_connect.api_token_secret'


class ConnectApiClient(models.Model):
    _name = 'elegomotors.connect.api.client'
    _description = 'Elego Connect API Client'
    _rec_name = 'name'

    name = fields.Char(required=True, help='e.g. "Elego Connect Backend - Production"')
    client_id = fields.Char(readonly=True, copy=False, index=True)
    client_secret_salt = fields.Char(readonly=True, copy=False)
    client_secret_hash = fields.Char(readonly=True, copy=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('client_id_unique', 'unique(client_id)', 'Client ID must be unique.'),
    ]

    def action_generate_credentials(self):
        self.ensure_one()
        client_id = 'conn_' + secrets.token_hex(8)
        client_secret = secrets.token_urlsafe(32)
        salt = secrets.token_hex(16)
        self.write({
            'client_id': client_id,
            'client_secret_salt': salt,
            'client_secret_hash': self._hash_secret(client_secret, salt),
        })
        wizard = self.env['elegomotors.connect.api.client.secret.wizard'].create({
            'client_id': client_id,
            'client_secret': client_secret,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'New API Credentials — copy the secret now, it will not be shown again',
            'res_model': 'elegomotors.connect.api.client.secret.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def _hash_secret(self, secret, salt):
        return hashlib.pbkdf2_hmac(
            'sha256', secret.encode(), salt.encode(), _PBKDF2_ITERATIONS
        ).hex()

    @api.model
    def _verify_credentials(self, client_id, client_secret):
        client = self.sudo().search(
            [('client_id', '=', client_id), ('active', '=', True)], limit=1
        )
        if not client or not client.client_secret_hash:
            return self.browse()
        expected = self._hash_secret(client_secret, client.client_secret_salt)
        if hmac.compare_digest(expected, client.client_secret_hash):
            return client
        return self.browse()

    @api.model
    def _token_secret(self):
        param = self.env['ir.config_parameter'].sudo()
        key = param.get_param(_TOKEN_SECRET_PARAM)
        if not key:
            key = secrets.token_hex(32)
            param.set_param(_TOKEN_SECRET_PARAM, key)
        return key

    @api.model
    def issue_token(self, client_id):
        payload = json.dumps({'cid': client_id, 'exp': int(time.time()) + TOKEN_TTL_SECONDS})
        payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')
        signature = hmac.new(
            self._token_secret().encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        return f'{payload_b64}.{signature}', TOKEN_TTL_SECONDS

    @api.model
    def verify_token(self, token):
        try:
            payload_b64, signature = (token or '').split('.', 1)
        except ValueError:
            return self.browse()
        expected_sig = hmac.new(
            self._token_secret().encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return self.browse()
        padded = payload_b64 + '=' * (-len(payload_b64) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        except (ValueError, TypeError):
            return self.browse()
        if payload.get('exp', 0) < time.time():
            return self.browse()
        return self.sudo().search(
            [('client_id', '=', payload.get('cid')), ('active', '=', True)], limit=1
        )


class ConnectApiClientSecretWizard(models.TransientModel):
    _name = 'elegomotors.connect.api.client.secret.wizard'
    _description = 'Elego Connect API Client — New Credentials'

    client_id = fields.Char(readonly=True)
    client_secret = fields.Char(readonly=True)


class ConnectApiLog(models.Model):
    _name = 'elegomotors.connect.api.log'
    _description = 'Elego Connect API Request Log'
    _order = 'create_date desc'

    client_id = fields.Char(readonly=True)
    endpoint = fields.Char(readonly=True)
    entity_ref = fields.Char(readonly=True, help='e.g. dealer code, PO number — whatever this call concerned')
    response_summary = fields.Char(readonly=True)
