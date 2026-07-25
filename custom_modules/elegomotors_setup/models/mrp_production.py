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
    x_lot_chassis_serial    = fields.Char(related='lot_producing_id.x_chassis_serial',    string='Chassis No.',      readonly=True)
    x_lot_motor_serial      = fields.Char(related='lot_producing_id.x_motor_serial',      string='Hub Motor S/N',    readonly=True)
    x_lot_battery_serial    = fields.Char(related='lot_producing_id.x_battery_serial',    string='Battery Pack S/N', readonly=True)
    x_lot_controller_serial = fields.Char(related='lot_producing_id.x_controller_serial', string='Controller S/N',   readonly=True)
    x_lot_charger_serial    = fields.Char(related='lot_producing_id.x_charger_serial',    string='Charger S/N',      readonly=True)

    # Colour selected in batch MO wizard — stored on MO and copied to the finished lot
    x_color = fields.Selection([
        ('red',   'Red'),
        ('black', 'Black'),
        ('gray',  'Gray'),
        ('white', 'White'),
    ], string='Colour', copy=True)

    # Battery type selected in batch wizard — stored as a label on the MO and lot
    x_battery_type = fields.Char(string='Battery Type', copy=True)

    # Req 2: Batch MO reference — links all MOs created together from the batch wizard
    x_batch_mo_ref = fields.Char(
        string='Batch Reference',
        index=True,
        copy=False,
        help='Shared reference for all MOs created together via the Batch Production Order wizard.',
    )

    # Consolidated Daily PI fields
    x_pi_urgent = fields.Boolean(
        string='Urgent PI',
        default=False,
        copy=False,
        help='When True: a dedicated Issue to Production picking is created immediately on confirm, '
             'bypassing the daily consolidation batch. Amit receives an urgent chatter notification.',
    )
    x_consolidated_picking_id = fields.Many2one(
        'stock.picking',
        string='Daily Issue Picking',
        copy=False,
        readonly=True,
        help='The consolidated daily PI that covers this MO\'s components.',
    )

    # --- Issue 8: gate "Produce" actions until Amit validates Issue to Production ---
    x_issue_picking_done = fields.Boolean(
        string='Issue to Production Done',
        compute='_compute_issue_picking_done',
        store=False,
        help='True once all Issue-to-Production pickings are validated by Amit.',
    )

    # --- Req 3 + Consolidated PI: manage Issue-to-Production picking on confirm ---
    def action_confirm(self):
        result = super().action_confirm()
        issue_type = self.env.ref(
            'elegomotors_setup.picking_type_production_issue', raise_if_not_found=False
        )
        if not issue_type:
            return result
        bike_templates = self._get_ego_templates()
        for prod in self:
            # Propagate MO creator's contact to any auto-created issue picking (Req 3)
            if prod.user_id and prod.user_id.partner_id:
                auto_pickings = prod.picking_ids.filtered(
                    lambda p: p.picking_type_id == issue_type
                )
                auto_pickings.write({'partner_id': prod.user_id.partner_id.id})

            # Only apply consolidated PI logic to EGO bike models
            if prod.product_id.product_tmpl_id not in bike_templates:
                continue

            # Cancel the Odoo-auto-created individual PI — we manage our own PI flow
            auto_pickings = prod.picking_ids.filtered(
                lambda p: p.picking_type_id == issue_type and p.state not in ('done', 'cancel')
            )
            auto_pickings.with_context(skip_immediate=True, skip_backorder=True).action_cancel()

            if prod.x_pi_urgent:
                # Urgent path: create a dedicated PI immediately and notify Amit
                self.env['elegomotors.consolidated.pi.generator']._create_urgent_pi(prod)
            # Non-urgent: x_consolidated_picking_id stays empty until daily cron / manual button

        return result

    def action_request_urgent_pi(self):
        """Request an immediate PI for this MO, bypassing the daily batch.

        Can be called on a confirmed MO that has not yet been assigned a PI
        (i.e. it was confirmed without the Urgent PI flag and is still waiting
        for the next daily cron run). Sets x_pi_urgent=True and creates the
        PI immediately.
        """
        self.ensure_one()
        if self.x_consolidated_picking_id:
            raise UserError(
                f'This MO already has an Issue to Production picking assigned: '
                f'{self.x_consolidated_picking_id.name}.'
            )
        if self.state not in ('confirmed', 'progress'):
            raise UserError(
                'Urgent PI can only be requested for MOs in Confirmed or In Progress state.'
            )
        self.x_pi_urgent = True
        self.env['elegomotors.consolidated.pi.generator']._create_urgent_pi(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Urgent PI Requested',
                'message': f'An urgent Issue to Production picking has been created for {self.name}. Amit has been notified.',
                'type': 'success',
                'sticky': False,
            },
        }

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
            # Primary check: consolidated (or urgent) picking assigned to this MO
            if prod.x_consolidated_picking_id:
                prod.x_issue_picking_done = prod.x_consolidated_picking_id.state == 'done'
                continue
            # Fallback: legacy individual pickings (pre-migration MOs, EGO-S1, backorders)
            issue_pickings = prod.picking_ids.filtered(
                lambda p: p.picking_type_id == issue_type and p.state != 'cancel'
            )
            if not issue_pickings:
                # No PI picking linked to this MO — backorder MO whose parent already issued
                # all components to Production WIP.
                prod.x_issue_picking_done = True
            else:
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

    def _ego_qty_remaining(self):
        """True remaining quantity to produce on this MO (demand - already produced),
        regardless of whatever qty_producing currently holds. Used so the "produce all"
        entry points (Generate Serial / Mark as Done) always default to the full
        remaining batch in a single click instead of requiring a manual quantity edit.
        """
        self.ensure_one()
        remaining = self.product_qty - self.qty_produced
        return int(remaining) if remaining >= 1 else 1

    # --- Issue 8: guard the "Produce" / serial-generation action in Odoo 18 MRP ---
    def action_generate_serial(self):
        """Block lot/serial generation until Issue to Production is validated by Amit.
        For EGO-S1 MOs: intercept and open the barcode capture wizard — single-unit
        form when only one unit remains, bulk table (all remaining units, one click)
        otherwise — instead of Odoo's native single-serial "Generate" wizard.
        """
        for prod in self:
            if not prod.x_issue_picking_done and not self.env.su:
                raise UserError(
                    f'{prod.name}: Materials must be issued to Production by Amit '
                    f'(Store) before production quantities can be recorded.'
                )
        if not self.env.context.get('skip_barcode_wizard'):
            ego_tmpls = self._get_ego_templates()
            self.ensure_one()
            if ego_tmpls and self.product_id.product_tmpl_id in ego_tmpls:
                if self._ego_qty_remaining() > 1:
                    wizard = self.env['elegomotors.bulk.barcode.wizard'].create({
                        'production_ids': [(6, 0, self.ids)],
                    })
                    return {
                        'type': 'ir.actions.act_window',
                        'name': 'Scan Component Barcodes — Bulk Production',
                        'res_model': 'elegomotors.bulk.barcode.wizard',
                        'res_id': wizard.id,
                        'view_mode': 'form',
                        'target': 'new',
                    }
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
        # Skipped under superuser (module installs, demo data, tests) —
        # matches Guards 1 and 3 below. Without this bypass, enabling any
        # Enterprise app whose demo data marks its own unrelated MOs done
        # (e.g. purchase_mrp_workorder_quality) fails at install time,
        # since this guard applied to every mrp.production, not just
        # ElegoMotors bike orders.
        if not self.env.su:
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

        # Guard 2b: for EGO bikes, Issue to Production picking must be validated
        # before production can be finalised. The same guard exists in
        # action_generate_serial(), but button_mark_done() is also reachable
        # directly via the "Mark as Done" button (bypassing action_generate_serial).
        if not self.env.su:
            ego_tmpls_check = self._get_ego_templates()
            if ego_tmpls_check:
                for production in self:
                    if (
                        production.product_id.product_tmpl_id in ego_tmpls_check
                        and not production.x_issue_picking_done
                    ):
                        raise UserError(
                            f'{production.name}: Materials must be issued to Production by Amit '
                            f'(Store) before production can be finalised.'
                        )

        # Guard 3: ElegoMotors bike templates require component serials scanned before
        # marking done. Intercepts any path that skips the barcode wizard.
        if not self.env.su:
            ego_tmpls = self._get_ego_templates()
            if ego_tmpls:
                for production in self:
                    if (
                        production.product_id.product_tmpl_id in ego_tmpls
                        and not production.lot_producing_id
                    ):
                        # True remaining quantity to produce — always defaults to the
                        # full undone batch so "Mark as Done" reaches the bulk (all
                        # units, one click) wizard without a manual quantity edit first.
                        qty_now = production._ego_qty_remaining()
                        if len(self) == 1 and qty_now <= 1:
                            # Single MO, single unit → single-unit form wizard
                            wizard = self.env['elegomotors.barcode.capture.wizard'].create({
                                'production_id': production.id,
                            })
                            return {
                                'type': 'ir.actions.act_window',
                                'name': 'Scan Component Barcodes',
                                'res_model': 'elegomotors.barcode.capture.wizard',
                                'res_id': wizard.id,
                                'view_mode': 'form',
                                'target': 'new',
                            }
                        else:
                            # Multiple units being produced simultaneously, OR multiple MOs
                            # selected → bulk wizard (one row per bike unit across all MOs)
                            if len(self) == 1:
                                mos_for_wizard = production
                            else:
                                mos_for_wizard = self.filtered(
                                    lambda p: p.product_id.product_tmpl_id in ego_tmpls
                                              and not p.lot_producing_id
                                )
                            if mos_for_wizard:
                                wizard = self.env['elegomotors.bulk.barcode.wizard'].create({
                                    'production_ids': [(6, 0, mos_for_wizard.ids)],
                                })
                                return {
                                    'type': 'ir.actions.act_window',
                                    'name': 'Scan Component Barcodes — Bulk Production',
                                    'res_model': 'elegomotors.bulk.barcode.wizard',
                                    'res_id': wizard.id,
                                    'view_mode': 'form',
                                    'target': 'new',
                                }
                            # All EGO-S1 MOs already have lots — fall through to super()

        # Re-assign raw material moves right before consumption. Necessary in
        # particular for units produced via Global Production Scan: FIFO
        # closing splits the MO with _split_productions() *after* the
        # Issue to Production picking (and its own reservation re-assign —
        # see stock_picking.button_validate()) already ran, and the split
        # creates this MO's own move_raw_ids fresh, unreserved. Without this
        # they stay at qty_done=0 and consume nothing on Mark Done even
        # though the components are physically sitting in Production WIP —
        # by this point Guard 1 above has already confirmed the user has
        # manufacturing access (or we're running as su), so no sudo() needed.
        self.move_raw_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        )._action_assign()

        # Skip Odoo's native "Consumption Warning" wizard: EGO bike component
        # traceability is handled via chassis/motor/controller serial scanning,
        # not per-component consumption matching against BOM demand, and this
        # method is routinely driven from automated loops (bulk/single barcode
        # wizards producing several units in one click) where nobody is present
        # to click through a confirmation dialog. If the skip_consumption context
        # doesn't suppress it (e.g. Odoo version differences), fall back to
        # auto-confirming the wizard exactly as the "Confirm" button would.
        result = super(MrpProduction, self.with_context(skip_consumption=True)).button_mark_done()
        if isinstance(result, dict) and result.get('res_model') == 'mrp.consumption.warning':
            warning_wizard = self.env['mrp.consumption.warning'].browse(result.get('res_id'))
            if warning_wizard:
                warning_wizard.action_confirm()

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

    def _get_ego_templates(self):
        """Return a recordset of all ElegoMotors bike product templates."""
        refs = [
            'elegomotors_setup.tmpl_ego_scooter',
            'elegomotors_setup.tmpl_elego_11',
            'elegomotors_setup.tmpl_elego_12',
            'elegomotors_setup.tmpl_elego_20p',
            'elegomotors_setup.tmpl_elego_30',
        ]
        result = self.env['product.template']
        for ref in refs:
            tmpl = self.env.ref(ref, raise_if_not_found=False)
            if tmpl:
                result |= tmpl
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
    x_chassis_serial    = fields.Char(string='Chassis No. (Frame Plate)')
    x_motor_serial      = fields.Char(string='Hub Motor Serial No.')
    x_controller_serial = fields.Char(string='Motor Controller Serial No.')
    x_battery_serial    = fields.Char(string='Battery Pack Serial No. (optional)')
    x_charger_serial    = fields.Char(string='Charger Serial No. (optional)')

    # Req 4: auto-advance toggle (default True = scanner auto-moves to next field)
    x_auto_scan = fields.Boolean(string='Auto-Advance on Scan', default=True)

    chassis_scanned    = fields.Boolean(compute='_compute_scan_progress')
    motor_scanned      = fields.Boolean(compute='_compute_scan_progress')
    controller_scanned = fields.Boolean(compute='_compute_scan_progress')
    battery_scanned    = fields.Boolean(compute='_compute_scan_progress')
    charger_scanned    = fields.Boolean(compute='_compute_scan_progress')
    all_scanned        = fields.Boolean(compute='_compute_scan_progress')

    @api.depends('x_chassis_serial', 'x_motor_serial', 'x_controller_serial', 'x_battery_serial', 'x_charger_serial')
    def _compute_scan_progress(self):
        for rec in self:
            rec.chassis_scanned    = bool(rec.x_chassis_serial)
            rec.motor_scanned      = bool(rec.x_motor_serial)
            rec.controller_scanned = bool(rec.x_controller_serial)
            rec.battery_scanned    = bool(rec.x_battery_serial)
            rec.charger_scanned    = bool(rec.x_charger_serial)
            # Battery and charger are optional — only chassis + motor + controller required
            rec.all_scanned = bool(
                rec.x_chassis_serial and rec.x_motor_serial and rec.x_controller_serial
            )

    @api.onchange('x_chassis_serial', 'x_motor_serial', 'x_controller_serial', 'x_battery_serial', 'x_charger_serial')
    def _onchange_barcodes(self):
        self._compute_scan_progress()

    def _get_next_lot_serial(self, production):
        """Return the next auto-generated serial name for this bike template.

        Format: <model prefix>-<YYMM>-<global counter>, where the counter is
        SHARED across all bike models/variants and never resets — the trailing
        number of the newest serial in Bike Traceability therefore always
        equals the total number of units the company has produced.
        e.g. EL11-2607-0001, then an Elego 1.2 produced next gets
        EL12-2607-0002. (The old per-model monthly sequences are retained
        only for serials issued before this change.)
        """
        prefix_map = [
            ('elegomotors_setup.tmpl_ego_scooter', 'EGO-S1'),
            ('elegomotors_setup.tmpl_elego_11',    'EL11'),
            ('elegomotors_setup.tmpl_elego_12',    'EL12'),
            ('elegomotors_setup.tmpl_elego_20p',   'EL20P'),
            ('elegomotors_setup.tmpl_elego_30',    'EL30'),
        ]
        tmpl = production.product_id.product_tmpl_id
        for tmpl_ref, prefix in prefix_map:
            t = self.env.ref(tmpl_ref, raise_if_not_found=False)
            if t and tmpl == t:
                number = self.env['ir.sequence'].sudo().next_by_code(
                    'elego.global.serial'
                )
                if not number:
                    raise UserError(
                        'Global bike serial counter (elego.global.serial) is '
                        'missing. Contact your administrator.'
                    )
                yymm = fields.Datetime.now().strftime('%y%m')
                return f'{prefix}-{yymm}-{number}'
        raise UserError(
            f'No serial number sequence configured for product "{production.product_id.name}". '
            f'Contact your administrator.'
        )

    def action_confirm(self):
        self.ensure_one()
        missing = []
        if not self.x_chassis_serial:
            missing.append('Chassis No. (Frame Plate)')
        if not self.x_motor_serial:
            missing.append('Hub Motor')
        if not self.x_controller_serial:
            missing.append('Motor Controller')
        if missing:
            raise UserError(
                'Please scan the following barcodes before confirming:\n'
                + '\n'.join(f'  \u2022 {m}' for m in missing)
            )

        production = self.production_id
        Lot = self.env['stock.lot']

        # Chassis plate number must be globally unique
        existing_chassis = Lot.search([('x_chassis_serial', '=', self.x_chassis_serial)], limit=1)
        if existing_chassis:
            raise UserError(
                f'Chassis number "{self.x_chassis_serial}" is already registered on '
                f'serial {existing_chassis.name}. Please verify the frame plate barcode.'
            )

        # Required component serials must be unique
        for field_name, label in [
            ('x_motor_serial',      'Hub Motor'),
            ('x_controller_serial', 'Motor Controller'),
        ]:
            val = getattr(self, field_name)
            existing = Lot.search([(field_name, '=', val)], limit=1)
            if existing:
                raise UserError(
                    f'{label} serial "{val}" is already registered on serial '
                    f'{existing.name}. Please verify the barcode.'
                )

        # Optional serials: only check uniqueness if provided
        for field_name, label in [
            ('x_battery_serial', 'Battery Pack'),
            ('x_charger_serial', 'Charger'),
        ]:
            val = getattr(self, field_name)
            if val:
                existing = Lot.search([(field_name, '=', val)], limit=1)
                if existing:
                    raise UserError(
                        f'{label} serial "{val}" is already registered on serial '
                        f'{existing.name}. Please verify the barcode.'
                    )

        # No duplicate serials within this wizard (only non-empty values)
        scanned_values = [v for v in [
            self.x_chassis_serial, self.x_motor_serial, self.x_controller_serial,
            self.x_battery_serial, self.x_charger_serial,
        ] if v]
        if len(scanned_values) != len(set(scanned_values)):
            raise UserError(
                'Duplicate serial numbers detected. '
                'Each component must have a unique serial number.'
            )

        # Auto-generate the bike serial number from the model sequence
        lot_name = self._get_next_lot_serial(production)
        lot = Lot.create({
            'name':       lot_name,
            'product_id': production.product_id.id,
            'company_id': production.company_id.id,
        })
        production.lot_producing_id = lot
        production.qty_producing    = 1

        # Auto-derive color from product variant if not explicitly set on the MO
        color = production.x_color or ''
        if not color:
            for ptav in production.product_id.product_template_attribute_value_ids:
                if ptav.attribute_id.name == 'Color':
                    color = ptav.product_attribute_value_id.name.lower()
                    break

        lot.write({
            'x_chassis_serial':    self.x_chassis_serial,
            'x_motor_serial':      self.x_motor_serial,
            'x_controller_serial': self.x_controller_serial,
            'x_battery_serial':    self.x_battery_serial or '',
            'x_charger_serial':    self.x_charger_serial or '',
            'x_color':             color,
            'x_battery_type':      production.x_battery_type or '',
        })
        production.with_context(skip_barcode_wizard=True).button_mark_done()
        return {'type': 'ir.actions.act_window_close'}
