# -*- coding: utf-8 -*-
from odoo import api, models, fields


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
