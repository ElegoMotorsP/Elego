# -*- coding: utf-8 -*-
"""Delivery-estimate settings (doc/delivery-estimate-api-plan.md §3).
Edited from Elego Connect ▸ Delivery Estimate Settings (admin only)."""
from odoo import fields, models


class ResCompanyDeliveryEstimate(models.Model):
    _inherit = 'res.company'

    x_de_rate_mode = fields.Selection(
        [('auto', 'Trailing output, fixed rate on anomalies'), ('fixed', 'Always fixed rate')],
        string='Production Rate Mode', default='auto', required=True,
        help='Auto: bikes finished over the last N working days, falling back to '
             'the fixed rate when that window looks abnormal (shutdown, idle days, '
             'bulk-closed MOs). Fixed: always use the fixed rate.')
    x_de_rate_window_days = fields.Integer(
        string='Rate Window (working days)', default=15)
    x_de_fixed_daily_rate = fields.Float(
        string='Fixed Rate (bikes / working day)', default=0.0,
        help='Planned plant output. Used in fixed mode and as the fallback when '
             'the trailing window is anomalous. 0 = not set: new builds then get '
             'no date when a fallback is needed.')
    x_de_max_idle_days = fields.Integer(
        string='Max Idle Days in Window', default=4,
        help='More working days than this with zero bikes finished = anomaly.')
    x_de_anomaly_low_pct = fields.Float(
        string='Anomaly Below (% of fixed)', default=50.0)
    x_de_anomaly_high_pct = fields.Float(
        string='Anomaly Above (% of fixed)', default=150.0)
    x_de_qc_pdi_buffer_days = fields.Integer(
        string='QC / PDI Buffer (working days)', default=1)
    x_de_dispatch_buffer_days = fields.Integer(
        string='Dispatch Buffer (working days)', default=1)
    x_de_transit_days = fields.Integer(
        string='Transit to Dealer (calendar days)', default=2)
    x_de_overdue_slip_days = fields.Integer(
        string='Overdue PO Slip (days)', default=7,
        help='An open PO line past its expected date is assumed to arrive this '
             'many days from today.')
    x_de_procurement_buffer_days = fields.Integer(
        string='Procurement Buffer (days)', default=3,
        help="Added to the vendor's lead time for parts that are short with no "
             "PO placed yet.")
    x_de_incoming_yield_pct = fields.Float(
        string='Incoming QC Yield (%)', default=100.0,
        help='Share of incoming parts expected to pass inward QC.')
