# -*- coding: utf-8 -*-
from odoo import models, fields


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

    x_motor_serial      = fields.Char(string='Hub Motor Serial No.',          index=True)
    x_battery_serial    = fields.Char(string='Battery Pack Serial No.',       index=True)
    x_controller_serial = fields.Char(string='Motor Controller Serial No.',   index=True)
    x_charger_serial    = fields.Char(string='Charger Serial No.',            index=True)
    x_cluster_serial    = fields.Char(string='Instrument Cluster Serial No.', index=True)
    x_frame_serial      = fields.Char(string='Frame Assembly Serial No.',     index=True)
    x_blacklisted       = fields.Boolean(
        string='Blacklisted (QC Fail)',
        default=False,
        index=True,
        help='Set to True when this serial/lot has failed QC. Prevents sale or store transfer.',
    )
