# -*- coding: utf-8 -*-
from odoo import api, fields, models


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    ego_mrp_production_id = fields.Many2one(
        'mrp.production',
        string='MO (Elego)',
        index=True,
        ondelete='cascade',
        copy=False,
    )

    def write(self, vals):
        res = super().write(vals)
        if vals.get('quality_state'):
            mos = self.mapped('ego_mrp_production_id')
            if mos:
                mos.invalidate_recordset(['qc_state', 'mo_flow_state'])
        return res
