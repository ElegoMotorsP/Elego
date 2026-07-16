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

    # --- Issue 8: gate "Produce" actions until Amit validates Issue to Production ---
    x_issue_picking_done = fields.Boolean(
        string='Issue to Production Done',
        compute='_compute_issue_picking_done',
        store=False,
        help='True once all Issue-to-Production pickings are validated by Amit.',
    )

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
                production.mo_flow_state = 'done'
            elif production.state in ('to_close', 'progress') and production.qty_producing > 0:
                # progress + qty_producing > 0 = multi-unit MO with one unit ready for QC
                production.mo_flow_state = (
                    'manufactured'
                    if production.qc_state == 'pending'
                    else 'in_qc'
                )
            else:
                production.mo_flow_state = False

    def _qc_state_check(self):
        """Shared guard: QC actions valid in progress (unit ready) or to_close."""
        self.ensure_one()
        if self.state == 'progress' and self.qty_producing <= 0:
            raise UserError("Set the quantity to produce first before recording QC.")
        if self.state not in ('progress', 'to_close'):
            raise UserError("QC can only be recorded when a unit is being produced.")

    def action_qc_pass(self):
        """Pratik approves post-production QC. Unblocks button_mark_done."""
        self.ensure_one()
        self._qc_state_check()
        self.qc_state = 'passed'
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
        prashant = self.env.ref(
            'elegomotors_setup.user_ego_prashant', raise_if_not_found=False
        )
        partner_ids = [prashant.partner_id.id] if prashant else []
        self.message_post(
            body=Markup(
                f"Post-production QC <b>FAILED</b> by {self.env.user.name}. "
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
        """Block lot/serial generation until Issue to Production is validated by Amit."""
        for prod in self:
            if not prod.x_issue_picking_done and not self.env.su:
                raise UserError(
                    f'{prod.name}: Materials must be issued to Production by Amit '
                    f'(Store) before production quantities can be recorded.'
                )
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

        # Guard 3: post-production QC must be approved by Pratik before closing.
        # qc_state is copy=False so each backorder MO starts at 'pending' automatically,
        # giving every serial unit its own QC cycle.
        for production in self:
            if production.qc_state != 'passed':
                state_label = dict(
                    production._fields['qc_state'].selection
                ).get(production.qc_state, production.qc_state)
                raise UserError(
                    f'{production.name}: Post-production QC is \'{state_label}\'. '
                    f'Pratik must click \'Pass QC\' before marking done.'
                )

        result = super().button_mark_done()

        # Auto-create + validate the FG picking (Production WIP → Finished Goods Store).
        # Runs only after super() succeeds and MO is in 'done' state.
        for production in self:
            if production.state == 'done':
                production._auto_move_fg_to_store()

        return result

    def _auto_move_fg_to_store(self):
        """Create and immediately validate a 'FG to Finished Goods Store' picking.

        Carries the specific product variant (color) and serial lot_id from the
        finished move — EGO-S1 is serial-tracked with color variants.
        QC was already approved via action_qc_pass(), so no further check needed.
        """
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
