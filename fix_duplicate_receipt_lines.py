# -*- coding: utf-8 -*-
"""One-off repair: done receipts whose QC-approved moves carry duplicate move
lines (each set to the full quantity), so Quantity = N x Demand and stock was
posted N times.

Run inside an Odoo shell (`env` is provided). On Odoo.sh, from the build's
Shell tab (stdin must be redirected from the file so the shell executes it as
a script):

    cd ~/src/user

    # 1) DRY RUN (default) - prints what would change, writes nothing
    odoo-bin shell -d <db_name> < fix_duplicate_receipt_lines.py

    # 2) DRY RUN limited to specific receipts
    ELEGO_PICKINGS="EGO/IN/00146,EGO/IN/00150" \\
        odoo-bin shell -d <db_name> < fix_duplicate_receipt_lines.py

    # 3) APPLY - writes and commits (only with ELEGO_APPLY=1)
    ELEGO_APPLY=1 ELEGO_PICKINGS="EGO/IN/00146" \\
        odoo-bin shell -d <db_name> < fix_duplicate_receipt_lines.py

The Odoo shell rolls back on exit, so nothing is saved unless this script
calls commit - which it only does in APPLY mode.

Target quantity per move = x_qty_qc_passed (what QC actually passed). Only
plain (no lot/serial) lines of done incoming moves are touched: the first line
keeps the target quantity, the duplicates are set to 0. Writing `quantity` on
a done move line makes Odoo reverse the difference out of the quants (and
post a correction valuation layer), and the PO's received quantity - computed
from done moves - follows.
"""
import os

APPLY = os.environ.get('ELEGO_APPLY') == '1'
PICKING_NAMES = [
    n.strip() for n in os.environ.get('ELEGO_PICKINGS', '').split(',') if n.strip()
]

domain = [
    ('picking_id.picking_type_code', '=', 'incoming'),
    ('state', '=', 'done'),
    ('x_qty_qc_passed', '>', 0),
]
if PICKING_NAMES:
    domain.append(('picking_id.name', 'in', PICKING_NAMES))

print('Mode: %s%s' % (
    'APPLY (will write + commit)' if APPLY else 'DRY RUN (nothing is written)',
    ' | receipts: %s' % ', '.join(PICKING_NAMES) if PICKING_NAMES else ' | all receipts',
))

affected = 0
for move in env['stock.move'].search(domain, order='picking_id, id'):
    lines = move.move_line_ids
    if len(lines) < 2 or lines.filtered('lot_id'):
        continue
    target = move.x_qty_qc_passed
    posted = sum(lines.mapped('quantity'))
    excess = posted - target
    if excess <= 0.0001:
        continue

    loc = lines[0].location_dest_id
    on_hand = move.product_id.with_context(location=loc.id).qty_available
    print('%s | %s | PO %s | lines=%d | posted=%s | should be=%s | excess=%s | on hand at %s=%s' % (
        move.picking_id.name, move.product_id.display_name,
        move.picking_id.origin or '-', len(lines), posted, target, excess,
        loc.complete_name, on_hand))
    if on_hand < excess - 0.0001:
        print('    WARNING: on hand is lower than the excess - part of it was '
              'already consumed; correcting will leave negative stock here.')

    if APPLY:
        lines[0].quantity = target
        (lines - lines[0]).write({'quantity': 0})
        move.picking_id.message_post(
            body='Duplicate move lines corrected for %s: %s posted, QC passed %s '
                 '(reversed %s).' % (move.product_id.display_name, posted, target, excess),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )
    affected += 1

if APPLY:
    env.cr.commit()
    print('FIXED and committed %d move(s).' % affected)
else:
    print('DRY RUN: %d move(s) would be fixed. Re-run with ELEGO_APPLY=1 to apply.' % affected)
