# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderRejectWizard(models.TransientModel):
    _name = 'sale.order.reject.wizard'
    _description = 'Reject Sales Order'

    order_id = fields.Many2one('sale.order', required=True, readonly=True)
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.order_id._do_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
