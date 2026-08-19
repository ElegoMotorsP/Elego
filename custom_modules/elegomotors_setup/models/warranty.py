# -*- coding: utf-8 -*-
"""Warranty module: admin-configurable policy, a per-component warranty
ledger, and a claims approval workflow (dealer -> Elego HQ), plus the
external API the separate customer/dealer app talks to.

The one rule that shapes the data model: a component replaced under
warranty inherits the REMAINING time of the original, not a fresh
warranty period. That's why registrations are their own ledger (with a
previous_registration_id chain) rather than fields on stock.lot.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from dateutil.relativedelta import relativedelta
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression

TOKEN_TTL_SECONDS = 3600
_PBKDF2_ITERATIONS = 100_000
_TOKEN_SECRET_PARAM = 'elegomotors_setup.warranty_api_token_secret'

COMPONENT_SELECTION = [
    ('motor', 'Motor'),
    ('controller', 'Controller'),
    ('charger', 'Charger'),
    ('battery', 'Battery'),
]
BATTERY_TYPE_SELECTION = [
    ('lead', 'Lead-acid'),
    ('lithium', 'Lithium'),
]


class WarrantyPolicyRule(models.Model):
    _name = 'elegomotors.warranty.policy.rule'
    _description = 'Warranty Policy Rule'
    _rec_name = 'display_name'

    component = fields.Selection(COMPONENT_SELECTION, required=True)
    context = fields.Selection([
        ('bundled', 'Bundled with bike'),
        ('standalone', 'Standalone / replacement purchase'),
    ], required=True, default='bundled')
    battery_type = fields.Selection(
        BATTERY_TYPE_SELECTION,
        help='Only relevant when Component = Battery.',
    )
    duration_months = fields.Integer(required=True)
    cycle_limit = fields.Integer(
        help='Charge-cycle cap (battery only). Warranty voids once this is '
             'exceeded, whichever comes first with the time limit. Checked '
             'manually at claim time, not tracked live. 0 = no cycle limit.',
    )
    water_damage_covered = fields.Boolean(
        help='Whether water-damage (IP67) claims are covered for this '
             'component. Not all motor/battery variants are water-rated.',
    )
    active = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name')

    @api.depends('component', 'context', 'battery_type', 'duration_months')
    def _compute_display_name(self):
        for rec in self:
            parts = [dict(COMPONENT_SELECTION).get(rec.component, '')]
            if rec.battery_type:
                parts.append(dict(BATTERY_TYPE_SELECTION).get(rec.battery_type, ''))
            parts.append(dict(rec._fields['context'].selection).get(rec.context, ''))
            if rec.duration_months:
                parts.append(f'{rec.duration_months}mo')
            rec.display_name = ' — '.join(p for p in parts if p)

    @api.constrains('component', 'context', 'battery_type', 'active')
    def _check_unique_active_rule(self):
        for rec in self:
            if not rec.active:
                continue
            domain = [
                ('id', '!=', rec.id), ('active', '=', True),
                ('component', '=', rec.component), ('context', '=', rec.context),
                ('battery_type', '=', rec.battery_type),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    f'An active policy rule already exists for {rec.display_name}.'
                )

    @api.model
    def _find_rule(self, component, context, battery_type=False):
        domain = [
            ('component', '=', component), ('context', '=', context),
            ('active', '=', True),
        ]
        if component == 'battery':
            domain.append(('battery_type', '=', battery_type))
        return self.search(domain, limit=1)


class WarrantyRegistration(models.Model):
    _name = 'elegomotors.warranty.registration'
    _description = 'Warranty Registration'
    _order = 'end_date desc'
    _rec_name = 'display_name'

    bike_lot_id = fields.Many2one('stock.lot', required=True, ondelete='restrict', index=True)
    component = fields.Selection(COMPONENT_SELECTION, required=True)
    battery_type = fields.Selection(BATTERY_TYPE_SELECTION)
    component_serial = fields.Char()

    dealer_id = fields.Many2one('res.partner', required=True)
    customer_name = fields.Char(required=True)
    customer_mobile = fields.Char(required=True)
    chassis_number = fields.Char(
        required=True, index=True,
        help="The bike's own serial number (stock.lot name).",
    )
    invoice_number = fields.Char(required=True, string="Dealer's Retail Invoice No.")
    invoice_date = fields.Date(required=True, string="Dealer's Retail Invoice Date")

    start_date = fields.Date(required=True, copy=False)
    duration_months = fields.Integer(
        required=True, copy=False,
        help='Snapshotted from the matching policy rule at registration time — '
             'a later change to the policy rule does not retroactively change '
             'warranties already registered under the old value.',
    )
    cycle_limit = fields.Integer(copy=False)
    water_damage_covered = fields.Boolean(copy=False)
    end_date = fields.Date(compute='_compute_end_date', store=True)
    days_remaining = fields.Integer(compute='_compute_days_remaining')

    state = fields.Selection([
        ('active', 'Active'),
        ('voided', 'Voided'),
        ('replaced', 'Replaced'),
    ], default='active', copy=False, index=True)
    void_reason = fields.Char(copy=False)
    warranty_status = fields.Selection([
        ('active', 'Active'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
        ('voided', 'Voided'),
        ('replaced', 'Replaced'),
    ], compute='_compute_warranty_status', search='_search_warranty_status', string='Status')

    previous_registration_id = fields.Many2one(
        'elegomotors.warranty.registration', copy=False, ondelete='restrict',
    )
    replacement_ids = fields.One2many(
        'elegomotors.warranty.registration', 'previous_registration_id',
    )
    claim_ids = fields.One2many('elegomotors.warranty.claim', 'registration_id')
    display_name = fields.Char(compute='_compute_display_name')

    @api.depends('start_date', 'duration_months')
    def _compute_end_date(self):
        for rec in self:
            rec.end_date = (
                rec.start_date + relativedelta(months=rec.duration_months)
                if rec.start_date and rec.duration_months else False
            )

    @api.depends('end_date')
    def _compute_days_remaining(self):
        today = fields.Date.today()
        for rec in self:
            rec.days_remaining = (rec.end_date - today).days if rec.end_date else 0

    @api.depends('state', 'end_date')
    def _compute_warranty_status(self):
        today = fields.Date.today()
        for rec in self:
            if rec.state in ('voided', 'replaced'):
                rec.warranty_status = rec.state
            elif not rec.end_date or rec.end_date < today:
                rec.warranty_status = 'expired'
            elif (rec.end_date - today).days <= 30:
                rec.warranty_status = 'expiring_soon'
            else:
                rec.warranty_status = 'active'

    @api.model
    def _search_warranty_status(self, operator, value):
        """Non-stored compute field — translate a domain leaf on
        warranty_status into an equivalent domain on the real, stored
        state/end_date fields so search-view filters keep working without
        needing a cron to keep a stored value fresh day to day."""
        today = fields.Date.today()
        soon = today + relativedelta(days=30)
        status_domains = {
            'active': ['&', ('state', '=', 'active'), ('end_date', '>', soon)],
            'expiring_soon': ['&', ('state', '=', 'active'), '&',
                               ('end_date', '>=', today), ('end_date', '<=', soon)],
            'expired': ['&', ('state', '=', 'active'), ('end_date', '<', today)],
            'voided': [('state', '=', 'voided')],
            'replaced': [('state', '=', 'replaced')],
        }
        values = value if isinstance(value, (list, tuple)) else [value]
        negate = operator in ('!=', 'not in')
        matched = [s for s, d in status_domains.items() if (s in values) != negate]
        if not matched:
            return [('id', '=', 0)]
        return expression.OR([status_domains[s] for s in matched])

    @api.depends('bike_lot_id.name', 'component')
    def _compute_display_name(self):
        for rec in self:
            comp = dict(COMPONENT_SELECTION).get(rec.component, '')
            rec.display_name = f'{rec.bike_lot_id.name or ""} — {comp}'

    def _check_warranty_manager(self):
        if not (self.env.user.has_group('elegomotors_setup.group_warranty_manager')
                or self.env.user.has_group('base.group_erp_manager')):
            raise UserError('Only a Warranty Manager or Administrator can do this.')

    def action_void(self):
        self.ensure_one()
        self._check_warranty_manager()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Void Warranty',
            'res_model': 'elegomotors.warranty.void.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_registration_id': self.id},
        }

    @api.model
    def _register_bike(self, bike_lot, dealer, customer_name, customer_mobile,
                        invoice_number, invoice_date):
        """Create one registration per covered component found on this bike
        (motor/controller/charger always; battery only if a type is known).
        Returns the created registrations."""
        Rule = self.env['elegomotors.warranty.policy.rule']
        created = self.browse()

        component_serials = {
            'motor': bike_lot.x_motor_serial,
            'controller': bike_lot.x_controller_serial,
            'charger': bike_lot.x_charger_serial,
            'battery': bike_lot.x_battery_serial,
        }
        for component in ('motor', 'controller', 'charger'):
            if not component_serials.get(component):
                continue
            rule = Rule._find_rule(component, 'bundled')
            if not rule:
                continue
            created |= self._create_from_rule(
                bike_lot, component, False, component_serials[component],
                dealer, customer_name, customer_mobile, invoice_number,
                invoice_date, rule,
            )

        battery_type = self._detect_battery_type(bike_lot.x_battery_type)
        if component_serials.get('battery') and battery_type:
            rule = Rule._find_rule('battery', 'bundled', battery_type)
            if rule:
                created |= self._create_from_rule(
                    bike_lot, 'battery', battery_type, component_serials['battery'],
                    dealer, customer_name, customer_mobile, invoice_number,
                    invoice_date, rule,
                )
        return created

    @api.model
    def _detect_battery_type(self, battery_type_label):
        label = (battery_type_label or '').lower()
        if 'lithium' in label:
            return 'lithium'
        if 'lead' in label:
            return 'lead'
        return False

    @api.model
    def _create_from_rule(self, bike_lot, component, battery_type, component_serial,
                           dealer, customer_name, customer_mobile, invoice_number,
                           invoice_date, rule):
        return self.create({
            'bike_lot_id': bike_lot.id,
            'component': component,
            'battery_type': battery_type,
            'component_serial': component_serial,
            'dealer_id': dealer.id,
            'customer_name': customer_name,
            'customer_mobile': customer_mobile,
            'chassis_number': bike_lot.name,
            'invoice_number': invoice_number,
            'invoice_date': invoice_date,
            'start_date': invoice_date,
            'duration_months': rule.duration_months,
            'cycle_limit': rule.cycle_limit,
            'water_damage_covered': rule.water_damage_covered,
        })


class WarrantyVoidWizard(models.TransientModel):
    _name = 'elegomotors.warranty.void.wizard'
    _description = 'Void a Warranty Registration'

    registration_id = fields.Many2one('elegomotors.warranty.registration', required=True)
    reason = fields.Char(required=True)

    def action_confirm(self):
        self.ensure_one()
        self.registration_id._check_warranty_manager()
        self.registration_id.write({'state': 'voided', 'void_reason': self.reason})
        self.registration_id.message_post(
            body=f'Warranty voided: {self.reason}',
            message_type='comment', subtype_xmlid='mail.mt_comment',
        )


class WarrantyClaim(models.Model):
    _name = 'elegomotors.warranty.claim'
    _description = 'Warranty Claim'
    _order = 'create_date desc'
    _rec_name = 'claim_number'

    claim_number = fields.Char(readonly=True, copy=False, index=True, default='New')
    registration_id = fields.Many2one(
        'elegomotors.warranty.registration', required=True, ondelete='restrict',
    )
    dealer_id = fields.Many2one(related='registration_id.dealer_id', store=True)
    customer_name = fields.Char(related='registration_id.customer_name', store=True)
    customer_mobile = fields.Char(related='registration_id.customer_mobile', store=True)
    customer_invoice_number = fields.Char(related='registration_id.invoice_number', store=True)
    chassis_number = fields.Char(related='registration_id.chassis_number', store=True)
    model_name = fields.Char(
        related='registration_id.bike_lot_id.product_id.display_name',
        store=True, string='Model',
    )

    faulty_part_name = fields.Char(required=True)
    faulty_part_serial = fields.Char()
    faulty_part_photo = fields.Image(max_width=1920, max_height=1920)
    reason = fields.Text(required=True)
    reported_usage = fields.Integer(
        string='Reported Usage (km / cycles)',
        help='Informational only, shown to the approver alongside the policy '
             "cycle limit — not automatically enforced (per the client's "
             'explicit preference against auto-blocking claims).',
    )

    claim_type = fields.Selection([
        ('repair', 'Repair'), ('replace', 'Replace'),
    ], required=True)
    repair_location = fields.Selection([
        ('dealer_inhouse', 'Dealer (in-house)'),
        ('sent_to_hq', 'Sent to Elego HQ'),
    ], required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', copy=False, index=True)
    rejection_reason = fields.Char(copy=False)
    new_component_serial = fields.Char(
        string='New Component Serial',
        help='Required when completing a Replace claim.',
    )
    zero_value_invoice_id = fields.Many2one('account.move', copy=False, readonly=True)
    new_registration_id = fields.Many2one(
        'elegomotors.warranty.registration', copy=False, readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('claim_number', 'New') == 'New':
                vals['claim_number'] = self.env['ir.sequence'].sudo().next_by_code(
                    'elegomotors.warranty.claim'
                ) or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only draft claims can be submitted.')
            rec.state = 'submitted'
            rec.message_post(
                body='Claim submitted for Elego HQ approval.',
                message_type='comment', subtype_xmlid='mail.mt_comment',
            )

    def _check_warranty_manager(self):
        if not (self.env.user.has_group('elegomotors_setup.group_warranty_manager')
                or self.env.user.has_group('base.group_erp_manager')):
            raise UserError('Only a Warranty Manager or Administrator can do this.')

    def action_approve(self):
        self._check_warranty_manager()
        for rec in self:
            if rec.state != 'submitted':
                raise UserError('Only submitted claims can be approved.')
            rec.state = 'approved'
            rec.message_post(
                body=Markup(f'Claim <b>Approved</b> by {self.env.user.name}.'),
                message_type='comment', subtype_xmlid='mail.mt_comment',
            )

    def action_reject(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject Claim',
            'res_model': 'elegomotors.warranty.claim.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_claim_id': self.id},
        }

    def action_cancel(self):
        for rec in self:
            if rec.state in ('completed',):
                raise UserError('A completed claim cannot be cancelled.')
            rec.state = 'cancelled'

    def action_complete(self):
        self._check_warranty_manager()
        for rec in self:
            if rec.state != 'approved':
                raise UserError('Only approved claims can be completed.')
            if rec.claim_type == 'replace':
                if not rec.new_component_serial:
                    raise UserError(
                        'Enter the new component serial before completing a Replace claim.'
                    )
                rec._create_replacement_registration()
            rec._create_zero_value_invoice()
            rec.state = 'completed'
            rec.message_post(
                body='Claim completed.',
                message_type='comment', subtype_xmlid='mail.mt_comment',
            )

    def _create_replacement_registration(self):
        """The core "no fresh clock" rule: the replacement inherits the
        original's start_date/duration_months/end_date exactly, it does not
        get its own new warranty period."""
        self.ensure_one()
        old = self.registration_id
        new = self.env['elegomotors.warranty.registration'].create({
            'bike_lot_id': old.bike_lot_id.id,
            'component': old.component,
            'battery_type': old.battery_type,
            'component_serial': self.new_component_serial,
            'dealer_id': old.dealer_id.id,
            'customer_name': old.customer_name,
            'customer_mobile': old.customer_mobile,
            'chassis_number': old.chassis_number,
            'invoice_number': old.invoice_number,
            'invoice_date': old.invoice_date,
            'start_date': old.start_date,
            'duration_months': old.duration_months,
            'cycle_limit': old.cycle_limit,
            'water_damage_covered': old.water_damage_covered,
            'state': 'active',
            'previous_registration_id': old.id,
        })
        old.write({'state': 'replaced'})
        self.new_registration_id = new.id

    def _create_zero_value_invoice(self):
        self.ensure_one()
        product = self.env.ref('elegomotors_setup.product_pi_section_header')
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.registration_id.dealer_id.id,
            'invoice_origin': self.claim_number,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': f'Warranty claim {self.claim_number} — '
                        f'{self.faulty_part_name} ({self.claim_type})',
                'quantity': 1,
                'price_unit': 0.0,
                'tax_ids': [(6, 0, [])],
            })],
        })
        move.action_post()
        self.zero_value_invoice_id = move.id


class WarrantyClaimRejectWizard(models.TransientModel):
    _name = 'elegomotors.warranty.claim.reject.wizard'
    _description = 'Reject a Warranty Claim'

    claim_id = fields.Many2one('elegomotors.warranty.claim', required=True)
    reason = fields.Char(required=True)

    def action_confirm(self):
        self.ensure_one()
        claim = self.claim_id
        claim._check_warranty_manager()
        if claim.state != 'submitted':
            raise UserError('Only submitted claims can be rejected.')
        claim.write({'state': 'rejected', 'rejection_reason': self.reason})
        claim.message_post(
            body=Markup(f'Claim <b>Rejected</b> by {self.env.user.name}: {self.reason}'),
            message_type='comment', subtype_xmlid='mail.mt_comment',
        )


# --- External API (dealer/customer app) -------------------------------
# Same stateless HMAC bearer-token design as the Bajaj Finance API
# (models/finance_api.py) — deliberately NOT sharing code with it, to
# avoid touching that already-shipped, production-deployed module for an
# unrelated feature. The ~60 lines below are a known, accepted duplicate.

class WarrantyApiClient(models.Model):
    _name = 'elegomotors.warranty.api.client'
    _description = 'Warranty API Client (dealer/customer app)'
    _rec_name = 'name'

    name = fields.Char(required=True, help='e.g. "Dealer App - Production"')
    client_id = fields.Char(readonly=True, copy=False, index=True)
    client_secret_salt = fields.Char(readonly=True, copy=False)
    client_secret_hash = fields.Char(readonly=True, copy=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('client_id_unique', 'unique(client_id)', 'Client ID must be unique.'),
    ]

    def action_generate_credentials(self):
        self.ensure_one()
        client_id = 'wty_' + secrets.token_hex(8)
        client_secret = secrets.token_urlsafe(32)
        salt = secrets.token_hex(16)
        self.write({
            'client_id': client_id,
            'client_secret_salt': salt,
            'client_secret_hash': self._hash_secret(client_secret, salt),
        })
        wizard = self.env['elegomotors.warranty.api.client.secret.wizard'].create({
            'client_id': client_id,
            'client_secret': client_secret,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'New API Credentials — copy the secret now, it will not be shown again',
            'res_model': 'elegomotors.warranty.api.client.secret.wizard',
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


class WarrantyApiClientSecretWizard(models.TransientModel):
    _name = 'elegomotors.warranty.api.client.secret.wizard'
    _description = 'One-time display of a freshly generated Warranty API client secret'

    client_id = fields.Char(readonly=True)
    client_secret = fields.Char(readonly=True)


class WarrantyApiLog(models.Model):
    _name = 'elegomotors.warranty.api.log'
    _description = 'Warranty API Request Log'
    _order = 'create_date desc'
    _rec_name = 'endpoint'

    client_id = fields.Char(readonly=True)
    endpoint = fields.Char(readonly=True)
    chassis_number = fields.Char(readonly=True)
    response_summary = fields.Char(readonly=True)
