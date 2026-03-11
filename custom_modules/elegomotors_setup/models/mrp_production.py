# -*- coding: utf-8 -*-
from odoo import models, SUPERUSER_ID
from odoo.exceptions import AccessError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def button_mark_done(self):
        # Superuser (uid=1) and sudo() environments bypass this restriction.
        # This allows Odoo's own test suite (which runs as admin/superuser) to
        # call button_mark_done without hitting the custom access guard.
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and not self.env.user.has_group('elegomotors_setup.group_manufacturing_operator')
        ):
            raise AccessError('Only Manufacturing Operators can mark Manufacturing Orders as done.')
        return super().button_mark_done()
