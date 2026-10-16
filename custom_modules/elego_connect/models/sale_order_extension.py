# -*- coding: utf-8 -*-
"""Sales Order creation for dealer stock-replenishment POs — called by
Elego Connect API's OrdersService once Elego HQ approves a dealer PO
(docs/07-module-dealer-catalogue-po-payments.md §7.5 in the app's own
design repo). Auto-confirms on creation: per the 2026-09-01 decision
recorded in that repo's docs/20-project-status.md, the order lands in the
same Rajshri/Manohar approval queue as every other sale — the base
sale_order.py override (elegomotors_setup) arms that gate universally,
including for orders confirmed via the API, and this does not bypass or
extend it. Invoicing stays exactly as gated as it already is for retail
sales (named-accountant group + delivery-scan requirement).
"""
from odoo import api, fields, models


class SaleOrderConnectExtension(models.Model):
    _inherit = 'sale.order'

    # 4th value alongside the 3 real salespeople (elegomotors_setup) so
    # dealer-originated orders are clearly distinguishable from retail
    # orders in every report/filter that groups by this field.
    x_actual_salesperson = fields.Selection(
        selection_add=[('elego_connect', 'Elego Connect (Dealer Orders)')],
        ondelete={'elego_connect': 'set default'},
    )

    @api.model
    def create_from_connect_po(self, vals):
        """vals: {poNumber, odooPartnerId, deliveryAddress, remarks,
        lines: [{odooProductId, quantity, unitPrice}]}. Returns
        (order, created) — idempotent on client_order_ref (= our
        poNumber): a retried call returns the existing order untouched
        rather than creating a duplicate, matching this app's idempotency
        convention (docs/02.5 in the app's design repo)."""
        existing = self.sudo().search([('client_order_ref', '=', vals['poNumber'])], limit=1)
        if existing:
            return existing, False

        note_parts = [f"Elego Connect PO {vals['poNumber']}"]
        if vals.get('deliveryAddress'):
            note_parts.append(f"Delivery address: {vals['deliveryAddress']}")
        if vals.get('remarks'):
            note_parts.append(f"Remarks: {vals['remarks']}")

        order = self.sudo().create({
            'partner_id': vals['odooPartnerId'],
            'client_order_ref': vals['poNumber'],
            'x_actual_salesperson': 'elego_connect',
            'note': '\n'.join(note_parts),
            'order_line': [
                (0, 0, {
                    'product_id': line['odooProductId'],
                    'product_uom_qty': line['quantity'],
                    'price_unit': line['unitPrice'],
                })
                for line in vals['lines']
            ],
        })
        order.action_confirm()
        return order, True

    def connect_record_decision(self, decision, approver=None, reason=None, actor_label=None):
        """Accounts / MD approval, or a rejection, requested from the Elego
        Connect app. The existing approve/reject methods in elegomotors_setup
        only accept the real approver users; this runs them as sudo (same
        trusted-API approach as the warranty approve/reject) and notes the
        person who actually clicked in the app on the order's chatter, so
        Odoo's audit trail stays honest. Returns an error code or None."""
        self.ensure_one()
        order = self.sudo()
        if not order.pending_approval:
            return 'not_pending_approval'
        if decision == 'approve':
            if approver == 'accounts':
                order.action_approve_accounts()
            else:
                order.action_approve_manohar()
        else:
            order._do_reject(reason)
        if actor_label:
            order.message_post(
                body=f'(Requested via Elego Connect by {actor_label})',
                message_type='comment', subtype_xmlid='mail.mt_comment',
            )
        return None

    def connect_status_payload(self):
        self.ensure_one()
        return {
            'odooSaleOrderId': self.id,
            'odooSaleOrderName': self.name,
            'state': self.state,
            'pendingApproval': self.pending_approval,
            'approvalAccounts': self.approval_accounts,
            'approvalManohar': self.approval_manohar,
            'rejectionReason': self.rejection_reason or None,
            'invoices': [
                {
                    'id': inv.id,
                    # inv.name is False (not None) on an unnumbered draft/
                    # cancelled invoice — Odoo's ORM convention for an
                    # unset Char field. `or None` normalizes that to a real
                    # JSON null instead of `false`, which broke the app's
                    # JSON parsing (a String? field, not a bool).
                    'number': inv.name or None,
                    'state': inv.state,
                    'paymentState': inv.payment_state,
                    'amountTotal': inv.amount_total,
                    'invoiceDate': inv.invoice_date.isoformat() if inv.invoice_date else None,
                }
                for inv in self.invoice_ids
            ],
        }
