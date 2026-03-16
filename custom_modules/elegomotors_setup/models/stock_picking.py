# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import AccessError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    elego_mo_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        ondelete='set null',
        index=True,
        help='The Manufacturing Order this Issue-to-Production transfer was created for.',
    )

    def button_validate(self):
        """Enforce picking-type group restriction on validation.

        If a picking type has group_id set, only members of that group
        (and the system superuser) may validate transfers of that type.
        """
        if not self.env.su:
            for picking in self:
                group = picking.picking_type_id.group_id
                if group and self.env.user not in group.users:
                    raise AccessError(
                        f'You are not authorised to validate '
                        f'"{picking.picking_type_id.name}" transfers. '
                        f'Contact Manohar (Admin) if you need access.'
                    )
        return super().button_validate()
