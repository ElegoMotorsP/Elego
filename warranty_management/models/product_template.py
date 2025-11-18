# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # x_warranty_months = fields.Integer(string='Warranty (months)', default=0)
    # warranty defaults (kept here for safety if already present)
    warranty_duration_months = fields.Integer(
        string='Warranty Duration (Months)',
        help='Default warranty duration assigned when sold.', default=0
    )
    warranty_terms = fields.Text(
        string='Warranty Terms', help='Default warranty terms.')

    def action_open_product_warranties_new(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Product Warranties",
            "res_model": "product.warranty",
            "view_mode": "list,form",
            "domain": [("product_id.product_tmpl_id", "=", self.id)],
            "context": {"default_product_id": self.product_variant_id.id},
            "target": "current",
        }
