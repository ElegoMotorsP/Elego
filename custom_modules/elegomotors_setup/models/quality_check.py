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
    ego_fg_transferred = fields.Boolean(
        string='FG moved to store',
        copy=False,
        default=False,
    )

    def write(self, vals):
        prev_state = {check.id: check.quality_state for check in self}
        res = super().write(vals)
        if vals.get('quality_state'):
            mos = self.mapped('ego_mrp_production_id')
            if mos:
                mos.invalidate_recordset(['qc_state', 'mo_flow_state'])
            newly_passed = self.filtered(
                lambda c: prev_state.get(c.id) != 'pass'
                and c.quality_state == 'pass'
                and c.ego_mrp_production_id
                and c.lot_id
                and not c.ego_fg_transferred
            )
            for check in newly_passed:
                check.ego_mrp_production_id._ego_move_fg_unit_to_store(check)
        return res
