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
        # group_sale_approver holders (Rajshri) can APPROVE SOs but not create them.
        # Rajshri retains sales_team.group_sale_manager for the approval button but
        # this check prevents her from raising new Quotations/SOs (13-Mar update).
        if (
            not self.env.su
            and self.env.user.has_group('elegomotors_setup.group_sale_approver')
        ):
            raise AccessError(
                'Sales approvers cannot create new Sales Orders or Quotations. '
                'Ask Tushar (Sales) or Manohar (Admin) to raise the order.'
            )
        return super().create(vals_list)
