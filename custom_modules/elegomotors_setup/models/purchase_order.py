# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import float_compare


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Gate Entry PO dropdown: a PO is "closed" for receiving once every stockable
    # line is fully received. Stored so it can be used in the search domain of
    # the Source PO dropdown on the Gate Entry form.
    x_receipt_complete = fields.Boolean(
        string='Fully Received',
        compute='_compute_x_receipt_complete',
        store=True,
        help='True when every stockable order line has been fully received. '
             'Such POs no longer appear in the Gate Entry Source PO dropdown.',
    )

    @api.depends('order_line.qty_received', 'order_line.product_qty', 'state')
    def _compute_x_receipt_complete(self):
        for po in self:
            lines = po.order_line.filtered(
                lambda l: not l.display_type and l.product_id.type != 'service'
            )
            po.x_receipt_complete = bool(lines) and all(
                float_compare(
                    line.qty_received, line.product_qty,
                    precision_rounding=line.product_uom.rounding,
                ) >= 0
                for line in lines
            )

    # A GRN is made by a person, never by confirming the PO. Odoo creates a
    # full-quantity receipt as soon as a PO is confirmed; here that receipt sat
    # untouched next to the GRN Amit then made for the real delivery (PO-160 had
    # EGO/GRN/00218 from OdooBot beside 00219-00221), so the same quantity was
    # asked for twice and the QC list showed several rows for one PO. The GRN is
    # now created when Amit picks the PO on a new GRN (x_source_po_id), which
    # fills it with what is still to receive. Pass ego_allow_po_receipt=True in
    # the context to get Odoo's own behaviour back for a specific call.
    def _create_picking(self):
        if self.env.context.get('ego_allow_po_receipt'):
            return super()._create_picking()
        return True

    # With no receipt made at confirmation, Odoo's own receipt status (worked
    # out from the receipts' states) would read "Fully Received" as soon as the
    # only GRN is validated, even when it covered part of the order. Work it out
    # from the quantities instead: ordered vs received on the lines.
    @api.depends('picking_ids', 'picking_ids.state', 'state',
                 'order_line.qty_received', 'order_line.product_qty')
    def _compute_receipt_status(self):
        for order in self:
            lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id.type != 'service'
            )
            if order.state not in ('purchase', 'done') or not lines:
                order.receipt_status = False
                continue
            fully = all(
                float_compare(
                    line.qty_received, line.product_qty,
                    precision_rounding=line.product_uom.rounding,
                ) >= 0
                for line in lines
            )
            any_received = any(
                float_compare(
                    line.qty_received, 0.0,
                    precision_rounding=line.product_uom.rounding,
                ) > 0
                for line in lines
            )
            if fully:
                order.receipt_status = 'full'
            elif any_received:
                order.receipt_status = 'partial'
            else:
                order.receipt_status = 'pending'

    @api.model_create_multi
    def create(self, vals_list):
        # group_purchase_viewer holders (Amit, Rajshri) can read POs but not
        # create new ones. Superuser and sudo() environments are exempt so
        # Odoo's own test suite can still create POs freely.
        if (
            not self.env.su
            and self.env.user.has_group('elegomotors_setup.group_purchase_viewer')
        ):
            raise AccessError(
                'Purchase viewers cannot create new Purchase Orders. '
                'Ask Prashant (Purchase) or Manohar (Admin) to raise the PO.'
            )
        return super().create(vals_list)

    # Issue 2: block non-inbound-operators from navigating to Gate Entry receipts via PO
    def action_view_picking(self):
        if (
            not self.env.su
            and not self.env.user.has_group('elegomotors_setup.group_inbound_operator')
            and not self.env.user.has_group('base.group_erp_manager')
        ):
            raise AccessError(
                'Only the Store Manager (Amit) or Admin can access receipt transfers.'
            )
        return super().action_view_picking()
