from odoo import models, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _is_serial_required_by_context(self, move):
        if not move:
            return False
        try:
            if move.sale_line_id:
                return True
        except Exception:
            pass
        try:
            if getattr(move, 'production_id', False):
                return True
        except Exception:
            pass
        picking = move.picking_id
        if picking and picking.origin:
            try:
                if 'quality' in (picking.origin or '').lower():
                    return True
            except Exception:
                pass
        return False

    def _serial_required_check_record(self, ml):
        if not ml.product_id:
            return
        tmpl = ml.product_id.product_tmpl_id
        if not tmpl or not tmpl.x_serial_mandatory:
            return
        move = ml.move_id
        if not move:
            return
        if not self._is_serial_required_by_context(move):
            return
        if not ml.lot_id:
            raise UserError(_("Serial/Lot number is mandatory for product '%s' in this operation") % (ml.product_id.display_name,))

    @api.model_create_multi
    def create(self, vals_list):
        mls = super(StockMoveLine, self).create(vals_list)
        for ml in mls:
            try:
                self._serial_required_check_record(ml)
            except UserError:
                _logger.warning('Deleting created move_line %s due to serial requirement check failure', ml.id)
                ml.unlink()
                raise
            except Exception:
                _logger.exception('Unexpected error during serial check on create for move_line %s', ml.id)
        return mls

    def write(self, vals):
        res = super(StockMoveLine, self).write(vals)
        for ml in self:
            try:
                self._serial_required_check_record(ml)
            except Exception:
                _logger.exception('Serial check failed on write for move_line %s', ml.id)
                raise
        return res
