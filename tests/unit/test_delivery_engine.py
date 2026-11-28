# -*- coding: utf-8 -*-
"""Plain-pytest tests for the pure-Python delivery engine.

NOT an Odoo test: it lives in the repo-level tests/ folder, outside any addon, so
Odoo's test runner never loads it. Run with:

    python -m pytest tests/unit

The engine module has no Odoo imports, so it is loaded straight from its file.
Calendar used throughout: Mon-Fri, today = Wed 2026-12-02.
"""
import importlib.util
import pathlib
import sys
from datetime import date, timedelta

import pytest

_PATH = (pathlib.Path(__file__).resolve().parents[2] / 'custom_modules' / 'elego_connect'
         / 'models' / 'delivery_engine.py')
_spec = importlib.util.spec_from_file_location('delivery_engine', _PATH)
E = importlib.util.module_from_spec(_spec)
sys.modules['delivery_engine'] = E      # dataclasses looks the module up here
_spec.loader.exec_module(E)

TODAY = date(2026, 12, 2)           # Wednesday
CAL = E.WorkCalendar()


def d(s):
    return date.fromisoformat(s)


def steady_output(per_day, days=15, cal=CAL, today=TODAY):
    return {wd: per_day for wd in cal.previous_working_days(today, days)}


def make(variants=None, backlog=(), wip=(), components=None, output=None, **cfg):
    config = {'fixed_daily_rate': 5, 'qc_pdi_buffer_days': 1,
              'dispatch_buffer_days': 1, 'transit_days': 2}
    config.update(cfg)
    if variants is None:
        variants = {1: E.Variant(1, 10, 'Elego 1.1', 'Red', fg_usable=0,
                                 bom={100: 1}, produce_delay=0)}
    if components is None:
        components = {100: E.Component(100, 'Frame', on_hand=1000)}
    return E.EstimateInputs(
        today=TODAY, calendar=CAL, config=config,
        daily_output=steady_output(5) if output is None else output,
        variants=variants, backlog=list(backlog), wip=list(wip),
        components=components)


def cart(inputs, lines, tracer=None):
    return E.estimate_cart(inputs, lines, tracer)


def first_model(res):
    return res['models'][0]


# ---------------------------------------------------------------- calendar

def test_calendar_helpers():
    assert CAL.add_working(d('2026-12-04'), 1) == d('2026-12-07')   # Fri -> Mon
    assert CAL.next_working(d('2026-12-05')) == d('2026-12-07')     # Sat -> Mon
    w = CAL.previous_working_days(TODAY, 15)
    assert len(w) == 15 and w[-1] == d('2026-12-01') and TODAY not in w
    assert all(CAL.is_working(x) for x in w)


# ---------------------------------------------------------------- 1. FG

def test_fg_covers_request():
    inp = make(variants={1: E.Variant(1, 10, 'Elego 1.1', 'Red', fg_usable=3, bom={100: 1})})
    m = first_model(cart(inp, [(1, 1)]))
    assert m['basis'] == E.BASIS_FG and m['limitingFactor'] == 'stock'
    # ready today, dispatch +1 wd (Thu 3), delivery +2 cd (Sat 5)
    assert m['lastUnitDate'] == '2026-12-05'
    assert m['fromStock'] == 1 and m['confidence'] == 'high'


# ---------------------------------------------------------------- 2/3. backlog

def test_fg_taken_by_approved_backlog_falls_through_to_build():
    inp = make(variants={1: E.Variant(1, 10, 'Elego 1.1', 'Red', fg_usable=2, bom={100: 1})},
               backlog=[E.BacklogLine('SO1', 1, 2, '2026-11-01')])
    m = first_model(cart(inp, [(1, 1)]))
    assert m['basis'] == E.BASIS_BUILD and m['fromStock'] == 0


def test_backlog_queue_follows_approval_time():
    # 1 FG unit; SO-B approved earlier than SO-A, so SO-B gets it. We observe
    # via the trace bookkeeping: the probe sees FG gone either way, so check
    # which SO consumed the WIP unit instead.
    inp = make(variants={1: E.Variant(1, 10, 'M', 'Red', fg_usable=0, bom={100: 1})},
               wip=[E.WipOrder('MO1', 1, 1, d('2026-12-03'))],
               backlog=[E.BacklogLine('SO-A', 1, 1, '2026-11-20'),
                        E.BacklogLine('SO-B', 1, 1, '2026-11-10')])
    t = E.Tracer()
    cart(inp, [(1, 1)], t)
    assert t.values['variants']['1']['wipTaken'] == [{'mo': 'MO1', 'takenBy': 'SO-B'}]


# ---------------------------------------------------------------- 4. blacklist

def test_blacklisted_fg_not_used():
    # Collector passes fg_usable already net of blacklisted lots.
    inp = make(variants={1: E.Variant(1, 10, 'M', 'Red', fg_usable=0, fg_blacklisted=2, bom={100: 1})})
    assert first_model(cart(inp, [(1, 1)]))['basis'] == E.BASIS_BUILD


# ---------------------------------------------------------------- 5. WIP

def test_wip_supplies_at_due_date():
    inp = make(wip=[E.WipOrder('MO7', 1, 2, d('2026-12-08'))])
    m = first_model(cart(inp, [(1, 1)]))
    # due Tue 8 + QC 1 wd = Wed 9, dispatch Thu 10, delivery Sat 12
    assert m['basis'] == E.BASIS_WIP and m['lastUnitDate'] == '2026-12-12'


def test_overdue_wip_counts_from_today():
    inp = make(wip=[E.WipOrder('MO7', 1, 1, d('2026-11-20'))])
    m = first_model(cart(inp, [(1, 1)]))
    # today Wed 2 + QC = Thu 3, dispatch Fri 4, delivery Sun 6
    assert m['lastUnitDate'] == '2026-12-06'


# ---------------------------------------------------------------- 6/7. material

def test_component_short_waits_for_po():
    comps = {100: E.Component(100, 'Controller', on_hand=0,
                              receipts=[E.Receipt(d('2026-12-14'), 20, 'P1')])}
    inp = make(components=comps)
    t = E.Tracer()
    m = first_model(cart(inp, [(1, 1)], t))
    vals = t.values['variants']['1']['cartUnits'][0]
    assert vals['readyDate'] == '2026-12-15'     # slot Mon 14 + QC 1 wd
    assert m['limitingFactor'] == 'material' and m['confidence'] == 'medium'


def test_ckd_kit_receipt_as_components():
    # The collector explodes a kit PO line (qty in kits) into one Receipt per
    # component at qty_per_kit x kits. Here: 3 kits x 2 bolts-sets per kit.
    comps = {100: E.Component(100, 'Frame', on_hand=0, receipts=[E.Receipt(d('2026-12-07'), 3, 'P-KIT')]),
             101: E.Component(101, 'Bolt set', on_hand=0, receipts=[E.Receipt(d('2026-12-07'), 6, 'P-KIT')])}
    v = {1: E.Variant(1, 10, 'M', 'Red', bom={100: 1, 101: 2})}
    res = cart(make(variants=v, components=comps), [(1, 4)])
    m = first_model(res)
    assert m['lastUnitDate'] is None and m['reason'] == E.REASON_UNAVAILABLE
    assert m['firstUnitDate'] is not None


# ---------------------------------------------------------------- 8. shared parts

def test_shared_component_older_so_of_other_model_starves_new_order():
    variants = {1: E.Variant(1, 10, 'A', 'Red', bom={100: 1}),
                2: E.Variant(2, 20, 'B', 'Red', bom={100: 1})}
    comps = {100: E.Component(100, 'Motor', on_hand=1,
                              receipts=[E.Receipt(d('2026-12-21'), 10, 'P9')])}
    without = cart(make(variants=variants, components=comps), [(2, 1)])
    with_bl = cart(make(variants=variants, components=comps,
                        backlog=[E.BacklogLine('SO-A', 1, 1, '2026-11-01')]), [(2, 1)])
    assert first_model(without)['lastUnitDate'] < first_model(with_bl)['lastUnitDate']
    assert first_model(with_bl)['limitingFactor'] == 'material'


# ---------------------------------------------------------------- 9. capacity & rate

def test_capacity_bound_backlog_of_50_at_5_per_day():
    inp = make(backlog=[E.BacklogLine('SO1', 1, 50, '2026-11-01')])
    t = E.Tracer()
    cart(inp, [(1, 1)], t)
    u = t.values['variants']['1']['cartUnits'][0]
    # 50 units fill 10 working days (Wed 2 .. Tue 15); unit 51 -> Wed 16
    assert t.values['rate']['source'] == 'trailing' and t.values['rate']['used'] == 5
    assert u['slotDate'] == '2026-12-16' and u['limitingFactor'] == 'capacity'


def test_rate_window_counts_weekend_output_and_excludes_today():
    out = steady_output(5)
    out[d('2026-11-28')] = 3            # Saturday inside the window
    out[TODAY] = 100                    # today: must be ignored
    t = E.Tracer()
    cart(make(output=out), [(1, 1)], t)
    r = t.values['rate']
    assert r['produced'] == 78 and r['windowDays'] == 15
    assert r['windowEnd'] == '2026-12-01'


def test_fractional_rate_slots():
    cap = E._Capacity(TODAY, CAL, 2.4)
    assert [cap._cap(i) for i in range(5)] == [2, 3, 2, 3, 2]


@pytest.mark.parametrize('output, anomaly', [
    ('idle', 'idle_days'),
    (1, 'below_band'),
    (9, 'above_band'),
])
def test_fixed_rate_fallback_triggers(output, anomaly):
    if output == 'idle':
        out = steady_output(5)
        for wd in CAL.previous_working_days(TODAY, 6):
            out[wd] = 0                 # 6 idle days > 4
    else:
        out = steady_output(output)
    t = E.Tracer()
    cart(make(output=out, fixed_daily_rate=4), [(1, 1)], t)
    r = t.values['rate']
    assert r['anomaly'] == anomaly and r['source'] == 'fixed' and r['used'] == 4


def test_normal_window_uses_trailing():
    t = E.Tracer()
    cart(make(output=steady_output(4.5), fixed_daily_rate=4), [(1, 1)], t)
    assert t.values['rate']['source'] == 'trailing' and t.values['rate']['used'] == 4.5


def test_fixed_mode_forces_fixed():
    t = E.Tracer()
    cart(make(output=steady_output(4.5), fixed_daily_rate=4, rate_mode='fixed'), [(1, 1)], t)
    assert t.values['rate']['source'] == 'fixed' and t.values['rate']['used'] == 4


def test_no_fixed_rate_and_anomalous_window():
    inp = make(output={}, fixed_daily_rate=0,
               variants={1: E.Variant(1, 10, 'A', 'Red', fg_usable=1, bom={100: 1}),
                         2: E.Variant(2, 20, 'B', 'Red', fg_usable=0, bom={100: 1})})
    res = cart(inp, [(1, 1), (2, 1)])
    a, b = res['models']
    assert a['lastUnitDate'] is not None                      # stock still dated
    assert b['lastUnitDate'] is None and b['reason'] == E.REASON_RATE
    assert res['orderCompleteDate'] is None


# ---------------------------------------------------------------- 10/11. edge rules

def test_overdue_po_slips_and_lowers_confidence():
    comps = {100: E.Component(100, 'Controller', on_hand=0,
                              receipts=[E.Receipt(d('2026-11-25'), 5, 'P-LATE')])}
    t = E.Tracer()
    m = first_model(cart(make(components=comps), [(1, 1)], t))
    u = t.values['variants']['1']['cartUnits'][0]
    assert u['materialDate'] == '2026-12-09'                  # today + 7 slip
    assert m['confidence'] == 'low'


def test_not_on_order_uses_vendor_lead_time():
    comps = {100: E.Component(100, 'Controller', on_hand=0, seller_delay=10)}
    t = E.Tracer()
    m = first_model(cart(make(components=comps), [(1, 1)], t))
    u = t.values['variants']['1']['cartUnits'][0]
    assert u['materialDate'] == '2026-12-15'                  # today + 10 + 3
    assert m['limitingFactor'] == 'material_not_on_order' and m['confidence'] == 'low'


def test_no_po_no_seller_unavailable():
    comps = {100: E.Component(100, 'Controller', on_hand=0)}
    m = first_model(cart(make(components=comps), [(1, 1)]))
    assert m['lastUnitDate'] is None and m['reason'] == E.REASON_UNAVAILABLE


def test_no_bom():
    v = {1: E.Variant(1, 10, 'M', 'Red', bom=None)}
    assert first_model(cart(make(variants=v), [(1, 1)]))['reason'] == E.REASON_NO_BOM


def test_incoming_yield_reduces_receipts():
    comps = {100: E.Component(100, 'Frame', on_hand=0,
                              receipts=[E.Receipt(d('2026-12-07'), 10, 'P1'),
                                        E.Receipt(d('2026-12-21'), 10, 'P2')])}
    t = E.Tracer()
    cart(make(components=comps, incoming_yield_pct=50), [(1, 6)], t)
    units = t.values['variants']['1']['cartUnits']
    assert units[4]['materialDate'] == '2026-12-07'           # 5 from P1 at 50%
    assert units[5]['materialDate'] == '2026-12-21'


# ---------------------------------------------------------------- 12. cart

def test_cart_lines_compete():
    comps = {100: E.Component(100, 'Motor', on_hand=1,
                              receipts=[E.Receipt(d('2026-12-21'), 10, 'P9')])}
    variants = {1: E.Variant(1, 10, 'A', 'Red', bom={100: 1}),
                2: E.Variant(2, 20, 'B', 'Red', bom={100: 1})}
    alone = first_model(cart(make(variants=variants, components=comps), [(2, 1)]))
    together = cart(make(variants=variants, components=comps), [(1, 1), (2, 1)])
    assert together['models'][1]['lastUnitDate'] > alone['lastUnitDate']
    assert together['orderCompleteDate'] == together['models'][1]['lastUnitDate']


def test_catalogue_rollup_earliest_colour_and_quote_latest_colour():
    variants = {1: E.Variant(1, 10, 'Elego 1.1', 'Red', fg_usable=1, bom={100: 1}),
                2: E.Variant(2, 10, 'Elego 1.1', 'Blue', fg_usable=0, bom={100: 1})}
    cat = E.estimate_catalogue(make(variants=variants))
    assert len(cat['items']) == 1
    item = cat['items'][0]
    assert item['basis'] == E.BASIS_FG and item['freeStockQty'] == 1
    q = first_model(cart(make(variants=variants), [(1, 1), (2, 1)]))
    assert q['quantity'] == 2 and q['fromStock'] == 1 and q['basis'] == E.BASIS_BUILD
    assert q['lastUnitDate'] > q['firstUnitDate']


def test_red_stock_never_serves_blue():
    variants = {1: E.Variant(1, 10, 'M', 'Red', fg_usable=5, bom={100: 1}),
                2: E.Variant(2, 10, 'M', 'Blue', fg_usable=0, bom={100: 1})}
    q = first_model(cart(make(variants=variants,
                              backlog=[E.BacklogLine('SO1', 2, 1, '2026-11-01')]), [(2, 1)]))
    assert q['fromStock'] == 0


def test_transit_spans_weekend():
    # Ready Thu 3 -> dispatch Fri 4 -> +2 calendar days = Sun 6
    inp = make(wip=[E.WipOrder('MO1', 1, 1, d('2026-12-02'))])
    assert first_model(cart(inp, [(1, 1)]))['lastUnitDate'] == '2026-12-06'


def test_unknown_product_and_bad_quantity():
    res = cart(make(), [(999, 1), (1, 0)])
    assert {e['error'] for e in res['errors']} == {'unknown_product', 'invalid_quantity'}


# ---------------------------------------------------------------- debug

def test_tracer_does_not_change_results():
    comps = {100: E.Component(100, 'Controller', on_hand=2,
                              receipts=[E.Receipt(d('2026-12-14'), 20, 'P1')])}
    args = dict(components=comps, backlog=[E.BacklogLine('SO1', 1, 7, '2026-11-01')],
                wip=[E.WipOrder('MO1', 1, 2, d('2026-12-04'))])
    plain = cart(make(**args), [(1, 3)])
    traced = cart(make(**args), [(1, 3)], E.Tracer())
    assert plain == traced
    assert E.estimate_catalogue(make(**args)) == E.estimate_catalogue(make(**args), E.Tracer())


def test_trace_dates_match_response_and_mention_inputs():
    comps = {100: E.Component(100, 'Controller 48V', on_hand=0,
                              receipts=[E.Receipt(d('2026-12-14'), 20, 'P00412')])}
    t = E.Tracer()
    res = E.estimate_catalogue(make(components=comps), t)
    text = '\n'.join(t.lines)
    assert 'RATE  -> using trailing 5/day' in text
    assert 'P00412' in text and 'Controller 48V' in text
    assert res['items'][0]['estimatedDeliveryDate'] in text
    assert t.values['variants']['1']['deliveryDate'] == res['items'][0]['estimatedDeliveryDate']


def test_trace_truncates():
    t = E.Tracer(max_lines=5)
    E.estimate_catalogue(make(), t)
    assert len(t.lines) == 6 and t.lines[-1] == '... truncated' and t.truncated


# ---------------------------------------------------------------- Connect asks

def test_quote_per_line_breakdown_multi_colour():
    """Ask #1: exact per-line split when a model has several colours in the cart."""
    variants = {1: E.Variant(1, 10, 'Elego 1.1', 'Red', fg_usable=3, bom={100: 1}),
                2: E.Variant(2, 10, 'Elego 1.1', 'White', fg_usable=0, bom={100: 1})}
    res = cart(make(variants=variants), [(1, 5), (2, 2)])
    red, white = res['lines']
    assert (red['odooProductId'], red['quantity'], red['fromStock'], red['fromProduction']) == (1, 5, 3, 2)
    assert (white['fromStock'], white['fromProduction']) == (0, 2)
    assert red['firstUnitDate'] == '2026-12-05' and red['lastUnitDate'] >= red['firstUnitDate']
    m = first_model(res)
    assert m['quantity'] == 7 and m['fromStock'] == 3
    assert m['lastUnitDate'] == max(red['lastUnitDate'], white['lastUnitDate'])
    # no internal detail on lines
    assert set(red) <= {'odooProductId', 'quantity', 'fromStock', 'fromProduction',
                        'firstUnitDate', 'lastUnitDate', 'reason'}


def test_quote_line_undated_has_reason():
    comps = {100: E.Component(100, 'Controller', on_hand=1)}
    res = cart(make(components=comps), [(1, 2)])
    line = res['lines'][0]
    assert line['firstUnitDate'] and line['lastUnitDate'] is None
    assert line['reason'] == E.REASON_UNAVAILABLE


def test_order_estimate_approved_uses_its_own_queue_place():
    """Ask #4: an approved SO keeps the dates its units got in the backlog —
    a later order does not push it back."""
    inp_args = dict(
        variants={1: E.Variant(1, 10, 'M', 'Red', fg_usable=1, bom={100: 1})},
        backlog=[E.BacklogLine('SO-OLD', 1, 1, '2026-11-01'),
                 E.BacklogLine('SO-MINE', 1, 3, '2026-11-05'),
                 E.BacklogLine('SO-NEW', 1, 20, '2026-11-20')])
    res = E.estimate_order(make(**inp_args), 'SO-MINE', [])
    assert res['inQueue'] is True and res['errors'] == []
    line = res['lines'][0]
    # SO-OLD took the only FG unit; SO-MINE builds 3 at 5/day from today
    assert (line['quantity'], line['fromStock'], line['fromProduction']) == (3, 0, 3)
    # same answer whatever is queued behind it
    without_new = E.estimate_order(make(**dict(inp_args, backlog=inp_args['backlog'][:2])), 'SO-MINE', [])
    assert without_new['lines'] == res['lines']


def test_order_estimate_not_approved_is_quoted_at_back():
    inp = make(variants={1: E.Variant(1, 10, 'M', 'Red', fg_usable=1, bom={100: 1})},
               backlog=[E.BacklogLine('SO-OLD', 1, 1, '2026-11-01')])
    res = E.estimate_order(inp, 'SO-PENDING', [(1, 2)])
    assert res['inQueue'] is False
    assert res['lines'][0]['fromStock'] == 0          # SO-OLD has the FG unit
    assert res['orderCompleteDate'] == res['lines'][0]['lastUnitDate']


def test_order_estimate_traced_same_result():
    args = dict(backlog=[E.BacklogLine('SO-MINE', 1, 3, '2026-11-05')])
    assert (E.estimate_order(make(**args), 'SO-MINE', [])
            == E.estimate_order(make(**args), 'SO-MINE', [], E.Tracer()))
