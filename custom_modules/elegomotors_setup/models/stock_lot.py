# -*- coding: utf-8 -*-
import json
from urllib.parse import quote

from markupsafe import Markup
from odoo import api, models, fields
from odoo.exceptions import AccessError, UserError


class StockLot(models.Model):
    """Extend stock.lot (serial/lot number records) with component serial fields.

    When Pratik produces a finished EGO-S1 scooter, each unit is assigned an
    auto-generated serial number (e.g. EGO-S1-2503-0001).  After physically
    assembling the bike, Pratik scans the barcode on each warranty-critical
    component and records the serial here.

    These five components move through inventory as plain quantities (tracking='none')
    because their serial numbers are not known until post-assembly scanning.  The
    custom fields on this record are the source of truth for unit-level traceability.

    Use cases:
      - Warranty claim  : look up bike serial → see exact motor / battery serial
      - Part replacement: identify which motor serial is in the bike needing service
      - Reverse lookup  : search x_motor_serial = 'MOT-001' → find which bike
    """
    _inherit = 'stock.lot'

    x_chassis_serial    = fields.Char(string='Chassis No. (Frame Plate)',     index=True)
    x_motor_serial      = fields.Char(string='Hub Motor Serial No.',          index=True)
    x_battery_serial    = fields.Char(string='Battery Pack Serial No.',       index=True)
    x_controller_serial = fields.Char(string='Motor Controller Serial No.',   index=True)
    x_charger_serial    = fields.Char(string='Charger Serial No.',            index=True)
    x_cluster_serial    = fields.Char(string='Instrument Cluster Serial No.', index=True)
    x_frame_serial      = fields.Char(string='Frame Assembly Serial No.',     index=True)
    x_color             = fields.Char(string='Colour',                        index=True)
    x_battery_type      = fields.Char(string='Battery Type',                  index=True)
    x_blacklisted       = fields.Boolean(
        string='Blacklisted (QC Fail)',
        default=False,
        index=True,
        help='Set to True when this serial/lot has failed QC. Prevents sale or store transfer.',
    )

    x_is_unbuilt = fields.Boolean(
        string='Unbuilt',
        compute='_compute_x_is_unbuilt', search='_search_x_is_unbuilt',
        help='The bike went through a done Unbuild Order and no unit is on hand '
             'any more. Bike Traceability hides these by default.',
    )

    # --- Finance partner API (Bajaj Finance serial validation) ---
    x_bfl_validated = fields.Boolean(
        string='Finance API Validated',
        default=False,
        copy=False,
        index=True,
        help='Set to True the first time this serial passes the Bajaj Finance '
             'serial-validation API. Later calls for the same serial return '
             '"Serial Number Already Validated" instead of re-validating.',
    )
    x_bfl_validated_date = fields.Datetime(
        string='Finance API Validated On', copy=False,
    )

    # --- PDI (Pre-Delivery Inspection) ---
    x_pdi_state = fields.Selection([
        ('pending', 'Pending PDI'),
        ('passed', 'PDI Passed'),
        ('failed', 'PDI Failed'),
    ], string='PDI Status', default='pending', copy=False,
       help='Pre-Delivery Inspection gate. Outgoing delivery cannot be validated '
            'for this bike until PDI is Passed.')
    x_pdi_checked_date = fields.Datetime(string='PDI Checked On', copy=False)
    x_pdi_check_result_ids = fields.One2many(
        'elegomotors.pdi.check.result', 'lot_id',
        string='PDI Checklist',
        copy=False,
    )

    # --- Master Traceability Report: full MO -> QC -> SO -> Delivery ->
    # Invoice -> Dealer chain for this bike, computed in one batched pass
    # (see _compute_trace_fields) rather than as stored/related fields,
    # since there is no forward relation from stock.lot to any of these
    # documents to declare as an @api.depends trigger.
    x_mo_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', compute='_compute_trace_fields',
    )
    x_mo_date = fields.Datetime(string='MO Date', compute='_compute_trace_fields')
    x_qc_status = fields.Char(string='QC Status', compute='_compute_trace_fields')
    x_qc_no = fields.Char(string='QC No.', compute='_compute_trace_fields')
    x_delivery_id = fields.Many2one(
        'stock.picking', string='Delivery Out', compute='_compute_trace_fields',
    )
    x_delivery_date = fields.Datetime(string='Delivery Out Date', compute='_compute_trace_fields')
    x_so_id = fields.Many2one('sale.order', string='Sales Order', compute='_compute_trace_fields')
    x_invoice_id = fields.Many2one(
        'account.move', string='Invoice', compute='_compute_trace_fields',
    )
    x_invoice_date = fields.Date(string='Invoice Date', compute='_compute_trace_fields')
    x_dealer_id = fields.Many2one('res.partner', string='Dealer', compute='_compute_trace_fields')
    x_dealer_address = fields.Char(string='Dealer Delivery Address', compute='_compute_trace_fields')

    # Serial-Number-Wise Bike Unbuild & Rebuild
    x_unbuild_id = fields.Many2one(
        'mrp.unbuild', string='Unbuild Order', compute='_compute_unbuild_rebuild',
        help='The most recent Unbuild Order that took this bike serial apart, if any.',
    )
    x_rebuild_mo_id = fields.Many2one(
        'mrp.production', string='Rebuild MO', compute='_compute_unbuild_rebuild',
        help='The MO auto-created to rebuild this bike after it was unbuilt, if any.',
    )

    def _compute_unbuild_rebuild(self):
        unbuilds = self.env['mrp.unbuild'].search(
            [('lot_id', 'in', self.ids)], order='id desc'
        )
        unbuild_by_lot = {}
        for unbuild in unbuilds:
            unbuild_by_lot.setdefault(unbuild.lot_id.id, unbuild)
        for lot in self:
            unbuild = unbuild_by_lot.get(lot.id)
            lot.x_unbuild_id = unbuild.id if unbuild else False
            lot.x_rebuild_mo_id = unbuild.x_rebuild_mo_id.id if unbuild else False

    def action_view_unbuild_order(self):
        self.ensure_one()
        if not self.x_unbuild_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'name': 'Unbuild Order',
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.unbuild',
            'view_mode': 'form',
            'res_id': self.x_unbuild_id.id,
        }

    def action_view_rebuild_mo(self):
        self.ensure_one()
        if not self.x_rebuild_mo_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'name': 'Rebuild Manufacturing Order',
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': self.x_rebuild_mo_id.id,
        }

    def action_unbuild_bike(self):
        """Entry point for the Serial-Number-Wise Bike Unbuild & Rebuild flow:
        creates and opens an Unbuild Order pre-filled for this bike serial,
        sourced from wherever it currently has stock and destined for
        Production WIP. Restricted via the button's view groups and enforced
        again in mrp.unbuild.create() (elegomotors_setup.group_unbuild_rebuild_operator)."""
        self.ensure_one()
        if not self.product_id.product_tmpl_id.x_is_ego_bike:
            raise UserError('Unbuild is only available for Elego bike serials.')
        quant = self.env['stock.quant'].search([
            ('lot_id', '=', self.id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ], limit=1)
        if not quant:
            raise UserError(f'Bike serial "{self.name}" has no stock on hand to unbuild.')
        wip = self.env.ref(
            'elegomotors_setup.location_ego_production_wip', raise_if_not_found=False
        )
        if not wip:
            raise UserError(
                'The "EGO/Production WIP" location (elegomotors_setup.location_ego_production_wip) '
                'could not be found. Recovered components cannot be routed correctly without it — '
                'contact your administrator instead of proceeding.'
            )
        bom = self.env['mrp.unbuild']._find_bom_for_product(self.product_id)
        unbuild = self.env['mrp.unbuild'].create({
            'product_id': self.product_id.id,
            'product_qty': 1,
            'product_uom_id': self.product_id.uom_id.id,
            'bom_id': bom.id if bom else False,
            'lot_id': self.id,
            'location_id': quant.location_id.id,
            'location_dest_id': wip.id,
            'company_id': self.company_id.id,
        })
        return {
            'name': 'Unbuild Bike',
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.unbuild',
            'view_mode': 'form',
            'res_id': unbuild.id,
        }

    def _compute_trace_fields(self):
        """Batch-resolve the full traceability chain for this bike's lot: the
        Manufacturing Order that produced it, its QC outcome, the outgoing
        delivery that shipped it, the Sales Order and Invoice it was billed
        on, and the dealer it went to. One search per hop across the whole
        recordset, not per record, so the Bike Traceability list/export
        stays fast for hundreds of bikes.
        """
        mos = self.env['mrp.production'].search([('lot_producing_id', 'in', self.ids)])
        mo_by_lot = {mo.lot_producing_id.id: mo for mo in mos}

        move_lines = self.env['stock.move.line'].search([
            ('lot_id', 'in', self.ids),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('picking_id.state', '=', 'done'),
            ('qty_done', '>', 0),
        ])
        delivery_by_lot = {}
        for ml in move_lines:
            delivery_by_lot.setdefault(ml.lot_id.id, ml.picking_id)

        try:
            invoices = self.env['account.move'].search([
                ('x_assigned_lot_ids', 'in', self.ids),
                ('move_type', 'in', ('out_invoice', 'out_refund')),
            ])
        except AccessError:
            # Viewer has no invoice access at all (e.g. a warehouse-only
            # user) — show the rest of the traceability chain, just leave
            # invoice/dealer-from-invoice columns blank instead of a crash.
            invoices = self.env['account.move']
        lot_ids = set(self.ids)
        invoice_by_lot = {}
        for inv in invoices:
            for lot in inv.x_assigned_lot_ids:
                if lot.id in lot_ids:
                    invoice_by_lot.setdefault(lot.id, inv)

        for lot in self:
            try:
                mo = mo_by_lot.get(lot.id)
                lot.x_mo_id = mo.id if mo else False
                lot.x_mo_date = (mo.date_start or mo.create_date) if mo else False
                lot.x_qc_status = dict(mo._fields['qc_state'].selection).get(mo.qc_state, '') if mo else ''
                lot.x_qc_no = f'{mo.name}-QC' if mo else ''

                delivery = delivery_by_lot.get(lot.id)
                lot.x_delivery_id = delivery.id if delivery else False
                lot.x_delivery_date = delivery.date_done if delivery else False

                invoice = invoice_by_lot.get(lot.id)
                so = (delivery.sale_id if delivery else False) or (
                    invoice.invoice_line_ids.sale_line_ids.order_id[:1] if invoice else False
                )
                lot.x_so_id = so.id if so else False

                lot.x_invoice_id = invoice.id if invoice else False
                lot.x_invoice_date = invoice.invoice_date if invoice else False

                dealer = (so.partner_id if so else False) or (invoice.partner_id if invoice else False) \
                    or (delivery.partner_id if delivery else False)
                lot.x_dealer_id = dealer.id if dealer else False
                addr_partner = (delivery.partner_id if delivery else False) \
                    or (so.partner_shipping_id if so else False) or dealer
                lot.x_dealer_address = self._format_partner_address(addr_partner)
            except AccessError:
                # Row-level record rules (e.g. a Salesperson restricted to
                # their own Sale Orders) can make one hop of another bike's
                # chain unreadable to this viewer — degrade that row to
                # blank trace fields rather than failing the whole list.
                lot.x_mo_id = lot.x_delivery_id = lot.x_so_id = lot.x_invoice_id = lot.x_dealer_id = False
                lot.x_mo_date = lot.x_delivery_date = False
                lot.x_invoice_date = False
                lot.x_qc_status = lot.x_qc_no = lot.x_dealer_address = ''

    @api.model
    def _format_partner_address(self, partner):
        if not partner:
            return ''
        parts = [
            partner.street, partner.street2, partner.city,
            partner.state_id.name if partner.state_id else '',
            partner.zip, partner.country_id.name if partner.country_id else '',
        ]
        return ', '.join(p for p in parts if p)

    def action_export_master_report(self):
        """Download the Bike Master Traceability Report (xlsx) for the
        selected bikes, or for every ElegoMotors bike unit when nothing
        is selected (e.g. run straight from the Action menu). Unbuilt bikes
        are left out of the all-bikes export.
        """
        if self:
            domain = [('id', 'in', self.ids)]
        else:
            bike_tmpls = self.env['mrp.production']._get_ego_templates()
            domain = [('product_id.product_tmpl_id', 'in', bike_tmpls.ids),
                      ('x_is_unbuilt', '=', False)]
        return {
            'type': 'ir.actions.act_url',
            'url': '/elegomotors/bike_traceability/xlsx?domain=%s' % quote(json.dumps(domain)),
            'target': 'self',
        }

    @api.model
    def _init_global_serial_counter(self):
        """Seed the global bike unit counter from the units already produced,
        so numbering continues from the true total. Called from
        company_config_data.xml on every upgrade; no-ops once the counter
        has advanced past 1 (i.e. after the first global serial was issued).
        """
        seq = self.env.ref(
            'elegomotors_setup.seq_elego_global_serial', raise_if_not_found=False
        )
        if not seq or seq.number_next_actual > 1:
            return
        bike_tmpls = self.env['mrp.production']._get_ego_templates()
        if not bike_tmpls:
            return
        count = self.search_count([
            ('product_id.product_tmpl_id', 'in', bike_tmpls.ids),
        ])
        if count:
            seq.sudo().number_next_actual = count + 1

    def action_view_manufacturing_orders(self):
        self.ensure_one()
        mo = self.env['mrp.production'].search(
            [('lot_producing_id', '=', self.id)], limit=1
        )
        if not mo:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'name': 'Manufacturing Order',
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': mo.id,
        }

    # --- PDI (Pre-Delivery Inspection) ---

    def _create_pdi_check_results(self):
        """Auto-create elegomotors.pdi.check.result rows for every active PDI
        checklist item on this bike serial. Idempotent — skips parameters
        that already have a result row for this lot (safe to call every
        time the bike is (re-)scanned onto a delivery)."""
        CheckResult = self.env['elegomotors.pdi.check.result'].sudo()
        params = self.env['elegomotors.pdi.parameter'].search([])
        for lot in self:
            existing_param_ids = set(lot.x_pdi_check_result_ids.mapped('parameter_id.id'))
            for param in params:
                if param.id not in existing_param_ids:
                    CheckResult.create({
                        'lot_id': lot.id,
                        'parameter_id': param.id,
                    })

    def action_pdi_approve(self):
        """Pratik/Amit approves PDI: passes if every checklist item is OK,
        otherwise fails — mirrors action_gate_entry_approve_qc's aggregation."""
        self.ensure_one()
        if not self.x_pdi_check_result_ids:
            raise UserError('No PDI checklist found for this serial. Scan it onto an outgoing delivery first.')
        any_fail = any(r.result == 'fail' for r in self.x_pdi_check_result_ids)
        self.x_pdi_state = 'failed' if any_fail else 'passed'
        self.x_pdi_checked_date = fields.Datetime.now()
        self.message_post(
            body=Markup(
                f"PDI {'<b>FAILED</b>' if any_fail else '<b>Passed</b>'} "
                f"by {self.env.user.name}."
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def action_pdi_fail(self):
        """Explicitly fail PDI regardless of individual checklist rows."""
        self.ensure_one()
        self.x_pdi_state = 'failed'
        self.x_pdi_checked_date = fields.Datetime.now()
        self.message_post(
            body=Markup(f"PDI <b>FAILED</b> by {self.env.user.name}."),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def action_export_qc_full_report(self):
        """Download the QC Report (Full) (xlsx) — FG + PDI status per bike
        serial — for the selected bikes, or for every ElegoMotors bike unit
        when nothing is selected."""
        if self:
            domain = [('id', 'in', self.ids)]
        else:
            bike_tmpls = self.env['mrp.production']._get_ego_templates()
            domain = [('product_id.product_tmpl_id', 'in', bike_tmpls.ids)]
        return {
            'type': 'ir.actions.act_url',
            'url': '/elegomotors/qc_report/bikes/xlsx?domain=%s' % quote(json.dumps(domain)),
            'target': 'self',
        }

    def action_pdi_reset(self):
        """Reset PDI to pending after rework, so it can be re-inspected."""
        self.ensure_one()
        self.x_pdi_state = 'pending'
        self.x_pdi_check_result_ids.write({'result': False, 'notes': False})
        self.message_post(
            body='PDI reset to Pending — ready for re-inspection.',
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    # ------------------------------------------------------------------
    # Component-serial uniqueness vs. unbuilt bikes
    # ------------------------------------------------------------------
    def _is_unbuilt(self):
        """True when this bike serial went through a done Unbuild Order and no
        unit of it is on hand any more - its component serials are free."""
        self.ensure_one()
        if not self.env['mrp.unbuild'].sudo().search_count(
                [('lot_id', '=', self.id), ('state', '=', 'done')]):
            return False
        on_hand = sum(self.env['stock.quant'].sudo().search([
            ('lot_id', '=', self.id), ('location_id.usage', '=', 'internal'),
        ]).mapped('quantity'))
        return on_hand <= 0

    @api.model
    def _unbuilt_lot_ids(self):
        """Ids of every bike lot that was unbuilt and has nothing on hand now.
        Same rule as _is_unbuilt(), computed for all lots in two queries."""
        unbuilds = self.env['mrp.unbuild'].sudo().search_read(
            [('state', '=', 'done'), ('lot_id', '!=', False)], ['lot_id'])
        lot_ids = {u['lot_id'][0] for u in unbuilds}
        if not lot_ids:
            return []
        on_hand = self.env['stock.quant'].sudo()._read_group(
            [('lot_id', 'in', list(lot_ids)), ('location_id.usage', '=', 'internal')],
            ['lot_id'], ['quantity:sum'])
        in_stock = {lot.id for lot, qty in on_hand if qty > 0}
        return list(lot_ids - in_stock)

    def _compute_x_is_unbuilt(self):
        unbuilt = set(self._unbuilt_lot_ids())
        for lot in self:
            lot.x_is_unbuilt = lot.id in unbuilt

    def _search_x_is_unbuilt(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError('Unbuilt can only be searched with "is" / "is not".')
        want_unbuilt = bool(value) == (operator == '=')
        return [('id', 'in' if want_unbuilt else 'not in', self._unbuilt_lot_ids())]

    def _release_component_serials(self):
        """Free the component serials held by bikes that are fully unbuilt, so
        the parts can go into the next bike. The Unbuild Order keeps its own
        snapshot, which is also what a rebuild MO pre-fills from."""
        # Only the five the Unbuild Order snapshots; cluster/frame serials are
        # typed in by hand, never checked for reuse, and would be lost.
        fields_ = ('x_chassis_serial', 'x_motor_serial', 'x_controller_serial',
                   'x_battery_serial', 'x_charger_serial')
        for lot in self:
            if lot._is_unbuilt():
                lot.write({f: False for f in fields_ if lot[f]})

    @api.model
    def _find_serial_holder(self, field_name, value):
        """The live bike lot that carries this component serial, or an empty
        recordset. Bikes that were fully unbuilt are skipped: their parts
        (recovered to Production WIP) may be built into another bike. The
        Unbuild Order keeps its own snapshot of those serials."""
        for lot in self.search([(field_name, '=', value)]):
            if not lot._is_unbuilt():
                return lot
        return self.browse()

    @api.model
    def _release_serials_from_unbuilt(self, vals, keep_lot=None):
        """Blank the component serials in `vals` on unbuilt bike lots that still
        hold them, so only one lot carries each serial (traceability and the
        warranty lookup stay unambiguous)."""
        fields_ = ('x_chassis_serial', 'x_motor_serial', 'x_controller_serial',
                   'x_battery_serial', 'x_charger_serial')
        for fname in fields_:
            value = vals.get(fname)
            if not value:
                continue
            for lot in self.search([(fname, '=', value)]):
                if lot != keep_lot and lot._is_unbuilt():
                    lot.write({fname: False})
