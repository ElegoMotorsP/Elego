from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _assign_serials_to_invoice_lines(self):
        """Assign serials (stock.production.lot) to account.move.line.lot_ids based on invoice origin and product.
        Best-effort matching: search stock.move.line by product and link to pickings whose origin or name matches invoice origin,
        or by sale order name matching invoice origin.
        """
        StockMoveLine = self.env['stock.move.line']
        Lot = self.env['stock.production.lot']
        for inv in self:
            origin = (inv.invoice_origin or inv.origin or '').strip()
            if not origin:
                # fallback: try to use invoice name or partner reference
                origin = inv.ref or ''
            for line in inv.invoice_line_ids:
                if not line.product_id:
                    continue
                domain = [('product_id', '=', line.product_id.id), ('lot_id', '!=', False)]
                # try to match by picking origin/name
                if origin:
                    domain_origin = ['|', ('picking_id.origin', '=', origin), ('picking_id.name', '=', origin)]
                    # also try sale order link
                    domain_sale = ['|', ('sale_line_id.order_id.name', '=', origin), ('sale_line_id.order_id.origin', '=', origin)]
                    full_domain = domain + domain_origin + domain_sale
                else:
                    full_domain = domain
                mls = StockMoveLine.search(full_domain)
                lot_ids = mls.mapped('lot_id.id')
                # set unique lot ids
                if lot_ids:
                    # assign to the invoice line's lot_ids (many2many)
                    try:
                        line.lot_ids = [(6, 0, list(dict.fromkeys(lot_ids)))]
                    except Exception:
                        _logger.exception('Failed to assign lot_ids to invoice line %s', line.id)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AccountMove, self).create(vals_list)
        try:
            records._assign_serials_to_invoice_lines()
        except Exception:
            _logger.exception('Failed to auto-assign serials on invoice create')
        return records

    def write(self, vals):
        res = super(AccountMove, self).write(vals)
        # re-run assignment when origin or lines change
        try:
            # only reassign for invoices
            if any(inv.move_type in ('out_invoice','out_refund') for inv in self):
                self._assign_serials_to_invoice_lines()
        except Exception:
            _logger.exception('Failed to auto-assign serials on invoice write')
        return res
