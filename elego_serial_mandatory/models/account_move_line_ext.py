from odoo import models, fields


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    lot_ids = fields.Many2many('stock.production.lot', 'account_move_line_lot_rel', 'move_line_id', 'lot_id', string='Serials')
