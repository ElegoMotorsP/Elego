# -*- coding: utf-8 -*-
"""Credentials, bearer tokens, and the request log for the Bajaj Finance
(BFL) serial-validation API — see controllers/finance_api.py for the actual
HTTP endpoints that use this.

Tokens are stateless HMAC-signed strings (client_id + expiry, signed with a
server secret in ir.config_parameter), not a DB-backed token table — nothing
to store or clean up per issuance, and no extra dependency beyond the stdlib.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from odoo import api, fields, models

TOKEN_TTL_SECONDS = 3600
_PBKDF2_ITERATIONS = 100_000
_TOKEN_SECRET_PARAM = 'elegomotors_setup.finance_api_token_secret'


class FinanceApiClient(models.Model):
    _name = 'elegomotors.finance.api.client'
    _description = 'Finance Partner API Client (e.g. Bajaj Finance serial validation)'
    _rec_name = 'name'

    name = fields.Char(
        required=True,
        help='e.g. "Bajaj Finance - UAT" / "Bajaj Finance - Production" — one '
             'record per environment, since each gets its own credentials.',
    )
    client_id = fields.Char(readonly=True, copy=False, index=True)
    client_secret_salt = fields.Char(readonly=True, copy=False)
    client_secret_hash = fields.Char(readonly=True, copy=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('client_id_unique', 'unique(client_id)', 'Client ID must be unique.'),
    ]

    def action_generate_credentials(self):
        """(Re)generate this client's id/secret. Only the salted hash is
        ever stored — the plaintext secret is shown exactly once, via the
        wizard this opens, and cannot be recovered afterwards (only reset)."""
        self.ensure_one()
        client_id = 'bfl_' + secrets.token_hex(8)
        client_secret = secrets.token_urlsafe(32)
        salt = secrets.token_hex(16)
        self.write({
            'client_id': client_id,
            'client_secret_salt': salt,
            'client_secret_hash': self._hash_secret(client_secret, salt),
        })
        wizard = self.env['elegomotors.finance.api.client.secret.wizard'].create({
            'client_id': client_id,
            'client_secret': client_secret,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'New API Credentials — copy the secret now, it will not be shown again',
            'res_model': 'elegomotors.finance.api.client.secret.wizard',
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
        """Return the matching active client record, or an empty recordset."""
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
        """Server-wide HMAC signing key for bearer tokens, generated once
        on first use and reused after that."""
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
        """Return the active client record the token was issued to, or an
        empty recordset if the token is missing, malformed, forged, expired,
        or its client has since been deactivated."""
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


class FinanceApiClientSecretWizard(models.TransientModel):
    _name = 'elegomotors.finance.api.client.secret.wizard'
    _description = 'One-time display of a freshly generated Finance API client secret'

    client_id = fields.Char(readonly=True)
    client_secret = fields.Char(readonly=True)


class FinanceApiLog(models.Model):
    _name = 'elegomotors.finance.api.log'
    _description = 'Finance API Request Log'
    _order = 'create_date desc'
    _rec_name = 'serial_number'

    client_id = fields.Char(readonly=True)
    material_code = fields.Char(readonly=True)
    serial_number = fields.Char(readonly=True, index=True)
    dealer_code = fields.Char(readonly=True)
    response_status = fields.Char(readonly=True)
    response_message = fields.Char(readonly=True)
