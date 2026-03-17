# -*- coding: utf-8 -*-
import logging
from markupsafe import Markup
from odoo import models, fields, api, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # ── Custom elego workflow state ──────────────────────────────────────────
    elego_state = fields.Selection([
        ('draft',         'Draft'),
        ('confirmed',     'Confirmed'),
        ('mat_requested', 'Material Requested'),
        ('mat_issued',    'Material Issued'),
        ('mat_received',  'Material Received'),
        ('in_production', 'In Production'),
        ('done',          'Done'),
    ], string='Production State', default='draft',
       tracking=True, copy=False,
       help='ElegoMotors material issuance handoff state. Tracks the '
            'Store → Production floor handoff before manufacturing begins.')

    # ── Linked Issue-to-Production pickings ─────────────────────────────────
    issue_picking_ids = fields.One2many(
        'stock.picking', 'elego_mo_id',
        string='Issue Transfers',
    )
    issue_picking_count = fields.Integer(
        compute='_compute_issue_picking_count',
        string='Issue Transfers',
    )
    all_components_issued = fields.Boolean(
        compute='_compute_all_components_issued',
        string='All Components Issued',
    )

    @api.depends('issue_picking_ids', 'issue_picking_ids.state')
    def _compute_issue_picking_count(self):
        for mo in self:
            mo.issue_picking_count = len(mo.issue_picking_ids)

    @api.depends('issue_picking_ids', 'issue_picking_ids.state')
    def _compute_all_components_issued(self):
        for mo in self:
            pickings = mo.issue_picking_ids
            mo.all_components_issued = bool(pickings) and all(
                p.state == 'done' for p in pickings
            )

    # ── State transition: confirm → mat_requested ────────────────────────────
    def action_request_material(self):
        """Auto-called on MO confirm. Creates Issue picking and notifies Store."""
        try:
            self._auto_create_issue_picking()
        except Exception:
            _logger.exception(
                "elegomotors: _auto_create_issue_picking failed for MO(s) %s",
                self.mapped('name'),
            )
        # State write is unconditional — picking creation failure must not block it
        self.write({'elego_state': 'mat_requested'})
        try:
            self.message_post(
                body=Markup(
                    '<b>Material request sent to Store.</b><br/>'
                    'Amit, please prepare the components and validate the '
                    '<b>Issue to Production</b> transfer in Inventory, '
                    'then click <b>Mark Material Issued</b> on this order.'
                ),
                subtype_xmlid='mail.mt_note',
            )
        except Exception:
            _logger.warning(
                "elegomotors: message_post failed for MO(s) %s",
                self.mapped('name'),
            )

    # ── State transition: mat_requested → mat_issued (Amit) ──────────────────
    def action_mark_material_issued(self):
        """Amit confirms all components have been dispatched to the floor."""
        if not self.all_components_issued:
            raise UserError(
                'The Issue-to-Production transfer must be validated (Done) '
                'before marking materials as issued.\n\n'
                'Please go to Inventory → Issue to Production, validate the '
                'transfer, then return here to click this button.'
            )
        self.write({'elego_state': 'mat_issued'})
        self.message_post(
            body=Markup(
                '<b>Materials issued to production by Store (Amit).</b><br/>'
                'Pratik, the components are on the production floor. '
                'Please click <b>Acknowledge Material Received</b> to confirm receipt.'
            ),
            subtype_xmlid='mail.mt_note',
        )

    # ── State transition: mat_issued → mat_received (Pratik) ─────────────────
    def action_acknowledge_material_received(self):
        """Pratik confirms components have been received on the production floor."""
        if self.elego_state != 'mat_issued':
            state_label = dict(
                self._fields['elego_state'].selection
            ).get(self.elego_state, self.elego_state)
            raise UserError(
                'Materials must be marked as issued by Store before you can '
                'acknowledge receipt.\n\n'
                f'Current state: {state_label}'
            )
        self.write({'elego_state': 'mat_received'})
        self.message_post(
            body=Markup(
                '<b>Material receipt acknowledged by Production (Pratik).</b><br/>'
                'Manufacturing can now begin. Click <b>Produce All</b> to proceed.'
            ),
            subtype_xmlid='mail.mt_note',
        )

    # ── Smart button: open linked Issue transfers ─────────────────────────────
    def action_view_issue_transfers(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Issue Transfers',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.issue_picking_ids.ids)],
            'context': {'default_elego_mo_id': self.id},
        }

    # ── Override button_mark_done: enforce two gates ──────────────────────────
    def button_mark_done(self):
        # Gate 1 (existing): Only Manufacturing Operator group (Pratik)
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and not self.env.user.has_group(
                'elegomotors_setup.group_manufacturing_operator'
            )
        ):
            raise AccessError(
                'Only Manufacturing Operators can mark Manufacturing Orders as done.'
            )

        # Gate 2 (new): Material must be acknowledged by Pratik first
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and self.elego_state not in ('mat_received', 'in_production', 'done')
        ):
            state_label = dict(
                self._fields['elego_state'].selection
            ).get(self.elego_state, self.elego_state)
            raise UserError(
                'Cannot produce: the material handoff is incomplete.\n\n'
                'Required steps:\n'
                '  1. Amit must validate the Issue-to-Production transfer\n'
                '  2. Amit must click "Mark Material Issued" on this order\n'
                '  3. Pratik must click "Acknowledge Material Received"\n\n'
                f'Current state: {state_label}'
            )

        self.write({'elego_state': 'in_production'})
        result = super().button_mark_done()
        # Advance to done if Odoo's native state reached 'done'
        for mo in self:
            if mo.state == 'done' and mo.elego_state != 'done':
                mo.elego_state = 'done'
        return result

    # ── Override action_confirm ───────────────────────────────────────────────
    def action_confirm(self):
        result = super().action_confirm()
        # Flush all pending ORM writes to the DB cursor, then invalidate the
        # cache so _auto_create_issue_picking reads the moves just created by
        # super().action_confirm() rather than the pre-confirm empty state.
        self.env.flush_all()
        self.invalidate_recordset()
        for mo in self.filtered(lambda m: m.state == 'confirmed'):
            if mo.elego_state in ('draft', 'confirmed'):
                mo.write({'elego_state': 'confirmed'})
                mo.action_request_material()
        return result

    # ── Auto-create Issue-to-Production picking ───────────────────────────────
    def _auto_create_issue_picking(self):
        """Create an Issue-to-Production (PI) picking for every MO that does
        not yet have one. Called by action_request_material on confirm.
        """
        IssueType = self.env['stock.picking.type'].search(
            [('sequence_code', '=', 'PI'), ('active', '=', True)],
            limit=1,
        )
        if not IssueType:
            return

        for mo in self:
            if mo.issue_picking_ids:
                continue  # idempotent: don't create duplicates

            # Read raw material moves — try ORM first, fall back to direct SQL
            # to handle cases where the ORM cache hasn't caught up to the DB yet
            # (super().action_confirm() writes moves; flush_all may not be enough)
            orm_moves = mo.move_raw_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
            )
            if not orm_moves:
                self.env.cr.execute(
                    """
                    SELECT id FROM stock_move
                    WHERE raw_material_production_id = %s
                      AND state NOT IN ('done', 'cancel')
                    """,
                    (mo.id,),
                )
                sql_ids = [r[0] for r in self.env.cr.fetchall()]
                orm_moves = self.env['stock.move'].browse(sql_ids)

            move_vals = []
            for move in orm_moves:
                move_vals.append((0, 0, {
                    'name': move.product_id.display_name,
                    'product_id': move.product_id.id,
                    'product_uom_qty': move.product_uom_qty,
                    'product_uom': move.product_uom.id,
                    'location_id': IssueType.default_location_src_id.id,
                    'location_dest_id': IssueType.default_location_dest_id.id,
                    'origin': mo.name,
                }))

            if not move_vals:
                continue

            picking = self.env['stock.picking'].create({
                'picking_type_id': IssueType.id,
                'location_id': IssueType.default_location_src_id.id,
                'location_dest_id': IssueType.default_location_dest_id.id,
                'elego_mo_id': mo.id,
                'origin': mo.name,
                'move_ids': move_vals,
            })
            picking.action_confirm()
            picking.action_assign()  # reserve if stock available
