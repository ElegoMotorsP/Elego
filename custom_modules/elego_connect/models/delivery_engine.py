# -*- coding: utf-8 -*-
"""Delivery-time estimation engine — pure Python, no Odoo imports.

See doc/delivery-estimate-api-plan.md. The Odoo side
(models/delivery_estimator.py) gathers a snapshot of the ERP into the plain
dataclasses below; this module simulates on that snapshot and never touches the
database. Keeping it Odoo-free means the allocation logic — the part most
likely to be wrong — is unit-testable with plain pytest
(tests/test_delivery_engine.py), without a database.

Simulation, in one paragraph: every approved, undelivered SO unit is placed in
a FIFO queue (by approval time). Each unit takes, in order: a free finished
bike of its colour; else a free unit from an open MO of its colour; else a new
build, which needs every BoM component covered by on-hand stock or incoming PO
receipts AND a free production slot (N per working day, N = trailing or fixed
rate). The dealer's prospective order is then run at the back of that queue.
"""
import copy
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

HORIZON_DAYS = 365
MAX_TRACE_LINES = 2000
_EPS = 1e-9

BASIS_FG = 'fg_stock'
BASIS_WIP = 'wip'
BASIS_BUILD = 'new_build'

LF_STOCK = 'stock'
LF_WIP = 'wip'
LF_CAPACITY = 'capacity'
LF_MATERIAL = 'material'
LF_NOT_ON_ORDER = 'material_not_on_order'

REASON_NO_BOM = 'no_bom'
REASON_UNAVAILABLE = 'unavailable'
REASON_RATE = 'rate_not_configured'
REASON_HORIZON = 'beyond_horizon'

# Supply kinds, for confidence and the trace.
_K_STOCK = 'stock'
_K_PO = 'po'
_K_PO_OVERDUE = 'po_overdue'
_K_NOT_ON_ORDER = 'not_on_order'

DEFAULT_CONFIG = {
    'rate_mode': 'auto',            # 'auto' | 'fixed'
    'rate_window_days': 15,
    'fixed_daily_rate': 0.0,        # 0 = not configured
    'max_idle_days': 4,
    'anomaly_low_pct': 50.0,
    'anomaly_high_pct': 150.0,
    'qc_pdi_buffer_days': 1,
    'dispatch_buffer_days': 1,
    'transit_days': 2,              # calendar days
    'overdue_slip_days': 7,
    'procurement_buffer_days': 3,
    'incoming_yield_pct': 100.0,
}


# ----------------------------------------------------------------------
# Snapshot dataclasses (filled by the Odoo collector, or by tests)
# ----------------------------------------------------------------------

@dataclass
class Variant:
    pid: int
    tmpl_id: int
    model: str
    colour: str = ''
    fg_usable: float = 0.0          # FG on hand, blacklisted lots excluded
    fg_blacklisted: float = 0.0     # for the trace only
    bom: dict = None                # {component pid: qty per bike}; None = no BoM
    bom_name: str = ''
    produce_delay: int = 0          # working days, mrp.bom.produce_delay

    @property
    def label(self):
        return f'{self.model} {self.colour}'.strip()


@dataclass
class BacklogLine:
    so: str
    pid: int
    qty: float
    approved_at: object = None      # datetime/date — sort key only


@dataclass
class WipOrder:
    mo: str
    pid: int
    qty: float
    due: date = None


@dataclass
class Receipt:
    date: date
    qty: float                      # in the component's own unit
    ref: str = ''                   # PO name


@dataclass
class Component:
    pid: int
    name: str
    on_hand: float = 0.0            # free on hand (open MO demand already netted off)
    receipts: list = field(default_factory=list)
    seller_delay: int = None        # days; None = no vendor known


@dataclass
class EstimateInputs:
    today: date
    calendar: 'WorkCalendar'
    config: dict
    daily_output: dict              # {date: bikes finished that day}
    variants: dict                  # {pid: Variant}
    backlog: list                   # [BacklogLine]
    wip: list                       # [WipOrder]
    components: dict                # {pid: Component}


# ----------------------------------------------------------------------
# Tracer
# ----------------------------------------------------------------------

class NullTracer:
    """Default: records nothing. The engine always calls the same methods, so
    turning debug on cannot change a result — only what gets recorded."""
    enabled = False

    def line(self, text):
        pass


class Tracer(NullTracer):
    enabled = True

    def __init__(self, max_lines=MAX_TRACE_LINES):
        self.lines = []
        self.values = {}
        self.truncated = False
        self._max = max_lines

    def line(self, text):
        if len(self.lines) < self._max:
            self.lines.append(text)
        elif not self.truncated:
            self.lines.append('... truncated')
            self.truncated = True

    def as_dict(self):
        return {'trace': self.lines, 'values': self.values}


# ----------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------

class WorkCalendar:
    """Working days = listed weekdays (0 = Monday) minus holidays."""

    def __init__(self, working_weekdays=(0, 1, 2, 3, 4), holidays=()):
        self.weekdays = frozenset(working_weekdays) or frozenset(range(5))
        self.holidays = frozenset(holidays)

    def is_working(self, d):
        return d.weekday() in self.weekdays and d not in self.holidays

    def next_working(self, d):
        """d itself if it is a working day, else the next one."""
        for _ in range(HORIZON_DAYS * 2):
            if self.is_working(d):
                return d
            d += timedelta(days=1)
        return d

    def add_working(self, d, n):
        """n working days after d (n <= 0 → d unchanged)."""
        n = int(n or 0)
        cur = d
        while n > 0:
            cur += timedelta(days=1)
            if self.is_working(cur):
                n -= 1
        return cur

    def previous_working_days(self, before, n):
        """The n working days strictly before `before`, oldest first."""
        days = []
        cur = before
        for _ in range(HORIZON_DAYS * 2):
            if len(days) >= n:
                break
            cur -= timedelta(days=1)
            if self.is_working(cur):
                days.append(cur)
        return list(reversed(days))


def _iso(d):
    return d.isoformat() if d else None


def _fmt(x):
    """Quantities in the trace: 3 not 3.0, 2.53 not 2.5333."""
    if x is None:
        return '-'
    if abs(x - round(x)) < _EPS:
        return str(int(round(x)))
    return f'{x:.2f}'


# ----------------------------------------------------------------------
# Production rate (plan §1.1)
# ----------------------------------------------------------------------

def compute_rate(inputs, tracer):
    cfg = inputs.config
    cal = inputs.calendar
    today = inputs.today
    n = int(cfg['rate_window_days'] or 15)
    window = cal.previous_working_days(today, n)
    start = window[0] if window else today
    end = window[-1] if window else today

    # Output on ANY date inside the span counts (a Saturday catch-up still
    # used line time); the divisor is the number of working days.
    produced = 0.0
    d = start
    while d < today:
        produced += inputs.daily_output.get(d, 0.0)
        d += timedelta(days=1)
    idle = sum(1 for wd in window if inputs.daily_output.get(wd, 0.0) <= _EPS)
    trailing = produced / n if n else 0.0

    fixed = float(cfg['fixed_daily_rate'] or 0.0)
    low = fixed * float(cfg['anomaly_low_pct']) / 100.0
    high = fixed * float(cfg['anomaly_high_pct']) / 100.0
    max_idle = int(cfg['max_idle_days'])

    anomaly = None
    if idle > max_idle:
        anomaly = 'idle_days'
    elif fixed > 0 and trailing < low - _EPS:
        anomaly = 'below_band'
    elif fixed > 0 and trailing > high + _EPS:
        anomaly = 'above_band'
    elif trailing <= _EPS:
        anomaly = 'no_output'

    mode = cfg['rate_mode'] or 'auto'
    if mode == 'fixed' or anomaly:
        used = fixed if fixed > 0 else None
        source = 'fixed'
    else:
        used = trailing
        source = 'trailing'

    info = {
        'windowStart': _iso(start), 'windowEnd': _iso(end), 'windowDays': n,
        'produced': produced, 'idleDays': idle, 'trailing': round(trailing, 4),
        'fixed': fixed or None, 'lowBound': round(low, 4) if fixed else None,
        'highBound': round(high, 4) if fixed else None, 'mode': mode,
        'anomaly': anomaly, 'used': round(used, 4) if used else None,
        'source': source,
    }
    if tracer.enabled:
        tracer.values['rate'] = info
        tracer.line(f'RATE  window {_iso(start)}..{_iso(end)} '
                    f'({n} working days, today excluded)')
        tracer.line(f'RATE  produced = {_fmt(produced)} bikes; idle days = {idle}')
        tracer.line(f'RATE  trailing = {_fmt(produced)} / {n} = {_fmt(trailing)}/day')
        checks = [f'idle {idle} {"<=" if idle <= max_idle else ">"} {max_idle} '
                  f'{"OK" if idle <= max_idle else "ANOMALY"}']
        if fixed > 0:
            checks.append(
                f'{_fmt(trailing)} >= {_fmt(cfg["anomaly_low_pct"])}% x {_fmt(fixed)} = '
                f'{_fmt(low)} {"OK" if trailing >= low - _EPS else "ANOMALY"}')
            checks.append(
                f'{_fmt(trailing)} <= {_fmt(cfg["anomaly_high_pct"])}% x {_fmt(fixed)} = '
                f'{_fmt(high)} {"OK" if trailing <= high + _EPS else "ANOMALY"}')
        else:
            checks.append('fixed rate not configured, band checks skipped')
        tracer.line('RATE  checks: ' + '; '.join(checks))
        if used is None:
            tracer.line(f'RATE  -> no usable rate (mode={mode}, anomaly={anomaly}, '
                        f'fixed rate not set): new builds cannot be dated')
        elif source == 'fixed':
            why = 'mode=fixed' if mode == 'fixed' else f'anomaly={anomaly}'
            tracer.line(f'RATE  -> using fixed {_fmt(used)}/day ({why})')
        else:
            tracer.line(f'RATE  -> using trailing {_fmt(used)}/day')
    return info


# ----------------------------------------------------------------------
# Simulation state
# ----------------------------------------------------------------------

class _ComponentSupply:
    """Time-phased supply of one component, consumed in queue order."""

    def __init__(self, comp, today, cfg):
        self.pid = comp.pid
        self.name = comp.name
        self.on_hand = comp.on_hand
        yield_f = float(cfg['incoming_yield_pct']) / 100.0
        slip = int(cfg['overdue_slip_days'])
        events = [(today, comp.on_hand, 'on hand', _K_STOCK)]
        for r in comp.receipts:
            qty = r.qty * yield_f
            if qty <= _EPS:
                continue
            if r.date < today:
                events.append((today + timedelta(days=slip), qty, r.ref, _K_PO_OVERDUE))
            else:
                events.append((r.date, qty, r.ref, _K_PO))
        # Stable: on-hand first on the same date.
        self.events = sorted(events, key=lambda e: (e[0], e[3] != _K_STOCK))
        self.fallback = None
        if comp.seller_delay is not None:
            self.fallback = today + timedelta(
                days=int(comp.seller_delay) + int(cfg['procurement_buffer_days']))
        self.consumed = 0.0

    def cover(self, need):
        """(date, kind, ref) on which `need` more units are covered, or None."""
        target = self.consumed + need
        cum = 0.0
        for d, q, ref, kind in self.events:
            cum += q
            if cum >= target - _EPS:
                return d, kind, ref
        if self.fallback:
            return self.fallback, _K_NOT_ON_ORDER, 'vendor lead time'
        return None

    def available_today(self, today):
        cum = sum(q for d, q, _r, _k in self.events if d <= today)
        return cum - self.consumed

    def receipts_desc(self):
        return [(d, q, ref, kind) for d, q, ref, kind in self.events if kind != _K_STOCK]


class _Capacity:
    """N slots per working day, fractional N carried over between days."""

    def __init__(self, today, cal, rate):
        self.rate = rate
        self.days = []
        d = cal.next_working(today)
        end = today + timedelta(days=HORIZON_DAYS)
        while d <= end:
            self.days.append(d)
            d = cal.add_working(d, 1)
        self.index = {d: i for i, d in enumerate(self.days)}
        self.used = defaultdict(int)
        self.booked = 0

    def _cap(self, i):
        k = i + 1
        r = self.rate
        return math.floor(k * r + 0.5) - math.floor((k - 1) * r + 0.5)

    def book(self, earliest):
        for i, d in enumerate(self.days):
            if d < earliest:
                continue
            if self.used[i] < self._cap(i):
                self.used[i] += 1
                self.booked += 1
                return d
        return None


class _State:
    def __init__(self, inputs, rate):
        self.fg = {pid: v.fg_usable for pid, v in inputs.variants.items()}
        self.wip = defaultdict(list)
        for w in sorted(inputs.wip, key=lambda w: (w.due or inputs.today, w.mo)):
            if w.qty > _EPS:
                self.wip[w.pid].append([w.mo, w.qty, w.due])
        self.supply = {pid: _ComponentSupply(c, inputs.today, inputs.config)
                       for pid, c in inputs.components.items()}
        self.capacity = _Capacity(inputs.today, inputs.calendar, rate) if rate else None
        # Trace bookkeeping.
        self.backlog_by_variant = defaultdict(list)   # pid -> [(so, qty)]
        self.wip_taken = defaultdict(list)            # pid -> [(mo, so)]
        # so -> [(BacklogLine, [unit results])], for estimate_order().
        self.backlog_results = defaultdict(list)


# ----------------------------------------------------------------------
# Allocation of one unit
# ----------------------------------------------------------------------

def _dates_from_ready(inputs, ready):
    cfg = inputs.config
    cal = inputs.calendar
    dispatch = cal.add_working(ready, cfg['dispatch_buffer_days'])
    delivery = dispatch + timedelta(days=int(cfg['transit_days']))
    return dispatch, delivery


def _result(inputs, basis, lf, confidence, ready, reason=None, extra=None):
    out = {'basis': basis, 'limitingFactor': lf, 'confidence': confidence,
           'readyDate': None, 'dispatchDate': None, 'deliveryDate': None,
           'leadDays': None, 'reason': reason}
    if ready is not None:
        dispatch, delivery = _dates_from_ready(inputs, ready)
        out.update({'readyDate': _iso(ready), 'dispatchDate': _iso(dispatch),
                    'deliveryDate': _iso(delivery),
                    'leadDays': (delivery - inputs.today).days})
    if extra:
        out.update(extra)
    return out


def _allocate(inputs, state, pid, demand_ref, tracer, detail=False):
    """Allocate one bike of variant `pid`. `detail` = write the full build
    working to the trace (probe/cart units, not backlog units)."""
    cfg = inputs.config
    cal = inputs.calendar
    today = inputs.today
    var = inputs.variants[pid]

    # 1. Finished goods.
    if state.fg.get(pid, 0.0) >= 1 - _EPS:
        state.fg[pid] -= 1
        res = _result(inputs, BASIS_FG, LF_STOCK, 'high', today)
        if detail and tracer.enabled:
            tracer.line(f'  FG    free unit taken -> ready {_iso(today)}')
        return res

    # 2. Work in progress.
    for slot in state.wip.get(pid, []):
        if slot[1] >= 1 - _EPS:
            slot[1] -= 1
            mo, _q, due = slot
            state.wip_taken[pid].append((mo, demand_ref))
            base = max(due or today, today)
            ready = cal.add_working(base, cfg['qc_pdi_buffer_days'])
            res = _result(inputs, BASIS_WIP, LF_WIP, 'high', ready,
                          extra={'mo': mo})
            if detail and tracer.enabled:
                tracer.line(f'  WIP   {mo} due {_iso(due)} -> ready {_iso(base)} + '
                            f'QC/PDI {cfg["qc_pdi_buffer_days"]} wd = {_iso(ready)}')
            return res

    # 3. New build.
    if var.bom is None:
        if detail and tracer.enabled:
            tracer.line('  BUILD no BoM for this variant -> cannot date')
        return _result(inputs, BASIS_BUILD, None, None, None, reason=REASON_NO_BOM)
    if state.capacity is None:
        if detail and tracer.enabled:
            tracer.line('  BUILD no production rate -> cannot date')
        return _result(inputs, BASIS_BUILD, None, None, None, reason=REASON_RATE)

    covers = []          # (comp pid, need, date, kind, ref)
    missing = []
    for cpid, need in sorted(var.bom.items()):
        sup = state.supply.get(cpid)
        if sup is None:
            missing.append(cpid)
            continue
        c = sup.cover(need)
        if c is None:
            missing.append(cpid)
        else:
            covers.append((cpid, need, c[0], c[1], c[2]))
    if missing:
        if detail and tracer.enabled:
            parts = []
            for m in missing:
                sup = state.supply.get(m)
                if sup is None:
                    parts.append(f'product {m} (not in snapshot)')
                    continue
                total = sum(q for _d, q, _r, _k in sup.events)
                parts.append(f'{sup.name} need {_fmt(var.bom[m])} | on hand + all POs '
                             f'{_fmt(total)}, already used {_fmt(sup.consumed)}')
            tracer.line('  BUILD short with no PO and no vendor: ' + '; '.join(parts)
                        + ' -> cannot date')
        return _result(inputs, BASIS_BUILD, None, None, None, reason=REASON_UNAVAILABLE,
                       extra={'missingComponents': missing} if tracer.enabled else None)

    material_date = max([c[2] for c in covers] + [today])
    bottleneck = max(covers, key=lambda c: c[2]) if covers else None
    queued_before = state.capacity.booked
    slot_day = state.capacity.book(cal.next_working(material_date))
    if slot_day is None:
        if detail and tracer.enabled:
            tracer.line(f'  BUILD no free production slot within {HORIZON_DAYS} days')
        return _result(inputs, BASIS_BUILD, None, None, None, reason=REASON_HORIZON)
    for cpid, need, _d, _k, _r in covers:
        state.supply[cpid].consumed += need

    kinds = {c[3] for c in covers}
    if kinds & {_K_PO_OVERDUE, _K_NOT_ON_ORDER}:
        confidence = 'low'
    elif material_date > today:
        confidence = 'medium'
    else:
        confidence = 'high'

    material_governs = (material_date > today
                        and slot_day == cal.next_working(material_date))
    if material_governs and bottleneck and bottleneck[3] == _K_NOT_ON_ORDER:
        lf = LF_NOT_ON_ORDER
    elif material_governs:
        lf = LF_MATERIAL
    else:
        lf = LF_CAPACITY

    delay = int(var.produce_delay or 0)
    qc = int(cfg['qc_pdi_buffer_days'])
    built = cal.add_working(slot_day, delay)
    ready = cal.add_working(built, qc)
    res = _result(inputs, BASIS_BUILD, lf, confidence, ready)

    if tracer.enabled:
        comp_vals = []
        for cpid, need, d, kind, ref in covers:
            sup = state.supply[cpid]
            comp_vals.append({
                'product': sup.name, 'productId': cpid, 'need': need,
                'onHand': sup.on_hand, 'coveredOn': _iso(d), 'coveredBy': ref,
                'kind': kind,
                'receipts': [{'ref': r, 'qty': q, 'date': _iso(dd),
                              'overdue': k == _K_PO_OVERDUE}
                             for dd, q, r, k in sup.receipts_desc()],
            })
        res['_debug'] = {
            'components': comp_vals, 'materialDate': _iso(material_date),
            'bottleneck': state.supply[bottleneck[0]].name if bottleneck else None,
            'queuedBefore': queued_before, 'slotDate': _iso(slot_day),
            'produceDelay': delay, 'builtDate': _iso(built),
        }
    if detail and tracer.enabled:
        tracer.line(f'  BUILD need 1; components (BoM {var.bom_name or "-"!r}, '
                    f'{len(var.bom)} lines):')
        quiet = 0
        for cpid, need, d, kind, ref in covers:
            sup = state.supply[cpid]
            is_bottleneck = bottleneck and cpid == bottleneck[0]
            if d <= today and not is_bottleneck:
                quiet += 1
                continue
            src = {'stock': 'on hand', 'po': f'{ref}', 'po_overdue': f'{ref} OVERDUE (+slip)',
                   'not_on_order': 'NOT ON ORDER, vendor lead time'}[kind]
            rec = ', '.join(f'{r} +{_fmt(q)} on {_iso(dd)}' for dd, q, r, k in sup.receipts_desc()) or 'no open PO'
            tracer.line(f'        {sup.name}  need {_fmt(need)} | on hand {_fmt(sup.on_hand)} | '
                        f'{rec} -> covered {_iso(d)} via {src}')
        if quiet:
            tracer.line(f'        ... ({quiet} more covered today)')
        bn = state.supply[bottleneck[0]].name if bottleneck else '-'
        tracer.line(f'  BUILD material date = max(component dates) = {_iso(material_date)} ({bn})')
        tracer.line(f'  BUILD capacity: {queued_before} units booked before this one at '
                    f'{_fmt(state.capacity.rate)}/day -> slot {_iso(slot_day)}')
        tracer.line(f'  READY {_iso(slot_day)} + produce_delay {delay} wd + QC/PDI {qc} wd = {_iso(ready)}')
    return res


def _trace_dates(inputs, tracer, res):
    if not tracer.enabled or not res['readyDate']:
        if tracer.enabled and res.get('reason'):
            tracer.line(f'  RESULT no date, reason={res["reason"]}')
        return
    cfg = inputs.config
    tracer.line(f'  SHIP  {res["readyDate"]} + dispatch {cfg["dispatch_buffer_days"]} wd = {res["dispatchDate"]}')
    tracer.line(f'  DELIV {res["dispatchDate"]} + transit {cfg["transit_days"]} cd = {res["deliveryDate"]}')
    tracer.line(f'  RESULT basis={res["basis"]} limitingFactor={res["limitingFactor"]} '
                f'confidence={res["confidence"]}')


# ----------------------------------------------------------------------
# Backlog
# ----------------------------------------------------------------------

def _run_backlog(inputs, state, tracer):
    def key(b):
        a = b.approved_at
        return (a is None, str(a) if a is not None else '', b.so)

    lines = sorted((b for b in inputs.backlog if b.pid in inputs.variants), key=key)
    units = 0
    sos = []
    unplaced = 0
    for b in lines:
        n = int(round(b.qty))
        state.backlog_by_variant[b.pid].append((b.so, n))
        if b.so not in sos:
            sos.append(b.so)
        results = []
        for _ in range(n):
            units += 1
            r = _allocate(inputs, state, b.pid, b.so, tracer)
            results.append(r)
            if r['readyDate'] is None:
                unplaced += 1
        state.backlog_results[b.so].append((b, results))
    if tracer.enabled:
        oldest = lines[0] if lines else None
        msg = f'QUEUE approved backlog ahead: {units} units across {len(sos)} SOs'
        if oldest:
            msg += f' (oldest {oldest.so}, approved {oldest.approved_at})'
        tracer.line(msg)
        if unplaced:
            tracer.line(f'QUEUE {unplaced} backlog units could not be dated (no BoM / no material / no rate)')
        tracer.values['backlog'] = {'units': units, 'orders': len(sos), 'undated': unplaced}
    return units


def _trace_variant_header(inputs, state, pid, tracer):
    if not tracer.enabled:
        return
    v = inputs.variants[pid]
    tracer.line(f'{v.label} (product {pid}):')
    tracer.line(f'  FG    on hand {_fmt(v.fg_usable + v.fg_blacklisted)} '
                f'({_fmt(v.fg_blacklisted)} blacklisted excluded) = {_fmt(v.fg_usable)} usable')
    bl = state.backlog_by_variant.get(pid, [])
    total = sum(q for _s, q in bl)
    det = ', '.join(f'{s} x{q}' for s, q in bl[:10]) + (' ...' if len(bl) > 10 else '')
    tracer.line(f'  FG    backlog for this colour {total}' + (f' ({det})' if bl else '') +
                f' -> free now {_fmt(max(state.fg.get(pid, 0.0), 0.0))}')
    for mo, so in state.wip_taken.get(pid, [])[:10]:
        tracer.line(f'  WIP   {mo} unit taken by {so}')


def _variant_values(inputs, state, pid, res):
    v = inputs.variants[pid]
    out = {
        'label': v.label, 'fgUsable': v.fg_usable, 'fgBlacklisted': v.fg_blacklisted,
        'backlogQty': sum(q for _s, q in state.backlog_by_variant.get(pid, [])),
        'backlogLines': [{'so': s, 'qty': q} for s, q in state.backlog_by_variant.get(pid, [])],
        'wipTaken': [{'mo': m, 'takenBy': s} for m, s in state.wip_taken.get(pid, [])],
    }
    if res is not None:
        out.update({k: v_ for k, v_ in res.items() if k != '_debug'})
        out.update(res.get('_debug') or {})
    return out


# ----------------------------------------------------------------------
# Public entry points
# ----------------------------------------------------------------------

def _prepare(inputs, tracer):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({k: v for k, v in (inputs.config or {}).items() if v is not None})
    inputs.config = cfg
    if tracer.enabled:
        tracer.values['config'] = {k: cfg[k] for k in (
            'qc_pdi_buffer_days', 'dispatch_buffer_days', 'transit_days',
            'overdue_slip_days', 'procurement_buffer_days', 'incoming_yield_pct')}
    rate = compute_rate(inputs, tracer)
    state = _State(inputs, rate['used'])
    _run_backlog(inputs, state, tracer)
    return rate, state


def _strip(res):
    return {k: v for k, v in res.items() if not k.startswith('_')}


def estimate_catalogue(inputs, tracer=None):
    """One bike per variant at the back of the backlog, rolled up per model
    (earliest colour). Returns {'rate': ..., 'items': [...]}."""
    tracer = tracer or NullTracer()
    rate, base = _prepare(inputs, tracer)
    per_variant = {}
    free_after_backlog = {pid: max(q, 0.0) for pid, q in base.fg.items()}
    var_values = {}
    for pid in sorted(inputs.variants):
        probe = copy.deepcopy(base)
        _trace_variant_header(inputs, probe, pid, tracer)
        res = _allocate(inputs, probe, pid, 'probe', tracer, detail=True)
        _trace_dates(inputs, tracer, res)
        per_variant[pid] = res
        if tracer.enabled:
            var_values[str(pid)] = _variant_values(inputs, probe, pid, res)

    by_model = defaultdict(list)
    for pid, v in inputs.variants.items():
        by_model[v.tmpl_id].append(pid)

    items = []
    for tmpl_id, pids in sorted(by_model.items(), key=lambda kv: inputs.variants[kv[1][0]].model):
        model = inputs.variants[pids[0]].model
        dated = [p for p in pids if per_variant[p]['deliveryDate']]
        if dated:
            best = min(dated, key=lambda p: (per_variant[p]['deliveryDate'], p))
        else:
            best = sorted(pids)[0]
        r = per_variant[best]
        item = {
            'odooTemplateId': tmpl_id, 'model': model,
            'freeStockQty': int(sum(free_after_backlog.get(p, 0.0) for p in pids)),
            'estimatedDispatchDate': r['dispatchDate'],
            'estimatedDeliveryDate': r['deliveryDate'],
            'leadDays': r['leadDays'], 'basis': r['basis'],
            'limitingFactor': r['limitingFactor'], 'confidence': r['confidence'],
        }
        if r.get('reason'):
            item['reason'] = r['reason']
        items.append(item)
        if tracer.enabled:
            parts = ', '.join(f'{inputs.variants[p].colour or p} {per_variant[p]["deliveryDate"] or "n/a"}'
                              for p in sorted(pids))
            tracer.line(f'{model} -> earliest colour {inputs.variants[best].colour or best} '
                        f'{r["deliveryDate"] or "n/a"} ({parts})')
    if tracer.enabled:
        tracer.values['variants'] = var_values
    return {'rate': rate, 'items': items}


def _line_summary(pid, qty, results):
    """Per cart / SO line (Connect ask #1): no component or supplier detail."""
    dated = [r['deliveryDate'] for r in results if r['deliveryDate']]
    undated = [r for r in results if not r['deliveryDate']]
    out = {
        'odooProductId': pid, 'quantity': qty,
        'fromStock': sum(1 for r in results if r['basis'] == BASIS_FG and r['readyDate']),
        'firstUnitDate': min(dated) if dated else None,
        'lastUnitDate': None if undated or not dated else max(dated),
    }
    out['fromProduction'] = qty - out['fromStock']
    if undated:
        out['reason'] = undated[0]['reason']
    return out


def _summarise(inputs, per_line):
    """per_line: [(pid, [unit results])] in order → (models, lines, orderCompleteDate)."""
    agg = {}
    order = []
    lines_out = []
    for pid, results in per_line:
        v = inputs.variants[pid]
        lines_out.append(_line_summary(pid, len(results), results))
        if v.tmpl_id not in agg:
            agg[v.tmpl_id] = {'odooTemplateId': v.tmpl_id, 'model': v.model, 'quantity': 0,
                              'fromStock': 0, 'fromProduction': 0, '_results': []}
            order.append(v.tmpl_id)
        a = agg[v.tmpl_id]
        for res in results:
            a['quantity'] += 1
            if res['basis'] == BASIS_FG and res['readyDate']:
                a['fromStock'] += 1
            else:
                a['fromProduction'] += 1
            a['_results'].append(res)

    models = []
    complete = []
    all_dated = True
    for tmpl_id in order:
        a = agg[tmpl_id]
        results = a.pop('_results')
        dated = [r for r in results if r['deliveryDate']]
        undated = [r for r in results if not r['deliveryDate']]
        a['firstUnitDate'] = min(r['deliveryDate'] for r in dated) if dated else None
        if undated:
            all_dated = False
            a['lastUnitDate'] = None
            a['reason'] = undated[0]['reason']
            setter = undated[0]
        else:
            setter = max(dated, key=lambda r: r['deliveryDate'])
            a['lastUnitDate'] = setter['deliveryDate']
            complete.append(setter['deliveryDate'])
        a['basis'] = setter['basis']
        a['limitingFactor'] = setter['limitingFactor']
        a['confidence'] = setter['confidence']
        models.append(a)
    order_complete = max(complete) if complete and all_dated else None
    return models, lines_out, order_complete


def _run_extra_lines(inputs, state, lines, tracer, label):
    """Allocate extra demand (a cart, or a not-yet-approved SO) after the
    backlog. → (per_line, errors)."""
    errors = []
    per_line = []
    var_values = {}
    for pid, qty in lines:
        if pid not in inputs.variants:
            errors.append({'odooProductId': pid, 'error': 'unknown_product'})
            continue
        n = int(round(qty or 0))
        if n <= 0:
            errors.append({'odooProductId': pid, 'error': 'invalid_quantity'})
            continue
        _trace_variant_header(inputs, state, pid, tracer)
        if tracer.enabled:
            tracer.line(f'  {label}  {n} unit(s) requested')
        results = []
        unit_vals = []
        for i in range(n):
            if tracer.enabled:
                tracer.line(f'  unit {i + 1}/{n}:')
            res = _allocate(inputs, state, pid, label.lower(), tracer, detail=True)
            _trace_dates(inputs, tracer, res)
            results.append(res)
            if tracer.enabled:
                uv = _strip(res)
                uv.update(res.get('_debug') or {})
                unit_vals.append(uv)
        per_line.append((pid, results))
        if tracer.enabled:
            var_values.setdefault(str(pid), _variant_values(inputs, state, pid, None))
            var_values[str(pid)].setdefault('cartUnits', []).extend(unit_vals)
    if tracer.enabled:
        tracer.values['variants'] = var_values
    return per_line, errors


def estimate_cart(inputs, lines, tracer=None):
    """lines: [(pid, qty)] in cart order. Unknown pids → 'errors'.
    Returns {'rate', 'models', 'lines', 'orderCompleteDate', 'errors'}."""
    tracer = tracer or NullTracer()
    rate, state = _prepare(inputs, tracer)
    per_line, errors = _run_extra_lines(inputs, state, lines, tracer, 'CART')
    models, lines_out, complete = _summarise(inputs, per_line)
    return {'rate': rate, 'models': models, 'lines': lines_out, 'errors': errors,
            'orderCompleteDate': complete}


def estimate_order(inputs, so_name, own_lines, tracer=None):
    """Estimate for an existing SO (Connect ask #4).

    Approved SO: it is already in the backlog, so its dates are the ones its
    own units got there — its place in the queue is real (inQueue True).
    Not approved yet: its undelivered lines (`own_lines`, [(pid, qty)]) are
    quoted at the back of the queue, like a cart (inQueue False)."""
    tracer = tracer or NullTracer()
    rate, state = _prepare(inputs, tracer)
    in_queue = so_name in state.backlog_results
    if in_queue:
        per_line = [(b.pid, results) for b, results in state.backlog_results[so_name]]
        errors = []
        if tracer.enabled:
            tracer.line(f'ORDER {so_name} is approved: dates are its own place in the queue')
            tracer.values['order'] = {
                'so': so_name, 'inQueue': True,
                'units': [dict(_strip(r), **(r.get('_debug') or {}), odooProductId=b.pid)
                          for b, results in state.backlog_results[so_name] for r in results]}
    else:
        if tracer.enabled:
            tracer.line(f'ORDER {so_name} is not approved: quoted at the back of the queue')
        per_line, errors = _run_extra_lines(inputs, state, own_lines, tracer, 'ORDER')
    models, lines_out, complete = _summarise(inputs, per_line)
    return {'rate': rate, 'inQueue': in_queue, 'models': models, 'lines': lines_out,
            'errors': errors, 'orderCompleteDate': complete}
