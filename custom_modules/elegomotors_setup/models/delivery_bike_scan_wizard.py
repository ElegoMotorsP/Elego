# -*- coding: utf-8 -*-
"""Delivery Bike Scan Wizard — Amit (Store) scans the exact bikes going OUT.

Random Bike Scanning: scan ANY available bike serial (no need to know which
delivery line it belongs to) — the matching/validation/assignment logic
lives once on stock.picking._scan_bike_unit(), shared with the mobile
Barcode app's action_scan_bike_serial(), so a physical USB/Bluetooth
scanner typing into this wizard's single input field behaves identically
to scanning through the mobile app. Each scan is applied immediately (not
staged for a later batch confirm) — the same "reserve every accepted
serial immediately" behavior the mobile flow already had.

Validations (in stock_picking.py): the serial must exist, match a
delivery line's model AND colour variant, be physically available in the
Finished Goods store, not be blacklisted (QC fail), not be reserved on
another open delivery, and not already be scanned here (Multiple Bike
Scanning Correction: "Already scanned" only fires on the exact same
serial — every other rejection has its own distinct message).

After Amit validates the delivery, the serials flow automatically to the
customer invoice (account_move._sync_assigned_lots_from_deliveries).
"""
from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class DeliveryBikeScanWizard(models.TransientModel):
    _name = 'elegomotors.delivery.bike.scan.wizard'
    _description = 'Scan Bike Serials on Outgoing Delivery'

    picking_id = fields.Many2one(
        'stock.picking', string='Delivery', required=True, readonly=True,
        ondelete='cascade',
    )
    scan_input = fields.Char(string='Scan Serial No.')
    last_message = fields.Char(readonly=True)
    last_success = fields.Boolean(readonly=True)
    line_ids = fields.One2many(
        'elegomotors.delivery.bike.scan.wizard.line', 'wizard_id',
        string='Scanned Units', readonly=True,
    )
    progress_summary = fields.Char(readonly=True, string='Progress')
    all_scanned = fields.Boolean(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._refresh()
        return records

    def _refresh(self):
        """Rebuild the read-only 'scanned so far' list and progress summary
        from the picking's actual move lines — the source of truth, so this
        reflects scans done from the mobile Barcode app too, not just this
        wizard.

        Rebuilds line_ids via One2many Command tuples (Command.clear() /
        Command.create(...)) rather than calling Line.create()/unlink()
        directly. This method runs from BOTH a real button click
        (action_scan, self.id a real integer) and from the scan_input
        onchange (self.id a NewId — Odoo runs onchange against a virtual
        proxy of the record so field changes stay client-side/previewed
        until Save). A direct Line.create({'wizard_id': self.id, ...}) call
        is a real, immediate cross-model write, and passing a NewId as that
        foreign key doesn't resolve to a real row — confirmed live, it
        inserted wizard_id=NULL and violated the NOT NULL constraint.
        Command tuples are the ORM-supported way to mutate a One2many that
        works correctly in both contexts.
        """
        self.ensure_one()
        bike_tmpls = self.env['mrp.production']._get_ego_templates()

        line_commands = [Command.clear()]
        progress_parts = []
        all_done = True
        for move in self.picking_id.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel') and m.product_id.product_tmpl_id in bike_tmpls
        ):
            demand = max(1, int(move.product_uom_qty))
            scanned_lines = move.move_line_ids.filtered(lambda ml: ml.qty_done > 0 and ml.lot_id)
            for ml in scanned_lines:
                line_commands.append(Command.create({
                    'move_id': move.id,
                    'lot_id': ml.lot_id.id,
                }))
            progress_parts.append(f'{move.product_id.display_name}: {len(scanned_lines)}/{demand}')
            if len(scanned_lines) < demand:
                all_done = False
        self.line_ids = line_commands
        self.progress_summary = ' | '.join(progress_parts) if progress_parts else 'No bike units on this delivery.'
        self.all_scanned = all_done and bool(progress_parts)

    @api.onchange('scan_input')
    def _onchange_scan_input(self):
        """Rapid scanning: a barcode scanner "types" the serial then sends a
        terminating Enter/Tab, which blurs the field and fires this onchange
        immediately — no button click needed between units. Processes the
        scan right here (this onchange's RPC runs the same
        picking._scan_bike_unit() as the manual button, committing the
        result straight away, not just staging a client-side field change),
        then clears the input so the field is empty and focused for the
        very next scan.
        """
        self._process_scan()

    def action_scan(self):
        """Manual fallback for the on-screen "Scan" button — same
        processing as the automatic onchange above, for anyone who prefers
        clicking (or whose input method doesn't reliably blur the field)."""
        self._process_scan()
        return self._reopen()

    def _process_scan(self):
        self.ensure_one()
        barcode = (self.scan_input or '').strip()
        if not barcode:
            self.last_success = False
            self.last_message = 'Scan or type a serial number first.'
            return
        result = self.picking_id._scan_bike_unit(barcode)
        self.last_success = result['success']
        self.last_message = result['message']
        self.scan_input = ''
        self._refresh()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    def action_done(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError('No bikes have been scanned yet.')
        return {'type': 'ir.actions.act_window_close'}


class DeliveryBikeScanWizardLine(models.TransientModel):
    _name = 'elegomotors.delivery.bike.scan.wizard.line'
    _description = 'Delivery Bike Scan Wizard Line — Already-Scanned Unit'
    _order = 'move_id, id'

    wizard_id = fields.Many2one(
        'elegomotors.delivery.bike.scan.wizard', required=True,
        ondelete='cascade',
    )
    move_id = fields.Many2one('stock.move', required=True, readonly=True)
    product_display = fields.Char(
        string='Model / Variant', compute='_compute_product_display',
    )
    lot_id = fields.Many2one('stock.lot', string='Serial No.', readonly=True)

    @api.depends('move_id')
    def _compute_product_display(self):
        for line in self:
            line.product_display = line.move_id.product_id.display_name or ''
