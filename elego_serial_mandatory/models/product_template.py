from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_serial_mandatory = fields.Boolean(
        string='Serial/Lot mandatory',
        help='If set, this product requires a serial/lot to be provided for specific operations (sales, production, quality).'
    )
