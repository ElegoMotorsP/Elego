from odoo import models, fields

class AccountMoveTransport(models.Model):
    _inherit = 'account.move'

    # Transportation Fields to capture data shown on the invoice
    transport_mode_custom = fields.Char(string='Transport Mode')
    transport_name_custom = fields.Char(string='Transporter Name')
    lr_no_custom = fields.Char(string='LR/AWB No')
    lr_date_custom = fields.Date(string='LR/AWB Date')
    vehicle_number_custom = fields.Char(string='Vehicle Number')
    eway_no_custom = fields.Char(string='E-Way Bill No')
    # Assuming PAN No. is a custom field on partner if not using the standard VAT/Tax ID field
    # pan_no_custom = fields.Char(related='partner_id.x_pan_no', string='PAN Number', readonly=True)