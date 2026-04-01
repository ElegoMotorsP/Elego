# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_qty_received = fields.Float(
        string='Received',
        digits='Product Unit of Measure',
        default=0,
        copy=False,
        help='Actual quantity received at gate entry (entered by store person).',
    )
    x_qty_qc_passed = fields.Float(
        string='QC Passed',
        digits='Product Unit of Measure',
        default=0,
        copy=False,
        help='Quantity that passed quality check.',
    )
    x_qty_qc_failed = fields.Float(
        string='QC Failed',
        digits='Product Unit of Measure',
        compute='_compute_qc_failed',
        store=True,
        copy=False,
        help='Quantity that failed quality check (= Received − QC Passed).',
    )
    x_qty_final = fields.Float(
        string='Final Quantities',
        digits='Product Unit of Measure',
        compute='_compute_qty_final',
        store=True,
        copy=False,
        help='Final accepted quantity that goes to store (= QC Passed).',
    )

    @api.depends('x_qty_received', 'x_qty_qc_passed')
    def _compute_qc_failed(self):
        for move in self:
            move.x_qty_qc_failed = move.x_qty_received - move.x_qty_qc_passed

    @api.depends('x_qty_qc_passed')
    def _compute_qty_final(self):
        for move in self:
            move.x_qty_final = move.x_qty_qc_passed

    # Issue 10: auto-fill x_qty_received from PO demand quantity on creation
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('x_qty_received') and vals.get('product_uom_qty'):
                vals['x_qty_received'] = vals['product_uom_qty']
        return super().create(vals_list)

    # Issue 10: keep x_qty_received in sync when demand qty changes (UI onchange)
    @api.onchange('product_uom_qty')
    def _onchange_x_qty_received_default(self):
        if self.product_uom_qty and not self.x_qty_received:
            self.x_qty_received = self.product_uom_qty
