# -*- coding: utf-8 -*-
"""Global Production Scan — FIFO MO closing.

ElegoMotors is moving from per-MO production recording to a "global" flow:
the shop floor scans any finished bike (Model → Colour → Chassis → Motor →
Controller) without opening a specific MO first. The system then:

  1. Resolves the scanned model + colour codes to a product variant.
  2. Finds the OLDEST open MO for that model + colour whose materials have
     already been issued to production (FIFO) — errors if none exists.
  3. Deducts one unit from that MO: generates the bike serial number from
     the model's sequence, records the scanned component serials on the lot
     (same traceability as the per-MO flow), and marks the unit done.
     Multi-unit MOs are split so only the scanned unit closes.
  4. The produced unit enters the normal post-production QC flow: Pratik is
     notified, passes/fails QC from his login, and the result shows in the
     Bike Traceability report exactly as today.
  5. Prints the bike serial barcode label (TSC TTP-244 Pro): auto-print by
     default, or on demand via the Print Labels button. A TSPL2 (.prn)
     download is also available for raw direct-to-printer transfer.
"""
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import UserError

# Scanned model codes → product template xml-id.
# Codes are normalised before lookup: uppercased, all non-alphanumerics
# stripped ("elego-1.1" → "ELEGO11"), so several printed spellings work.
MODEL_CODE_MAP = {
    'EGOS1':      'elegomotors_setup.tmpl_ego_scooter',
    'S1':         'elegomotors_setup.tmpl_ego_scooter',
    'ELEGO11':    'elegomotors_setup.tmpl_elego_11',
    'EL11':       'elegomotors_setup.tmpl_elego_11',
    'ELEGO12':    'elegomotors_setup.tmpl_elego_12',
    'EL12':       'elegomotors_setup.tmpl_elego_12',
    'ELEGO20P':   'elegomotors_setup.tmpl_elego_20p',
    'ELEGO20':    'elegomotors_setup.tmpl_elego_20p',
    'ELEGO20PLUS': 'elegomotors_setup.tmpl_elego_20p',
    'EL20P':      'elegomotors_setup.tmpl_elego_20p',
    'ELEGO30':    'elegomotors_setup.tmpl_elego_30',
    'EL30':       'elegomotors_setup.tmpl_elego_30',
}

COLOR_CODE_MAP = {
    'RED':   'Red',
    'BLACK': 'Black',
    'GRAY':  'Gray',
    'GREY':  'Gray',
    'WHITE': 'White',
}


def _normalize_code(value):
    return ''.join(ch for ch in (value or '').upper() if ch.isalnum())


class GlobalScanWizard(models.TransientModel):
    _name = 'elegomotors.global.scan.wizard'
    _description = 'Global Production Scan — FIFO MO Closing'

    x_scan_qty = fields.Integer(
        string='Units to Scan', default=1,
        help='How many bikes to scan in this session. Default 1 — increase '
             'to scan N bikes in one window.',
    )
    x_auto_print = fields.Boolean(
        string='Auto-Print Labels', default=True,
        help='When ON, the serial barcode labels are sent to print '
             'automatically as soon as scanning completes.',
    )
    x_auto_scan = fields.Boolean(string='Auto-Advance on Scan', default=True)

    line_ids = fields.One2many(
        'elegomotors.global.scan.wizard.line', 'wizard_id', string='Bikes',
    )
    generated_lot_ids = fields.Many2many(
        'stock.lot', string='Generated Serials', readonly=True,
    )
    generated_serials_display = fields.Char(
        compute='_compute_generated_serials_display',
    )

    total_units      = fields.Integer(compute='_compute_progress')
    scanned_units    = fields.Integer(compute='_compute_progress')
    all_complete     = fields.Boolean(compute='_compute_progress')
    progress_display = fields.Char(compute='_compute_progress')

    @api.depends('line_ids', 'line_ids.all_scanned')
    def _compute_progress(self):
        for wiz in self:
            total = len(wiz.line_ids)
            done = len(wiz.line_ids.filtered('all_scanned'))
            wiz.total_units = total
            wiz.scanned_units = done
            wiz.all_complete = total > 0 and done == total
            wiz.progress_display = f'{done} / {total} bikes scanned'

    @api.depends('generated_lot_ids')
    def _compute_generated_serials_display(self):
        for wiz in self:
            wiz.generated_serials_display = ', '.join(
                wiz.generated_lot_ids.mapped('name')
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.line_ids:
                rec._sync_line_count()
        return records

    def _sync_line_count(self):
        """Keep one scan row per unit requested in x_scan_qty. Rows already
        scanned are never removed."""
        self.ensure_one()
        qty = max(1, self.x_scan_qty or 1)
        current = len(self.line_ids)
        if qty > current:
            self.write({'line_ids': [
                (0, 0, {'sequence': current + i + 1})
                for i in range(qty - current)
            ]})
        elif qty < current:
            removable = self.line_ids.sorted('sequence', reverse=True).filtered(
                lambda l: not (l.x_model_code or l.x_chassis_serial)
            )[: current - qty]
            removable.unlink()

    @api.onchange('x_scan_qty')
    def _onchange_scan_qty(self):
        qty = max(1, self.x_scan_qty or 1)
        current = len(self.line_ids)
        if qty > current:
            self.update({'line_ids': [
                (0, 0, {'sequence': current + i + 1})
                for i in range(qty - current)
            ]})
        elif qty < current:
            empties = self.line_ids.filtered(lambda l: not (
                l.x_model_code or l.x_color_code or l.x_chassis_serial
                or l.x_motor_serial or l.x_controller_serial
            ))
            surplus = current - qty
            drop = empties[-surplus:] if surplus <= len(empties) else empties
            self.line_ids = self.line_ids - drop

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    @api.model
    def _resolve_model_code(self, code):
        """Return the product.template for a scanned model code, or None."""
        ref = MODEL_CODE_MAP.get(_normalize_code(code))
        if not ref:
            return None
        return self.env.ref(ref, raise_if_not_found=False)

    @api.model
    def _resolve_color_code(self, code):
        """Return the canonical colour name ('Red', …) for a scanned code."""
        return COLOR_CODE_MAP.get(_normalize_code(code))

    @api.model
    def _resolve_variant(self, tmpl, color_name):
        """Match the Color attribute to the product.product variant."""
        for variant in tmpl.product_variant_ids:
            variant_colors = variant.product_template_attribute_value_ids.filtered(
                lambda ptav: ptav.attribute_id.name == 'Color'
            ).mapped('product_attribute_value_id.name')
            if variant_colors and variant_colors[0].lower() == color_name.lower():
                return variant
        # Template without a Color attribute — single variant is acceptable
        if len(tmpl.product_variant_ids) == 1:
            return tmpl.product_variant_ids[0]
        return None

    def _find_fifo_mo(self, tmpl, color_name, exclude_ids):
        """Oldest open MO for this model + colour with materials issued.

        FIFO = ordered by scheduled start date then id. Eligible MOs are
        confirmed/in-progress, have at least 1 unit remaining, no serial
        already assigned, and Amit has validated their Issue-to-Production
        picking (x_issue_picking_done). MOs still waiting for materials are
        skipped, per the agreed rule.
        """
        candidates = self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress', 'to_close')),
            ('product_id.product_tmpl_id', '=', tmpl.id),
            ('id', 'not in', list(exclude_ids)),
        ], order='date_start asc, id asc')
        for mo in candidates:
            # Colour match: variant Color attribute first, x_color fallback
            mo_color = ''
            for ptav in mo.product_id.product_template_attribute_value_ids:
                if ptav.attribute_id.name == 'Color':
                    mo_color = ptav.product_attribute_value_id.name
                    break
            if not mo_color:
                mo_color = mo.x_color or ''
            if mo_color.lower() != color_name.lower():
                continue
            if mo.lot_producing_id:
                continue  # a unit is already mid-recording on this MO
            if (mo.product_qty - mo.qty_produced) < 1:
                continue
            if not mo.x_issue_picking_done:
                continue  # materials not yet issued by Amit — skip (FIFO rule)
            return mo
        return self.env['mrp.production']

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def action_confirm(self):
        self.ensure_one()
        Lot = self.env['stock.lot']
        lines = self.line_ids.sorted('sequence').filtered(
            lambda l: l.x_model_code or l.x_color_code or l.x_chassis_serial
            or l.x_motor_serial or l.x_controller_serial
        )
        if not lines:
            raise UserError('Nothing scanned yet — scan at least one bike.')

        incomplete = lines.filtered(lambda l: not l.all_scanned)
        if incomplete:
            raise UserError(
                'Rows %s are missing scans. Each bike needs Model, Colour, '
                'Chassis No., Motor Number and Controller.' % ', '.join(
                    str(l.sequence) for l in incomplete
                )
            )

        # Validate codes + serial uniqueness (within batch and globally)
        seen_serials = []
        resolved = []
        for line in lines:
            tmpl = self._resolve_model_code(line.x_model_code)
            if not tmpl:
                raise UserError(
                    f'Row {line.sequence}: unknown model code '
                    f'"{line.x_model_code}". Valid codes: EGOS1, ELEGO11, '
                    f'ELEGO12, ELEGO20P, ELEGO30.'
                )
            color = self._resolve_color_code(line.x_color_code)
            if not color:
                raise UserError(
                    f'Row {line.sequence}: unknown colour code '
                    f'"{line.x_color_code}". Valid codes: RED, BLACK, GRAY, WHITE.'
                )
            for val in (line.x_chassis_serial, line.x_motor_serial,
                        line.x_controller_serial):
                if val in seen_serials:
                    raise UserError(
                        f'Serial "{val}" appears more than once in this batch. '
                        f'Each serial must be unique.'
                    )
                seen_serials.append(val)
            for field_name, label in [
                ('x_chassis_serial',    'Chassis'),
                ('x_motor_serial',      'Hub Motor'),
                ('x_controller_serial', 'Controller'),
            ]:
                val = getattr(line, field_name)
                existing = Lot.search([(field_name, '=', val)], limit=1)
                if existing:
                    raise UserError(
                        f'{label} serial "{val}" is already registered on bike '
                        f'serial {existing.name}. Please verify the barcode '
                        f'(row {line.sequence}).'
                    )
            resolved.append((line, tmpl, color))

        # Process each bike: FIFO MO → split 1 unit → serial → mark done
        SingleWizard = self.env['elegomotors.barcode.capture.wizard']
        produced_lots = Lot
        used_mo_ids = set()
        for line, tmpl, color in resolved:
            mo = self._find_fifo_mo(tmpl, color, used_mo_ids)
            if not mo:
                raise UserError(
                    f'Row {line.sequence}: no open Manufacturing Order found for '
                    f'{tmpl.name} ({color}) with materials issued to production. '
                    f'Ask Prashant to create/confirm an MO and Amit to issue '
                    f'the materials first.'
                )

            remaining = int(mo.product_qty - mo.qty_produced)
            if remaining > 1:
                # Split off the remainder so only the scanned unit closes.
                # _split_productions keeps `mo` as the first split (qty 1);
                # the new backorder holds the rest and keeps its FIFO slot
                # (same schedule date, later id).
                split_result = mo._split_productions({mo: [1.0, float(remaining - 1)]})
                # x_consolidated_picking_id is copy=False, so the new
                # backorder record loses the link to its real Issue to
                # Production picking. _compute_issue_picking_done() then
                # falls back to "no picking linked -> treat as done" (a rule
                # written for the pre-consolidated-PI flow), which wrongly
                # makes an unissued backorder eligible for FIFO closing on a
                # later scan — producing a unit whose components were never
                # actually received/reserved. Re-propagate the link so the
                # gate still works correctly on the split-off piece.
                backorder = split_result - mo
                if backorder:
                    backorder.x_consolidated_picking_id = mo.x_consolidated_picking_id
                # _split_productions keeps `mo` itself as the first amount
                # (qty 1); the new backorder holds the remainder and keeps
                # its FIFO slot (same schedule date, later id).
                unit_mo = mo
            else:
                unit_mo = mo
            # A fresh lot is being assigned below; exclude this MO from the
            # rest of the batch — its remainder split has a new id and stays
            # eligible automatically.
            used_mo_ids.add(unit_mo.id)

            lot_name = SingleWizard._get_next_lot_serial(unit_mo)
            lot = Lot.create({
                'name':       lot_name,
                'product_id': unit_mo.product_id.id,
                'company_id': unit_mo.company_id.id,
            })
            unit_mo.lot_producing_id = lot
            unit_mo.qty_producing = 1
            lot.write({
                'x_chassis_serial':    line.x_chassis_serial,
                'x_motor_serial':      line.x_motor_serial,
                'x_controller_serial': line.x_controller_serial,
                'x_color':             color.lower(),
                'x_battery_type':      unit_mo.x_battery_type or '',
            })
            # Marks the unit done → post-production QC gate kicks in exactly
            # as in the per-MO flow: Pratik is notified, FG transfer waits
            # for his Pass QC, and pass/fail lands in Bike Traceability.
            unit_mo.with_context(skip_barcode_wizard=True).button_mark_done()
            unit_mo.message_post(
                body=Markup(
                    f"Unit recorded via <b>Global Production Scan</b> by "
                    f"{self.env.user.name} — serial <b>{lot.name}</b> "
                    f"(FIFO deduction, {tmpl.name} / {color})."
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            line.x_lot_id = lot
            produced_lots |= lot

        # Continuous scanning: the window never closes on its own. Reset the
        # rows to a fresh empty batch (per Units to Scan) so the operator can
        # scan the next bike(s) immediately; the last generated serials stay
        # available in the banner and for the Print/TSPL buttons until the
        # operator closes the window.
        self.write({'generated_lot_ids': [(6, 0, produced_lots.ids)]})
        self.line_ids.unlink()
        self._sync_line_count()

        if self.x_auto_print:
            # Fire the label report WITHOUT closing the wizard: report
            # downloads don't close dialogs unless close_on_report_download
            # is set. The form then reloads with the fresh empty rows.
            return self.env.ref(
                'elegomotors_setup.action_report_bike_serial_label'
            ).report_action(produced_lots)
        # Auto-print OFF: just reload — banner + Print Barcode button appear
        return None

    # ------------------------------------------------------------------
    # Label printing
    # ------------------------------------------------------------------

    def action_print_labels(self):
        self.ensure_one()
        if not self.generated_lot_ids:
            raise UserError('No serial numbers generated yet.')
        return self.env.ref(
            'elegomotors_setup.action_report_bike_serial_label'
        ).report_action(self.generated_lot_ids)

    def action_download_tspl(self):
        """Raw TSPL2 command file for the TSC TTP-244 Pro (203 dpi).

        For fully silent printing: pair this .prn download with a small
        watcher on the PC that copies new .prn files to the printer share
        (e.g. `copy /b label.prn \\\\PC\\TSC_TTP244`).
        """
        self.ensure_one()
        if not self.generated_lot_ids:
            raise UserError('No serial numbers generated yet.')
        tspl = self._build_tspl(self.generated_lot_ids)
        attachment = self.env['ir.attachment'].create({
            'name': 'bike_labels_%s.prn' % fields.Datetime.now().strftime('%Y%m%d_%H%M%S'),
            'raw': tspl.encode('utf-8'),
            'mimetype': 'application/octet-stream',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    @api.model
    def _build_tspl(self, lots):
        """TSPL2 for a 75 x 50 mm label at 203 dpi (TSC TTP-244 Pro).

        Layout per label: model + colour header, Code-128 serial barcode
        with human-readable text.
        """
        commands = []
        for lot in lots:
            model_name = lot.product_id.product_tmpl_id.name or lot.product_id.name
            color = (lot.x_color or '').capitalize()
            commands += [
                'SIZE 75 mm, 50 mm',
                'GAP 2 mm, 0 mm',
                'DIRECTION 1',
                'CLS',
                f'TEXT 40,24,"3",0,1,1,"{model_name} {color}"',
                f'BARCODE 40,72,"128",120,1,0,2,2,"{lot.name}"',
                'PRINT 1,1',
            ]
        return '\r\n'.join(commands) + '\r\n'


class GlobalScanWizardLine(models.TransientModel):
    _name = 'elegomotors.global.scan.wizard.line'
    _description = 'Global Production Scan — Bike Row'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'elegomotors.global.scan.wizard', required=True, ondelete='cascade',
    )
    sequence = fields.Integer(default=1)

    x_model_code        = fields.Char(string='Model')
    x_color_code        = fields.Char(string='Colour')
    x_chassis_serial    = fields.Char(string='Chassis No.')
    x_motor_serial      = fields.Char(string='Motor Number')
    x_controller_serial = fields.Char(string='Controller')

    x_resolved_display = fields.Char(
        string='Detected', compute='_compute_resolved_display',
    )
    all_scanned = fields.Boolean(compute='_compute_all_scanned', store=True)
    x_lot_id = fields.Many2one('stock.lot', string='Generated Serial', readonly=True)

    @api.depends('x_model_code', 'x_color_code')
    def _compute_resolved_display(self):
        Wizard = self.env['elegomotors.global.scan.wizard']
        for line in self:
            parts = []
            if line.x_model_code:
                tmpl = Wizard._resolve_model_code(line.x_model_code)
                parts.append(tmpl.name if tmpl else '⚠ unknown model')
            if line.x_color_code:
                color = Wizard._resolve_color_code(line.x_color_code)
                parts.append(color if color else '⚠ unknown colour')
            line.x_resolved_display = ' / '.join(parts)

    @api.depends('x_model_code', 'x_color_code', 'x_chassis_serial',
                 'x_motor_serial', 'x_controller_serial')
    def _compute_all_scanned(self):
        for line in self:
            line.all_scanned = bool(
                line.x_model_code and line.x_color_code
                and line.x_chassis_serial and line.x_motor_serial
                and line.x_controller_serial
            )
