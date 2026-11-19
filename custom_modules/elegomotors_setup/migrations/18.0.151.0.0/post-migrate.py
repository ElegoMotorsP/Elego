# -*- coding: utf-8 -*-
"""PO Tracking: QC Pass / Reject / Pending and the stage now work for real GRNs.

The report only looked for QC on the module's own "Gate Entry" operation type, but
the receipts people really make are of the warehouse's "GRN" type, so those columns
were empty for every PO. They are stored fields and only recompute when a receipt
changes, so recompute them once for the confirmed purchase orders. Safe to run more
than once. A problem here is logged and never stops the module update; the figures
correct themselves the next time the PO's receipts change.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

TRACKING_FIELDS = (
    'x_trk_po_qty', 'x_trk_received_qty', 'x_trk_pending_qty', 'x_trk_qc_passed_qty',
    'x_trk_qc_rejected_qty', 'x_trk_qc_pending_qty', 'x_trk_stock_qty', 'x_trk_stage',
)


def migrate(cr, version):
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            orders = env['purchase.order'].with_context(active_test=False).search(
                [('state', 'in', ('purchase', 'done'))]
            )
            for name in TRACKING_FIELDS:
                env.add_to_compute(orders._fields[name], orders)
            env.flush_all()
            _logger.info('PO Tracking figures recomputed on %d purchase order(s)', len(orders))
    except Exception:  # noqa: BLE001
        _logger.exception('Could not recompute the PO Tracking figures of existing purchase orders')
