# -*- coding: utf-8 -*-
"""A CKD kit line's Received now counts only validated receipts.

Until now a kit line counted a part as received as soon as it was picked, so after
"Approve QC" and before Store validated the GRN the PO already read fully received
(and a bill could be made for it). It now counts validated quantity only, from the
same calculation PO Tracking uses (see ckd_kit.py / po_tracking.py).

Received (and To Receive) of a line are stored fields and only recompute when a
move changes, so recompute them once for the kit lines of the POs that are already
confirmed, together with the stored figures of the PO Tracking report. Safe to run
more than once. A problem here is logged and never stops the module update; the
figures correct themselves the next time the PO's receipts change.
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
            kit_lines = orders._ckd_kit_lines()
            if not kit_lines:
                _logger.info('No CKD kit lines on confirmed purchase orders: nothing to recompute')
                return
            kit_orders = kit_lines.order_id
            env.add_to_compute(kit_lines._fields['qty_received'], kit_lines)
            env.add_to_compute(kit_lines._fields['x_qty_remaining'], kit_lines)
            for name in TRACKING_FIELDS:
                env.add_to_compute(kit_orders._fields[name], kit_orders)
            env.flush_all()
            _logger.info(
                'Received / To Receive recomputed on %d CKD kit line(s) of %d purchase order(s)',
                len(kit_lines), len(kit_orders),
            )
    except Exception:  # noqa: BLE001
        _logger.exception('Could not recompute the Received quantity of existing CKD kit lines')
