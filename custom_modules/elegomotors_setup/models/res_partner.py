# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_dealer_code = fields.Char(
        string='Dealer Code (Finance API)',
        index=True,
        copy=False,
        help='Code finance partners (e.g. Bajaj Finance) use to identify this '
             'dealer as "dealerCode" in the serial-validation API. Must match '
             'the code the finance partner has on file for this dealership — '
             'get it from them, this field does not generate one.',
    )
