# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    ego_unit_quality_check_id = fields.Many2one(
        'quality.check',
        string='Post-prod unit QC',
        copy=False,
        ondelete='set null',
    )

    def _ego_get_post_prod_point(self):
        return self.env.ref(
            'elegomotors_setup.qc_point_post_prod_unit',
            raise_if_not_found=False,
        )

    def _ego_should_create_post_prod_qc(self):
        self.ensure_one()
        move = self.move_id
        if not move or move.state == 'cancel' or move.scrapped:
            return False
        production = move.production_id
        if not production:
            return False
        if move not in production.move_finished_ids:
            return False
        if move.product_id != production.product_id:
            return False
        if not self.qty_done or not self.lot_id:
            return False
        if self.product_id.tracking != 'serial':
            return False
        return True

    def _ego_create_post_prod_unit_check(self):
        point = self._ego_get_post_prod_point()
        if not point:
            _logger.warning('elegomotors: qc_point_post_prod_unit missing; skip unit QC')
            return False
        self.ensure_one()
        if not self._ego_should_create_post_prod_qc():
            return False
        if self.ego_unit_quality_check_id:
            return self.ego_unit_quality_check_id
        production = self.move_id.production_id
        existing = self.env['quality.check'].search([
            ('ego_mrp_production_id', '=', production.id),
            ('lot_id', '=', self.lot_id.id),
        ], limit=1)
        if existing:
            self.ego_unit_quality_check_id = existing.id
            return existing
        Check = self.env['quality.check']
        vals = {
            'point_id': point.id,
            'product_id': self.product_id.id,
            'lot_id': self.lot_id.id,
            'company_id': production.company_id.id,
            'ego_mrp_production_id': production.id,
        }
        if 'production_id' in Check._fields:
            vals['production_id'] = production.id
        elif 'mrp_production_id' in Check._fields:
            vals['mrp_production_id'] = production.id
        qc = Check.sudo().create(vals)
        self.ego_unit_quality_check_id = qc.id
        production.message_post(
            body=(
                f"Post-production unit QC created for serial <b>{self.lot_id.name}</b> — "
                f"<a href='/web#id={qc.id}&model=quality.check&view_type=form'>open check</a>."
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        production.invalidate_recordset(['qc_state', 'mo_flow_state'])
        return qc

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            line._ego_create_post_prod_unit_check()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('qty_done', 'lot_id', 'move_id', 'product_id')):
            for line in self:
                line._ego_create_post_prod_unit_check()
        return res
