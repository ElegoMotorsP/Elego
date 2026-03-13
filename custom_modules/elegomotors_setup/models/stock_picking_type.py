# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    # Odoo 18 removed group_id from stock.picking.type.
    # Re-add it so we can restrict which users can create/validate
    # each operation type (Gate Entry, QC Pass, FG Transfer, etc.).
    group_id = fields.Many2one(
        'res.groups',
        string="Restricted to Group",
        help="If set, only members of this group can create or validate "
             "transfers of this type.",
    )
