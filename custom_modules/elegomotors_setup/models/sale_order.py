# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.exceptions import AccessError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model_create_multi
    def create(self, vals_list):
        # group_sale_viewer holders (Amit) can read SOs/Quotations but not
        # create new ones. Superuser and sudo() environments are exempt so
        # Odoo's own test suite can still create SOs freely.
        if (
            not self.env.su
            and self.env.user.has_group('elegomotors_setup.group_sale_viewer')
        ):
            raise AccessError(
                'Sales viewers cannot create new Sales Orders or Quotations. '
                'Ask Tushar (Sales) or Manohar (Admin) to raise the order.'
            )
        return super().create(vals_list)
