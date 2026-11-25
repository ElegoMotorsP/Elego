# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models

from .ckd_part_allocation import choose_candidate


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

    @api.depends('x_qty_received', 'x_qty_qc_passed', 'picking_id.x_gate_entry_state',
                 'picking_id.move_ids.x_qty_received', 'picking_id.move_ids.x_qty_qc_passed')
    def _compute_qc_failed(self):
        for move in self:
            # Only meaningful once QC has been decided (approved); show 0 while
            # inspection is still in progress, otherwise the formula reads as
            # "received - 0" and every move looks fully failed before anyone
            # has actually inspected it.
            if move.picking_id.x_gate_entry_state != 'ready':
                move.x_qty_qc_failed = 0.0
                continue
            group = move._ckd_merge_group()
            if len(group) > 1 and move.id == move._ckd_merge_representative().id:
                # The merged row shows the group's combined failed count —
                # each kit's own move still carries its own share underneath.
                move.x_qty_qc_failed = sum(group.mapped('x_qty_received')) - sum(group.mapped('x_qty_qc_passed'))
            else:
                move.x_qty_qc_failed = move.x_qty_received - move.x_qty_qc_passed

    @api.depends('x_qty_qc_passed', 'picking_id.x_gate_entry_state',
                 'picking_id.move_ids.x_qty_qc_passed')
    def _compute_qty_final(self):
        for move in self:
            # Mirror x_qty_qc_passed only once QC has been decided (approved)
            if move.picking_id.x_gate_entry_state != 'ready':
                move.x_qty_final = 0.0
                continue
            group = move._ckd_merge_group()
            if len(group) > 1 and move.id == move._ckd_merge_representative().id:
                move.x_qty_final = sum(group.mapped('x_qty_qc_passed'))
            else:
                move.x_qty_final = move.x_qty_qc_passed

    # ------------------------------------------------------------------
    # CKD part merge: a part common to two or more CKD kits on the same
    # receipt (e.g. a Red kit and a Black kit both needing the front fender)
    # keeps one move per kit underneath — each needs its own Received/QC
    # figures and its own bom_line_id for kit costing (see
    # _ego_link_kit_component above) — but the Operations tab shows ONE row
    # for the part: the FIRST kit's move (by the kit's own line order on the
    # PO) stays visible, its Received/QC Passed cells repurposed to mean the
    # combined total, and every other sibling move is hidden (not removed —
    # still there, still counted individually, just not a separate row to
    # scroll past). Products that are individually lot/serial-tracked are
    # never merged: each physical unit still needs its own row to take a
    # serial number.
    # ------------------------------------------------------------------

    def _ckd_merge_group(self):
        """This move's CKD-merge siblings on the same receipt, itself
        included — every live move of the same product, on the same
        picking, tied to a CKD kit's bom_line, for a product that isn't
        individually lot/serial tracked. Empty when this move isn't part of
        a mergeable CKD group at all (plain part, not a CKD kit, or a
        serial/lot-tracked product)."""
        self.ensure_one()
        if not self.bom_line_id or not self.bom_line_id.bom_id.x_is_ckd_kit:
            return self.browse()
        if self.product_id.tracking != 'none':
            return self.browse()
        return self.picking_id.move_ids.filtered(
            lambda m: m.state != 'cancel' and m.product_id == self.product_id
            and m.bom_line_id and m.bom_line_id.bom_id.x_is_ckd_kit
        )

    def _ckd_merge_representative(self):
        """The one move of this CKD-merge group whose row stays visible and
        whose Received/QC Passed cells drive the whole group — first by the
        kit line's own position on the PO, so a shortfall or an over-receipt
        always lands on the LAST kit in line, matching the order the kits
        were ordered in. A group of one (no merge needed) is its own
        representative."""
        self.ensure_one()
        group = self._ckd_merge_group()
        if not group:
            return self
        return group.sorted(lambda m: (m.purchase_line_id.sequence or 0, m.purchase_line_id.id, m.id))[0]

    x_ckd_merge_hidden = fields.Boolean(
        compute='_compute_ckd_merge_display', store=False,
        help='True for every move of a merged CKD part except the one '
             'representing the whole group on screen.')
    x_ckd_merge_used_in = fields.Char(
        string='Kit', compute='_compute_ckd_merge_display', store=False,
        help='Which kit(s) this part belongs to — every kit on the group '
             'row, just this one\'s own kit line everywhere else.')
    x_ckd_merge_total_demand = fields.Float(
        string='Demand', compute='_compute_ckd_merge_display', store=False,
        digits='Product Unit of Measure',
        help='Combined demand across every kit sharing this part on the '
             'group row; this move\'s own demand everywhere else.')

    @api.depends('product_id', 'picking_id', 'bom_line_id', 'state', 'product_uom_qty',
                 'purchase_line_id', 'description_bom_line')
    def _compute_ckd_merge_display(self):
        for move in self:
            group = move._ckd_merge_group()
            if len(group) <= 1:
                move.x_ckd_merge_hidden = False
                move.x_ckd_merge_used_in = move.description_bom_line or ''
                move.x_ckd_merge_total_demand = move.product_uom_qty
                continue
            ordered = group.sorted(lambda m: (m.purchase_line_id.sequence or 0, m.purchase_line_id.id, m.id))
            rep = ordered[0]
            move.x_ckd_merge_hidden = move.id != rep.id
            if move.id == rep.id:
                kits = []
                for m in ordered:
                    name = m.purchase_line_id.product_id.display_name
                    if name and name not in kits:
                        kits.append(name)
                move.x_ckd_merge_used_in = ', '.join(kits)
                move.x_ckd_merge_total_demand = sum(group.mapped('product_uom_qty'))
            else:
                move.x_ckd_merge_used_in = move.description_bom_line or ''
                move.x_ckd_merge_total_demand = move.product_uom_qty

    x_ckd_merge_received_input = fields.Float(
        string='Received', digits='Product Unit of Measure',
        compute='_compute_ckd_merge_inputs', inverse='_inverse_ckd_merge_received',
        help='Received quantity. On a part shared by several kits, this is '
             'the combined total — enter it once here and it fills each '
             "kit's own figure underneath, in the order the kits were "
             'ordered in, kit by kit until the number runs out.')
    x_ckd_merge_qc_passed_input = fields.Float(
        string='QC Passed', digits='Product Unit of Measure',
        compute='_compute_ckd_merge_inputs', inverse='_inverse_ckd_merge_qc_passed',
        help='Same idea as Received above, for the quantity that passed QC '
             "— capped per kit at what that kit's own move actually received.")

    @api.depends('x_qty_received', 'x_qty_qc_passed', 'product_id', 'picking_id', 'bom_line_id',
                 'picking_id.move_ids.x_qty_received', 'picking_id.move_ids.x_qty_qc_passed')
    def _compute_ckd_merge_inputs(self):
        for move in self:
            group = move._ckd_merge_group()
            if len(group) <= 1 or move.id != move._ckd_merge_representative().id:
                move.x_ckd_merge_received_input = move.x_qty_received
                move.x_ckd_merge_qc_passed_input = move.x_qty_qc_passed
            else:
                move.x_ckd_merge_received_input = sum(group.mapped('x_qty_received'))
                move.x_ckd_merge_qc_passed_input = sum(group.mapped('x_qty_qc_passed'))

    def _inverse_ckd_merge_received(self):
        for move in self:
            group = move._ckd_merge_group()
            if len(group) <= 1:
                move.x_qty_received = move.x_ckd_merge_received_input
            else:
                move._ckd_distribute(group, received=move.x_ckd_merge_received_input)

    def _inverse_ckd_merge_qc_passed(self):
        for move in self:
            group = move._ckd_merge_group()
            if len(group) <= 1:
                move.x_qty_qc_passed = move.x_ckd_merge_qc_passed_input
            else:
                move._ckd_distribute(group, qc_passed=move.x_ckd_merge_qc_passed_input)

    def _ckd_distribute(self, group, received=None, qc_passed=None):
        """Spread a merged Received and/or QC Passed total across every move
        in the group, in kit order (by the kit line's own sequence on the
        PO): each kit's own demand is filled before the next kit gets
        anything, so a shortfall lands on the LAST kit in line and an
        over-receipt is absorbed there too. QC Passed is always capped per
        move at that move's own Received — never more than what actually
        arrived for that kit. Passing None for one of the two leaves it
        untouched, so editing Received alone doesn't reset QC Passed."""
        self.ensure_one()
        ordered = group.sorted(lambda m: (m.purchase_line_id.sequence or 0, m.purchase_line_id.id, m.id))
        last = ordered[-1]
        if received is not None:
            remaining = received
            for move in ordered:
                share = max(remaining, 0.0) if move.id == last.id else min(
                    move.product_uom_qty, max(remaining, 0.0))
                remaining -= share
                move.x_qty_received = share
        if qc_passed is not None:
            remaining = qc_passed
            for move in ordered:
                share = min(move.x_qty_received, max(remaining, 0.0))
                remaining -= share
                move.x_qty_qc_passed = share

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

        When several lines of the PO could take the move (the same product on
        two lines, or the same part in two CKD kits) it goes to the one that
        still has room for exactly its quantity, else the first with room left
        (see _ego_pick_candidate). Always taking "the first line of that
        product" tied the second kit's parts to the first kit's line: Odoo then
        merged the identical moves when the receipt was marked To Do (demand
        summed, Received kept from the first move) and the second kit's line
        never saw its parts. A product that is not on the PO stays unlinked.
        """
        if 'purchase_line_id' not in self._fields:
            return
        for move in self:
            picking = move.picking_id
            po = picking.x_source_po_id
            if not po or picking.picking_type_code != 'incoming':
                continue
            if move.purchase_line_id:
                # Already on a PO line: if that line is a CKD kit and this move
                # is one of its parts, make sure it also carries the BoM line
                # and cost share the kit pricing needs (the web client drops
                # those two fields on save just like it drops purchase_line_id).
                move._ego_complete_kit_component()
                continue
            lines = po.order_line.filtered(
                lambda l: not l.display_type and l.product_id == move.product_id
            )
            if len(lines) == 1:
                move.purchase_line_id = lines
            elif lines:
                # room = still to receive on the line, less what the other moves
                # of this receipt already cover of it
                move.purchase_line_id = move._ego_pick_candidate([
                    (line, line.product_uom._compute_quantity(
                        line.product_qty - line.qty_received, move.product_uom,
                    ) - move._ego_sibling_qty(line))
                    for line in lines
                ])
            else:
                move._ego_link_kit_component(po)

    def _ego_sibling_qty(self, line, bom_line=None):
        """What the OTHER moves of this move's receipt already cover of a PO line
        (of one BoM line of it, for a kit part), in this move's unit."""
        self.ensure_one()
        total = 0.0
        for other in self.picking_id.move_ids:
            if other.id == self.id or other.state == 'cancel' or other.purchase_line_id != line:
                continue
            if bom_line and other.bom_line_id != bom_line:
                continue
            total += other.product_uom._compute_quantity(other.product_uom_qty, self.product_uom)
        return total

    def _ego_pick_candidate(self, candidates):
        """Of (record, room) pairs, the record this move should be tied to; see
        choose_candidate for the rule."""
        self.ensure_one()
        return choose_candidate(
            candidates, self.product_uom_qty, rounding=self.product_uom.rounding or 0.01)

    def _ego_link_kit_component(self, po):
        """A part of a CKD kit that is on the PO as a kit line: tie the move to
        the kit line (and BoM line) it is for.

        Two kit lines of one PO often share a part (Kit A x3 and Kit B x4 both
        need the front fender). Each candidate is a (kit line, BoM line) pair
        with the room it still has for the part: what that line has left to
        receive, less what the other moves of this receipt already cover. The
        move goes where its quantity fits exactly, else to the first with room
        left, so the receipt keeps one separate move per kit and each kit line
        counts its own parts."""
        self.ensure_one()
        pairs = []
        for line in po.order_line.filtered(lambda l: l._ckd_kit_bom()):
            for bom_line in line._ckd_kit_bom().bom_line_ids.filtered(
                lambda bl: bl.product_id == self.product_id
            ):
                pairs.append((line, bom_line))
        if not pairs:
            return
        if len(pairs) == 1:
            # a part only one kit needs: nothing to choose between
            line, bom_line = pairs[0]
        else:
            line, bom_line = self._ego_pick_candidate([
                ((line, bom_line), bom_line.product_uom_id._compute_quantity(
                    line._ckd_part_to_receive(bom_line), self.product_uom,
                ) - self._ego_sibling_qty(line, bom_line))
                for line, bom_line in pairs
            ])
        self.write({
            'purchase_line_id': line.id,
            'bom_line_id': bom_line.id,
            'cost_share': line._ckd_cost_share_for(bom_line, bom_line.cost_share) or 0.0,
        })

    def _ego_complete_kit_component(self):
        """Fill bom_line_id / cost_share on a part move already linked to its
        CKD kit PO line."""
        self.ensure_one()
        line = self.purchase_line_id
        if not line or line.product_id == self.product_id:
            return
        bom = line._ckd_kit_bom()
        if not bom:
            return
        bom_line = self.bom_line_id or bom.bom_line_ids.filtered(
            lambda bl: bl.product_id == self.product_id
        )[:1]
        if not bom_line:
            return
        vals = {}
        if not self.bom_line_id:
            vals['bom_line_id'] = bom_line.id
        if not self.cost_share:
            vals['cost_share'] = line._ckd_cost_share_for(bom_line, bom_line.cost_share) or 0.0
        if vals:
            self.write(vals)

    def _merge_moves_fields(self):
        """Odoo merges identical moves of a receipt when it is marked To Do (same
        product, PO line and so on) and adds up only their demand: the merged
        move kept the FIRST move's Received and QC Passed, so a part wanted
        7 = 3 + 4 showed Demand 7 but Received 3, and only 3 was ever posted.
        On a receipt they are quantities of the same product like the demand, so
        add them up too."""
        vals = super()._merge_moves_fields()
        if (
            len(self) > 1
            and not self.env.context.get('merge_extra')
            and all(move.picking_type_id.code == 'incoming' for move in self)
        ):
            vals['x_qty_received'] = sum(self.mapped('x_qty_received'))
            vals['x_qty_qc_passed'] = sum(self.mapped('x_qty_qc_passed'))
        return vals

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
