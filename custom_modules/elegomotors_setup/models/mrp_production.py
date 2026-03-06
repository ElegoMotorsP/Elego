# -*- coding: utf-8 -*-
from odoo import models
from odoo.exceptions import AccessError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def button_mark_done(self):
        if not self.user_has_groups('elegomotors_setup.group_manufacturing_operator'):
            raise AccessError('Only Manufacturing Operators can mark Manufacturing Orders as done.')
        return super().button_mark_done()
