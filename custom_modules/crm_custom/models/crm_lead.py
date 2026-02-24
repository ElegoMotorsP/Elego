from odoo import fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    custom_score = fields.Integer(
        string='Custom Score',
        default=0,
        help='Lead scoring value (0–100). Scores ≥ 50 are considered high-priority.',
    )
    lead_source = fields.Selection(
        selection=[
            ('website', 'Website'),
            ('referral', 'Referral'),
            ('cold_call', 'Cold Call'),
            ('exhibition', 'Exhibition / Trade Show'),
            ('social_media', 'Social Media'),
            ('dealer', 'Dealer / Partner'),
            ('other', 'Other'),
        ],
        string='Lead Source',
        help='Channel through which this lead was acquired.',
    )
