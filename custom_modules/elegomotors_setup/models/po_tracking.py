# -*- coding: utf-8 -*-
"""All Purchase Order Tracking Report.

One row per Purchase Order: type (Domestic / Import), PO quantity, supplier
invoice(s), GRN(s), received / pending quantity, QC pass / reject / pending,
what has reached stock and the PO's current stage. Cancelled POs stay in.

Everything the report shows is stored on the PO (or built on demand from the
PO's own receipts and bills), so the standard list filters, grouping and the
native Export work on it. The list itself is views/po_tracking_views.xml.

"Received" is what Store booked on the GRN at the gate (the Received column of a
Gate Entry), exactly as the report's own sample rows read (GRN received 60, QC
pass 55, reject 5) - NOT only what has been validated into stock after QC. On
receipts that do not go through Gate Entry it is the validated quantity.

Units: every quantity is in the PO line's own unit. For a CKD kit line that is
KITS, so a kit PO reads "100 ordered / 60 received / 55 QC passed", not a mix
of kits and individual parts (see _trk_line_figures).
"""
from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_compare, float_is_zero

TRACKING_STAGES = [
    ('rfq', 'RFQ / Not Confirmed'),
    ('awaiting', 'Awaiting Delivery'),
    ('partial', 'Partially Received'),
    ('partial_qc', 'Partial / QC'),
    ('quality', 'Quality Pending'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
]


class PurchaseOrderTracking(models.Model):
    _inherit = 'purchase.order'

    x_po_type = fields.Selection(
        [('domestic', 'Domestic'), ('import', 'Import')],
        string='Domestic / Import',
        compute='_compute_x_po_type', store=True, readonly=False, index=True,
        help='Import when the vendor is in another country or the PO is in a '
             'foreign currency; otherwise Domestic. Set automatically, and '
             'can be corrected by hand.',
    )

    x_trk_po_qty = fields.Float(
        string='PO Qty', compute='_compute_x_tracking', store=True,
        digits='Product Unit of Measure')
    x_trk_received_qty = fields.Float(
        string='Received', compute='_compute_x_tracking', store=True,
        digits='Product Unit of Measure')
    x_trk_pending_qty = fields.Float(
        string='Pending', compute='_compute_x_tracking', store=True,
        digits='Product Unit of Measure',
        help='PO Qty - Received (0 for a cancelled PO).')
    x_trk_qc_passed_qty = fields.Float(
        string='QC Pass', compute='_compute_x_tracking', store=True,
        digits='Product Unit of Measure')
    x_trk_qc_rejected_qty = fields.Float(
        string='QC Reject', compute='_compute_x_tracking', store=True,
        digits='Product Unit of Measure')
    x_trk_qc_pending_qty = fields.Float(
        string='QC Pending', compute='_compute_x_tracking', store=True,
        digits='Product Unit of Measure',
        help='Received quantity of QC items that QC has not decided yet.')
    x_trk_stock_qty = fields.Float(
        string='Stock', compute='_compute_x_tracking', store=True,
        digits='Product Unit of Measure',
        help='Quantity of this PO that has reached stock: QC-approved quantity '
             'for QC items, the validated receipt quantity for the rest.')
    x_trk_stage = fields.Selection(
        TRACKING_STAGES, string='Current Stage',
        compute='_compute_x_tracking', store=True, index=True)

    x_trk_grn_refs = fields.Char(
        string='GRN No.', compute='_compute_x_trk_refs')
    x_trk_qc_refs = fields.Char(
        string='QC No.', compute='_compute_x_trk_refs',
        help='The GRN(s) that carry QC items, with their QC status.')
    x_trk_invoice_refs = fields.Char(
        string='Supplier Invoice No. / Date', compute='_compute_x_trk_refs')
    x_trk_bill_refs = fields.Char(
        string='Elego Purchase Invoice', compute='_compute_x_trk_refs',
        help="Elego's own purchase invoice: the number of the vendor bill booked for "
             "this PO (not the supplier's invoice number, which is the column before).")

    # ------------------------------------------------------------------
    # Domestic / Import
    # ------------------------------------------------------------------

    @api.depends('partner_id.country_id', 'currency_id', 'company_id')
    def _compute_x_po_type(self):
        for po in self:
            company = po.company_id
            home = company.account_fiscal_country_id or company.country_id
            foreign_currency = bool(
                po.currency_id and company.currency_id and po.currency_id != company.currency_id
            )
            country = po.partner_id.country_id
            foreign_country = bool(country and home and country != home)
            po.x_po_type = 'import' if (foreign_currency or foreign_country) else 'domestic'

    # ------------------------------------------------------------------
    # Quantities and stage
    # ------------------------------------------------------------------

    def _trk_kit_boms(self, lines):
        """{product: phantom (kit) BoM} for the products of these PO lines,
        looked up in one query (a PO can have 200+ lines)."""
        products = lines.product_id
        if not products:
            return {}
        return self.env['mrp.bom'].sudo()._bom_find(
            products, company_id=self.company_id.id, bom_type='phantom')

    def _trk_gate_entry_type(self):
        return self.env.ref('elegomotors_setup.picking_type_gate_entry', raise_if_not_found=False)

    def _trk_move_figures(self, move, gate_type):
        """(received, passed, failed, pending, stock, is_qc) for one receipt
        move, in the move's own unit.

        Received is the gate's booked quantity on the module's own Gate Entry
        type, and the VALIDATED quantity on any other receipt (see
        _trk_kit_figures). QC, though, applies to every receipt: the GRNs people
        really make are of the warehouse's "GRN" operation type, not Gate Entry,
        and button_validate sends every incoming receipt through the same QC
        steps. Looking for Gate Entry alone left QC Pass / Reject / Pending and
        the QC No. empty for all real receipts."""
        picking = move.picking_id
        is_gate = bool(gate_type and picking and picking.picking_type_id == gate_type)
        is_qc = bool(
            picking and picking.picking_type_code == 'incoming' and move.product_id.x_qc_required
        )
        validated = move.quantity if move.state == 'done' else 0.0
        received = move.x_qty_received if is_gate else validated
        if is_qc:
            decided = picking.x_gate_entry_state == 'ready'
            passed = move.x_qty_qc_passed if decided else 0.0
            failed = move.x_qty_qc_failed if decided else 0.0
            # Waiting for QC: on a Gate Entry once booked, on an ordinary receipt
            # once Store has sent it to QC (not while the GRN is only a draft).
            in_qc = is_gate or picking.x_gate_entry_state == 'in_qc'
            pending = move.x_qty_received if (in_qc and not decided) else 0.0
            stock = (move.x_qty_final if decided else 0.0) if is_gate else validated
            return received, passed, failed, pending, stock, True
        return received, 0.0, 0.0, 0.0, validated, False

    def _trk_line_figures(self, line, gate_type, kit_bom):
        """Figures of one PO line, in the line's own unit (kits for a kit)."""
        if kit_bom:
            figures = self._trk_kit_figures(line, gate_type, kit_bom)
            if line._ckd_kit_bom():
                # A CKD kit line's own Received (the PO form, and what a vendor bill
                # is made from) is worked out from these very figures: see
                # PurchaseOrderLineCkd._ckd_kit_qty_received. So the two can never
                # differ, and the line's stored value must not be folded back in here.
                return figures
            received, passed, failed, pending, stock = figures
            # Any other kit (e.g. a battery pack): Odoo's own kit quantity still counts
            return max(received, line.qty_received), passed, failed, pending, stock

        moves = line.move_ids.filtered(
            lambda m: m.state != 'cancel' and m.location_id.usage == 'supplier'
        )
        received = passed = failed = pending = stock = 0.0
        for move in moves:
            r, p, f, q, s, _is_qc = self._trk_move_figures(move, gate_type)
            received += r
            passed += p
            failed += f
            pending += q
            stock += s
        # Odoo's own received quantity covers receipts booked without a Gate Entry
        return max(received, line.qty_received), passed, failed, pending, stock

    def _trk_kit_parts(self, line, gate_type, kit_bom):
        """The per-part figures of a kit line, in the PARTS' own unit.

        Returns (per_kit, acc): per_kit is {BoM line id: quantity of that part in
        one kit}, acc is {BoM line id: [received, passed, failed, pending, stock,
        is_qc]} summed over the part's receipt moves. A part with no receipt move
        has no entry in acc."""
        moves = line.move_ids.filtered(
            lambda m: m.state != 'cancel' and m.location_id.usage == 'supplier'
        )
        per_kit = {}
        for bom_line in kit_bom.bom_line_ids:
            per_kit[bom_line.id] = (
                (bom_line.product_qty / kit_bom.product_qty) if kit_bom.product_qty else bom_line.product_qty
            ) or 1.0
        acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0, False])
        for move in moves:
            if not move.bom_line_id or move.bom_line_id.id not in per_kit:
                continue
            r, p, f, q, s, is_qc = self._trk_move_figures(move, gate_type)
            row = acc[move.bom_line_id.id]
            row[0] += r
            row[1] += p
            row[2] += f
            row[3] += q
            row[4] += s
            row[5] = row[5] or is_qc
        return per_kit, acc

    def _trk_kit_figures(self, line, gate_type, kit_bom):
        """(received, passed, failed, pending, stock) of a kit line, in kits.

        The receipt is in individual parts. Convert every part to "kits worth"
        with its BoM quantity, then take the limiting part (min for what is good,
        max for what is bad / undecided) so the figures stay in kits and a
        half-received kit is not counted whole.

        Received of a part is what _trk_move_figures says: the validated
        quantity for an ordinary receipt (so a receipt that is only QC-approved
        and still waiting for Store to validate it does not count yet), and the
        gate's own Received figure for the module's Gate Entry type."""
        per_kit, acc = self._trk_kit_parts(line, gate_type, kit_bom)
        qc_rows = [(bid, r) for bid, r in acc.items() if r[5]]
        received = min(
            (acc[bid][0] / per_kit[bid] if bid in acc else 0.0 for bid in per_kit),
            default=0.0,
        )
        passed = min((r[1] / per_kit[bid] for bid, r in qc_rows), default=0.0)
        failed = max((r[2] / per_kit[bid] for bid, r in qc_rows), default=0.0)
        pending = max((r[3] / per_kit[bid] for bid, r in qc_rows), default=0.0)
        stock = min(
            (acc[bid][4] / per_kit[bid] if bid in acc else 0.0 for bid in per_kit),
            default=0.0,
        )
        return received, passed, failed, pending, stock

    # A CKD kit line's figures now come straight from its part moves, not from the
    # line's stored Received, so the part moves' bom_line_id and source location
    # are triggers too.
    @api.depends(
        'state',
        'order_line.display_type', 'order_line.product_id',
        'order_line.product_qty', 'order_line.qty_received',
        'order_line.move_ids.bom_line_id', 'order_line.move_ids.location_id',
        'order_line.move_ids.state', 'order_line.move_ids.quantity',
        'order_line.move_ids.x_qty_received', 'order_line.move_ids.x_qty_qc_passed',
        'order_line.move_ids.x_qty_qc_failed', 'order_line.move_ids.x_qty_final',
        'order_line.move_ids.picking_id.x_gate_entry_state',
    )
    def _compute_x_tracking(self):
        gate_type = self._trk_gate_entry_type()
        for po in self:
            lines = po.order_line.filtered(
                lambda l: not l.display_type and l.product_id and l.product_id.type != 'service'
            )
            ordered = sum(lines.mapped('product_qty'))
            received = passed = failed = pending = stock = 0.0
            if po.state in ('purchase', 'done'):
                kit_boms = po._trk_kit_boms(lines)
                for line in lines:
                    r, p, f, q, s = po._trk_line_figures(
                        line, gate_type, kit_boms.get(line.product_id) or self.env['mrp.bom'])
                    received += r
                    passed += p
                    failed += f
                    pending += q
                    stock += s
            po.x_trk_po_qty = ordered
            po.x_trk_received_qty = received
            po.x_trk_pending_qty = 0.0 if po.state == 'cancel' else max(ordered - received, 0.0)
            po.x_trk_qc_passed_qty = passed
            po.x_trk_qc_rejected_qty = failed
            po.x_trk_qc_pending_qty = pending
            po.x_trk_stock_qty = stock
            po.x_trk_stage = po._trk_stage(ordered, received, pending, failed)

    # ------------------------------------------------------------------
    # Part rows (the client's Excel lists each PO with its parts underneath)
    # ------------------------------------------------------------------

    def _trk_part_rows(self):
        """One row per PART of this PO: the product of an ordinary line, and every
        part of a kit line (a kit is received as its individual parts). Same
        figures as the PO row, worked out by the same functions, but in the
        PART's own unit. A kit part's ordered quantity is kits x quantity per kit."""
        self.ensure_one()
        gate_type = self._trk_gate_entry_type()
        lines = self.order_line.filtered(
            lambda l: not l.display_type and l.product_id and l.product_id.type != 'service'
        )
        confirmed = self.state in ('purchase', 'done')
        kit_boms = self._trk_kit_boms(lines) if confirmed else {}
        rows = []
        for line in lines:
            kit_bom = kit_boms.get(line.product_id) if confirmed else False
            if kit_bom:
                per_kit, acc = self._trk_kit_parts(line, gate_type, kit_bom)
                for bom_line in kit_bom.bom_line_ids:
                    r, p, f, q, s, _is_qc = acc.get(bom_line.id) or (0.0, 0.0, 0.0, 0.0, 0.0, False)
                    rows.append(self._trk_part_row(
                        bom_line.product_id, line.product_qty * per_kit[bom_line.id], r, p, f, q, s))
                continue
            if confirmed:
                r, p, f, q, s = self._trk_line_figures(line, gate_type, False)
            else:
                r = p = f = q = s = 0.0
            rows.append(self._trk_part_row(line.product_id, line.product_qty, r, p, f, q, s))
        return rows

    def _trk_part_row(self, product, ordered, received, passed, failed, qc_pending, stock):
        self.ensure_one()
        return {
            'name': product.display_name,
            'ordered': ordered,
            'received': received,
            'pending': 0.0 if self.state == 'cancel' else max(ordered - received, 0.0),
            'qc_passed': passed,
            'qc_rejected': failed,
            'qc_pending': qc_pending,
            'stock': stock,
        }

    def action_open_client_export(self):
        """The "Download Excel" button of the report: opens the download window,
        for the POs ticked in the list (or, with none ticked, for the filters in
        the window)."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Download PO Tracking (Excel)',
            'res_model': 'elegomotors.po.tracking.export',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_ids': [(6, 0, self.ids)]},
        }

    def _trk_stage(self, ordered, received, qc_pending, qc_rejected=0.0):
        self.ensure_one()
        if self.state == 'cancel':
            return 'cancelled'
        if self.state not in ('purchase', 'done'):
            return 'rfq'
        if float_is_zero(received, precision_digits=4):
            # Nothing validated yet. Material that is sitting in QC is already here.
            return 'quality' if qc_pending > 0 else 'awaiting'
        fully = float_compare(received, ordered, precision_digits=4) >= 0
        if qc_pending > 0:
            return 'quality' if fully else 'partial_qc'
        if qc_rejected > 0:
            return 'partial_qc'  # rejected goods are waiting for replacement
        return 'completed' if fully else 'partial'

    # ------------------------------------------------------------------
    # Reference lists (shown in the report, built from the PO's own documents)
    # ------------------------------------------------------------------

    @api.depends('picking_ids', 'invoice_ids', 'invoice_ids.name', 'invoice_ids.state',
                 'order_line.move_ids.picking_id')
    def _compute_x_trk_refs(self):
        Picking = self.env['stock.picking']
        by_source = defaultdict(lambda: Picking)
        for picking in Picking.search([('x_source_po_id', 'in', self.ids)]):
            by_source[picking.x_source_po_id.id] |= picking
        state_labels = dict(Picking._fields['x_gate_entry_state'].selection)
        for po in self:
            pickings = (
                po.order_line.move_ids.picking_id | po.picking_ids | by_source[po.id]
            ).filtered(lambda p: p.picking_type_code == 'incoming' and p.state != 'cancel')
            pickings = pickings.sorted('id')
            po.x_trk_grn_refs = ', '.join(pickings.mapped('name'))
            qc_refs = []
            for picking in pickings:
                # every receipt with QC items, whatever its operation type
                if any(m.product_id.x_qc_required for m in picking.move_ids):
                    qc_refs.append('%s (%s)' % (
                        picking.name, state_labels.get(picking.x_gate_entry_state, '')))
            po.x_trk_qc_refs = ', '.join(qc_refs)
            # Elego's own purchase invoice: the vendor bill(s) booked for this PO
            # (a bill still in draft has no number yet).
            bills = po.invoice_ids.filtered(
                lambda b: b.move_type == 'in_invoice' and b.state != 'cancel').sorted('id')
            po.x_trk_bill_refs = ', '.join(
                b.name if b.name and b.name != '/' else 'Draft' for b in bills)
            seen, refs = set(), []
            candidates = [
                (p.x_vendor_invoice_number, p.x_vendor_invoice_date) for p in pickings
            ] + [
                (b.ref, b.invoice_date)
                for b in po.invoice_ids.filtered(lambda b: b.move_type == 'in_invoice' and b.state != 'cancel')
            ]
            for number, date in candidates:
                number = (number or '').strip()
                if not number or number.casefold() in seen:
                    continue
                seen.add(number.casefold())
                refs.append('%s (%s)' % (number, date.strftime('%d/%m/%Y')) if date else number)
            po.x_trk_invoice_refs = ', '.join(refs)
