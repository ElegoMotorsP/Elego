# -*- coding: utf-8 -*-
"""Bill of Entry (import) — customs duty and landed cost for an import PO.

One Bill of Entry records what customs charged on one or more import GRNs:
assessable value, customs duty (BCD + Social Welfare Surcharge), other landed
costs (freight, insurance, port / CFS, CHA, transport) and the Import IGST.

  * Everything marked "Capitalise" is added to the value of the RECEIVED PARTS
    through Odoo's standard Landed Cost (stock.landed.cost) on the chosen GRNs —
    split over the parts by their current value — so Final component value =
    allocated kit cost + freight + insurance + duty + eligible landed costs.
  * Import IGST is NOT capitalised: it is recoverable input credit. It is
    booked as a journal entry (Debit Input IGST / Credit customs payable) that
    the accountant reviews and posts.

Landed cost only applies to parts costed Average or FIFO; parts on another
costing method are reported on the form and would be skipped by Odoo.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

KINDS = [
    ('bcd', 'Basic Customs Duty (BCD)'),
    ('sws', 'Social Welfare Surcharge'),
    ('igst', 'Import IGST'),
    ('freight', 'Freight'),
    ('insurance', 'Insurance'),
    ('port', 'Port / CFS Charges'),
    ('cha', 'CHA Charges'),
    ('transport', 'Transport to Factory'),
    ('other', 'Other'),
]
SPLIT_METHODS = [
    ('by_current_cost_price', 'By Current Value'),
    ('by_quantity', 'By Quantity'),
    ('equal', 'Equal'),
]
# What a fresh Bill of Entry starts with (amounts left at 0 are ignored).
DEFAULT_KINDS = ['bcd', 'sws', 'igst', 'freight', 'insurance', 'port', 'cha', 'transport']
# Words that find the landed-cost product of each line in the existing product
# list (Basic Customs Duty (BCD), Social Welfare Surcharge, Ocean Freight,
# Marine Insurance, CFS Charges, CHA Charges ...), so nobody has to pick them.
LANDED_PRODUCT_HINTS = {
    'bcd': ('basic customs duty', 'bcd'),
    'sws': ('social welfare',),
    'freight': ('freight',),
    'insurance': ('insurance',),
    'port': ('cfs',),
    'cha': ('cha charges',),
    'transport': ('transport',),
}


class BillOfEntry(models.Model):
    _name = 'elegomotors.bill.of.entry'
    _description = 'Bill of Entry (Import)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', default='New', readonly=True, copy=False)
    boe_number = fields.Char(string='Bill of Entry No.', required=True, tracking=True)
    date = fields.Date(
        string='Bill of Entry Date', required=True, default=fields.Date.context_today, tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('landed', 'Landed Cost Created'),
         ('done', 'Landed Cost Posted'), ('cancel', 'Cancelled')],
        default='draft', readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

    order_ids = fields.Many2many(
        'purchase.order', string='Import Purchase Orders',
        domain="[('x_po_type', '=', 'import'), ('state', 'in', ('purchase', 'done'))]")
    picking_ids = fields.Many2many(
        'stock.picking', string='GRNs (receipts)',
        help='The validated receipts the duty and landed costs are added to.')
    supplier_invoice_ref = fields.Char(string='Supplier Invoice No.')
    exchange_rate = fields.Float(
        string='Customs Exchange Rate', digits=(12, 4),
        help='INR per unit of foreign currency used by customs. For reference.')
    assessable_value = fields.Monetary(
        string='Assessable Value', currency_field='currency_id',
        help='As on the Bill of Entry: goods + freight + insurance, in INR.')

    line_ids = fields.One2many('elegomotors.bill.of.entry.line', 'boe_id', string='Duties and Costs')
    capitalised_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id', string='Added to Part Value')
    duty_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id', string='Customs Duty (BCD + SWS)')
    igst_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id', string='Import IGST (not capitalised)')
    costing_warning = fields.Text(compute='_compute_costing_warning')

    landed_cost_id = fields.Many2one(
        'stock.landed.cost', string='Landed Cost', readonly=True, copy=False)
    igst_journal_id = fields.Many2one(
        'account.journal', string='IGST Journal', domain="[('type', '=', 'general')]")
    igst_debit_account_id = fields.Many2one(
        'account.account', string='Input IGST Account')
    igst_credit_account_id = fields.Many2one(
        'account.account', string='Customs Payable / Bank Account')
    igst_move_id = fields.Many2one(
        'account.move', string='IGST Journal Entry', readonly=True, copy=False)

    # ------------------------------------------------------------------

    @api.model
    def _default_landed_products(self):
        """{kind: landed-cost product id} found by name among the products
        marked "Is a Landed Cost"."""
        Product = self.env['product.product'].sudo()
        found = {}
        for kind, hints in LANDED_PRODUCT_HINTS.items():
            for hint in hints:
                product = Product.search(
                    [('landed_cost_ok', '=', True), ('name', 'ilike', hint)], limit=1)
                if product:
                    found[kind] = product.id
                    break
        return found

    @api.model
    def _default_igst_account(self):
        """The Input IGST account: the one the purchase IGST taxes post their
        tax amount to (IGST Receivable), so it follows the company's own setup."""
        tax = self.env['account.tax'].sudo().search([
            ('type_tax_use', '=', 'purchase'), ('company_id', '=', self.env.company.id),
            ('name', 'ilike', 'igst'), ('name', 'not ilike', ' RC'), ('amount', '>', 0),
        ], order='amount desc', limit=1)
        repartition = tax.invoice_repartition_line_ids.filtered(
            lambda r: r.repartition_type == 'tax' and r.account_id)[:1]
        return repartition.account_id

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'line_ids' in fields_list and not res.get('line_ids'):
            labels = dict(KINDS)
            products = self._default_landed_products()
            res['line_ids'] = [(0, 0, {
                'kind': kind,
                'name': labels[kind],
                'product_id': products.get(kind, False),
                'capitalise': kind != 'igst',
                'amount': 0.0,
            }) for kind in DEFAULT_KINDS]
        if 'igst_debit_account_id' in fields_list and not res.get('igst_debit_account_id'):
            account = self._default_igst_account()
            if account:
                res['igst_debit_account_id'] = account.id
        if 'igst_journal_id' in fields_list and not res.get('igst_journal_id'):
            journal = self.env['account.journal'].sudo().search(
                [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1)
            if journal:
                res['igst_journal_id'] = journal.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('elegomotors.bill.of.entry') or 'New'
        return super().create(vals_list)

    @api.depends('line_ids.amount', 'line_ids.capitalise', 'line_ids.kind')
    def _compute_totals(self):
        for boe in self:
            lines = boe.line_ids
            boe.capitalised_total = sum(lines.filtered('capitalise').mapped('amount'))
            boe.duty_total = sum(lines.filtered(lambda l: l.kind in ('bcd', 'sws')).mapped('amount'))
            boe.igst_total = sum(lines.filtered(lambda l: l.kind == 'igst').mapped('amount'))

    @api.depends('picking_ids.move_ids.product_id')
    def _compute_costing_warning(self):
        for boe in self:
            products = boe.picking_ids.move_ids.filtered(
                lambda m: m.state == 'done').product_id
            skipped = products.filtered(lambda p: p.cost_method not in ('average', 'fifo'))
            boe.costing_warning = _(
                'These parts use Standard costing, so Odoo will NOT add duty / landed cost '
                'to them (move them to an Average-cost category first): %s',
                ', '.join(skipped.mapped('display_name')[:15]) + (' …' if len(skipped) > 15 else ''),
            ) if skipped else False

    def _candidate_pickings(self):
        self.ensure_one()
        Picking = self.env['stock.picking']
        pickings = Picking
        for po in self.order_ids:
            pickings |= po.order_line.move_ids.picking_id | po.picking_ids
            pickings |= Picking.search([('x_source_po_id', '=', po.id)])
        return pickings.filtered(
            lambda p: p.picking_type_code == 'incoming' and p.state == 'done')

    @api.onchange('order_ids')
    def _onchange_order_ids(self):
        self.picking_ids = [(6, 0, self._candidate_pickings().ids)]

    # ------------------------------------------------------------------
    # Landed cost (duty + capitalised costs -> value of the received parts)
    # ------------------------------------------------------------------

    def _check_landed_cost_ready(self):
        self.ensure_one()
        if not self.picking_ids:
            raise UserError(_('Choose the GRN(s) the duty and costs belong to.'))
        not_done = self.picking_ids.filtered(lambda p: p.state != 'done')
        if not_done:
            raise UserError(_('These receipts are not validated yet: %s',
                              ', '.join(not_done.mapped('name'))))
        lines = self.line_ids.filtered(
            lambda l: l.capitalise and not float_is_zero(l.amount, precision_rounding=self.currency_id.rounding))
        if not lines:
            raise UserError(_('Enter at least one amount to capitalise (duty, freight, insurance, …).'))
        missing = lines.filtered(lambda l: not l.product_id)
        if missing:
            raise UserError(_(
                'Pick the landed-cost product for: %s. (A product with "Is a Landed Cost" ticked.)',
                ', '.join(missing.mapped('name'))))
        return lines

    def action_create_landed_cost(self):
        self.ensure_one()
        if self.state != 'draft' or self.landed_cost_id:
            raise UserError(_('The landed cost has already been created for this Bill of Entry.'))
        lines = self._check_landed_cost_ready()
        Landed = self.env['stock.landed.cost'].sudo().with_company(self.company_id)
        journal = Landed._default_account_journal_id() or self.env['account.journal'].sudo().search(
            [('type', '=', 'general'), ('company_id', '=', self.company_id.id)], limit=1)
        if not journal:
            raise UserError(_('No journal is set for landed costs. Set one in Accounting settings '
                              '(Landed Costs journal), then try again.'))
        landed = Landed.create({
            'account_journal_id': journal.id,
            'date': self.date,
            'target_model': 'picking',
            'picking_ids': [(6, 0, self.picking_ids.ids)],
            'description': _('Bill of Entry %s (%s)', self.boe_number, self.name),
            'company_id': self.company_id.id,
            'cost_lines': [(0, 0, {
                'name': line.name or line.product_id.name,
                'product_id': line.product_id.id,
                'price_unit': line.amount,
                'split_method': line.split_method,
            }) for line in lines],
        })
        landed.compute_landed_cost()
        self.write({'landed_cost_id': landed.id, 'state': 'landed'})
        self.message_post(body=_(
            'Landed cost %(lc)s created for %(n)s receipt(s): %(amount).2f to be added to the value of the received parts.',
            lc=landed.name, n=len(self.picking_ids), amount=sum(lines.mapped('amount'))))
        return self.action_view_landed_cost()

    def action_validate_landed_cost(self):
        self.ensure_one()
        if self.state != 'landed' or not self.landed_cost_id:
            raise UserError(_('Create the landed cost first.'))
        self.landed_cost_id.sudo().button_validate()
        self.state = 'done'
        self.message_post(body=_(
            'Landed cost %s posted: the duty and charges are now part of the parts\' value.',
            self.landed_cost_id.name))
        return True

    def action_view_landed_cost(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Landed Cost'),
            'res_model': 'stock.landed.cost', 'res_id': self.landed_cost_id.id,
            'view_mode': 'form', 'target': 'current',
        }

    # ------------------------------------------------------------------
    # Import IGST (input credit — never capitalised)
    # ------------------------------------------------------------------

    def action_create_igst_entry(self):
        self.ensure_one()
        if self.igst_move_id:
            raise UserError(_('The IGST journal entry has already been created.'))
        amount = self.igst_total
        if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
            raise UserError(_('Enter the Import IGST amount on its line first.'))
        if not (self.igst_journal_id and self.igst_debit_account_id and self.igst_credit_account_id):
            raise UserError(_('Choose the journal, the Input IGST account and the Customs Payable / Bank account first.'))
        label = _('Import IGST — Bill of Entry %s', self.boe_number)
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': self.igst_journal_id.id,
            'date': self.date,
            'ref': label,
            'line_ids': [
                (0, 0, {'name': label, 'account_id': self.igst_debit_account_id.id,
                        'debit': amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'account_id': self.igst_credit_account_id.id,
                        'debit': 0.0, 'credit': amount}),
            ],
        })
        self.igst_move_id = move
        self.message_post(body=_(
            'Draft IGST journal entry %s created (%.2f) — please review and post it in Accounting.',
            move.name or move.display_name, amount))
        return {
            'type': 'ir.actions.act_window', 'name': _('IGST Journal Entry'),
            'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form', 'target': 'current',
        }

    def action_cancel(self):
        for boe in self:
            if boe.state == 'done':
                raise UserError(_('A posted landed cost cannot be cancelled. Reverse it with a negative landed cost.'))
            if boe.landed_cost_id and boe.landed_cost_id.state == 'draft':
                boe.landed_cost_id.sudo().button_cancel()
            boe.state = 'cancel'
        return True

    def action_reset_draft(self):
        for boe in self:
            if boe.state != 'cancel':
                raise UserError(_('Only a cancelled Bill of Entry can be set back to draft.'))
            boe.write({'state': 'draft', 'landed_cost_id': False})
        return True


class BillOfEntryLine(models.Model):
    _name = 'elegomotors.bill.of.entry.line'
    _description = 'Bill of Entry Line'
    _order = 'sequence, id'

    boe_id = fields.Many2one('elegomotors.bill.of.entry', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    kind = fields.Selection(KINDS, string='Type', required=True, default='other')
    name = fields.Char(string='Description')
    product_id = fields.Many2one(
        'product.product', string='Landed-Cost Product',
        domain="[('landed_cost_ok', '=', True)]",
        help='Needed for the lines that are capitalised. A service product with '
             '"Is a Landed Cost" ticked (e.g. Basic Customs Duty).')
    amount = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='boe_id.currency_id')
    capitalise = fields.Boolean(
        string='Add to Part Value', default=True,
        help='Untick for amounts that are not part of the inventory value, e.g. Import IGST.')
    split_method = fields.Selection(
        SPLIT_METHODS, string='Split Over Parts', default='by_current_cost_price', required=True)

    @api.onchange('kind')
    def _onchange_kind(self):
        if self.kind:
            self.capitalise = self.kind != 'igst'
            if not self.name:
                self.name = dict(KINDS).get(self.kind)
