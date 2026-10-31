# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.tools import float_compare


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
    # phantom BOMs). Shown on the exploded "Battery Cell" line (its own
    # product name, e.g. "Battery Cell — Lead 12V32AH", only carries the
    # cell's own 12V rating, not the pack's total voltage — the count is
    # derived from the pack it belongs to via x_kit_pack_name instead), or
    # on the Battery Pack line itself when not exploded into cells here.
    # Matches the same hint already shown on the invoice's Vehicle Serial
    # Details table (account_move.py _ego_battery_type_display).
    x_battery_cell_hint = fields.Char(
        string='Cells',
        compute='_compute_battery_cell_hint',
    )

    @api.depends('product_id', 'x_kit_pack_name')
    def _compute_battery_cell_hint(self):
        for move in self:
            move.x_battery_cell_hint = ''
            name = (move.product_id.name or '').lower()
            if move.x_kit_pack_name:
                # Any component exploded from a battery pack's phantom BOM
                # — derive the cell count from the PACK's name, not the
                # component's own. Gating on x_kit_pack_name rather than
                # requiring the component's own name to literally contain
                # "battery cell" matters for a manually-created pack (e.g.
                # the client's own 60V42Ah kit, adopted as-is in
                # _ensure_battery_lead_60v42ah_adopted): its cell product's
                # name isn't controlled by this module and has no
                # guarantee of containing that substring — confirmed live
                # via QA, the pack showed up in the delivery's Battery/
                # Charger Totals table (stock_picking.py's
                # _compute_battery_summary, fixed the same way) but with a
                # blank Cells column, because this compute alone still
                # required the old substring match to even look up the
                # pack name.
                source_name = move.x_kit_pack_name
            elif 'battery pack' in name:
                source_name = move.product_id.name or ''
            else:
                # Chargers, and anything else, never get a cell count —
                # even "Lead Charger" matches "lead" and has its own
                # voltage in its name, but isn't a battery at all.
                continue
            if 'lead' not in source_name.lower():
                continue
            match = re.search(r'(\d+)\s*V', source_name, re.IGNORECASE)
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
        moves = super().create(vals_list)
        moves._ego_link_to_source_po()
        return moves

    def _ego_link_to_source_po(self):
        """Link receipt moves to the order line of the receipt's Purchase Order.

        The PO picker on a hand-made receipt fills the operation lines through
        an onchange that also sends purchase_line_id, but the web client keeps
        only the fields that are in the line list view and purchase_line_id is
        not one of them, so it was dropped on save. The receipt then posted its
        stock but never counted towards the PO: Received stayed 0, the PO never
        counted as fully received (so it stayed in the picker for ever) and
        validating the receipt could not bill it. Linking here, on the server,
        does not depend on what the browser sends.

        A move goes to the first line of its product that is still open, else
        the first line of that product; a product that is not on the PO stays
        unlinked.
        """
        if 'purchase_line_id' not in self._fields:
            return
        for move in self:
            picking = move.picking_id
            po = picking.x_source_po_id
            if not po or move.purchase_line_id or picking.picking_type_code != 'incoming':
                continue
            lines = po.order_line.filtered(
                lambda l: not l.display_type and l.product_id == move.product_id
            )
            open_lines = lines.filtered(
                lambda l: float_compare(
                    l.product_qty, l.qty_received, precision_rounding=l.product_uom.rounding,
                ) > 0
            )
            line = (open_lines or lines)[:1]
            if line:
                move.purchase_line_id = line

    def _action_assign(self, force_qty=False):
        """Never re-reserve a receipt whose quantity QC has already approved.

        Approve QC trims a supplier receipt down to what passed (500 of 1000),
        which leaves the move partially available until Amit validates it.
        Odoo's reservation then treats the missing 500 as "not reserved yet"
        and, because a supplier location needs no stock, simply adds it back
        up to the full ordered quantity. The scheduler does this to every
        partially available move, so the approved quantity silently reverted
        to the ordered one before the receipt was validated.

        Only moves that already hold their approved lines are skipped: the
        backorder moves Odoo splits off while validating are still under this
        receipt for a moment and have no lines yet, and those must reserve
        normally.
        """
        fixed = self.filtered(
            lambda m: m.picking_id.picking_type_code == 'incoming'
            and m.picking_id.x_gate_entry_state == 'ready'
            and m.state not in ('draft', 'done', 'cancel')
            and m.move_line_ids
        )
        return super(StockMove, self - fixed)._action_assign(force_qty=force_qty)

    # Issue 10: keep x_qty_received in sync when demand qty changes (UI onchange)
    @api.onchange('product_uom_qty')
    def _onchange_x_qty_received_default(self):
        if self.product_uom_qty and not self.x_qty_received:
            self.x_qty_received = self.product_uom_qty
