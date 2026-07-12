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
