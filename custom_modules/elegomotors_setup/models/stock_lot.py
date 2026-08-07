# -*- coding: utf-8 -*-
import json
from urllib.parse import quote

from odoo import api, models, fields
from odoo.exceptions import AccessError


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
        is selected (e.g. run straight from the Action menu).
        """
        if self:
            domain = [('id', 'in', self.ids)]
        else:
            bike_tmpls = self.env['mrp.production']._get_ego_templates()
            domain = [('product_id.product_tmpl_id', 'in', bike_tmpls.ids)]
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
