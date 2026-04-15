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

    # --- Issue 5/6: QC action methods (used by Pratik via view buttons) ---

    def action_gate_entry_start_qc(self):
        """Amit sends Gate Entry to QC.
        If picking has non-QC products, shows the routing wizard first.
        If all products require QC, proceeds with the normal send-to-QC flow.
        """
        self.ensure_one()

        non_qc_moves = self.move_ids.filtered(lambda m: not m.product_id.x_qc_required)
        qc_moves = self.move_ids.filtered(lambda m: m.product_id.x_qc_required)

        if non_qc_moves and qc_moves:
            # Mixed picking → show the routing wizard
            return {
                'type': 'ir.actions.act_window',
                'name': 'QC Routing',
                'res_model': 'stock.picking.qc.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_picking_id': self.id},
            }

        if non_qc_moves and not qc_moves:
            # Nothing requires QC — guide Amit to use Validate instead
            raise UserError(
                'None of the products in this receipt require QC inspection. '
                'Use the Validate button to send them directly to Store.'
            )

        # All products require QC → normal send-to-QC flow
        self.x_gate_entry_state = 'in_qc'
        pratik = self.env.ref('elegomotors_setup.user_ego_pratik', raise_if_not_found=False)
        partner_ids = [pratik.partner_id.id] if pratik and pratik.partner_id else []
        self.message_post(
            body=Markup(
                f"Material sent to QC by <b>{self.env.user.name}</b>. "
                f"<b>Quality (Pratik):</b> Please perform inward QC inspection and "
                f"enter QC Passed quantity, then click <b>Approve QC</b>. "
                f"Only QC-passed quantity will be accepted into Store."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

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
                    if qc_moves:
                        # Has QC-required products → show routing wizard
                        return {
                            'type': 'ir.actions.act_window',
                            'name': 'QC Routing',
                            'res_model': 'stock.picking.qc.wizard',
                            'view_mode': 'form',
                            'target': 'new',
                            'context': {'default_picking_id': picking.id},
                        }
                    else:
                        # All products are non-QC → bypass gate, validate directly to Store
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
                failed_qty = sum(m.x_qty_qc_failed for m in picking.move_ids)
                if failed_qty > 0:
                    picking.x_pending_replacement_qty = failed_qty

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
