# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.exceptions import AccessError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        # group_store_billing holders (Amit) can view products but not create
        # new ones. Superuser and sudo() environments are exempt so Odoo's
        # own test suite can still create products freely.
        if (
            not self.env.su
            and self.env.user.has_group('elegomotors_setup.group_store_billing')
        ):
            raise AccessError(
                'Store billing users cannot create new Products. '
                'Ask Manohar (Admin) to create the product.'
            )
        return super().create(vals_list)
