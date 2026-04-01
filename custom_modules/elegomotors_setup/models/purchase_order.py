# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.exceptions import AccessError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

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
