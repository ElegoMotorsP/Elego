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
        move, in the move's own unit."""
        picking = move.picking_id
        is_gate = bool(gate_type and picking and picking.picking_type_id == gate_type)
        is_qc = is_gate and bool(move.product_id.x_qc_required)
        if is_gate:
            received = move.x_qty_received
        else:
            received = move.quantity if move.state == 'done' else 0.0
        if is_qc:
            decided = picking.x_gate_entry_state == 'ready'
            passed = move.x_qty_qc_passed if decided else 0.0
            failed = move.x_qty_qc_failed if decided else 0.0
            pending = 0.0 if decided else move.x_qty_received
            stock = move.x_qty_final if decided else 0.0
            return received, passed, failed, pending, stock, True
        stock = move.quantity if move.state == 'done' else 0.0
        return received, 0.0, 0.0, 0.0, stock, False

    def _trk_line_figures(self, line, gate_type, kit_bom):
        """Figures of one PO line, in the line's own unit (kits for a kit)."""
        moves = line.move_ids.filtered(
            lambda m: m.state != 'cancel' and m.location_id.usage == 'supplier'
        )
        if not kit_bom:
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

        # Kit line: the receipt is in individual parts. Convert every part to
        # "kits worth" with its BoM quantity, then take the limiting part
        # (min for what is good, max for what is bad / undecided) so the
        # figures stay in kits and a half-received kit is not counted whole.
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
        return max(received, line.qty_received), passed, failed, pending, stock

    @api.depends(
        'state',
        'order_line.display_type', 'order_line.product_id',
        'order_line.product_qty', 'order_line.qty_received',
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

    def _trk_stage(self, ordered, received, qc_pending, qc_rejected=0.0):
        self.ensure_one()
        if self.state == 'cancel':
            return 'cancelled'
        if self.state not in ('purchase', 'done'):
            return 'rfq'
        if float_is_zero(received, precision_digits=4):
            return 'awaiting'
        fully = float_compare(received, ordered, precision_digits=4) >= 0
        if qc_pending > 0:
            return 'quality' if fully else 'partial_qc'
        if qc_rejected > 0:
            return 'partial_qc'  # rejected goods are waiting for replacement
        return 'completed' if fully else 'partial'

    # ------------------------------------------------------------------
    # Reference lists (shown in the report, built from the PO's own documents)
    # ------------------------------------------------------------------

    @api.depends('picking_ids', 'invoice_ids', 'order_line.move_ids.picking_id')
    def _compute_x_trk_refs(self):
        gate_type = self._trk_gate_entry_type()
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
                if gate_type and picking.picking_type_id == gate_type and any(
                    m.product_id.x_qc_required for m in picking.move_ids
                ):
                    qc_refs.append('%s (%s)' % (
                        picking.name, state_labels.get(picking.x_gate_entry_state, '')))
            po.x_trk_qc_refs = ', '.join(qc_refs)
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
