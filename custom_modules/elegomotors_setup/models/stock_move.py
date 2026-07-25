# -*- coding: utf-8 -*-
import re

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

    # Kit decomposition visibility: when a battery pack (phantom BOM) explodes
    # into base cells on the PI OUT, this shows which pack the cells belong to
    # — e.g. product "Battery Cell — Lead 12V32AH ×5", Part of Pack
    # "Battery Pack — Lead Acid 60V32Ah".
    x_kit_pack_name = fields.Char(
        string='Part of Pack',
        compute='_compute_kit_pack_name',
    )

    # Lead Acid battery packs are physically built from 12V cells — e.g. a
    # 60V32Ah pack is 5 cells, a 72V32Ah pack is 6 (see battery_kit_data.xml's
    # phantom BOMs). Shown on the Battery Pack line itself (whether or not it
    # was exploded into individual cell lines here) so Store knows the cell
    # count at a glance, matching the same hint already shown on the invoice's
    # Vehicle Serial Details table (account_move.py _ego_battery_type_display).
    x_battery_cell_hint = fields.Char(
        string='Cells',
        compute='_compute_battery_cell_hint',
    )

    @api.depends('product_id')
    def _compute_battery_cell_hint(self):
        for move in self:
            name = move.product_id.name or ''
            name_lower = name.lower()
            move.x_battery_cell_hint = ''
            # Only the Battery Pack line itself, not its exploded-out
            # "Battery Cell" components (already individual cells — a
            # 12V32AH cell matching "12V" would wrongly compute "12V x 1")
            # nor the Charger line (matches "lead" via "Lead Charger" and
            # its own voltage, but isn't a battery at all).
            if 'battery pack' not in name_lower or 'lead' not in name_lower:
                continue
            match = re.search(r'(\d+)\s*V', name, re.IGNORECASE)
            if match:
                cells = int(match.group(1)) // 12
                if cells:
                    move.x_battery_cell_hint = f'12V x {cells}'

    @api.depends('bom_line_id')
    def _compute_kit_pack_name(self):
        for move in self:
            bom = move.bom_line_id.bom_id
            move.x_kit_pack_name = (
                bom.product_tmpl_id.display_name
                if bom and bom.type == 'phantom' else ''
            )

    @api.depends('x_qty_received', 'x_qty_qc_passed', 'picking_id.x_gate_entry_state')
    def _compute_qc_failed(self):
        for move in self:
            # Only meaningful once QC has been decided (approved); show 0 while
            # inspection is still in progress, otherwise the formula reads as
            # "received - 0" and every move looks fully failed before anyone
            # has actually inspected it.
            if move.picking_id.x_gate_entry_state == 'ready':
                move.x_qty_qc_failed = move.x_qty_received - move.x_qty_qc_passed
            else:
                move.x_qty_qc_failed = 0.0

    @api.depends('x_qty_qc_passed', 'picking_id.x_gate_entry_state')
    def _compute_qty_final(self):
        for move in self:
            # Mirror x_qty_qc_passed only once QC has been decided (approved)
            if move.picking_id.x_gate_entry_state == 'ready':
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
