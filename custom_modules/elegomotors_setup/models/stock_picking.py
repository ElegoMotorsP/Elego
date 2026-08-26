# -*- coding: utf-8 -*-
import json
import math
from urllib.parse import quote

from markupsafe import Markup
from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model_create_multi
    def create(self, vals_list):
        # Show the Quotation Number as Source Document on customer deliveries,
        # not the Sales Order number: sale_stock sets origin = sale_order.name
        # directly in the creation vals (the order has already been renamed
        # to its SO number, EGO-SO-…, by then — see sale_order.py's
        # _assign_sale_order_number()). Matched here directly on the vals'
        # origin string, BEFORE creation: rewriting picking.sale_id after
        # super().create() doesn't reliably work, because sale_id is
        # computed from move_ids, and the procurement rule can create the
        # picking shell before its moves are attached — so sale_id isn't
        # guaranteed to resolve yet at that point. Matching on origin avoids
        # that timing dependency entirely, the same way the existing
        # fallback in _update_invoice_serials_on_delivery() below already
        # matches sale.order by name. Safe to override outright: nothing
        # else in this codebase matches sale.order by picking.origin except
        # that one fallback, which already prefers the real sale_id link first.
        for vals in vals_list:
            origin = vals.get('origin')
            if not origin:
                continue
            sale = self.env['sale.order'].search([('name', '=', origin)], limit=1)
            if sale and sale.x_quotation_number:
                vals['origin'] = sale.x_quotation_number
        return super().create(vals_list)

    # --- existing fields (d93d856) ---
    x_vendor_invoice_number = fields.Char(
        string='Vendor Invoice Number',
        copy=False,
        help='Supplier invoice reference captured during receipt.',
    )
    x_vendor_invoice_date = fields.Date(
        string='Vendor Invoice Date',
        copy=False,
        help='Date on the supplier invoice captured during receipt.',
    )

    # --- Gate Entry: pick an active PO for the selected vendor and auto-fill lines ---
    x_source_po_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        copy=False,
        help='Select an open Purchase Order of the vendor above — the operation '
             'lines are filled automatically with the remaining (not yet received) '
             'quantities of that PO. Fully received or closed POs are not listed.',
    )

    @api.onchange('partner_id')
    def _onchange_partner_clear_source_po(self):
        # Vendor changed — a PO of the old vendor no longer applies
        if self.x_source_po_id and self.x_source_po_id.partner_id != self.partner_id:
            self.x_source_po_id = False

    @api.onchange('x_source_po_id')
    def _onchange_x_source_po_id(self):
        po = self.x_source_po_id
        if not po:
            return
        if not self.partner_id:
            self.partner_id = po.partner_id
        self.origin = po.name
        moves = [Command.clear()]
        for line in po.order_line:
            if line.display_type or line.product_id.type == 'service':
                continue
            qty_remaining = line.product_qty - line.qty_received
            if qty_remaining <= 0:
                continue
            # purchase_line_id links the move back to the PO so qty_received
            # updates on validation and picking.purchase_id resolves for the
            # auto vendor-bill logic in button_validate (Issue 4).
            moves.append(Command.create({
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom': line.product_uom.id,
                'product_uom_qty': qty_remaining,
                'purchase_line_id': line.id,
                'location_id': self.location_id.id,
                'location_dest_id': self.location_dest_id.id,
                'picking_type_id': self.picking_type_id.id,
                'company_id': self.company_id.id,
            }))
        self.move_ids_without_package = moves

    # --- Issue 5/6: Gate Entry QC workflow state ---
    x_gate_entry_state = fields.Selection([
        ('pending_qc', 'Pending QC'),
        ('in_qc', 'In QC'),
        ('ready', 'Ready'),
    ], string='Gate Entry Status', default='pending_qc', copy=False,
       help='Custom QC workflow state for Gate Entry receipts only.')

    # --- Issue 12: replacement tracking ---
    x_pending_replacement_qty = fields.Float(
        string='Pending Replacement Qty',
        default=0.0,
        copy=False,
        help='Items awaiting replacement from vendor after QC failure.',
    )
    x_has_pending_replacement = fields.Boolean(
        string='Has Pending Replacement',
        compute='_compute_has_pending_replacement',
        store=True,
        help='True when replacement goods from vendor are still outstanding.',
    )
    x_qc_check_result_ids = fields.One2many(
        'elegomotors.qc.check.result', 'picking_id',
        string='QC Inspection Results',
        copy=False,
    )
    x_is_gate_entry = fields.Boolean(
        string='Is Gate Entry',
        compute='_compute_is_gate_entry',
        store=False,
    )
    x_qc_required_product_names = fields.Char(
        string='QC Products',
        compute='_compute_qc_display_fields',
        help='Products on this Gate Entry that require QC inspection.',
    )
    x_qc_serial_nos = fields.Char(
        string='QC Serial No(s)',
        compute='_compute_qc_display_fields',
        help='Serial/lot numbers already recorded against this Gate Entry\'s QC results.',
    )

    # OUT deliveries: True once Amit has assigned the bike serials via the
    # Scan Bike Serials wizard. Bike deliveries cannot be validated without
    # it — serials must come from scanning, never from auto-reservation.
    x_bike_serials_scanned = fields.Boolean(
        string='Bike Serials Scanned',
        default=False,
        copy=False,
    )

    # Serial numbers picked on outgoing deliveries — traceability for SO → invoice flow
    x_picked_serial_nos = fields.Char(
        string='Serial No(s)',
        compute='_compute_picked_serial_nos',
        store=False,
        help='Serial/lot numbers of bike units picked in this outgoing delivery.',
    )

    # Battery/charger combined totals — a multi-bike delivery lists one
    # exploded "Battery Cell" / charger row per bike combo line (traceability
    # to each bike stays intact), which makes the real total hard to read at
    # a glance. This rolls them up into one summary table, mirroring the
    # "Hand Over With Bike(s): Battery: X  Charger: Y" line already shown
    # on the printed invoice (report_invoice.xml), but broken out per
    # battery/charger type with its cell count.
    x_battery_summary = fields.Html(
        string='Battery/Charger Totals',
        compute='_compute_battery_summary',
    )

    @api.depends('move_ids.product_id', 'move_ids.product_uom_qty',
                 'move_ids.state', 'move_ids.x_kit_pack_name',
                 'move_ids.x_battery_cell_hint')
    def _compute_battery_summary(self):
        for picking in self:
            if picking.picking_type_code != 'outgoing':
                picking.x_battery_summary = False
                continue
            totals = {}
            order = []
            for move in picking.move_ids.filtered(lambda m: m.state != 'cancel'):
                name_lower = (move.product_id.name or '').lower()
                if 'battery cell' in name_lower:
                    key = move.x_kit_pack_name or move.product_id.name
                elif 'charger' in name_lower or 'battery pack' in name_lower:
                    key = move.product_id.name
                else:
                    continue
                if key not in totals:
                    totals[key] = {'qty': 0.0, 'cells': move.x_battery_cell_hint or ''}
                    order.append(key)
                totals[key]['qty'] += move.product_uom_qty
            if not totals:
                picking.x_battery_summary = False
                continue
            rows = ''.join(
                '<tr><td>%s</td><td>%s</td><td style="text-align:right;">%s</td></tr>'
                % (key, totals[key]['cells'], '%g' % totals[key]['qty'])
                for key in order
            )
            picking.x_battery_summary = Markup(
                '<table class="table table-sm table-bordered" style="max-width:500px;">'
                '<thead><tr><th>Item</th><th>Cells</th><th>Total Qty</th></tr></thead>'
                '<tbody>%s</tbody></table>' % rows
            )

    # Consolidated Daily PI fields
    x_consolidated_mo_ids = fields.Many2many(
        'mrp.production',
        'stock_picking_consolidated_mo_rel',
        'picking_id',
        'production_id',
        string='Source Manufacturing Orders',
        copy=False,
        help='MOs whose components are aggregated into this consolidated daily PI.',
    )
    x_pi_model_key = fields.Char(
        string='PI Model Key',
        copy=False,
        index=True,
        help='Product template external ID key used for grouping and idempotency.',
    )

    @api.depends('picking_type_id')
    def _compute_is_gate_entry(self):
        gate_ref = self.env.ref(
            'elegomotors_setup.picking_type_gate_entry', raise_if_not_found=False
        )
        for picking in self:
            picking.x_is_gate_entry = bool(gate_ref and picking.picking_type_id == gate_ref)

    @api.depends('move_ids.product_id.x_qc_required', 'x_qc_check_result_ids.lot_id')
    def _compute_qc_display_fields(self):
        for picking in self:
            qc_moves = picking.move_ids.filtered(lambda m: m.product_id.x_qc_required)
            picking.x_qc_required_product_names = ', '.join(
                qc_moves.mapped('product_id.name')
            )
            lots = picking.x_qc_check_result_ids.mapped('lot_id').filtered(bool)
            picking.x_qc_serial_nos = ', '.join(lots.mapped('name'))

    @api.depends('move_line_ids', 'move_line_ids.lot_id', 'state',
                 'picking_type_code', 'x_bike_serials_scanned')
    def _compute_picked_serial_nos(self):
        for picking in self:
            if picking.picking_type_code == 'outgoing':
                # Only show serials that were actually scanned by the Store
                # (or on already-validated legacy transfers) — never Odoo's
                # auto-reserved lots, which do not represent the physical
                # bikes picked.
                if not picking.x_bike_serials_scanned and picking.state != 'done':
                    picking.x_picked_serial_nos = ''
                    continue
                lots = picking.move_line_ids.filtered(
                    lambda ml: ml.lot_id and ml.qty_done > 0
                ).mapped('lot_id.name')
                # Also include reserved (not yet done) lots so it's visible before validate
                if not lots:
                    lots = picking.move_line_ids.filtered(
                        lambda ml: ml.lot_id
                    ).mapped('lot_id.name')
                picking.x_picked_serial_nos = ', '.join(lots) if lots else ''
            else:
                picking.x_picked_serial_nos = ''

    @api.depends('x_pending_replacement_qty')
    def _compute_has_pending_replacement(self):
        for picking in self:
            picking.x_has_pending_replacement = picking.x_pending_replacement_qty > 0

    # Hide Validate from Pratik (group_qc_pass_operator) on incoming receipts.
    # Overrides Odoo's show_validate computed field, which every Validate button
    # in the form (stock, purchase_stock, etc.) reads for its visibility.
    @api.depends_context('uid')
    def _compute_show_validate(self):
        super()._compute_show_validate()
        is_inbound_op = self.env.user.has_group(
            'elegomotors_setup.group_inbound_operator'
        )
        for picking in self:
            if picking.picking_type_code == 'incoming' and not is_inbound_op:
                picking.show_validate = False

    # --- QC parameter checklist helpers ---

    def _create_qc_check_results(self):
        """Auto-create elegomotors.qc.check.result rows for every QC-required
        product move in this picking. Creates one row per parameter per
        SAMPLED unit (unit_index 1..sample_count) — sample_count is derived
        from the product's x_qc_sample_percent (Manohar/Admin-only setting,
        default 100%), so a bulk receipt doesn't force Pratik to fill a
        checklist for every single unit. At least 1 unit is always sampled
        unless the percentage is explicitly set to 0. Idempotent — skips
        (parameter, unit) pairs that already have a result record (safe to
        call multiple times)."""
        CheckResult = self.env['elegomotors.qc.check.result'].sudo()
        for picking in self:
            for move in picking.move_ids.filtered(lambda m: m.product_id.x_qc_required):
                tmpl = move.product_id.product_tmpl_id
                params = tmpl.x_qc_parameter_ids
                unit_count = max(1, int(move.x_qty_received or move.product_uom_qty))
                sample_pct = min(100.0, max(0.0, tmpl.x_qc_sample_percent))
                if sample_pct <= 0:
                    sample_count = 0
                else:
                    sample_count = min(unit_count, max(1, math.ceil(unit_count * sample_pct / 100.0)))
                existing = picking.x_qc_check_result_ids.filtered(
                    lambda r: r.move_id == move
                )
                existing_pairs = {(r.parameter_id.id, r.unit_index) for r in existing}
                for unit_idx in range(1, sample_count + 1):
                    for param in params:
                        if (param.id, unit_idx) not in existing_pairs:
                            CheckResult.create({
                                'picking_id': picking.id,
                                'move_id': move.id,
                                'parameter_id': param.id,
                                'unit_index': unit_idx,
                            })

    def _auto_route_qc_items(self):
        """Auto-route a mixed incoming receipt without a wizard popup.
        Non-QC items go to Store (qty_done = received), QC items get a
        backorder that is immediately placed in 'in_qc' state.
        Mirrors the logic in stock.picking.qc.wizard.action_send_qc_and_validate_others().
        """
        self.ensure_one()
        store_loc = self.env.ref('elegomotors_setup.location_ego_store')
        qc_inward_loc = self.env.ref(
            'elegomotors_setup.location_ego_qc_inward', raise_if_not_found=False
        )
        MoveL = self.env['stock.move.line']
        qc_names = ', '.join(
            self.move_ids.filtered(lambda m: m.product_id.x_qc_required).mapped('product_id.name')
        )
        non_qc_names = ', '.join(
            self.move_ids.filtered(lambda m: not m.product_id.x_qc_required).mapped('product_id.name')
        )
        # Create explicit move lines: non-QC fully done → Store, QC done=0 → QC Inward (backorder)
        for move in self.move_ids:
            move.move_line_ids.unlink()
            qty = move.x_qty_received or move.product_uom_qty
            if not move.product_id.x_qc_required:
                move.x_qty_qc_passed = qty
                move.location_dest_id = store_loc.id
                MoveL.create({
                    'move_id': move.id,
                    'picking_id': self.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'qty_done': qty,
                    'location_id': move.location_id.id,
                    'location_dest_id': store_loc.id,
                })
            else:
                dest_id = qc_inward_loc.id if qc_inward_loc else move.location_dest_id.id
                move.location_dest_id = dest_id
                MoveL.create({
                    'move_id': move.id,
                    'picking_id': self.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'qty_done': 0,
                    'location_id': move.location_id.id,
                    'location_dest_id': dest_id,
                })
        result = self.with_context(skip_qc_wizard=True).button_validate()
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            backorder_wiz = self.env['stock.backorder.confirmation'].with_context(
                button_validate_picking_ids=self.ids,
                skip_qc_wizard=True,
            ).create({'pick_ids': [(4, self.id)]})
            backorder_wiz.process()
        backorder = self.backorder_ids[:1]
        if backorder:
            backorder.x_gate_entry_state = 'in_qc'
            backorder._create_qc_check_results()
            pratik = self.env.ref('elegomotors_setup.user_ego_pratik', raise_if_not_found=False)
            partner_ids = [pratik.partner_id.id] if pratik and pratik.partner_id else []
            backorder.message_post(
                body=Markup(
                    f"Auto-routed to QC by <b>{self.env.user.name}</b>. "
                    f"Items requiring inspection: <b>{qc_names}</b>.<br/>"
                    f"<b>Pratik:</b> Please inspect each item, enter QC Passed qty, "
                    f"then click <b>Approve QC</b>."
                ),
                partner_ids=partner_ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        return False

    def action_gate_entry_approve_qc(self):
        """Pratik approves QC: sets qty_done per serial based on pass/fail results,
        blacklists failed serials immediately, routes the approved goods on to
        Store, then marks the picking ready."""
        self.ensure_one()
        MoveL = self.env['stock.move.line']
        store_loc = self.env.ref('elegomotors_setup.location_ego_store', raise_if_not_found=False)

        for move in self.move_ids:
            # QC-required moves arrive at EGO/QC Inward (Gate Entry -> in_qc routing).
            # Once approved they must land in EGO/Store — "Issue to Production"
            # sources components from Store only, so leaving them at QC Inward
            # would make them invisible to MO material reservation even though
            # the product's aggregate on-hand quantity looks correct.
            if store_loc:
                move.location_dest_id = store_loc.id
                move.move_line_ids.location_dest_id = store_loc.id

            qc_results = self.x_qc_check_result_ids.filtered(lambda r: r.move_id == move)
            lots_in_results = qc_results.mapped('lot_id').filtered(bool)

            if move.product_id.tracking in ('serial', 'lot') and lots_in_results:
                # Build per-lot pass/fail: a lot fails if ANY parameter row is 'fail'
                lot_pass = {}
                for r in qc_results:
                    if not r.lot_id:
                        continue
                    lid = r.lot_id.id
                    if lid not in lot_pass:
                        lot_pass[lid] = True
                    if r.result == 'fail':
                        lot_pass[lid] = False

                # Sampling safety net: a lot already reserved on this move
                # but with NO check-result rows (skipped by QC Sample %)
                # was never inspected — treat it as passed rather than
                # silently dropping it when move lines are rebuilt below.
                for ml in move.move_line_ids:
                    if ml.lot_id and ml.lot_id.id not in lot_pass:
                        lot_pass[ml.lot_id.id] = True

                # Rebuild move lines: 1 line per lot, qty_done=1 if pass, 0 if fail
                move.move_line_ids.unlink()
                passed_qty = 0
                for lot_id_val, passed in lot_pass.items():
                    lot = self.env['stock.lot'].browse(lot_id_val)
                    if passed:
                        passed_qty += 1
                        MoveL.create({
                            'move_id': move.id,
                            'picking_id': self.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'qty_done': 1.0,
                            'lot_id': lot.id,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                        })
                    else:
                        lot.sudo().x_blacklisted = True

                move.x_qty_qc_passed = passed_qty
            else:
                # Non-serial/lot tracked, or no lots entered: use aggregate x_qty_qc_passed.
                # Default to the full received quantity (all passed) unless Pratik
                # has explicitly entered a lower "QC Passed" value on this row while
                # inspecting — that lower value is what makes the remainder count
                # as QC Failed once approved.
                qty = move.x_qty_qc_passed or move.x_qty_received or move.product_uom_qty
                move.x_qty_qc_passed = qty
                for ml in move.move_line_ids:
                    ml.qty_done = qty
                if not move.move_line_ids:
                    move.write({'quantity': qty})

        self.x_gate_entry_state = 'ready'
        amit = self.env.ref('elegomotors_setup.user_ego_amit', raise_if_not_found=False)
        partner_ids = [amit.partner_id.id] if amit and amit.partner_id else []
        self.message_post(
            body=Markup(
                f"QC approved by <b>{self.env.user.name}</b>. "
                f"Transfer is ready for Store validation (Amit)."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    # --- Req 10: auto-create QC results when ANY incoming picking is confirmed ---

    def action_confirm(self):
        result = super().action_confirm()
        for picking in self:
            if picking.picking_type_code == 'incoming':
                qc_moves = picking.move_ids.filtered(lambda m: m.product_id.x_qc_required)
                if qc_moves:
                    picking._create_qc_check_results()
        return result

    # --- Issue 12: clear replacement flag when replacements arrive ---

    def action_clear_pending_replacement(self):
        """Amit confirms replacement goods have been received — clears the flag."""
        self.ensure_one()
        self.x_pending_replacement_qty = 0.0
        self.message_post(
            body=f"Replacement goods confirmed received by {self.env.user.name}.",
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    # --- MODIFIED: button_validate integrates Issues 5/6, 4, 9, 12 ---

    def button_validate(self):
        gate_entry_ref = self.env.ref(
            'elegomotors_setup.picking_type_gate_entry', raise_if_not_found=False
        )
        issue_type_ref = self.env.ref(
            'elegomotors_setup.picking_type_production_issue', raise_if_not_found=False
        )

        if not self.env.su:
            # --- Existing guard: picking-type group restriction ---
            for picking in self:
                group = picking.picking_type_id.group_id
                if group and self.env.user not in group.users:
                    raise AccessError(
                        f'You are not authorised to validate '
                        f'"{picking.picking_type_id.name}" transfers. '
                        f'Contact Manohar (Admin) if you need access.'
                    )

            # --- SO approval gate: outgoing deliveries of a confirmed but not
            #     yet approved Sales Order cannot be validated (shipped) ---
            for picking in self:
                if picking.picking_type_code == 'outgoing':
                    sale = getattr(picking, 'sale_id', False)
                    if sale and sale.pending_approval:
                        raise UserError(
                            f'{picking.name}: Sales Order {sale.name} is still '
                            f'awaiting approval from Rajshri (Accounts) or '
                            f'Manohar (MD). The delivery cannot be validated '
                            f'until the SO is approved.'
                        )

            # --- Blacklist gate: a QC-failed bike serial can never ship ---
            for picking in self:
                if picking.picking_type_code == 'outgoing':
                    bad = picking.move_line_ids.filtered(
                        lambda ml: ml.lot_id and ml.lot_id.x_blacklisted
                    )
                    if bad:
                        names = ', '.join(bad.mapped('lot_id.name'))
                        raise UserError(
                            f'{picking.name}: serial(s) {names} are blacklisted '
                            f'(QC failed) and cannot be shipped. Use "Scan Bike '
                            f'Serials" to pick different unit(s).'
                        )

            # --- PDI gate: a bike whose Pre-Delivery Inspection is not yet
            #     approved (pending or failed) can never ship. Mirrors the
            #     blacklist gate above.
            #     DISABLED for now (2026-08-16): the PDI workflow isn't fully
            #     rolled out yet, so it must not block deliveries — including
            #     from the mobile Barcode app's "Scan Bike Serials" flow.
            #     Flip PDI_GATE_ENABLED to True once PDI QC is in regular use. ---
            PDI_GATE_ENABLED = False
            if PDI_GATE_ENABLED:
                pdi_bike_tmpls = self.env['mrp.production']._get_ego_templates()
                for picking in self:
                    if picking.picking_type_code == 'outgoing':
                        unapproved = picking.move_line_ids.filtered(
                            lambda ml: ml.lot_id and ml.lot_id.x_pdi_state != 'passed'
                            and ml.lot_id.product_id.product_tmpl_id in pdi_bike_tmpls
                        )
                        if unapproved:
                            names = ', '.join(unapproved.mapped('lot_id.name'))
                            raise UserError(
                                f'{picking.name}: serial(s) {names} have not passed PDI '
                                f'(Pre-Delivery Inspection) yet. Complete PDI QC for these '
                                f'units before validating the delivery.'
                            )

            # --- Scan gate: bike serials must be assigned by scanning, never
            #     by Odoo's automatic reservation. Amit (Store) must run the
            #     Scan Bike Serials wizard before the delivery can validate. ---
            bike_tmpls = self.env['mrp.production']._get_ego_templates()
            for picking in self:
                if (
                    picking.picking_type_code == 'outgoing'
                    and not picking.x_bike_serials_scanned
                    and bike_tmpls
                    and any(
                        m.product_id.product_tmpl_id in bike_tmpls
                        for m in picking.move_ids
                        if m.state not in ('done', 'cancel')
                    )
                ):
                    raise UserError(
                        f'{picking.name}: bike serial numbers must be assigned '
                        f'by scanning the physical units. Click "Scan Bike '
                        f'Serials" and scan each bike before validating.'
                    )

            # --- Issue 5/6 + QC-required products: smart QC routing ---
            for picking in self:
                if picking.picking_type_code != 'incoming':
                    continue  # not an incoming receipt — skip

                # The wizard sets this flag when it calls button_validate itself
                if self.env.context.get('skip_qc_wizard'):
                    continue

                if picking.x_gate_entry_state == 'in_qc':
                    # QC started but Pratik hasn't approved yet
                    raise UserError(
                        f'{picking.name}: QC inspection is in progress. '
                        f'Wait for Pratik (Quality) to click Approve QC.'
                    )

                if picking.x_gate_entry_state == 'pending_qc':
                    qc_moves = picking.move_ids.filtered(
                        lambda m: m.product_id.x_qc_required
                    )
                    non_qc_moves = picking.move_ids.filtered(
                        lambda m: not m.product_id.x_qc_required
                    )
                    if qc_moves and non_qc_moves:
                        # Mixed: auto-route QC to backorder → in_qc, non-QC to Store
                        return picking._auto_route_qc_items()
                    elif qc_moves and not non_qc_moves:
                        # All QC-required → route to QC Inward, block validation
                        qc_inward_loc = self.env.ref(
                            'elegomotors_setup.location_ego_qc_inward', raise_if_not_found=False
                        )
                        if qc_inward_loc:
                            for move in qc_moves:
                                move.location_dest_id = qc_inward_loc.id
                                for ml in move.move_line_ids:
                                    ml.location_dest_id = qc_inward_loc.id
                        picking.x_gate_entry_state = 'in_qc'
                        picking._create_qc_check_results()
                        pratik = self.env.ref(
                            'elegomotors_setup.user_ego_pratik', raise_if_not_found=False
                        )
                        partner_ids = [pratik.partner_id.id] if pratik and pratik.partner_id else []
                        picking.message_post(
                            body=Markup(
                                f"Material auto-sent to QC by <b>{self.env.user.name}</b>. "
                                f"<b>Pratik:</b> Please perform inward QC inspection, "
                                f"enter QC Passed quantity, then click <b>Approve QC</b>."
                            ),
                            partner_ids=partner_ids,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                        )
                        return False
                    else:
                        # All non-QC → bypass gate, validate directly to Store
                        store_loc = self.env.ref('elegomotors_setup.location_ego_store')
                        for move in picking.move_ids:
                            move.location_dest_id = store_loc.id
                            qty = move.x_qty_received or move.product_uom_qty
                            move.x_qty_qc_passed = qty
                            for ml in move.move_line_ids:
                                ml.location_dest_id = store_loc.id
                                ml.qty_done = qty
                        picking.x_gate_entry_state = 'ready'

                elif picking.x_gate_entry_state != 'ready':
                    state_label = dict(
                        picking._fields['x_gate_entry_state'].selection
                    ).get(picking.x_gate_entry_state, picking.x_gate_entry_state)
                    raise UserError(
                        f'{picking.name}: Cannot validate. '
                        f'Current QC status: {state_label}'
                    )

        # --- Non-bike delivery lines default to sourcing from EGO/Finished
        #     Goods (the outgoing picking type's own default location) —
        #     correct for bikes, which are properly staged there after QC
        #     pass, but wrong for standalone battery/charger/accessory items:
        #     they live in EGO/Store and are never moved to FG. Left
        #     uncorrected, a validated delivery for e.g. a battery-only order
        #     (or the battery/charger lines of a bike combo) silently
        #     decrements — goes negative on — Finished Goods instead of the
        #     Store stock that's actually there, and the real on-hand
        #     quantity never moves. Runs for every outgoing delivery, not
        #     just bike-serial-scanned ones, since a pure accessory order has
        #     nothing to scan at all.
        store_loc = self.env.ref('elegomotors_setup.location_ego_store', raise_if_not_found=False)
        fg_loc = self.env.ref('elegomotors_setup.location_ego_fg', raise_if_not_found=False)
        bike_tmpls_for_location = self.env['mrp.production']._get_ego_templates()
        if store_loc and fg_loc:
            for picking in self:
                if picking.picking_type_code != 'outgoing':
                    continue
                for move in picking.move_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                    and m.product_id.product_tmpl_id not in bike_tmpls_for_location
                    and m.location_id == fg_loc
                ):
                    move.location_id = store_loc.id
                    move.move_line_ids.write({'location_id': store_loc.id})

        # --- Kit/accessory completion: once bike serials are scanned, the
        #     battery-pack kit components exploded onto the same delivery
        #     (Battery Cell, Charger — plain quantity-tracked, no lot) are
        #     otherwise left however Odoo's own reservation left them. The
        #     Scan Bike Serials wizard only ever touches the bike's own move
        #     line, so these sibling moves can validate at qty_done=0 even
        #     though the physical units ship with the bike, and on-hand stock
        #     for them never actually decreases. Force them to their full
        #     demand here. Serial/lot-tracked components are left alone —
        #     none exist among today's battery/charger kit parts, and forcing
        #     a lot choice isn't safe to guess.
        bike_tmpls_for_kit = self.env['mrp.production']._get_ego_templates()
        MoveLine = self.env['stock.move.line']
        for picking in self:
            if picking.picking_type_code != 'outgoing' or not picking.x_bike_serials_scanned:
                continue
            for move in picking.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
                and m.product_id.product_tmpl_id not in bike_tmpls_for_kit
                and m.product_id.tracking == 'none'
            ):
                remaining = move.product_uom_qty - sum(move.move_line_ids.mapped('qty_done'))
                if remaining <= 0.0001:
                    continue
                if move.move_line_ids:
                    move.move_line_ids[0].qty_done += remaining
                else:
                    MoveLine.create({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'qty_done': remaining,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    })

        result = super().button_validate()

        # Post-validation hooks — run only for records that are now 'done'
        for picking in self:
            if picking.state != 'done':
                continue

            # --- Consolidated/urgent Issue to Production: the picking's own
            #     stock moves are hand-built by consolidated_pi_generator.py —
            #     aggregated quantities across many MOs — with no push/pull
            #     link back to any MO's own move_raw_ids (unlike Odoo's normal
            #     auto-generated PBM picking, which action_confirm() on
            #     mrp.production cancels in favour of this one). Validating it
            #     correctly moves stock Store -> Production WIP, but nothing
            #     else ever re-triggers reservation on the linked MOs' raw
            #     moves, so they consume nothing on Mark Done and the issued
            #     stock just accumulates in Production WIP. Re-assign them now
            #     that the components are actually available there. sudo():
            #     this is system bookkeeping on the MO, not something the
            #     validating user (e.g. Amit, Store — no manufacturing access)
            #     needs rights for; without sudo() this reservation call hits
            #     mrp.workorder's ACL (touched internally by MRP's own
            #     reservation-state recompute) and raises an AccessError.
            if picking.x_consolidated_mo_ids:
                picking.sudo().x_consolidated_mo_ids.mapped('move_raw_ids').filtered(
                    lambda m: m.state not in ('done', 'cancel')
                )._action_assign()

            # --- Issue 4: auto-create vendor bill for validated Gate Entry receipts ---
            if (
                gate_entry_ref
                and picking.picking_type_id == gate_entry_ref
                and hasattr(picking, 'purchase_id')
                and picking.purchase_id
            ):
                po = picking.purchase_id
                existing_draft_bill = po.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'in_invoice' and inv.state == 'draft'
                )
                if not existing_draft_bill:
                    # NOTE: method name verified as action_create_invoice in Odoo 18 purchase
                    po.sudo().action_create_invoice()
                bill = po.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'in_invoice' and inv.state == 'draft'
                )[:1]
                if bill:
                    update_vals = {}
                    if picking.x_vendor_invoice_number:
                        update_vals['ref'] = picking.x_vendor_invoice_number
                    if picking.x_vendor_invoice_date:
                        update_vals['invoice_date'] = picking.x_vendor_invoice_date
                    if update_vals:
                        bill.write(update_vals)

            # --- Issue 12: flag pending replacement if QC failures recorded ---
            if picking.picking_type_code == 'incoming':
                failed_qty = sum(
                    m.x_qty_qc_failed for m in picking.move_ids
                    if m.product_id.x_qc_required
                )
                if failed_qty > 0:
                    picking.x_pending_replacement_qty = failed_qty

            # --- Req 9: blacklist serial-tracked lots that failed inward QC ---
            # (serial-tracked lots are already blacklisted in action_gate_entry_approve_qc
            #  when lots are entered in the QC tab; this catches any remaining cases
            #  where move lines with lot_id and qty_done=0 slip through to validation)
            if picking.picking_type_code == 'incoming':
                for move in picking.move_ids:
                    if (
                        move.product_id.x_qc_required
                        and move.product_id.tracking == 'serial'
                        and move.x_qty_qc_failed > 0
                    ):
                        for ml in move.move_line_ids:
                            if ml.lot_id and not ml.qty_done:
                                ml.lot_id.sudo().x_blacklisted = True

            # --- Req 8: when outgoing delivery is validated for EGO-S1, push serial
            #     numbers into any already-created invoices for the same SO.
            #     This covers the case where the invoice was created (or proforma
            #     printed) before the delivery was validated.
            if picking.picking_type_code == 'outgoing':
                picking._update_invoice_serials_on_delivery()

            # --- Issue 9: notify Pratik + Prashant when Amit issues to Production ---
            if issue_type_ref and picking.picking_type_id == issue_type_ref:
                pratik = self.env.ref(
                    'elegomotors_setup.user_ego_pratik', raise_if_not_found=False
                )
                prashant = self.env.ref(
                    'elegomotors_setup.user_ego_prashant', raise_if_not_found=False
                )
                partner_ids = [
                    u.partner_id.id for u in [pratik, prashant]
                    if u and u.partner_id
                ]
                picking.message_post(
                    body=Markup(
                        f"Materials issued to Production by <b>{self.env.user.name}</b>. "
                        f"Production can now proceed for "
                        f"<b>{picking.origin or picking.name}</b>."
                    ),
                    partner_ids=partner_ids,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )

        return result

    def _update_invoice_serials_on_delivery(self):
        """Push EGO-S1 serial numbers into linked SO invoices immediately after delivery.

        Called when an outgoing picking is validated. Covers the case where
        the invoice/proforma was created before the delivery was validated.
        """
        self.ensure_one()
        ego_tmpl = self.env.ref(
            'elegomotors_setup.tmpl_ego_scooter', raise_if_not_found=False
        )
        if not ego_tmpl:
            return
        ego_lots = self.move_line_ids.filtered(
            lambda ml: ml.product_id.product_tmpl_id == ego_tmpl and ml.lot_id
        )
        if not ego_lots:
            return
        # Find the linked sale order
        sale = getattr(self, 'sale_id', False)
        if not sale and self.origin:
            sale = self.env['sale.order'].search(
                [('name', '=', self.origin)], limit=1
            )
        if not sale:
            return
        invoices = sale.invoice_ids.filtered(
            lambda inv: inv.move_type in ('out_invoice', 'out_refund')
        )
        for invoice in invoices:
            # Preferred: pull the store-scanned serials into x_assigned_lot_ids
            # (renders as Page 2 of the Tax Invoice). Legacy name-block
            # injection only when no delivery lots were found.
            if not invoice._sync_assigned_lots_from_deliveries():
                invoice.action_refresh_ego_serials()

    def action_open_delivery_bike_scan_wizard(self):
        """Amit scans the exact bikes being shipped on this delivery."""
        self.ensure_one()
        wizard = self.env['elegomotors.delivery.bike.scan.wizard'].create({
            'picking_id': self.id,
        })
        if not wizard.line_ids:
            raise UserError(
                'This delivery has no bike units to scan '
                '(no ElegoMotors bike products on it).'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Scan Bike Serials — Outgoing Delivery',
            'res_model': 'elegomotors.delivery.bike.scan.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    def action_scan_bike_serial(self, barcode):
        """Mobile Barcode app: a scan on the delivery's own scan screen that
        matches a bike serial is assigned directly, without needing the
        "Scan Bike Serials" wizard opened first. Mirrors that wizard's
        validations (model/colour match, FG availability, blacklist,
        duplicate-delivery check), one unit at a time.

        Returns {'handled': False} when the barcode isn't a recognised bike
        serial at all, so the caller falls back to normal barcode handling
        (product scan, etc). Otherwise returns {'handled': True, 'success':
        bool, 'message': str}.
        """
        self.ensure_one()
        bike_tmpls = self.env['mrp.production']._get_ego_templates()
        lot = self.env['stock.lot'].search([('name', '=', barcode)], limit=1)
        if not lot or lot.product_id.product_tmpl_id not in bike_tmpls:
            return {'handled': False}

        label = lot.product_id.display_name
        move = self.move_ids.filtered(
            lambda m: m.product_id == lot.product_id and m.state not in ('done', 'cancel')
        )[:1]
        if not move:
            return {
                'handled': True, 'success': False,
                'message': f'{label} is not on this delivery.',
            }

        # Odoo's automatic reservation can pre-populate lot_id on a move line
        # from whichever FG quant it happened to reserve — that's NOT a scan.
        # A line only counts as genuinely scanned once qty_done is set (which
        # only this method / a real "done" pick ever sets), never from
        # reservation alone. Checking lot_id here would falsely reject the
        # very first real scan whenever it happens to match what Odoo
        # auto-reserved.
        scanned_lines = move.move_line_ids.filtered(lambda ml: ml.qty_done > 0)
        if lot in scanned_lines.mapped('lot_id'):
            return {
                'handled': True, 'success': False,
                'message': f'Serial "{barcode}" is already scanned on this delivery.',
            }
        demanded = max(1, int(move.product_uom_qty))
        if len(scanned_lines) >= demanded:
            return {
                'handled': True, 'success': False,
                'message': f'All {label} units on this delivery are already scanned.',
            }
        if lot.x_blacklisted:
            return {
                'handled': True, 'success': False,
                'message': f'Serial "{barcode}" is BLACKLISTED (QC failed) — pick a different unit.',
            }

        quant = None
        fg_location = self.env.ref(
            'elegomotors_setup.location_ego_fg', raise_if_not_found=False
        )
        if fg_location:
            quant = self.env['stock.quant'].search([
                ('lot_id', '=', lot.id),
                ('location_id', 'child_of', fg_location.id),
                ('quantity', '>', 0),
            ], limit=1)
            if not quant:
                return {
                    'handled': True, 'success': False,
                    'message': f'Serial "{barcode}" is not currently available in Finished Goods.',
                }

        # Same reasoning as the auto-reservation comment above: only a line
        # with qty_done > 0 on the OTHER delivery represents a real scan —
        # an unscanned auto-reserved placeholder there must not block this
        # delivery from claiming the physical unit it's actually scanning.
        other_ml = self.env['stock.move.line'].search([
            ('lot_id', '=', lot.id),
            ('picking_id', '!=', self.id),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('qty_done', '>', 0),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=1)
        if other_ml:
            return {
                'handled': True, 'success': False,
                'message': f'Serial "{barcode}" is already scanned on delivery {other_ml.picking_id.name}.',
            }

        # Release any stale auto-reservation placeholder (qty_done still 0
        # — never actually scanned) another open delivery is still holding
        # on this exact lot, so this claim doesn't double-reserve the quant.
        self.env['stock.move.line'].search([
            ('lot_id', '=', lot.id),
            ('picking_id', '!=', self.id),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('qty_done', '=', 0),
            ('state', 'not in', ('done', 'cancel')),
        ]).unlink()

        # Same reasoning as above: pick a line by qty_done, not by lot_id —
        # an auto-reserved line's lot_id gets overwritten with whatever was
        # actually scanned, exactly like the wizard's own scan-only philosophy.
        target_ml = move.move_line_ids.filtered(lambda ml: ml.qty_done <= 0)[:1]
        if target_ml:
            target_ml.write({
                'lot_id': lot.id,
                'qty_done': 1,
                'location_id': quant.location_id.id if quant else move.location_id.id,
            })
        else:
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': self.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'qty_done': 1,
                'lot_id': lot.id,
                'location_id': quant.location_id.id if quant else move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
            })

        lot._create_pdi_check_results()
        lot.x_pdi_check_result_ids.filtered(lambda r: not r.picking_id).write({'picking_id': self.id})

        bike_moves = self.move_ids.filtered(
            lambda m: m.product_id.product_tmpl_id in bike_tmpls and m.state not in ('done', 'cancel')
        )
        if bike_moves and all(
            len(m.move_line_ids.filtered(lambda ml: ml.qty_done > 0)) >= max(1, int(m.product_uom_qty))
            for m in bike_moves
        ):
            self.x_bike_serials_scanned = True

        self.message_post(
            body=Markup(
                f"Bike serial scanned for shipment by <b>{self.env.user.name}</b>: "
                f"<b>{lot.name}</b> ({label})."
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return {
            'handled': True, 'success': True,
            'message': f'{label}: {lot.name} scanned.',
        }

    def action_export_qc_inward_report(self):
        """Download the Inward Material QC Report (xlsx) for the selected
        incoming receipts, or for every incoming receipt when nothing is
        selected (e.g. run straight from the Action menu)."""
        if self:
            domain = [('id', 'in', self.ids)]
        else:
            domain = [('picking_type_code', '=', 'incoming')]
        return {
            'type': 'ir.actions.act_url',
            'url': '/elegomotors/qc_report/inward/xlsx?domain=%s' % quote(json.dumps(domain)),
            'target': 'self',
        }
