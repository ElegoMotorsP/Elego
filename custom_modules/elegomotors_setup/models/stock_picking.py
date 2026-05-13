# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

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

    @api.depends('picking_type_id')
    def _compute_is_gate_entry(self):
        gate_ref = self.env.ref(
            'elegomotors_setup.picking_type_gate_entry', raise_if_not_found=False
        )
        for picking in self:
            picking.x_is_gate_entry = bool(gate_ref and picking.picking_type_id == gate_ref)

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
        product move in this picking, based on the parameter list defined on
        each product template. Idempotent — skips parameters that already have
        a result record (safe to call multiple times)."""
        CheckResult = self.env['elegomotors.qc.check.result'].sudo()
        for picking in self:
            for move in picking.move_ids.filtered(lambda m: m.product_id.x_qc_required):
                params = move.product_id.product_tmpl_id.x_qc_parameter_ids
                existing_param_ids = picking.x_qc_check_result_ids.filtered(
                    lambda r: r.move_id == move
                ).mapped('parameter_id.id')
                for param in params:
                    if param.id not in existing_param_ids:
                        CheckResult.create({
                            'picking_id': picking.id,
                            'move_id': move.id,
                            'parameter_id': param.id,
                        })

    def _auto_route_qc_items(self):
        """Auto-route a mixed Gate Entry without a wizard popup.
        Non-QC items go to Store (qty_done = received), QC items get a
        backorder that is immediately placed in 'in_qc' state.
        Mirrors the logic in stock.picking.qc.wizard.action_send_qc_and_validate_others().
        """
        self.ensure_one()
        store_loc = self.env.ref('elegomotors_setup.location_ego_store')
        MoveL = self.env['stock.move.line']
        qc_names = ', '.join(
            self.move_ids.filtered(lambda m: m.product_id.x_qc_required).mapped('product_id.name')
        )
        non_qc_names = ', '.join(
            self.move_ids.filtered(lambda m: not m.product_id.x_qc_required).mapped('product_id.name')
        )
        # Create explicit move lines: non-QC fully done → Store, QC done=0 → backorder
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
                MoveL.create({
                    'move_id': move.id,
                    'picking_id': self.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'qty_done': 0,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
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
        """Pratik approves QC: propagates x_qty_qc_passed → qty_done, notifies Amit."""
        self.ensure_one()
        for move in self.move_ids:
            qty = move.x_qty_qc_passed or move.product_uom_qty
            for ml in move.move_line_ids:
                ml.qty_done = qty
            if not move.move_line_ids:
                # Odoo 18 uses 'quantity' field name on stock.move for done qty
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

            # --- Issue 5/6 + QC-required products: smart QC routing ---
            for picking in self:
                if not (gate_entry_ref and picking.picking_type_id == gate_entry_ref):
                    continue  # not a Gate Entry — skip

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
                        # All QC-required → send straight to QC, no validation yet
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
                            for ml in move.move_line_ids:
                                ml.location_dest_id = store_loc.id
                                ml.qty_done = move.x_qty_received or move.product_uom_qty
                        picking.x_gate_entry_state = 'ready'

                elif picking.x_gate_entry_state != 'ready':
                    state_label = dict(
                        picking._fields['x_gate_entry_state'].selection
                    ).get(picking.x_gate_entry_state, picking.x_gate_entry_state)
                    raise UserError(
                        f'{picking.name}: Cannot validate. '
                        f'Current QC status: {state_label}'
                    )

        result = super().button_validate()

        # Post-validation hooks — run only for records that are now 'done'
        for picking in self:
            if picking.state != 'done':
                continue

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
            if gate_entry_ref and picking.picking_type_id == gate_entry_ref:
                failed_qty = sum(
                    m.x_qty_qc_failed for m in picking.move_ids
                    if m.product_id.x_qc_required  # non-QC products going to Store are never "failed"
                )
                if failed_qty > 0:
                    picking.x_pending_replacement_qty = failed_qty

            # --- Req 9: blacklist serial-tracked lots that failed inward QC ---
            if gate_entry_ref and picking.picking_type_id == gate_entry_ref:
                for move in picking.move_ids:
                    if (
                        move.product_id.x_qc_required
                        and move.product_id.tracking == 'serial'
                        and move.x_qty_qc_failed > 0
                    ):
                        for ml in move.move_line_ids:
                            if ml.lot_id and not ml.qty_done:
                                ml.lot_id.x_blacklisted = True

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
            invoice.action_refresh_ego_serials()
