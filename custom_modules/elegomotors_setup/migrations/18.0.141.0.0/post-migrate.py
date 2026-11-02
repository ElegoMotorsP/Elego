# -*- coding: utf-8 -*-
"""Receipt status of existing POs now follows the received quantities.

A PO's receipt status used to be worked out from its receipts' states, so a PO
whose only receipt had been validated for part of the order read "Fully
Received". It is now worked out from ordered vs received on the lines (see
purchase_order.py). The status is a stored field and only recomputes when a
line changes, so recompute it once for the POs that are already confirmed.
Safe to run more than once. A problem here is logged and never stops the
module update; the status corrects itself the next time the PO changes.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            orders = env['purchase.order'].with_context(active_test=False).search(
                [('state', 'in', ('purchase', 'done'))]
            )
            env.add_to_compute(orders._fields['receipt_status'], orders)
            env.flush_all()
            _logger.info('Receipt status recomputed on %d purchase order(s)', len(orders))
    except Exception:  # noqa: BLE001
        _logger.exception('Could not recompute the receipt status of existing purchase orders')
