# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # def action_view_warranties(self):
    #     Warranty = self.env['product.warranty']
    #     warranties = Warranty.search([('sale_order_id', '=', self.id)])
    #     action = self.env.ref(
    #         'warranty_management.action_open_product_warranties').read()[0]
    #     action['domain'] = [('id', 'in', warranties.ids)]
    #     return action

    def action_view_warranties(self):
        self.ensure_one()
        Warranty = self.env["product.warranty"]

        domain = []

        # -----------------------------------------
        # CASE 1: Called from Sale Order
        # -----------------------------------------
        if self._name == "sale.order":
            domain = [('sale_order_id', '=', self.id)]

        # -----------------------------------------
        # CASE 2: Called from Product
        # -----------------------------------------
        elif self._name == "product.product":
            domain = [('product_id', '=', self.id)]

        # -----------------------------------------
        # CASE 3: Called from Product Template
        # -----------------------------------------
        elif self._name == "product.template":
            domain = [('product_id', 'in', self.product_variant_ids.ids)]

        # -----------------------------------------
        # CASE 4: Called from Customer (res.partner)
        # -----------------------------------------
        elif self._name == "res.partner":
            domain = [('partner_id', '=', self.id)]

        # -----------------------------------------
        # Fallback → show all warranties (unlikely)
        # -----------------------------------------
        else:
            domain = [('id', '!=', 0)]

        # Retrieve the matching warranties
        warranties = Warranty.search(domain)

        # Load the action
        action = self.env.ref(
            'warranty_management.action_open_product_warranties'
        ).read()[0]

        # Pass domain to action
        action['domain'] = [('id', 'in', warranties.ids)]
        return action
