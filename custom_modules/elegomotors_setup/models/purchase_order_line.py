# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models
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

    # ------------------------------------------------------------------
    # Overseas vendors: a PO with no tax at all
    # ------------------------------------------------------------------
    # An overseas vendor's PO must carry no GST, IGST or reverse-charge tax; the
    # import IGST is booked separately through the Bill of Entry. Odoo fills the
    # taxes from the product's vendor taxes in several places (the product
    # onchange, lines made from code, the vendor bill), so the rule is kept in
    # one helper and applied at each of them rather than only on the form.

    def _ego_overseas_lines(self):
        return self.filtered(lambda line: line.order_id.partner_id.x_overseas_supplier)

    # In Odoo 18 this is NOT a computed field: taxes_id is a plain field, and this
    # method is just what the product onchange (and a fiscal-position change on
    # the PO) calls to fill it. So there is nothing to add to a depends list; the
    # create/write overrides below cover everything that does not go through it.
    def _compute_tax_id(self):
        overseas = self._ego_overseas_lines()
        for line in overseas:
            line.taxes_id = [Command.clear()]
        super(PurchaseOrderLine, self - overseas)._compute_tax_id()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # A line made with taxes in its values (a copied line, the BoM wizard, CKD
        # kit lines, code) is cleaned after the fact, whichever way it was made.
        taxed = lines._ego_overseas_lines().filtered('taxes_id')
        if taxed:
            taxed.write({'taxes_id': [Command.clear()]})
        return lines

    def write(self, vals):
        if 'taxes_id' in vals:
            overseas = self._ego_overseas_lines()
            if overseas:
                # Hand-picked taxes on an overseas vendor's line are thrown away.
                res = super(PurchaseOrderLine, overseas).write(
                    dict(vals, taxes_id=[Command.clear()]))
                rest = self - overseas
                if rest:
                    res = super(PurchaseOrderLine, rest).write(vals) and res
                return res
        return super().write(vals)

    # The vendor bill copies the PO line's taxes, so an untaxed PO line already
    # gives an untaxed bill line. This makes it certain even for a PO that was
    # confirmed before the vendor was marked overseas.
    def _prepare_account_move_line(self, move=False):
        res = super()._prepare_account_move_line(move=move)
        if self.order_id.partner_id.x_overseas_supplier:
            res['tax_ids'] = [Command.clear()]
        return res
