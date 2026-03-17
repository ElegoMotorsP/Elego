# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import models


class IrActionsServer(models.Model):
    _inherit = 'ir.actions.server'

    def _get_eval_context(self, action=None):
        ctx = super()._get_eval_context(action=action)
        ctx['Markup'] = Markup
        return ctx
