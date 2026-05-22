# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class ElegomotorsBulkBarcodeWizard(models.TransientModel):
    _name = 'elegomotors.bulk.barcode.wizard'
    _description = 'Bulk Barcode Capture Wizard — Multiple EGO-S1 Units'

    production_ids = fields.Many2many(
        'mrp.production',
        string='Manufacturing Orders',
    )
    line_ids = fields.One2many(
        'elegomotors.bulk.barcode.wizard.line',
        'wizard_id',
        string='Units',
    )
    x_auto_scan = fields.Boolean(string='Auto-Advance on Scan', default=True)

    total_units      = fields.Integer(compute='_compute_progress', string='Total Units')
    scanned_units    = fields.Integer(compute='_compute_progress', string='Units Complete')
    all_complete     = fields.Boolean(compute='_compute_progress', string='All Complete')
    progress_display = fields.Char(compute='_compute_progress', string='Progress')

    @api.depends('line_ids', 'line_ids.all_scanned')
    def _compute_progress(self):
        for wiz in self:
            total = len(wiz.line_ids)
            done = len(wiz.line_ids.filtered('all_scanned'))
            wiz.total_units = total
            wiz.scanned_units = done
            wiz.all_complete = total > 0 and done == total
            wiz.progress_display = f'{done} / {total} units complete'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._populate_lines()
        return records

    def _populate_lines(self):
        """Create one wizard line per bike unit.

        For a single MO with qty=2, this creates 2 lines (Unit 1, Unit 2).
        For multiple qty=1 MOs, this creates one line per MO.
        """
        Line = self.env['elegomotors.bulk.barcode.wizard.line']
        for mo in self.production_ids:
            total_units = max(1, int(mo.product_qty))
            for unit_idx in range(1, total_units + 1):
                label = (
                    f"{mo.name} — Unit {unit_idx}" if total_units > 1 else mo.name
                )
                Line.create({
                    'wizard_id':     self.id,
                    'production_id': mo.id,
                    'mo_name':       label,
                    'unit_index':    unit_idx,
                })

    def action_confirm(self):
        self.ensure_one()

        # 1. All rows must have chassis + motor + controller (battery and charger are optional)
        incomplete = self.line_ids.filtered(lambda l: not l.all_scanned)
        if incomplete:
            labels = ', '.join(incomplete.mapped('mo_name'))
            raise UserError(
                f'Please scan the chassis number, motor serial, and controller serial for:\n{labels}'
            )

        # 2. No duplicate serials within this batch (only non-empty values)
        all_serials = []
        for line in self.line_ids:
            for val in [
                line.x_chassis_serial,
                line.x_motor_serial,
                line.x_controller_serial,
                line.x_battery_serial,
                line.x_charger_serial,
            ]:
                if not val:
                    continue
                if val in all_serials:
                    raise UserError(
                        f'Serial "{val}" appears more than once in this batch. '
                        f'Each serial must be unique.'
                    )
                all_serials.append(val)

        # 3. No conflict with already-existing lots
        Lot = self.env['stock.lot']
        required_fields = [
            ('x_motor_serial',      'Hub Motor'),
            ('x_controller_serial', 'Motor Controller'),
        ]
        optional_fields = [
            ('x_battery_serial', 'Battery Pack'),
            ('x_charger_serial', 'Charger'),
        ]
        for line in self.line_ids:
            existing_chassis = Lot.search([
                ('x_chassis_serial', '=', line.x_chassis_serial),
            ], limit=1)
            if existing_chassis:
                raise UserError(
                    f'Chassis "{line.x_chassis_serial}" is already registered on serial '
                    f'{existing_chassis.name}. Please verify barcode for {line.mo_name}.'
                )
            for field_name, label in required_fields:
                val = getattr(line, field_name)
                existing = Lot.search([(field_name, '=', val)], limit=1)
                if existing:
                    raise UserError(
                        f'{label} serial "{val}" is already registered on serial '
                        f'{existing.name}. Please verify barcode for {line.mo_name}.'
                    )
            for field_name, label in optional_fields:
                val = getattr(line, field_name)
                if val:
                    existing = Lot.search([(field_name, '=', val)], limit=1)
                    if existing:
                        raise UserError(
                            f'{label} serial "{val}" is already registered on serial '
                            f'{existing.name}. Please verify barcode for {line.mo_name}.'
                        )

        # 4. Auto-generate lot serial + store chassis + component serials + mark done.
        #    For MOs with qty > 1, pre-split into N individual qty=1 productions so
        #    that each unit can be marked done independently with no backorder dialog.
        WizardSingle = self.env['elegomotors.barcode.capture.wizard']
        for mo in self.production_ids.sorted('id'):
            lines = self.line_ids.filtered(
                lambda l: l.production_id == mo
            ).sorted('unit_index')

            total = len(lines)

            if total > 1:
                split_result = mo._split_productions({mo: [1.0] * total})
                if len(split_result) != total:
                    raise UserError(
                        f'{mo.name}: expected {total} split productions, '
                        f'got {len(split_result)}. Contact your administrator.'
                    )
                new_copies = (split_result - mo).sorted('id')
                productions = new_copies + mo  # [unit1_mo, unit2_mo, ..., unitN_mo]
            else:
                productions = mo

            # Re-use the single-unit wizard helper for sequence lookup
            dummy = WizardSingle.new({'production_id': mo.id})
            for split_mo, line in zip(productions, lines):
                dummy.production_id = split_mo
                lot_name = dummy._get_next_lot_serial(split_mo)
                lot = Lot.create({
                    'name':       lot_name,
                    'product_id': split_mo.product_id.id,
                    'company_id': split_mo.company_id.id,
                })
                split_mo.lot_producing_id = lot
                split_mo.qty_producing    = 1
                lot.write({
                    'x_chassis_serial':    line.x_chassis_serial,
                    'x_motor_serial':      line.x_motor_serial,
                    'x_controller_serial': line.x_controller_serial,
                    'x_battery_serial':    line.x_battery_serial or '',
                    'x_charger_serial':    line.x_charger_serial or '',
                    'x_color':             split_mo.x_color or '',
                    'x_battery_type':      split_mo.x_battery_type or '',
                })
                split_mo.with_context(skip_barcode_wizard=True).button_mark_done()

        return {'type': 'ir.actions.act_window_close'}


class ElegomotorsBulkBarcodeWizardLine(models.TransientModel):
    _name = 'elegomotors.bulk.barcode.wizard.line'
    _description = 'Bulk Barcode Wizard — Unit Row'

    wizard_id = fields.Many2one(
        'elegomotors.bulk.barcode.wizard',
        required=True, ondelete='cascade',
    )
    production_id = fields.Many2one('mrp.production', string='MO', readonly=True)
    mo_name       = fields.Char(string='MO / Unit', readonly=True)
    unit_index    = fields.Integer(string='Unit #', default=1)

    x_chassis_serial    = fields.Char(string='Chassis No.')
    x_motor_serial      = fields.Char(string='Motor Serial')
    x_controller_serial = fields.Char(string='Controller Serial')
    x_battery_serial    = fields.Char(string='Battery Serial (opt.)')
    x_charger_serial    = fields.Char(string='Charger Serial (opt.)')

    all_scanned = fields.Boolean(
        string='Done?',
        compute='_compute_all_scanned',
        store=True,
    )

    @api.depends('x_chassis_serial', 'x_motor_serial', 'x_controller_serial', 'x_battery_serial', 'x_charger_serial')
    def _compute_all_scanned(self):
        for line in self:
            # Battery and charger are optional — only chassis + motor + controller required
            line.all_scanned = bool(
                line.x_chassis_serial
                and line.x_motor_serial
                and line.x_controller_serial
            )
