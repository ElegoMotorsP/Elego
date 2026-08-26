# -*- coding: utf-8 -*-
"""Delivery Bike Scan Wizard — Amit (Store) scans the exact bikes going OUT.

Serial assignment for customer deliveries moves from Accounts (invoice-side
wizard) to the Store: when Amit processes the outgoing delivery of a Sales
Order, he scans the serial of each physical bike being shipped, model-wise.
Validations: the serial must exist, match the delivery line's model AND
colour variant, be physically available in the Finished Goods store, not be
blacklisted (QC fail), and not be reserved on another open delivery.

On confirm the scanned lots become the delivery's move lines (qty 1 each,
sourced from the bike's actual FG location). After Amit validates the
delivery, the serials flow automatically to the customer invoice
(account_move._sync_assigned_lots_from_deliveries) — Accounts no longer
scans anything.
"""
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import UserError


class DeliveryBikeScanWizard(models.TransientModel):
    _name = 'elegomotors.delivery.bike.scan.wizard'
    _description = 'Scan Bike Serials on Outgoing Delivery'

    picking_id = fields.Many2one(
        'stock.picking', string='Delivery', required=True, readonly=True,
        ondelete='cascade',
    )
    line_ids = fields.One2many(
        'elegomotors.delivery.bike.scan.wizard.line', 'wizard_id',
        string='Bike Units',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.line_ids:
                rec._populate_lines()
        return records

    def _populate_lines(self):
        """One scan row per bike unit demanded on the delivery."""
        self.ensure_one()
        bike_tmpls = self.env['mrp.production']._get_ego_templates()
        Line = self.env['elegomotors.delivery.bike.scan.wizard.line']
        for move in self.picking_id.move_ids:
            if move.state in ('done', 'cancel'):
                continue
            if move.product_id.product_tmpl_id not in bike_tmpls:
                continue
            qty = max(1, int(move.product_uom_qty))
            for unit_idx in range(1, qty + 1):
                # Intentionally NOT pre-filled with Odoo's auto-reserved
                # serial: serials are assigned by scanning only — Amit must
                # scan the physical bike being shipped, every time.
                Line.create({
                    'wizard_id': self.id,
                    'move_id': move.id,
                    'unit_index': unit_idx,
                    'scanned_serial': '',
                })

    def _validate_serial(self, line, seen_lot_ids):
        """Return (lot, quant, error). error is falsy when the scan is valid."""
        Lot = self.env['stock.lot']
        product = line.move_id.product_id
        serial = (line.scanned_serial or '').strip()
        label = f'Unit #{line.unit_index} ({product.display_name})'
        if not serial:
            return None, None, f'{label}: serial number not scanned.'

        lot = Lot.search([('name', '=', serial)], limit=1)
        if not lot:
            return None, None, f'{label}: serial "{serial}" not found in the system.'
        if lot.product_id.product_tmpl_id != product.product_tmpl_id:
            return None, None, (
                f'{label}: serial "{serial}" is a '
                f'{lot.product_id.display_name} — wrong model for this line.'
            )
        if lot.product_id != product:
            return None, None, (
                f'{label}: serial "{serial}" is a {lot.product_id.display_name}, '
                f'but this line needs {product.display_name} '
                f'(wrong colour/variant).'
            )
        if lot.x_blacklisted:
            return None, None, (
                f'{label}: serial "{serial}" is BLACKLISTED (QC failed) — '
                f'this unit cannot be shipped. Pick a different bike.'
            )

        # Physically available in Finished Goods?
        quant = None
        fg_location = self.env.ref(
            'elegomotors_setup.location_ego_fg', raise_if_not_found=False
        )
        if fg_location:
            quant = self.env['stock.quant'].search([
                ('lot_id', '=', lot.id),
                ('location_id', 'child_of', fg_location.id),
                ('quantity', '>', 0),
            ], limit=1)
            if not quant:
                return None, None, (
                    f'{label}: serial "{serial}" is not currently available '
                    f'in the Finished Goods store.'
                )

        # Not already SCANNED (qty_done > 0) on another open delivery. A lot
        # merely auto-reserved by Odoo's standard removal strategy on some
        # other delivery (qty_done still 0 there — nobody has scanned it)
        # is just a placeholder, not a real claim — it must not block
        # whoever actually scans the physical unit first. See the matching
        # comment in stock_picking.py::action_scan_bike_serial.
        other_ml = self.env['stock.move.line'].search([
            ('lot_id', '=', lot.id),
            ('picking_id', '!=', self.picking_id.id),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('qty_done', '>', 0),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=1)
        if other_ml:
            return None, None, (
                f'{label}: serial "{serial}" is already scanned on delivery '
                f'{other_ml.picking_id.name}.'
            )

        if lot.id in seen_lot_ids:
            return None, None, (
                f'{label}: serial "{serial}" is scanned more than once '
                f'in this delivery.'
            )
        return lot, quant, None

    def action_confirm(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError('This delivery has no bike units to scan.')

        errors = []
        seen_lot_ids = set()
        lots_by_move = {}
        for line in self.line_ids:
            lot, quant, error = self._validate_serial(line, seen_lot_ids)
            if error:
                errors.append(error)
                continue
            seen_lot_ids.add(lot.id)
            lots_by_move.setdefault(line.move_id, []).append((lot, quant))
        if errors:
            raise UserError('\n'.join(errors))

        # Rebuild the move lines with the scanned bikes: one line per unit,
        # sourced from the bike's actual FG location so reservation matches
        # physical reality (fixes "Not Available" on FG-stored bikes too).
        MoveL = self.env['stock.move.line']
        for move, lot_quants in lots_by_move.items():
            move.move_line_ids.unlink()
            for lot, quant in lot_quants:
                # Release any stale auto-reservation placeholder (qty_done
                # still 0 — never actually scanned) another open delivery is
                # still holding on this exact lot, so this delivery's claim
                # on the physical unit doesn't double-reserve the quant.
                self.env['stock.move.line'].search([
                    ('lot_id', '=', lot.id),
                    ('picking_id', '!=', self.picking_id.id),
                    ('picking_id.picking_type_code', '=', 'outgoing'),
                    ('qty_done', '=', 0),
                    ('state', 'not in', ('done', 'cancel')),
                ]).unlink()
                MoveL.create({
                    'move_id': move.id,
                    'picking_id': self.picking_id.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'qty_done': 1,
                    'lot_id': lot.id,
                    'location_id': quant.location_id.id if quant else move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                })

        # Marks the delivery as scan-verified — button_validate refuses bike
        # deliveries without this flag (serials must never come from Odoo's
        # automatic reservation).
        self.picking_id.x_bike_serials_scanned = True

        # Create the PDI checklist for each scanned bike now — this is the
        # moment we know exactly which serials are going out on this
        # delivery. Idempotent, so re-scanning the same bike doesn't
        # duplicate rows. button_validate() blocks the delivery until each
        # of these is approved (see stock_picking.py).
        scanned_lots = self.env['stock.lot']
        for pairs in lots_by_move.values():
            for lot, _quant in pairs:
                scanned_lots |= lot
        scanned_lots._create_pdi_check_results()
        scanned_lots.x_pdi_check_result_ids.filtered(
            lambda r: not r.picking_id
        ).write({'picking_id': self.picking_id.id})

        serial_names = ', '.join(
            lot.name for pairs in lots_by_move.values() for lot, _q in pairs
        )
        self.picking_id.message_post(
            body=Markup(
                f"Bike serials scanned for shipment by <b>{self.env.user.name}</b>: "
                f"<b>{serial_names}</b>. These serials will appear on the "
                f"customer invoice automatically."
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return {'type': 'ir.actions.act_window_close'}


class DeliveryBikeScanWizardLine(models.TransientModel):
    _name = 'elegomotors.delivery.bike.scan.wizard.line'
    _description = 'Delivery Bike Scan Wizard Line'
    _order = 'move_id, unit_index'

    wizard_id = fields.Many2one(
        'elegomotors.delivery.bike.scan.wizard', required=True,
        ondelete='cascade',
    )
    move_id = fields.Many2one('stock.move', required=True, readonly=True)
    product_display = fields.Char(
        string='Model / Variant', compute='_compute_product_display',
    )
    unit_index = fields.Integer(string='Unit #', default=1, readonly=True)
    scanned_serial = fields.Char(string='Scan Serial No.')
    status = fields.Char(readonly=True)

    @api.depends('move_id')
    def _compute_product_display(self):
        for line in self:
            line.product_display = line.move_id.product_id.display_name or ''

    @api.onchange('scanned_serial')
    def _onchange_scanned_serial(self):
        serial = (self.scanned_serial or '').strip()
        if not serial:
            self.status = ''
            return
        product = self.move_id.product_id
        lot = self.env['stock.lot'].search([('name', '=', serial)], limit=1)
        if not lot:
            self.status = 'Not found'
        elif lot.product_id.product_tmpl_id != product.product_tmpl_id:
            self.status = 'Wrong model'
        elif lot.product_id != product:
            self.status = 'Wrong colour/variant'
        elif lot.x_blacklisted:
            self.status = 'BLACKLISTED'
        else:
            fg = self.env.ref(
                'elegomotors_setup.location_ego_fg', raise_if_not_found=False
            )
            if fg and not self.env['stock.quant'].search([
                ('lot_id', '=', lot.id),
                ('location_id', 'child_of', fg.id),
                ('quantity', '>', 0),
            ], limit=1):
                self.status = 'Not in FG'
            else:
                self.status = 'OK'
