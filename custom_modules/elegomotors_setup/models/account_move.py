# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    # True only for users in group_store_billing (Amit).
    # @api.depends_context('uid') ensures each user gets their own value —
    # the field is non-stored so it never persists or breaks other users' views.
    store_billing_readonly = fields.Boolean(
        compute='_compute_store_billing_readonly',
    )

    @api.depends_context('uid')
    def _compute_store_billing_readonly(self):
        is_store_billing = self.env.user.has_group(
            'elegomotors_setup.group_store_billing'
        )
        for record in self:
            record.store_billing_readonly = is_store_billing
