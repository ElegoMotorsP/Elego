# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _auto_create_warranties_from_picking(self):
        _logger.warning(">>> WARRANTY DEBUG: Auto-create was triggered.")

        """Create product.warranty records for delivered lots if product template
        defines warranty months (warranty_duration_months > 0) and warranty for the lot
        + customer does not already exist."""
        Warranty = self.env['product.warranty']
        for pick in self:
            # Only process completed outgoing pickings
            try:
                if pick.picking_type_code != 'outgoing' or pick.state != 'done':
                    continue
            except Exception:
                # defensive: if fields missing, skip
                continue

            for ml in pick.move_line_ids:
                lot = ml.lot_id
                product = ml.product_id
                if not lot or not product:
                    continue

                months = product.product_tmpl_id.warranty_duration_months or 0
                if not months:
                    continue

                # Check existing warranty for same product, lot and partner
                exists = Warranty.search([
                    ('product_id', '=', product.id),
                    ('serial_number', 'ilike', lot.name),
                    ('partner_id', '=', pick.partner_id.id)
                ], limit=1)
                if exists:
                    _logger.debug("Warranty already exists for product %s lot %s partner %s",
                                  product.display_name, lot.name, pick.partner_id and pick.partner_id.name)
                    continue

                vals = {
                    'product_id': product.id,
                    'serial_number': lot.name,
                    'partner_id': pick.partner_id.id,
                    'sale_order_id': getattr(pick, 'sale_id', False) and pick.sale_id.id or False,
                    'picking_id': pick.id,
                }
                try:
                    Warranty.create(vals)
                    _logger.info("Created warranty for product %s lot %s (picking %s)",
                                 product.display_name, lot.name, pick.name)
                except Exception as e:
                    _logger.exception(
                        "Error creating warranty for picking %s: %s", pick.name, e)

    # Override action_done which is called when a picking is validated / done
    def action_done(self):
        res = super().action_done()
        # After picking is done, create warranties (non-blocking)
        try:
            self._auto_create_warranties_from_picking()
        except Exception as e:
            _logger.exception(
                "Auto-create warranties failed after action_done: %s", e)
        return res

    # Also override button_validate / _action_done for extra compatibility if needed
    def button_validate(self):
        res = super().button_validate()
        try:
            # many workflows call action_done; still call the same helper for safety
            self._auto_create_warranties_from_picking()
        except Exception as e:
            _logger.exception(
                "Auto-create warranties failed after button_validate: %s", e)
        return res
