# -*- coding: utf-8 -*-
"""Sales Return — Amit (Store Billing) / Manohar (Admin) only.

Lets an authorised user return specific bikes (by serial) from an already-
posted customer invoice, optionally including battery/charger/other
accessory quantities from the same invoice. Auto-calculates the return
value, creates a draft credit note against the original invoice (Amit
creates it here, Rajshri posts it — same split as every other invoice
today), and moves the returned bikes straight back into EGO/Finished
Goods (any returned accessories into EGO/Store) via a dedicated
"Sales Return" operation type — deliberately NOT routed through Gate
Entry/QC Inward like Odoo's own native "Return" button on a delivery,
since a plain sales return isn't a quality inspection.
"""
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class SalesReturn(models.Model):
    _name = 'elegomotors.sales.return'
    _description = 'Sales Return'
    _order = 'create_date desc'

    invoice_id = fields.Many2one(
        'account.move', string='Original Invoice', required=True,
        ondelete='cascade', index=True,
    )
    credit_note_id = fields.Many2one(
        'account.move', string='Credit Note', readonly=True,
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Return Transfer', readonly=True,
    )
    lot_ids = fields.Many2many(
        'stock.lot', string='Returned Bikes', readonly=True,
    )
    currency_id = fields.Many2one(related='invoice_id.currency_id')
    amount_total = fields.Monetary(
        string='Return Amount', currency_field='currency_id', readonly=True,
    )
    reason = fields.Text(required=True, readonly=True)


class SalesReturnWizard(models.TransientModel):
    _name = 'elegomotors.sales.return.wizard'
    _description = 'Create Sales Return'

    invoice_id = fields.Many2one(
        'account.move', required=True, readonly=True, ondelete='cascade',
    )
    currency_id = fields.Many2one(related='invoice_id.currency_id')
    bike_line_ids = fields.One2many(
        'elegomotors.sales.return.wizard.bike.line', 'wizard_id', string='Bikes',
    )
    accessory_line_ids = fields.One2many(
        'elegomotors.sales.return.wizard.accessory.line', 'wizard_id', string='Accessories',
    )
    # NOT required=True at the field level — the wizard record is created
    # (with reason still blank) the instant the button is clicked, before
    # the user has typed anything. A field-level DB constraint on a
    # TransientModel created that way can fail on a later, unrelated ORM
    # flush rather than right away (confirmed live on a different wizard in
    # this module). The mandatory-reason rule is enforced correctly instead,
    # in Python, in action_confirm() below.
    reason = fields.Text(
        string='Reason for Return',
        help='Compulsory — recorded on the permanent Sales Return record.',
    )
    amount_total = fields.Monetary(compute='_compute_amount_total', currency_field='currency_id')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.bike_line_ids and not rec.accessory_line_ids:
                rec._populate_lines()
        return records

    def _populate_lines(self):
        """One row per bike serial already invoiced (x_assigned_lot_ids),
        excluding any already returned via a prior Sales Return on this
        same invoice, plus one row per non-bike invoice line (accessories)
        with a quantity-to-return input."""
        self.ensure_one()
        bike_tmpls = self.env['mrp.production']._get_ego_templates()
        BikeLine = self.env['elegomotors.sales.return.wizard.bike.line']
        AccLine = self.env['elegomotors.sales.return.wizard.accessory.line']

        already_returned = self.env['elegomotors.sales.return'].search([
            ('invoice_id', '=', self.invoice_id.id),
        ]).lot_ids

        for lot in self.invoice_id.x_assigned_lot_ids - already_returned:
            line = self.invoice_id.invoice_line_ids.filtered(
                lambda l, lot=lot: l.product_id == lot.product_id
            )[:1]
            BikeLine.create({
                'wizard_id': self.id,
                'lot_id': lot.id,
                'invoice_line_id': line.id if line else False,
                'amount': line.price_subtotal if line else 0.0,
            })

        for line in self.invoice_id.invoice_line_ids:
            if line.display_type in ('line_section', 'line_note'):
                continue
            if line.product_id.product_tmpl_id in bike_tmpls:
                continue
            if line.quantity <= 0:
                continue
            AccLine.create({
                'wizard_id': self.id,
                'invoice_line_id': line.id,
                'max_qty': line.quantity,
                'qty_returned': 0,
            })

    @api.depends(
        'bike_line_ids.selected', 'bike_line_ids.amount',
        'accessory_line_ids.qty_returned', 'accessory_line_ids.invoice_line_id',
    )
    def _compute_amount_total(self):
        for wiz in self:
            total = sum(wiz.bike_line_ids.filtered('selected').mapped('amount'))
            for acc in wiz.accessory_line_ids:
                if acc.qty_returned:
                    total += acc.invoice_line_id.price_unit * acc.qty_returned
            wiz.amount_total = total

    def _check_sales_return_access(self):
        # NOTE: deliberately NOT named _check_access — Odoo's ORM defines its
        # own internal hook of that exact name (models.py check_access() ->
        # self._check_access(operation)); a same-named zero-arg override
        # collides with it and crashes every create() on this model
        # (hit this exact bug on a different wizard in this module already).
        if (
            not self.env.su
            and not self.env.user.has_group('elegomotors_setup.group_store_billing')
            and not self.env.user.has_group('base.group_erp_manager')
        ):
            raise AccessError(
                'Only Store Billing (Amit) or Admin (Manohar) can create a '
                'Sales Return.'
            )

    def action_confirm(self):
        self.ensure_one()
        self._check_sales_return_access()
        if not (self.reason or '').strip():
            raise UserError('A reason is required to create a Sales Return.')

        selected_bikes = self.bike_line_ids.filtered('selected')
        selected_accessories = self.accessory_line_ids.filtered(lambda l: l.qty_returned > 0)
        if not selected_bikes and not selected_accessories:
            raise UserError('Select at least one bike or accessory quantity to return.')
        for acc in selected_accessories:
            if acc.qty_returned > acc.max_qty:
                raise UserError(
                    f'Cannot return {acc.qty_returned:g} of '
                    f'"{acc.invoice_line_id.product_id.display_name}" — only '
                    f'{acc.max_qty:g} were invoiced.'
                )

        invoice = self.invoice_id
        credit_line_vals = []
        for bike in selected_bikes:
            src = bike.invoice_line_id
            credit_line_vals.append((0, 0, {
                'product_id': src.product_id.id,
                'quantity': 1,
                'price_unit': src.price_unit,
                'discount': src.discount,
                'tax_ids': [(6, 0, src.tax_ids.ids)],
                'name': f'{src.name} — Sales Return ({bike.lot_id.name})',
            }))
        for acc in selected_accessories:
            src = acc.invoice_line_id
            credit_line_vals.append((0, 0, {
                'product_id': src.product_id.id,
                'quantity': acc.qty_returned,
                'price_unit': src.price_unit,
                'discount': src.discount,
                'tax_ids': [(6, 0, src.tax_ids.ids)],
                'name': f'{src.name} — Sales Return',
            }))

        credit_note = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': invoice.partner_id.id,
            'invoice_origin': invoice.name,
            'reversed_entry_id': invoice.id,
            'invoice_line_ids': credit_line_vals,
        })

        picking = self._create_return_picking(selected_bikes, selected_accessories) if selected_bikes else False

        self.env['elegomotors.sales.return'].create({
            'invoice_id': invoice.id,
            'credit_note_id': credit_note.id,
            'picking_id': picking.id if picking else False,
            'lot_ids': [(6, 0, selected_bikes.mapped('lot_id').ids)],
            'amount_total': self.amount_total,
            'reason': self.reason,
        })

        invoice.message_post(
            body=Markup(
                f"Sales Return created by <b>{self.env.user.name}</b> for "
                f"{len(selected_bikes)} bike(s) — credit note "
                f"<a href='/web#id={credit_note.id}&model=account.move'>"
                f"{credit_note.name or 'draft'}</a>. Reason: {self.reason}"
            ),
            message_type='comment', subtype_xmlid='mail.mt_comment',
        )
        credit_note.message_post(
            body=Markup(
                f"Created as a Sales Return against "
                f"<a href='/web#id={invoice.id}&model=account.move'>{invoice.name}</a> "
                f"by <b>{self.env.user.name}</b>."
            ),
            message_type='comment', subtype_xmlid='mail.mt_comment',
        )

        return {
            'type': 'ir.actions.act_window',
            'name': 'Credit Note',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': credit_note.id,
        }

    def _create_return_picking(self, selected_bikes, selected_accessories):
        """Move the returned bikes straight to EGO/Finished Goods (and any
        returned accessories to EGO/Store) via a dedicated "Sales Return"
        operation type, force-completed the same way other direct stock
        movements in this module are (e.g. mrp_production.py's
        _auto_move_fg_to_store) rather than driving the interactive
        transfer UI.
        """
        self.ensure_one()
        picking_type = self.env.ref(
            'elegomotors_setup.picking_type_sales_return', raise_if_not_found=False
        )
        if not picking_type:
            raise UserError(
                'The "Sales Return" operation type is not configured. '
                'Contact your administrator.'
            )
        fg_loc = self.env.ref('elegomotors_setup.location_ego_fg')
        store_loc = self.env.ref('elegomotors_setup.location_ego_store')
        customer_loc = self.env.ref('stock.stock_location_customers')

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': self.invoice_id.name,
            'partner_id': self.invoice_id.partner_id.id,
            'location_id': customer_loc.id,
            'location_dest_id': fg_loc.id,
        })
        MoveLine = self.env['stock.move.line']
        for bike in selected_bikes:
            product = bike.lot_id.product_id
            move = self.env['stock.move'].create({
                'name': product.display_name,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_qty': 1,
                'product_uom': product.uom_id.id,
                'location_id': customer_loc.id,
                'location_dest_id': fg_loc.id,
            })
            MoveLine.create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'qty_done': 1,
                'lot_id': bike.lot_id.id,
                'location_id': customer_loc.id,
                'location_dest_id': fg_loc.id,
            })

        for acc in selected_accessories:
            product = acc.invoice_line_id.product_id
            move = self.env['stock.move'].create({
                'name': product.display_name,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_qty': acc.qty_returned,
                'product_uom': product.uom_id.id,
                'location_id': customer_loc.id,
                'location_dest_id': store_loc.id,
            })
            MoveLine.create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'qty_done': acc.qty_returned,
                'location_id': customer_loc.id,
                'location_dest_id': store_loc.id,
            })

        picking.action_confirm()
        # skip_qc_wizard=True: without it, button_validate()'s generic
        # "any code=='incoming' picking" QC-routing block (built for Gate
        # Entry) treats this picking the same way and force-redirects every
        # move's destination to EGO/Store — silently overriding the bike's
        # EGO/Finished Goods destination set above. That block already
        # supports this exact bypass for known non-QC automated pickings.
        picking.with_context(
            skip_immediate=True, skip_backorder=True, skip_qc_wizard=True,
        ).button_validate()
        return picking


class SalesReturnWizardBikeLine(models.TransientModel):
    _name = 'elegomotors.sales.return.wizard.bike.line'
    _description = 'Sales Return Wizard — Bike Line'
    _order = 'id'

    wizard_id = fields.Many2one(
        'elegomotors.sales.return.wizard', required=True, ondelete='cascade',
    )
    lot_id = fields.Many2one('stock.lot', string='Bike Serial', required=True, readonly=True)
    invoice_line_id = fields.Many2one('account.move.line', readonly=True)
    product_display = fields.Char(compute='_compute_product_display')
    selected = fields.Boolean(string='Return')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    amount = fields.Monetary(readonly=True, currency_field='currency_id')

    @api.depends('lot_id')
    def _compute_product_display(self):
        for line in self:
            line.product_display = f'{line.lot_id.product_id.display_name} — {line.lot_id.name}'


class SalesReturnWizardAccessoryLine(models.TransientModel):
    _name = 'elegomotors.sales.return.wizard.accessory.line'
    _description = 'Sales Return Wizard — Accessory Line'
    _order = 'id'

    wizard_id = fields.Many2one(
        'elegomotors.sales.return.wizard', required=True, ondelete='cascade',
    )
    invoice_line_id = fields.Many2one('account.move.line', required=True, readonly=True)
    product_display = fields.Char(related='invoice_line_id.product_id.display_name')
    max_qty = fields.Float(readonly=True)
    qty_returned = fields.Float(string='Qty to Return')
