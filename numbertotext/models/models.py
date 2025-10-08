from odoo import fields, models


class Sales(models.Model):
    _inherit = "sale.order"

    number_to_words = fields.Char(string="Amount in words",compute="_compute_number_to_words")

    def _compute_number_to_words(self):
         for order in self:
              order.number_to_words = order.currency_id.amount_to_text(order.amount_total)
              print(order.name,order.amount_total,order.number_to_words)


class Account(models.Model):
    _inherit = "account.move"

    number_to_words = fields.Char(string="Amount in words",compute="_compute_number_to_words")

    def _compute_number_to_words(self):
         for order in self:
              order.number_to_words = order.currency_id.amount_to_text(order.amount_total)
              print(order.name,order.amount_total,order.number_to_words)

class Purchase(models.Model):
    _inherit = "purchase.order"

    number_to_words = fields.Char(string="Amount in words",compute="_compute_number_to_words")

    def _compute_number_to_words(self):
         for order in self:
              order.number_to_words = order.currency_id.amount_to_text(order.amount_total)
              print(order.name,order.amount_total,order.number_to_words)
