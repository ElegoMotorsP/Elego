from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'

    amount_total_text = fields.Char(
        string='Total Amount in Words',
        compute='_compute_amount_total_text'
    )

    @api.depends('amount_total')
    def _compute_amount_total_text(self):
        """
        Calculates the total invoice amount in words using Odoo's utility.
        """
        for move in self:
            if move.amount_total:
                # Use the partner's language for correct localization if available
                move.amount_total_text = move.currency_id.with_context(lang=move.partner_id.lang or 'en_US').amount_to_text(move.amount_total)
            else:
                move.amount_total_text = ''