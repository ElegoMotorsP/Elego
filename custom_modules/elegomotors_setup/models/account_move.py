# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class AccountMove(models.Model):
    _inherit = 'account.move'

    # True only for users in group_store_billing (Amit).
    # @api.depends_context('uid') ensures each user gets their own value —
    # the field is non-stored so it never persists or breaks other users' views.
    store_billing_readonly = fields.Boolean(
        compute='_compute_store_billing_readonly',
    )

    @api.depends_context('uid')
    def _compute_store_billing_readonly(self):
        is_store_billing = self.env.user.has_group(
            'elegomotors_setup.group_store_billing'
        )
        for record in self:
            record.store_billing_readonly = is_store_billing

    # True for non-manager users (i.e. Rajshri / accounting users).
    # When True the view makes qty + price_unit readonly on PO-linked bill lines
    # so that the billed quantities and amounts always match the gate entry.
    vendor_bill_lines_readonly = fields.Boolean(
        compute='_compute_vendor_bill_lines_readonly',
    )

    @api.depends_context('uid')
    def _compute_vendor_bill_lines_readonly(self):
        is_manager = (
            self.env.user.has_group('base.group_erp_manager')
            or self.env.user.has_group('purchase.group_purchase_manager')
        )
        for record in self:
            record.vendor_bill_lines_readonly = not is_manager

    # Displays the Gate Entry (stock.picking) references linked to this vendor
    # bill via its PO lines, so the accounts user can trace: Gate Entry → PO → Bill.
    gate_entry_reference = fields.Char(
        string='Gate Entry Reference',
        compute='_compute_gate_entry_reference',
        store=False,
    )

    @api.depends('invoice_line_ids.purchase_line_id')
    def _compute_gate_entry_reference(self):
        for move in self:
            if move.move_type not in ('in_invoice', 'in_refund'):
                move.gate_entry_reference = False
                continue
            picking_names = set()
            for line in move.invoice_line_ids:
                if line.purchase_line_id:
                    for sm in line.purchase_line_id.move_ids:
                        if sm.picking_id and sm.picking_id.state == 'done':
                            picking_names.add(sm.picking_id.name)
            move.gate_entry_reference = ', '.join(sorted(picking_names)) or False

    @api.model_create_multi
    def create(self, vals_list):
        # group_purchase_vendor_bill_viewer holders (Prashant) can read vendor
        # bills but must not create new accounting entries.
        if (
            not self.env.su
            and self.env.user.has_group(
                'elegomotors_setup.group_purchase_vendor_bill_viewer'
            )
        ):
            raise AccessError(
                'Purchase viewers cannot create new accounting entries. '
                'Ask Rajshri (Accounts) or Manohar (Admin) to create the bill.'
            )
        return super().create(vals_list)
