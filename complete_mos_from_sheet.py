# -*- coding: utf-8 -*-
"""One-off: finish the bikes of already-issued MOs from the production sheet.

The MOs exist and their materials are issued (Store -> Production WIP). Each
sheet row (model, colour, chassis, hub motor, controller) is recorded through
the SAME code as the Global Production Scan (elegomotors.global.scan.wizard):
oldest issued MO of that model + colour (FIFO), bike serial from the model
sequence, component serials on the lot, MO marked done. Then QC is passed
(action_qc_pass), which moves the bike to Finished Goods.

Data: complete_mos_from_sheet.csv (same folder) - row, date, model, colour,
chassis, motor, controller. The date column is informational: MOs close with
the run date.

Serial rules (agreed with the client):
  - The same number in DIFFERENT columns (e.g. a controller number that is also
    a motor number) is fine - they are different parts.
  - The same number twice in the SAME column: the first row (sheet order) keeps
    the number as it is, the second gets A, the third B, ... e.g. KIN-...518
    (first), KIN-...518A (second), KIN-...518B (third).
  - Serial formats are taken exactly as in the sheet.

Run on Odoo.sh, from ~/src/user (stdin must be redirected):

    # 1) DRY RUN (default) - validates every row, writes nothing
    odoo-bin shell < complete_mos_from_sheet.py

    # 2) small real test first: 3 bikes of one model + colour
    APPLY=1 LIMIT=3 ONLY="Elego 1.1:Red" odoo-bin shell < complete_mos_from_sheet.py

    # 3) everything, in batches (re-runnable: finished bikes are skipped)
    APPLY=1 odoo-bin shell < complete_mos_from_sheet.py

Options (environment variables):
    ONLY=<model[:colour],...>   only these rows, e.g. "Elego 1.2 42Ah,Elego 1.1:Red"
    SKIP=<row,row,...>          sheet row numbers to leave out
    LIMIT=<n>                   stop after n bikes
    CHUNK=<n>                   bikes per commit (default 20)
    QUIET_MAIL=0                keep the "QC required" emails (default: queued
                                emails of the processed MOs / FG transfers are
                                cancelled; Odoo inbox notes are still posted)

Apply mode stops, before changing anything, if any selected row has a problem
(serial already used on another bike, unknown model or colour, not enough issued
MO units). Nothing is deleted; QC pass is the only step after Done.
"""
import csv
import os
from collections import defaultdict

APPLY = os.environ.get('APPLY') == '1'
ONLY = [t.strip().lower() for t in os.environ.get('ONLY', '').split(',') if t.strip()]
SKIP = {t.strip() for t in os.environ.get('SKIP', '').split(',') if t.strip()}
LIMIT = int(os.environ.get('LIMIT') or 0)
CHUNK = int(os.environ.get('CHUNK') or 20)
QUIET_MAIL = os.environ.get('QUIET_MAIL', '1') == '1'
PATH = os.environ.get('CSV') or os.path.expanduser('~/src/user/complete_mos_from_sheet.csv')

# No "send immediately" emails and no field-tracking noise while bulk processing.
env = env(context=dict(env.context, mail_notify_force_send=False, tracking_disable=True))  # noqa: F821

MODEL_CODE = {
    'Elego 1.1': 'ELEGO11',
    'Elego 1.1 42Ah': 'ELEGO1142',
    'Elego 1.2': 'ELEGO12',
    'Elego 1.2 42Ah': 'ELEGO1242',
    'Elego 2.0+': 'ELEGO20P',
}
SERIAL_FIELDS = (('chassis', 'x_chassis_serial'), ('motor', 'x_motor_serial'),
                 ('controller', 'x_controller_serial'))

W = env['elegomotors.global.scan.wizard']
Lot, MO = env['stock.lot'], env['mrp.production']

rows = list(csv.DictReader(open(PATH, encoding='utf-8')))
for r in rows:
    r['row'] = str(r['row'])

# Same number twice in the SAME column -> letters A, B, C ... (decided on the
# whole file, in sheet order, so a filtered / resumed run gives the same result).
KEEP_FIRST = True   # first appearance keeps the plain number; later ones get A, B, C ...
LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
renamed = []
for _key, _f in (('chassis', 'x_chassis_serial'), ('motor', 'x_motor_serial'), ('controller', 'x_controller_serial')):
    groups = defaultdict(list)
    for r in sorted(rows, key=lambda x: int(x['row'])):
        if r[_key]:
            groups[r[_key]].append(r)
    for value, rs in groups.items():
        if len(rs) > 1:
            for i, r in enumerate(rs):
                if KEEP_FIRST and i == 0:
                    continue
                r[_key] = value + LETTERS[i - 1 if KEEP_FIRST else i]
                renamed.append('row %s %s %s -> %s' % (r['row'], _key, value, r[_key]))
if renamed:
    print('same-column duplicates given letters:')
    for line in renamed:
        print('   ', line)
print('Mode: %s | file rows: %d' % ('APPLY' if APPLY else 'DRY RUN (nothing is written)', len(rows)))


def selected(r):
    if r['row'] in SKIP:
        return False
    if not ONLY:
        return True
    for tok in ONLY:
        model, _, colour = tok.partition(':')
        if r['model'].lower() == model.strip() and (not colour or r['colour'].lower() == colour.strip()):
            return True
    return False


rows = [r for r in rows if selected(r)]
rows.sort(key=lambda r: (r['date'], int(r['row'])))
print('rows selected: %d' % len(rows))

problems = []


def problem(r, msg):
    problems.append('row %s (%s %s, chassis %s): %s' % (r['row'], r['model'], r['colour'], r['chassis'], msg))


# ---- 1. each row: known model + colour, all three serials present -------
tmpl_of = {}
for model, code in MODEL_CODE.items():
    t = W._resolve_model_code(code)
    if not t or t.name != model:
        print('ABORT: model %r does not resolve to a product template named %r' % (code, model))
        raise SystemExit
    tmpl_of[model] = t
for r in rows:
    if r['model'] not in MODEL_CODE:
        problem(r, 'unknown model %r' % r['model'])
    if not W._resolve_color_code(r['colour']):
        problem(r, 'unknown colour %r' % r['colour'])
    for key, _f in SERIAL_FIELDS:
        if not r[key]:
            problem(r, 'blank %s' % key)

# ---- 2. one number twice on the SAME bike -------------------------------
for r in rows:
    vals = [r[k] for k, _f in SERIAL_FIELDS if r[k]]
    if len(vals) != len(set(vals)):
        problem(r, 'the same number is used twice on this bike')

# ---- 3. serials already in the system -----------------------------------
done_rows = []      # bikes already recorded by an earlier run of this script
pending = []
for r in rows:
    holder = Lot._find_serial_holder('x_chassis_serial', r['chassis']) if r['chassis'] else Lot.browse()
    if holder:
        if (holder.x_motor_serial == r['motor'] and holder.x_controller_serial == r['controller']
                and holder.product_id.product_tmpl_id.name == r['model']):
            done_rows.append((r, holder))
            continue
        problem(r, 'chassis already on bike %s with different details' % holder.name)
        continue
    pending.append(r)
    for key, fname in SERIAL_FIELDS[1:]:
        other = Lot._find_serial_holder(fname, r[key]) if r[key] else Lot.browse()
        if other:
            problem(r, '%s %s already on bike %s' % (key, r[key], other.name))
print('already recorded earlier: %d | to do: %d' % (len(done_rows), len(pending)))


# ---- 4. issued MO units available per model + colour --------------------
def mo_colour(mo):
    for ptav in mo.product_id.product_template_attribute_value_ids:
        if ptav.attribute_id.name == 'Color':
            return ptav.product_attribute_value_id.name
    return mo.x_color or ''


open_mos = MO.search([('state', 'in', ('confirmed', 'progress', 'to_close'))], order='date_start asc, id asc')
need = defaultdict(int)
for r in pending:
    need[(r['model'], r['colour'])] += 1
first_mo = {}
print('\n%-16s %-7s %6s %9s' % ('model', 'colour', 'to do', 'MO units'))
for (model, colour), n in sorted(need.items()):
    avail = 0
    for mo in open_mos:
        if (mo.product_id.product_tmpl_id == tmpl_of.get(model) and mo_colour(mo).lower() == colour.lower()
                and not mo.lot_producing_id and mo.x_issue_picking_done):
            avail += max(mo.product_qty - mo.qty_produced, 0)
            first_mo.setdefault((model, colour), mo)
    flag = '' if avail >= n else '  <-- NOT ENOUGH'
    print('%-16s %-7s %6d %9d%s' % (model, colour, n, avail, flag))
    if avail < n:
        problems.append('%s %s: %d bikes in the file but only %d issued MO units' % (model, colour, n, avail))

# ---- 5. components in Production WIP ------------------------------------
wip = env.ref('elegomotors_setup.location_ego_production_wip')
required = defaultdict(float)
for (model, colour), n in need.items():
    mo = first_mo.get((model, colour))
    if not mo or not mo.product_qty:
        continue
    for m in mo.move_raw_ids.filtered(lambda x: x.state != 'cancel'):
        required[m.product_id] += m.product_uom_qty / mo.product_qty * n
if required:
    quants = env['stock.quant'].search([('location_id', 'child_of', wip.id),
                                        ('product_id', 'in', [p.id for p in required])])
    on_hand = defaultdict(float)
    for q in quants:
        on_hand[q.product_id] += q.quantity
    short = [(p, q, on_hand[p]) for p, q in required.items() if q - on_hand[p] > 0.0001]
    print('\nBOM components in Production WIP vs what these bikes will consume: %d short' % len(short))
    for p, q, have in sorted(short, key=lambda x: x[2] - x[1])[:40]:
        print('   %-48s needs %9.1f | in WIP %9.1f | short %9.1f' % (p.display_name[:48], q, have, q - have))
    if short:
        print('   (WIP may also be needed by other open MOs not in this file; stock would go negative)')

print('\nPROBLEMS: %d' % len(problems))
for p in problems[:200]:
    print('   ', p)
if len(problems) > 200:
    print('    ... and %d more' % (len(problems) - 200))

# ---- bikes done earlier but QC not passed yet ---------------------------
stuck_qc = []
for r, lot in done_rows:
    mo = MO.search([('lot_producing_id', '=', lot.id)], limit=1)
    if mo and mo.state == 'done' and mo.qc_state != 'passed':
        stuck_qc.append(mo)
print('bikes recorded earlier but QC not passed: %d' % len(stuck_qc))

if not APPLY:
    print('\nDRY RUN finished - nothing written.')
    raise SystemExit
if problems:
    print('\nAPPLY stopped: fix or SKIP the problem rows above first. Nothing was written.')
    raise SystemExit

# ---- apply ---------------------------------------------------------------
Mail = env['mail.mail']


def quiet(mos):
    if not QUIET_MAIL or not mos:
        return
    picks = env['stock.picking'].search([('origin', 'in', mos.mapped('name'))])
    Mail.search(['&', ('state', '=', 'outgoing'), '|',
                 '&', ('model', '=', 'mrp.production'), ('res_id', 'in', mos.ids),
                 '&', ('model', '=', 'stock.picking'), ('res_id', 'in', picks.ids)]).write({'state': 'cancel'})


for mo in stuck_qc:
    mo.action_qc_pass()
quiet(env['mrp.production'].browse([m.id for m in stuck_qc]))
env.cr.commit()

todo = pending[:LIMIT] if LIMIT else pending


def make_chunks(items, size):
    """Sheet order, at most `size` bikes per chunk, and no number shared by two
    bikes of one chunk (the scan wizard rejects a number that appears twice in
    a batch, even if it is a motor on one bike and a controller on another)."""
    chunks, cur, used = [], [], set()
    for r in items:
        vals = {r['chassis'], r['motor'], r['controller']}
        if cur and (len(cur) >= size or used & vals):
            chunks.append(cur)
            cur, used = [], set()
        cur.append(r)
        used |= vals
    if cur:
        chunks.append(cur)
    return chunks


made = 0
for chunk in make_chunks(todo, CHUNK):
    try:
        wiz = W.create({'x_scan_qty': len(chunk), 'x_auto_print': False})
        lines = wiz.line_ids.sorted('sequence')
        assert len(lines) == len(chunk), 'scan rows %d != %d' % (len(lines), len(chunk))
        for line, r in zip(lines, chunk):
            line.write({
                'x_model_code': MODEL_CODE[r['model']],
                'x_color_code': r['colour'],
                'x_chassis_serial': r['chassis'],
                'x_motor_serial': r['motor'],
                'x_controller_serial': r['controller'],
            })
        wiz.action_confirm()
        lots = wiz.generated_lot_ids
        assert len(lots) == len(chunk), 'recorded %d bikes for %d rows' % (len(lots), len(chunk))
        mos = MO.search([('lot_producing_id', 'in', lots.ids)])
        assert len(mos) == len(lots) and all(m.state == 'done' for m in mos), 'MO not done'
        for mo in mos:
            mo.action_qc_pass()
        quiet(mos)
        env.cr.commit()
    except Exception as exc:  # noqa: BLE001 - report the chunk, keep earlier chunks
        env.cr.rollback()
        print('STOPPED in chunk rows %s ... %s: %s' % (chunk[0]['row'], chunk[-1]['row'], exc))
        print('Earlier chunks are saved. Fix the cause and re-run; finished bikes are skipped.')
        raise SystemExit
    made += len(chunk)
    print('saved rows %s-%s (%d bikes, serials %s ... %s) | total %d/%d' % (
        chunk[0]['row'], chunk[-1]['row'], len(chunk), lots[:1].name, lots[-1:].name, made, len(todo)))
print('\nFINISHED: %d bikes recorded and QC passed.' % made)
