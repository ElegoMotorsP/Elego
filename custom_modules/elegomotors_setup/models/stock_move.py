# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_qty_received = fields.Float(
        string='Received',
        digits='Product Unit of Measure',
        default=0,
        copy=False,
        help='Actual quantity received at gate entry (entered by store person).',
    )
    x_qty_qc_passed = fields.Float(
        string='QC Passed',
        digits='Product Unit of Measure',
        default=0,
        copy=False,
        help='Quantity that passed quality check.',
    )
    x_qty_qc_failed = fields.Float(
        string='QC Failed',
        digits='Product Unit of Measure',
        compute='_compute_qc_failed',
        store=True,
        copy=False,
        help='Quantity that failed quality check (= Received − QC Passed).',
    )
    x_qty_final = fields.Float(
        string='Final Quantities',
        digits='Product Unit of Measure',
        compute='_compute_qty_final',
        store=True,
        copy=False,
        help='Final accepted quantity that goes to store (= QC Passed).',
    )

    @api.depends('x_qty_received', 'x_qty_qc_passed', 'picking_id.x_gate_entry_state')
    def _compute_qc_failed(self):
        for move in self:
            # Only meaningful once QC inspection has started; show 0 at Pending QC
            if move.picking_id.x_gate_entry_state in ('in_qc', 'ready'):
                move.x_qty_qc_failed = move.x_qty_received - move.x_qty_qc_passed
            else:
                move.x_qty_qc_failed = 0.0

    @api.depends('x_qty_qc_passed', 'picking_id.x_gate_entry_state')
    def _compute_qty_final(self):
        for move in self:
            # Mirror x_qty_qc_passed only once QC is in progress/done
            if move.picking_id.x_gate_entry_state in ('in_qc', 'ready'):
                move.x_qty_final = move.x_qty_qc_passed
            else:
                move.x_qty_final = 0.0

    # Barcode wizard: show the scanned component serial next to the relevant BOM row
    x_component_serial = fields.Char(
        string='Scanned Serial',
        compute='_compute_component_serial',
        store=False,
    )

    @api.depends(
        'product_id',
        'raw_material_production_id.lot_producing_id.x_motor_serial',
        'raw_material_production_id.lot_producing_id.x_battery_serial',
        'raw_material_production_id.lot_producing_id.x_controller_serial',
        'raw_material_production_id.lot_producing_id.x_charger_serial',
    )
    def _compute_component_serial(self):
        motor      = self.env.ref('elegomotors_setup.comp_hub_motor',    raise_if_not_found=False)
        battery    = self.env.ref('elegomotors_setup.comp_battery_pack', raise_if_not_found=False)
        controller = self.env.ref('elegomotors_setup.comp_controller',   raise_if_not_found=False)
        charger    = self.env.ref('elegomotors_setup.comp_charger',      raise_if_not_found=False)
        for move in self:
            lot = move.raw_material_production_id.lot_producing_id if move.raw_material_production_id else False
            if not lot:
                move.x_component_serial = False
                continue
            pid = move.product_id.id
            if motor and pid == motor.id:
                move.x_component_serial = lot.x_motor_serial or False
            elif controller and pid == controller.id:
                move.x_component_serial = lot.x_controller_serial or False
            elif battery and pid == battery.id:
                move.x_component_serial = lot.x_battery_serial or False
            elif charger and pid == charger.id:
                move.x_component_serial = lot.x_charger_serial or False
            else:
                move.x_component_serial = False

    # Section header moves for consolidated PI display
    x_is_section_header = fields.Boolean(
        string='Is Section Header',
        default=False,
        help='True for display-only section separator rows in consolidated PI pickings.',
    )
    x_section_label = fields.Char(string='Section Label')

    # Issue 10: auto-fill x_qty_received from PO demand quantity on creation
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('x_qty_received') and vals.get('product_uom_qty'):
                vals['x_qty_received'] = vals['product_uom_qty']
        return super().create(vals_list)

    # Issue 10: keep x_qty_received in sync when demand qty changes (UI onchange)
    @api.onchange('product_uom_qty')
    def _onchange_x_qty_received_default(self):
        if self.product_uom_qty and not self.x_qty_received:
            self.x_qty_received = self.product_uom_qty
