# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartnerConnectExtension(models.Model):
    _inherit = 'res.partner'

    x_dealer_territory = fields.Char(
        string='Dealer Territory (Elego Connect)',
        help='Set by Elego HQ when approving a dealer registration in Elego '
             'Connect — used for inquiry auto-assignment by pincode/territory. '
             'x_dealer_code (elegomotors_setup) is the join key between Odoo '
             'and Elego Connect; this field is Elego-Connect-specific, hence '
             'living in this module rather than elegomotors_setup.',
    )
