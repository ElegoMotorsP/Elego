# -*- coding: utf-8 -*-
"""One-off repair: receipts made by hand from the Purchase Order picker that
were never linked to the PO's order lines (stock.move.purchase_line_id empty).

Their stock was posted, but the PO still shows Received 0, never counts as
fully received (so it stays in the GRN Purchase Order picker) and cannot be
billed from what was received. New receipts are linked automatically from
module v139; this links the ones that already exist.

Run inside an Odoo shell (`env` is provided). On Odoo.sh, from the build's
Shell tab (stdin must be redirected from the file so the shell executes it as
a script):

    cd ~/src/user

    # 1) DRY RUN (default) - prints what would be linked, writes nothing
    ELEGO_POS="EGO-PO-00158" odoo-bin shell < fix_unlinked_receipt_moves.py

    # 2) APPLY - links the moves and commits (only with ELEGO_APPLY=1)
    ELEGO_APPLY=1 ELEGO_POS="EGO-PO-00158" odoo-bin shell < fix_unlinked_receipt_moves.py

ELEGO_POS is required (comma separated PO numbers): linking changes what a PO
reports as received and billable, so it is done one reviewed PO at a time,
never across the whole database.

Only incoming moves that are not cancelled, have no PO line yet and sit on a
receipt of that PO (its Purchase Order field, or its Source Document) are
touched. Each goes to the first line of its product that is still open, else
the first line of that product, exactly like the module does for new receipts.
Nothing else is written: no quantities, no stock, no state.

The Odoo shell rolls back on exit, so nothing is saved unless this script
calls commit - which it only does in APPLY mode.
"""
import os

APPLY = os.environ.get('ELEGO_APPLY') == '1'
PO_NAMES = [n.strip() for n in os.environ.get('ELEGO_POS', '').split(',') if n.strip()]

print('Mode: %s' % ('APPLY (will write + commit)' if APPLY else 'DRY RUN (nothing is written)'))

if not PO_NAMES:
    print('Nothing to do: set ELEGO_POS="EGO-PO-00158" (comma separated PO numbers).')
else:
    Move = env['stock.move']
    for po_name in PO_NAMES:
        po = env['purchase.order'].search([('name', '=', po_name)], limit=1)
        if not po:
            print('\n%s: not found' % po_name)
            continue

        print('\n=== %s | %s | state %s ===' % (po.name, po.partner_id.name, po.state))
        for line in po.order_line.filtered(lambda l: not l.display_type):
            print('  line %s | %s | ordered %s | received %s' % (
                line.id, line.product_id.display_name, line.product_qty, line.qty_received))

        moves = Move.search([
            ('picking_id.picking_type_code', '=', 'incoming'),
            ('state', '!=', 'cancel'),
            ('purchase_line_id', '=', False),
            '|',
            ('picking_id.x_source_po_id', '=', po.id),
            ('picking_id.origin', '=', po.name),
        ], order='picking_id, id')

        plan = []
        for move in moves:
            lines = po.order_line.filtered(
                lambda l: not l.display_type and l.product_id == move.product_id)
            open_lines = lines.filtered(lambda l: l.product_qty > l.qty_received)
            line = (open_lines or lines)[:1]
            print('  %s | %s | %s | demand %s | quantity %s | -> %s' % (
                move.picking_id.name, move.picking_id.state, move.product_id.display_name,
                move.product_uom_qty, move.quantity,
                'line %s' % line.id if line else 'NOT ON THIS PO (left unlinked)'))
            if line:
                plan.append((move, line))

        if not plan:
            print('  nothing to link')
        else:
            # What the PO would report as received once the done moves count.
            projected = {}
            for move, line in plan:
                if move.state == 'done':
                    projected[line.id] = projected.get(line.id, 0.0) + move.quantity
            for line in po.order_line.filtered(lambda l: not l.display_type):
                total = line.qty_received + projected.get(line.id, 0.0)
                flag = '  <-- MORE THAN ORDERED, check for a doubled receipt' if total > line.product_qty else ''
                print('  after linking: line %s received %s of %s%s' % (
                    line.id, total, line.product_qty, flag))

        if APPLY and plan:
            for move, line in plan:
                move.purchase_line_id = line
            env.flush_all()
            env.cr.commit()
            po.invalidate_recordset()
            print('  APPLIED. %s now: fully received = %s' % (po.name, po.x_receipt_complete))
            for line in po.order_line.filtered(lambda l: not l.display_type):
                print('  line %s | received %s of %s' % (line.id, line.qty_received, line.product_qty))

        open_pickings = po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        open_pickings |= env['stock.picking'].search([
            ('picking_type_code', '=', 'incoming'),
            ('state', 'not in', ('done', 'cancel')),
            '|', ('x_source_po_id', '=', po.id), ('origin', '=', po.name),
        ])
        if open_pickings:
            print('  receipts of this PO still open (not touched): %s' % ', '.join(
                '%s (%s)' % (p.name, p.state) for p in open_pickings.sorted('name')))
