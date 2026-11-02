# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import float_compare


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    x_qty_remaining = fields.Float(
        string='To Receive',
        compute='_compute_x_qty_remaining',
        store=True,
        digits='Product Unit of Measure',
        help='Ordered quantity not yet received on a validated GRN. A short '
             'delivery does not create a backorder: this is what is still to '
             'come, and the user makes another GRN for it when it arrives.',
    )

    @api.depends('product_qty', 'qty_received', 'display_type')
    def _compute_x_qty_remaining(self):
        for line in self:
            if line.display_type:
                line.x_qty_remaining = 0.0
                continue
            remaining = line.product_qty - line.qty_received
            if float_compare(
                remaining, 0.0, precision_rounding=line.product_uom.rounding or 0.01,
            ) <= 0:
                remaining = 0.0
            line.x_qty_remaining = remaining
