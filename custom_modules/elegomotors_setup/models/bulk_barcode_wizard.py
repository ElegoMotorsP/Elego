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
        Line = self.env['elegomotors.bulk.barcode.wizard.line']
        for mo in self.production_ids:
            Line.create({
                'wizard_id': self.id,
                'production_id': mo.id,
                'mo_name': mo.name,
            })

    def action_confirm(self):
        self.ensure_one()

        # 1. All rows must have all 4 serials
        incomplete = self.line_ids.filtered(lambda l: not l.all_scanned)
        if incomplete:
            mos = ', '.join(incomplete.mapped('mo_name'))
            raise UserError(
                f'Please scan all 4 component serials for the following unit(s):\n{mos}'
            )

        # 2. No duplicate serials within this batch
        all_serials = []
        for line in self.line_ids:
            for val in [
                line.x_motor_serial,
                line.x_battery_serial,
                line.x_controller_serial,
                line.x_charger_serial,
            ]:
                if val in all_serials:
                    raise UserError(
                        f'Serial "{val}" appears more than once across the units in this batch. '
                        f'Each component must have a unique serial number.'
                    )
                all_serials.append(val)

        # 3. No conflict with already-existing lots
        Lot = self.env['stock.lot']
        serial_fields = [
            ('x_motor_serial',      'Hub Motor'),
            ('x_battery_serial',    'Battery Pack'),
            ('x_controller_serial', 'Motor Controller'),
            ('x_charger_serial',    'Charger'),
        ]
        for line in self.line_ids:
            for field_name, label in serial_fields:
                val = getattr(line, field_name)
                existing = Lot.search([(field_name, '=', val)], limit=1)
                if existing:
                    raise UserError(
                        f'{label} serial "{val}" is already registered on lot '
                        f'{existing.name}. Please verify the barcode for MO {line.mo_name}.'
                    )

        # 4. Generate chassis serial + write component serials for each unit
        for line in self.line_ids:
            production = line.production_id
            production.with_context(skip_barcode_wizard=True).action_generate_serial()
            lot = production.lot_producing_id
            if lot:
                lot.write({
                    'x_motor_serial':      line.x_motor_serial,
                    'x_battery_serial':    line.x_battery_serial,
                    'x_controller_serial': line.x_controller_serial,
                    'x_charger_serial':    line.x_charger_serial,
                })

        return {'type': 'ir.actions.act_window_close'}


class ElegomotorsBulkBarcodeWizardLine(models.TransientModel):
    _name = 'elegomotors.bulk.barcode.wizard.line'
    _description = 'Bulk Barcode Wizard — Unit Row'

    wizard_id = fields.Many2one(
        'elegomotors.bulk.barcode.wizard',
        required=True, ondelete='cascade',
    )
    production_id = fields.Many2one('mrp.production', string='MO', readonly=True)
    mo_name = fields.Char(string='MO Reference', readonly=True)

    x_motor_serial      = fields.Char(string='Motor Serial')
    x_battery_serial    = fields.Char(string='Battery Serial')
    x_controller_serial = fields.Char(string='Controller Serial')
    x_charger_serial    = fields.Char(string='Charger Serial')

    all_scanned = fields.Boolean(
        string='Done?',
        compute='_compute_all_scanned',
        store=True,
    )

    @api.depends('x_motor_serial', 'x_battery_serial', 'x_controller_serial', 'x_charger_serial')
    def _compute_all_scanned(self):
        for line in self:
            line.all_scanned = bool(
                line.x_motor_serial
                and line.x_battery_serial
                and line.x_controller_serial
                and line.x_charger_serial
            )
