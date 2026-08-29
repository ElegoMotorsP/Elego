# -*- coding: utf-8 -*-
"""Outgoing Delivery Changes — Amit (Store) / Manohar (Admin) only.

Lets an authorised user reduce a bike unit's quantity, replace its scanned
serial, or swap it for a different colour of the SAME bike model, on a
delivery that hasn't been validated yet — every change requires a reason
and is logged (elegomotors.delivery.change.log: who, when, what changed,
why).

Reduce Quantity permanently drops that unit's demand on this delivery (and
its scanned claim, if any) — the remaining units ship normally on
validation, with NO backorder created for the reduced unit. The Sales
Order's own ordered quantity is left untouched; only this delivery's own
demand shrinks.

Change Bike is deliberately scoped to variants of the same model
(product_tmpl_id) — swapping colour is allowed, swapping to a different
bike model entirely is not; that's a bigger change than this wizard is
meant for.
"""
from markupsafe import Markup
from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError, UserError


class DeliveryChangeLog(models.Model):
    _name = 'elegomotors.delivery.change.log'
    _description = 'Outgoing Delivery Change Log'
    _order = 'create_date desc'

    picking_id = fields.Many2one(
        'stock.picking', string='Delivery', required=True,
        ondelete='cascade', index=True,
    )
    move_id = fields.Many2one('stock.move', string='Delivery Line', ondelete='set null')
    change_type = fields.Selection([
        ('reduce_qty', 'Reduce Quantity'),
        ('replace_serial', 'Replace Serial'),
        ('change_bike', 'Change Colour (same model)'),
    ], required=True)
    old_value = fields.Char(string='Before')
    new_value = fields.Char(string='After')
    reason = fields.Text(required=True)


class DeliveryChangeWizard(models.TransientModel):
    _name = 'elegomotors.delivery.change.wizard'
    _description = 'Modify Outgoing Delivery — Reduce Qty / Replace Serial / Change Bike'

    picking_id = fields.Many2one(
        'stock.picking', string='Delivery', required=True, readonly=True,
        ondelete='cascade',
    )
    line_ids = fields.One2many(
        'elegomotors.delivery.change.wizard.line', 'wizard_id',
        string='Bike Units',
    )
    # NOT required=True at the field level: the wizard record is created
    # (with reason still blank) the instant "Modify Delivery" is clicked,
    # before the user has typed anything — a field-level DB constraint would
    # make that half-formed record fail on the next unrelated ORM flush
    # (confirmed live: it surfaced as a "mandatory field" error when
    # clicking "Validate" on the delivery, not when opening this wizard).
    # The mandatory-reason rule is enforced correctly instead, in Python,
    # in action_apply() below, at the moment the user actually submits.
    reason = fields.Text(
        string='Reason for Change',
        help='Compulsory — recorded against every change made in this session, '
             'with your name and the current date/time.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.line_ids:
                rec._populate_lines()
        return records

    def _populate_lines(self):
        """One row per bike unit demanded on the delivery — already-scanned
        units show their serial, still-open slots show 'not yet scanned'."""
        self.ensure_one()
        bike_tmpls = self.env['mrp.production']._get_ego_templates()
        Line = self.env['elegomotors.delivery.change.wizard.line']
        for move in self.picking_id.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel') and m.product_id.product_tmpl_id in bike_tmpls
        ):
            demand = max(1, int(move.product_uom_qty))
            scanned = move.move_line_ids.filtered(lambda ml: ml.qty_done > 0 and ml.lot_id)
            for ml in scanned:
                Line.create({
                    'wizard_id': self.id,
                    'move_id': move.id,
                    'move_line_id': ml.id,
                    'lot_id': ml.lot_id.id,
                })
            for _ in range(demand - len(scanned)):
                Line.create({'wizard_id': self.id, 'move_id': move.id})

    def _check_delivery_change_access(self):
        # NOTE: deliberately NOT named _check_access — Odoo 18's ORM defines
        # its own internal hook of that exact name (models.py check_access()
        # calls self._check_access(operation)), and a same-named zero-arg
        # override on this model collides with it, raising a TypeError on
        # every create() (confirmed live: "takes 1 positional argument but
        # 2 were given").
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and not self.env.user.has_group('elegomotors_setup.group_delivery_change_operator')
        ):
            raise AccessError(
                'Only users with Delivery Change access can modify a delivery '
                'before validation. Ask Manohar (Admin) to grant this from '
                'Settings > Users.'
            )

    def action_apply(self):
        self.ensure_one()
        self._check_delivery_change_access()
        if not (self.reason or '').strip():
            raise UserError('A reason is required to modify this delivery.')
        active_lines = self.line_ids.filtered(lambda l: l.action != 'keep')
        if not active_lines:
            raise UserError('No changes selected — pick an action for at least one unit.')
        for line in active_lines:
            if line.action == 'change_bike' and not line.new_product_id:
                raise UserError(
                    f'Select a new colour for {line.product_display}.'
                )

        Log = self.env['elegomotors.delivery.change.log']
        for line in active_lines:
            move = line.move_id
            old_serial = line.lot_id.name if line.lot_id else '(not yet scanned)'

            if line.action == 'reduce_qty':
                # Ship the remaining units normally, no separate backorder:
                # drop the demand for this specific unit permanently (not
                # just its scanned claim), so qty_done stays matched to
                # product_uom_qty and the delivery validates straight
                # through for whatever remains.
                if line.move_line_id:
                    line.move_line_id.unlink()
                move.product_uom_qty = max(0, move.product_uom_qty - 1)
                Log.create({
                    'picking_id': self.picking_id.id, 'move_id': move.id,
                    'change_type': 'reduce_qty',
                    'old_value': f'{old_serial} — {move.product_uom_qty + 1:.0f} {move.product_id.display_name} demanded',
                    'new_value': f'{move.product_uom_qty:.0f} {move.product_id.display_name} demanded — not shipped, no backorder',
                    'reason': self.reason,
                })

            elif line.action == 'replace_serial':
                if line.move_line_id:
                    line.move_line_id.unlink()
                Log.create({
                    'picking_id': self.picking_id.id, 'move_id': move.id,
                    'change_type': 'replace_serial',
                    'old_value': old_serial,
                    'new_value': '(pending re-scan)',
                    'reason': self.reason,
                })

            elif line.action == 'change_bike':
                if line.move_line_id:
                    line.move_line_id.unlink()
                move.product_uom_qty = max(0, move.product_uom_qty - 1)
                new_move = self.picking_id.move_ids.filtered(
                    lambda m: m.product_id == line.new_product_id and m.state not in ('done', 'cancel')
                )[:1]
                if new_move:
                    new_move.product_uom_qty += 1
                else:
                    self.env['stock.move'].create({
                        'name': line.new_product_id.display_name,
                        'picking_id': self.picking_id.id,
                        'product_id': line.new_product_id.id,
                        'product_uom_qty': 1,
                        'product_uom': line.new_product_id.uom_id.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'picking_type_id': self.picking_id.picking_type_id.id,
                        'company_id': self.picking_id.company_id.id,
                        'state': 'confirmed',
                    })
                Log.create({
                    'picking_id': self.picking_id.id, 'move_id': move.id,
                    'change_type': 'change_bike',
                    'old_value': f'{move.product_id.display_name} ({old_serial})',
                    'new_value': line.new_product_id.display_name,
                    'reason': self.reason,
                })

        self.picking_id._recompute_bike_serials_scanned()
        self.picking_id.message_post(
            body=Markup(
                f"Delivery modified by <b>{self.env.user.name}</b> "
                f"({len(active_lines)} change(s)). Reason: {self.reason}"
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return {'type': 'ir.actions.act_window_close'}


class DeliveryChangeWizardLine(models.TransientModel):
    _name = 'elegomotors.delivery.change.wizard.line'
    _description = 'Delivery Change Wizard Line'
    _order = 'move_id, id'

    wizard_id = fields.Many2one(
        'elegomotors.delivery.change.wizard', required=True, ondelete='cascade',
    )
    move_id = fields.Many2one('stock.move', required=True, readonly=True)
    move_line_id = fields.Many2one('stock.move.line', readonly=True)
    lot_id = fields.Many2one('stock.lot', string='Current Serial', readonly=True)
    product_display = fields.Char(compute='_compute_product_display')
    action = fields.Selection([
        ('keep', 'Keep as-is'),
        ('reduce_qty', "Reduce Quantity (this unit won't ship — no backorder)"),
        ('replace_serial', 'Replace Serial (re-scan a different unit)'),
        ('change_bike', 'Change Colour (same model)'),
    ], default='keep', required=True)
    # Change Bike is scoped to the SAME model — only lets you swap the colour
    # variant, never jump to a different bike model entirely (that's a bigger
    # change than this wizard is meant for).
    current_tmpl_id = fields.Many2one(
        'product.template', compute='_compute_current_tmpl_id',
    )
    new_product_id = fields.Many2one(
        'product.product', string='New Colour Variant',
        domain="[('product_tmpl_id', '=', current_tmpl_id)]",
    )

    @api.depends('move_id')
    def _compute_current_tmpl_id(self):
        for line in self:
            line.current_tmpl_id = line.move_id.product_id.product_tmpl_id.id

    @api.depends('move_id', 'lot_id')
    def _compute_product_display(self):
        for line in self:
            base = line.move_id.product_id.display_name or ''
            line.product_display = f'{base} — {line.lot_id.name}' if line.lot_id else f'{base} (not yet scanned)'
