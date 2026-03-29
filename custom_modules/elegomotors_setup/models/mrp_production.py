# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    ego_unit_quality_check_ids = fields.One2many(
        'quality.check',
        'ego_mrp_production_id',
        string='Unit QC checks',
        copy=False,
    )

    ego_unit_qc_count = fields.Integer(
        compute='_compute_ego_unit_qc_count',
        string='Unit QC count',
    )

    qc_state = fields.Selection([
        ('pending', 'Pending QC'),
        ('passed', 'QC Passed'),
        ('failed', 'QC Failed'),
    ], compute='_compute_qc_state', string='QC Status', store=True, copy=False,
       help="Aggregate post-production QC from per-unit quality checks (serial FG).")

    mo_flow_state = fields.Selection([
        ('manufactured', 'Manufactured'),
        ('in_qc', 'In QC'),
        ('done', 'Done'),
    ], compute='_compute_mo_flow_state', string='MO QC Flow', store=False, copy=False,
       help="Manufactured / In QC / Done from production state and unit QC progress.")

    @api.depends('ego_unit_quality_check_ids')
    def _compute_ego_unit_qc_count(self):
        for prod in self:
            prod.ego_unit_qc_count = len(prod.ego_unit_quality_check_ids)

    def action_ego_view_unit_quality_checks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Unit QC checks',
            'res_model': 'quality.check',
            'domain': [('ego_mrp_production_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_ego_mrp_production_id': self.id},
        }

    def _ego_finished_serial_move_lines(self):
        self.ensure_one()
        return self.move_finished_ids.filtered(
            lambda m: m.product_id == self.product_id and not m.scrapped
        ).mapped('move_line_ids').filtered(
            lambda ml: ml.qty_done and ml.lot_id and ml.product_id.tracking == 'serial'
        )

    def _ego_has_pending_unit_qc(self):
        self.ensure_one()
        lines = self._ego_finished_serial_move_lines()
        if not lines:
            return False
        checks = self.ego_unit_quality_check_ids
        by_lot = {c.lot_id.id: c for c in checks if c.lot_id}
        for line in lines:
            c = by_lot.get(line.lot_id.id)
            if not c or c.quality_state != 'pass':
                return True
        return False

    @api.depends(
        'ego_unit_quality_check_ids.quality_state',
        'ego_unit_quality_check_ids.lot_id',
        'qty_produced',
        'product_qty',
        'product_id',
        'product_uom_id',
        'state',
        'move_finished_ids.move_line_ids.qty_done',
        'move_finished_ids.move_line_ids.lot_id',
    )
    def _compute_qc_state(self):
        for prod in self:
            if prod.product_id.tracking == 'serial':
                checks = prod.ego_unit_quality_check_ids
                if any(c.quality_state == 'fail' for c in checks):
                    prod.qc_state = 'failed'
                    continue
                lines = prod._ego_finished_serial_move_lines()
                if not lines:
                    prod.qc_state = 'pending'
                    continue
                if float_compare(
                    prod.qty_produced,
                    prod.product_qty,
                    precision_rounding=prod.product_uom_id.rounding,
                ) < 0:
                    prod.qc_state = 'pending'
                    continue
                by_lot = {c.lot_id.id: c for c in checks if c.lot_id}
                ok = True
                for line in lines:
                    c = by_lot.get(line.lot_id.id)
                    if not c or c.quality_state != 'pass':
                        ok = False
                        break
                prod.qc_state = 'passed' if ok else 'pending'
            else:
                if prod.ego_unit_quality_check_ids:
                    checks = prod.ego_unit_quality_check_ids
                    if any(c.quality_state == 'fail' for c in checks):
                        prod.qc_state = 'failed'
                    elif all(c.quality_state == 'pass' for c in checks):
                        prod.qc_state = 'passed'
                    else:
                        prod.qc_state = 'pending'
                else:
                    if float_compare(
                        prod.qty_produced,
                        prod.product_qty,
                        precision_rounding=prod.product_uom_id.rounding,
                    ) >= 0 and prod.state in ('to_close', 'done', 'progress'):
                        prod.qc_state = 'passed'
                    else:
                        prod.qc_state = 'pending'

    @api.depends('state', 'qc_state', 'qty_produced', 'move_finished_ids.move_line_ids.qty_done')
    def _compute_mo_flow_state(self):
        for production in self:
            if production.state == 'done':
                production.mo_flow_state = 'done'
            elif production.state == 'progress':
                production.mo_flow_state = (
                    'in_qc' if production._ego_has_pending_unit_qc() else 'manufactured'
                )
            elif production.state == 'to_close':
                production.mo_flow_state = 'in_qc'
            else:
                production.mo_flow_state = False

    def action_qc_pass(self):
        """Pass all pending per-unit quality checks (bulk)."""
        self.ensure_one()
        if self.state != 'to_close':
            raise UserError(
                "QC can only be recorded when production is complete (state: To Close)."
            )
        pending = self.ego_unit_quality_check_ids.filtered(
            lambda c: c.quality_state not in ('pass', 'fail')
        )
        if pending:
            pending.sudo().write({'quality_state': 'pass'})
        self.invalidate_recordset(['qc_state', 'mo_flow_state'])
        self.message_post(
            body=Markup(
                f"Post-production unit QC <b>passed</b> (bulk) by {self.env.user.name}. "
                f"Click <b>Mark as Done</b> when ready to finalise the MO."
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def action_qc_fail(self):
        self.ensure_one()
        if self.state != 'to_close':
            raise UserError("QC can only be recorded when production is complete.")
        pending = self.ego_unit_quality_check_ids.filtered(
            lambda c: c.quality_state not in ('pass', 'fail')
        )
        if pending:
            pending.sudo().write({'quality_state': 'fail'})
        self.invalidate_recordset(['qc_state', 'mo_flow_state'])
        prashant = self.env.ref(
            'elegomotors_setup.user_ego_prashant', raise_if_not_found=False
        )
        partner_ids = [prashant.partner_id.id] if prashant else []
        self.message_post(
            body=Markup(
                f"Post-production QC <b>FAILED</b> (unit checks) by {self.env.user.name}. "
                f"Rework required — reset failed checks in Quality when ready to re-inspect."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def action_qc_reset(self):
        self.ensure_one()
        if self.state != 'to_close':
            raise UserError("Can only reset QC on an MO that is in 'To Close' state.")
        failed = self.ego_unit_quality_check_ids.filtered(
            lambda c: c.quality_state == 'fail'
        )
        if failed:
            failed.sudo().write({'quality_state': 'none'})
        self.invalidate_recordset(['qc_state', 'mo_flow_state'])
        self.message_post(
            body="QC reset on failed unit checks — rework complete, ready for re-inspection.",
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def button_mark_done(self):
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and not self.env.user.has_group('elegomotors_setup.group_manufacturing_operator')
        ):
            raise AccessError('Only Manufacturing Operators can mark Manufacturing Orders as done.')

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

        for production in self:
            rounding = production.product_uom_id.rounding
            if float_compare(
                production.qty_produced,
                production.product_qty,
                precision_rounding=rounding,
            ) < 0:
                raise UserError(
                    f'{production.name}: Cannot mark done until the full ordered quantity '
                    f'is produced ({production.product_qty} {production.product_uom_id.name}).'
                )

        for production in self:
            if production.product_id.tracking == 'serial':
                lines = production._ego_finished_serial_move_lines()
                checks = production.ego_unit_quality_check_ids
                by_lot = {c.lot_id.id: c for c in checks if c.lot_id}
                for line in lines:
                    c = by_lot.get(line.lot_id.id)
                    if not c:
                        raise UserError(
                            f'{production.name}: Missing post-production quality check for '
                            f'serial {line.lot_id.name}.'
                        )
                    if c.quality_state != 'pass':
                        raise UserError(
                            f'{production.name}: Serial {line.lot_id.name} is not QC passed '
                            f'(state: {c.quality_state}).'
                        )
                if any(c.quality_state == 'fail' for c in checks):
                    raise UserError(
                        f'{production.name}: One or more unit QC checks failed — resolve before '
                        f'marking done.'
                    )

        for production in self:
            if production.qc_state != 'passed':
                state_label = dict(
                    production._fields['qc_state'].selection
                ).get(production.qc_state, production.qc_state)
                raise UserError(
                    f'{production.name}: Post-production QC is \'{state_label}\'. '
                    f'Complete per-unit QC (Pass) before marking done.'
                )

        result = super().button_mark_done()

        for production in self:
            if production.state == 'done':
                production._auto_move_fg_to_store()

        return result

    def _auto_move_fg_to_store(self):
        picking_type = self.env.ref(
            'elegomotors_setup.picking_type_fg_to_stock', raise_if_not_found=False
        )
        if not picking_type:
            return

        finished_lines = self.move_finished_ids.filtered(
            lambda m: m.state == 'done' and not m.scrapped
        ).mapped('move_line_ids')
        if not finished_lines:
            return

        move_vals = [(0, 0, {
            'name': ml.product_id.name,
            'product_id': ml.product_id.id,
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
        picking.action_assign()

        for ml, src_ml in zip(picking.move_line_ids, finished_lines):
            ml.qty_done = src_ml.qty_done
            ml.lot_id = src_ml.lot_id

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
