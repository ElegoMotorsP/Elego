# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    qc_state = fields.Selection([
        ('pending', 'Pending QC'),
        ('passed', 'QC Passed'),
        ('failed', 'QC Failed'),
    ], default='pending', string='QC Status', copy=False,
       help="Post-production quality gate. Must be 'passed' before MO can be marked done.")

    mo_flow_state = fields.Selection([
        ('manufactured', 'Manufactured'),
        ('in_qc', 'In QC'),
        ('done', 'Done'),
    ], compute='_compute_mo_flow_state', string='MO QC Flow', store=False, copy=False,
       help="Derived UI flow (Manufactured -> In QC -> Done) based on production state and QC status.")

    # --- Issue 7: show produced serial number in MO list view ---
    x_finished_serial = fields.Char(
        string='Finished Serial No.',
        compute='_compute_finished_serial',
        store=False,
        help='Serial number of the produced unit (from lot_producing_id).',
    )

    # Component serial numbers from the generated lot — shown on MO form after scanning
    x_lot_motor_serial      = fields.Char(related='lot_producing_id.x_motor_serial',      string='Hub Motor S/N',    readonly=True)
    x_lot_battery_serial    = fields.Char(related='lot_producing_id.x_battery_serial',    string='Battery Pack S/N', readonly=True)
    x_lot_controller_serial = fields.Char(related='lot_producing_id.x_controller_serial', string='Controller S/N',   readonly=True)
    x_lot_charger_serial    = fields.Char(related='lot_producing_id.x_charger_serial',    string='Charger S/N',      readonly=True)

    # Req 2: Batch MO reference — links all MOs created together from the batch wizard
    x_batch_mo_ref = fields.Char(
        string='Batch Reference',
        index=True,
        copy=False,
        help='Shared reference for all MOs created together via the Batch Production Order wizard.',
    )

    # --- Issue 8: gate "Produce" actions until Amit validates Issue to Production ---
    x_issue_picking_done = fields.Boolean(
        string='Issue to Production Done',
        compute='_compute_issue_picking_done',
        store=False,
        help='True once all Issue-to-Production pickings are validated by Amit.',
    )

    # --- Req 3: propagate MO creator as Contact on Issue-to-Production picking ---
    def action_confirm(self):
        result = super().action_confirm()
        issue_type = self.env.ref(
            'elegomotors_setup.picking_type_production_issue', raise_if_not_found=False
        )
        if issue_type:
            for prod in self:
                if prod.user_id and prod.user_id.partner_id:
                    issue_pickings = prod.picking_ids.filtered(
                        lambda p: p.picking_type_id == issue_type
                    )
                    issue_pickings.write({'partner_id': prod.user_id.partner_id.id})
        return result

    @api.depends('lot_producing_id')
    def _compute_finished_serial(self):
        for prod in self:
            prod.x_finished_serial = prod.lot_producing_id.name or ''

    def _compute_issue_picking_done(self):
        issue_type = self.env.ref(
            'elegomotors_setup.picking_type_production_issue', raise_if_not_found=False
        )
        for prod in self:
            if not issue_type:
                prod.x_issue_picking_done = True
                continue
            issue_pickings = prod.picking_ids.filtered(
                lambda p: p.picking_type_id == issue_type and p.state != 'cancel'
            )
            if not issue_pickings:
                # No PI picking linked to this MO — this is a backorder MO.
                # The parent MO's PI picking already issued all components to
                # Production WIP; no new PI picking is created for the backorder.
                prod.x_issue_picking_done = True
            else:
                # PI picking exists — must be fully validated before production
                prod.x_issue_picking_done = all(p.state == 'done' for p in issue_pickings)

    @api.depends('state', 'qc_state', 'qty_producing')
    def _compute_mo_flow_state(self):
        for production in self:
            if production.state == 'done':
                # If QC passed: fully done. If pending/failed: unit produced, waiting for QC.
                production.mo_flow_state = 'done' if production.qc_state == 'passed' else 'in_qc'
            elif production.state in ('to_close', 'progress') and production.qty_producing > 0:
                production.mo_flow_state = 'manufactured'
            else:
                production.mo_flow_state = False

    def _qc_state_check(self):
        """Shared guard: QC actions valid in progress/to_close (mid-production) or done (post-production)."""
        self.ensure_one()
        if self.state == 'progress' and self.qty_producing <= 0:
            raise UserError("Set the quantity to produce first before recording QC.")
        if self.state not in ('progress', 'to_close', 'done'):
            raise UserError("QC can only be recorded on an active or completed manufacturing order.")

    def action_qc_pass(self):
        """Pratik approves post-production QC.
        If MO is already done (post-production flow): triggers FG transfer immediately.
        If MO is in to_close/progress (pre-mark-done flow): unblocks Mark as Done.
        """
        self.ensure_one()
        self._qc_state_check()
        self.qc_state = 'passed'
        if self.state == 'done':
            self.message_post(
                body=Markup(
                    f"Post-production QC <b>passed</b> by {self.env.user.name}. "
                    f"Releasing bike to Finished Goods Store."
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            self._auto_move_fg_to_store()
        else:
            self.message_post(
                body=Markup(
                    f"Post-production QC <b>passed</b> by {self.env.user.name}. "
                    f"Click <b>Mark as Done</b> to finalise the MO and release to Finished Goods."
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def action_qc_fail(self):
        """Pratik fails post-production QC. MO stays in progress/to_close for rework."""
        self.ensure_one()
        self._qc_state_check()
        self.qc_state = 'failed'
        # Req 9: blacklist the finished unit's serial so it cannot be sold or re-transferred
        if self.lot_producing_id:
            self.lot_producing_id.x_blacklisted = True
        prashant = self.env.ref(
            'elegomotors_setup.user_ego_prashant', raise_if_not_found=False
        )
        partner_ids = [prashant.partner_id.id] if prashant else []
        serial = self.lot_producing_id.name if self.lot_producing_id else ''
        self.message_post(
            body=Markup(
                f"Post-production QC <b>FAILED</b> by {self.env.user.name}. "
                f"Serial <b>{serial}</b> has been blacklisted. "
                f"Rework required — bike remains in Production WIP. "
                f"Click <b>Reset QC</b> when rework is complete to re-inspect."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def action_qc_reset(self):
        """Reset QC state to pending after rework so Pratik can re-inspect."""
        self.ensure_one()
        self._qc_state_check()
        self.qc_state = 'pending'
        self.message_post(
            body="QC reset to Pending — rework complete, ready for re-inspection.",
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    # --- Issue 8: guard the "Produce" / serial-generation action in Odoo 18 MRP ---
    def action_generate_serial(self):
        """Block lot/serial generation until Issue to Production is validated by Amit.
        For EGO-S1 MOs: intercept and open barcode capture wizard first.
        """
        for prod in self:
            if not prod.x_issue_picking_done and not self.env.su:
                raise UserError(
                    f'{prod.name}: Materials must be issued to Production by Amit '
                    f'(Store) before production quantities can be recorded.'
                )
        if not self.env.context.get('skip_barcode_wizard'):
            ego_tmpl = self.env.ref(
                'elegomotors_setup.tmpl_ego_scooter', raise_if_not_found=False
            )
            self.ensure_one()
            if ego_tmpl and self.product_id.product_tmpl_id == ego_tmpl:
                wizard = self.env['elegomotors.barcode.capture.wizard'].create({
                    'production_id': self.id,
                })
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Scan Component Barcodes',
                    'res_model': 'elegomotors.barcode.capture.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'target': 'new',
                }
        return super().action_generate_serial()

    def button_mark_done(self):
        # Guard 1: only group_manufacturing_operator (Pratik, Prashant) may mark MOs done.
        # Superuser (uid=1) and sudo() environments bypass this so Odoo's own
        # test suite can call button_mark_done without hitting the access guard.
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and not self.env.user.has_group('elegomotors_setup.group_manufacturing_operator')
        ):
            raise AccessError('Only Manufacturing Operators can mark Manufacturing Orders as done.')

        # Guard 2: all linked Picking Slips (Raw Material) must be Done before
        # the MO can be finalised.  In 2-step manufacturing (pbm mode) Odoo
        # auto-creates one Picking Slip per MO confirmation linked via
        # production.picking_ids.  Pratik must wait for Amit to validate the
        # picking (EGO/Store → EGO/Production WIP) before producing.
        for production in self:
            pending = production.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
            )
            if pending:
                names = ', '.join(pending.mapped('name'))
                raise UserError(
                    f'Please complete the Picking Slip (Raw Material) before finalising '
                    f'{production.name}.\nPending transfer(s): {names}'
                )

        result = super().button_mark_done()

        # Post-production QC gate: FG transfer is deferred until Pratik approves QC.
        # qc_state is copy=False so each backorder MO starts at 'pending' automatically,
        # giving every serial unit its own independent QC cycle.
        for production in self:
            if production.state == 'done':
                if production.qc_state == 'passed':
                    # QC was pre-approved (Pass QC clicked before Mark as Done)
                    production._auto_move_fg_to_store()
                else:
                    # QC pending — defer FG transfer, notify Pratik to inspect
                    production._notify_qc_needed()

        return result

    def _notify_qc_needed(self):
        """Post a chatter notification after MO completes, asking Pratik to do QC."""
        pratik = self.env.ref('elegomotors_setup.user_ego_pratik', raise_if_not_found=False)
        partner_ids = [pratik.partner_id.id] if pratik and pratik.partner_id else []
        serial = self.lot_producing_id.name if self.lot_producing_id else ''
        self.message_post(
            body=Markup(
                f"Unit <b>{serial}</b> has been produced and is ready for QC. "
                f"<b>Pratik:</b> Please perform post-production inspection, "
                f"then click <b>Pass QC</b> or <b>Fail QC</b> on this MO."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def _auto_move_fg_to_store(self):
        """Create and immediately validate a 'FG to Finished Goods Store' picking.

        Carries the specific product variant (color) and serial lot_id from the
        finished move — EGO-S1 is serial-tracked with color variants.
        QC was already approved via action_qc_pass(), so no further check needed.
        """
        # Req 9: block FG transfer for blacklisted lots
        if self.lot_producing_id and self.lot_producing_id.x_blacklisted:
            raise UserError(
                f'Lot {self.lot_producing_id.name} is blacklisted due to QC failure. '
                f'Rework is required before releasing to Finished Goods.'
            )
        picking_type = self.env.ref(
            'elegomotors_setup.picking_type_fg_to_stock', raise_if_not_found=False
        )
        if not picking_type:
            return

        # Collect finished move lines from the just-closed MO (state=done, not scrapped)
        finished_lines = self.move_finished_ids.filtered(
            lambda m: m.state == 'done' and not m.scrapped
        ).mapped('move_line_ids')
        if not finished_lines:
            return

        move_vals = [(0, 0, {
            'name': ml.product_id.name,
            'product_id': ml.product_id.id,          # specific variant (e.g. EGO-S1 Red)
            'product_uom_qty': ml.qty_done,
            'product_uom': ml.product_uom_id.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
        }) for ml in finished_lines]

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': self.name,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
            'move_ids': move_vals,
        })
        picking.action_confirm()

        # Do NOT use action_assign() — Odoo MRP may land finished goods at its own
        # virtual output location rather than EGO/Production WIP, so reservation
        # would find nothing and button_validate() would raise "no quantities reserved".
        # Instead, directly create move lines with qty_done to force the transfer.
        for move, src_ml in zip(picking.move_ids, finished_lines):
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': src_ml.product_id.id,
                'product_uom_id': src_ml.product_uom_id.id,
                'qty_done': src_ml.qty_done,
                'lot_id': src_ml.lot_id.id if src_ml.lot_id else False,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
            })

        picking.with_context(skip_immediate=True, skip_backorder=True).button_validate()

        serial_name = finished_lines[0].lot_id.name if finished_lines[0].lot_id else ''
        self.message_post(
            body=Markup(
                f"Bike <b>{serial_name}</b> transferred to Finished Goods — "
                f"<a href='/web#id={picking.id}&model=stock.picking'>{picking.name}</a>"
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )


class MrpBarcodeWizard(models.TransientModel):
    _name = 'elegomotors.barcode.capture.wizard'
    _description = 'Barcode Capture Wizard — EGO-S1 Component Serials'

    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order',
        readonly=True, required=True, ondelete='cascade',
    )
    x_motor_serial      = fields.Char(string='Hub Motor Serial No.')
    x_battery_serial    = fields.Char(string='Battery Pack Serial No.')
    x_controller_serial = fields.Char(string='Motor Controller Serial No.')
    x_charger_serial    = fields.Char(string='Charger Serial No.')

    # Req 4: auto-advance toggle (default True = scanner auto-moves to next field)
    x_auto_scan = fields.Boolean(string='Auto-Advance on Scan', default=True)

    motor_scanned      = fields.Boolean(compute='_compute_scan_progress')
    battery_scanned    = fields.Boolean(compute='_compute_scan_progress')
    controller_scanned = fields.Boolean(compute='_compute_scan_progress')
    charger_scanned    = fields.Boolean(compute='_compute_scan_progress')
    all_scanned        = fields.Boolean(compute='_compute_scan_progress')

    @api.depends('x_motor_serial', 'x_battery_serial', 'x_controller_serial', 'x_charger_serial')
    def _compute_scan_progress(self):
        for rec in self:
            rec.motor_scanned      = bool(rec.x_motor_serial)
            rec.battery_scanned    = bool(rec.x_battery_serial)
            rec.controller_scanned = bool(rec.x_controller_serial)
            rec.charger_scanned    = bool(rec.x_charger_serial)
            rec.all_scanned = bool(
                rec.x_motor_serial and rec.x_battery_serial
                and rec.x_controller_serial and rec.x_charger_serial
            )

    @api.onchange('x_motor_serial', 'x_battery_serial', 'x_controller_serial', 'x_charger_serial')
    def _onchange_barcodes(self):
        self._compute_scan_progress()

    def action_confirm(self):
        self.ensure_one()
        missing = []
        if not self.x_motor_serial:
            missing.append('Hub Motor (250W BLDC)')
        if not self.x_battery_serial:
            missing.append('Battery Pack (48V 20Ah)')
        if not self.x_controller_serial:
            missing.append('Motor Controller (BLDC 48V)')
        if not self.x_charger_serial:
            missing.append('Charger')
        if missing:
            raise UserError(
                'Please scan the following barcodes before confirming:\n'
                + '\n'.join(f'  \u2022 {m}' for m in missing)
            )
        # Req 5: each serial must be unique across all existing lots
        current_lot_id = self.production_id.lot_producing_id.id or 0
        Lot = self.env['stock.lot']
        for field_name, label in [
            ('x_motor_serial',      'Hub Motor'),
            ('x_battery_serial',    'Battery Pack'),
            ('x_controller_serial', 'Motor Controller'),
            ('x_charger_serial',    'Charger'),
        ]:
            val = getattr(self, field_name)
            domain = [(field_name, '=', val)]
            if current_lot_id:
                domain += [('id', '!=', current_lot_id)]
            existing = Lot.search(domain, limit=1)
            if existing:
                raise UserError(
                    f'{label} serial "{val}" is already registered on lot {existing.name}. '
                    f'Please verify the barcode.'
                )
        scanned = [self.x_motor_serial, self.x_battery_serial,
                   self.x_controller_serial, self.x_charger_serial]
        if len(scanned) != len(set(scanned)):
            raise UserError(
                'Duplicate serial numbers detected. '
                'Each component must have a unique serial number.'
            )
        production = self.production_id
        production.with_context(skip_barcode_wizard=True).action_generate_serial()
        lot = production.lot_producing_id
        if lot:
            lot.write({
                'x_motor_serial':      self.x_motor_serial,
                'x_battery_serial':    self.x_battery_serial,
                'x_controller_serial': self.x_controller_serial,
                'x_charger_serial':    self.x_charger_serial,
            })
        return {'type': 'ir.actions.act_window_close'}
