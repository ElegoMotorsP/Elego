# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    WARRANTY_TRIGGER_SELECTION = [
        ('sale_confirm', 'Sale Confirmation'),
        ('delivery_done', 'Delivery Done'),
        ('invoice_post', 'Invoice Posted'),
    ]

    warranty_generation_trigger = fields.Selection(
        WARRANTY_TRIGGER_SELECTION,
        string='Warranty Start Trigger',
        default='sale_confirm',
        help='When to auto-generate warranties for sold products.'
    )

    PARAM_KEY = 'warranty_management.warranty_generation_trigger'

    def set_values(self):
        super().set_values()
        # Save into ir.config_parameter (stable across Odoo versions)
        self.env['ir.config_parameter'].sudo().set_param(
            self.PARAM_KEY,
            self.warranty_generation_trigger or 'sale_confirm'
        )

    @api.model
    def get_values(self):
        res = super().get_values()
        # Prefer the config param; fallback to default sale_confirm
        val = self.env['ir.config_parameter'].sudo().get_param(
            self.PARAM_KEY, default='sale_confirm')
        res.update({'warranty_generation_trigger': val})
        return res
