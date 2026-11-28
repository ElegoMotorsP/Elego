# -*- coding: utf-8 -*-
"""Delivery-estimate collector: reads one snapshot of the ERP and hands it to
the pure-Python engine (delivery_engine.py). See
doc/delivery-estimate-api-plan.md.

Read-only by design: everything here is search / read. No reservation, no
write, no procurement. Queries are batched up front (about a dozen in total,
not one per bike) and the simulation runs in plain Python on the result.

Where each engine input comes from:

  variants      product.product of templates with x_is_ego_bike, active,
                sale_ok — the same set the catalogue endpoint lists.
  fg_usable     stock.quant under EGO/Finished Goods; lots flagged
                x_blacklisted (QC fail) are counted separately and NOT usable.
  backlog       sale.order.line of APPROVED orders only (state 'sale' and
                pending_approval False), undelivered qty. Queue key is
                x_approved_at, falling back to date_order for orders approved
                before that field existed.
  wip           open bike MOs (confirmed / progress / to_close), qty not yet
                produced, due on date_finished.
  bom           mrp.bom.explode() for the variant — phantom kits flattened,
                variant-specific lines applied. Storable components only.
  components    on hand in internal locations (quarantine excluded), minus the
                still-open raw-material demand of every open MO (WIP output is
                counted as supply in its own right, so its parts are spoken for).
  receipts      open purchase.order.line (x_qty_remaining > 0). A CKD / kit
                line is exploded through its phantom BoM into per-component
                receipts. Dated on date_planned.
  daily_output  done bike MOs per local day (qty_produced by date_finished).
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

from . import delivery_engine as E

_logger = logging.getLogger(__name__)

DEBUG_PARAM = 'elego_connect.delivery_estimate_debug'

# Per-worker cache of exploded BoMs (see _de_explode). Not shared state:
# each worker keeps its own copy and rebuilds it on any miss.
_EXPLODE_CACHE = {}
_EXPLODE_TTL = 600          # seconds
_EXPLODE_MAX = 5000         # entries; cleared wholesale beyond this
OPEN_MO_STATES = ('confirmed', 'progress', 'to_close')
DEFAULT_TZ = 'Asia/Kolkata'


class DeliveryEstimator(models.AbstractModel):
    _name = 'elegomotors.delivery.estimator'
    _description = 'Dealer PO delivery-time estimator'

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @api.model
    def debug_enabled(self):
        value = self.env['ir.config_parameter'].sudo().get_param(DEBUG_PARAM, '')
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    @api.model
    def estimate_catalogue(self, debug=False):
        """→ (result dict, tracer or None)."""
        tracer = E.Tracer() if debug else None
        result = E.estimate_catalogue(self._de_snapshot(), tracer)
        return result, tracer

    @api.model
    def estimate_cart(self, lines, debug=False):
        """lines: [(product_id, qty)] → (result dict, tracer or None)."""
        tracer = E.Tracer() if debug else None
        result = E.estimate_cart(self._de_snapshot(), lines, tracer)
        return result, tracer

    @api.model
    def estimate_order(self, order, debug=False):
        """Estimate for an existing SO → (result dict, tracer or None).
        result also carries 'outstanding': False when no bike is left to
        deliver on it."""
        order = order.sudo()
        snapshot = self._de_snapshot()
        own_lines = []
        for line in order.order_line:
            if line.display_type or line.product_id.id not in snapshot.variants:
                continue
            remaining = line.product_uom._compute_quantity(
                line.product_uom_qty - line.qty_delivered, line.product_id.uom_id)
            if remaining > 1e-6:
                own_lines.append((line.product_id.id, remaining))
        tracer = E.Tracer() if debug else None
        if not own_lines:
            result = {'rate': {}, 'inQueue': False, 'models': [], 'lines': [],
                      'errors': [], 'orderCompleteDate': None}
        else:
            result = E.estimate_order(snapshot, order.name, own_lines, tracer)
        result['outstanding'] = bool(own_lines)
        return result, tracer

    @api.model
    def now_local(self):
        return datetime.now(pytz.timezone(self._de_tz_name()))

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    @api.model
    def _de_snapshot(self):
        estimator = self.sudo()
        env = estimator.env
        company = env.company
        today = estimator.now_local().date()
        calendar = estimator._de_calendar(company, today)
        config = estimator._de_config(company)

        variants_rs = env['product.product'].search([
            ('product_tmpl_id.x_is_ego_bike', '=', True),
            ('active', '=', True),
            ('sale_ok', '=', True),
        ])
        variants, component_ids = estimator._de_variants(variants_rs)
        estimator._de_fg_stock(variants, variants_rs)

        window_days = int(config.get('rate_window_days') or 15)
        window = calendar.previous_working_days(today, window_days)
        daily_output = estimator._de_daily_output(window[0] if window else today, today)

        return E.EstimateInputs(
            today=today,
            calendar=calendar,
            config=config,
            daily_output=daily_output,
            variants=variants,
            backlog=estimator._de_backlog(variants_rs),
            wip=estimator._de_wip(variants_rs),
            components=estimator._de_components(component_ids, today),
        )

    # ------------------------------------------------------------------
    # Pieces
    # ------------------------------------------------------------------

    def _de_tz_name(self):
        return (self.env.user.tz or self.env.company.partner_id.tz or DEFAULT_TZ)

    def _de_local_date(self, dt):
        if not dt:
            return None
        if not isinstance(dt, datetime):
            return dt                       # already a date
        return pytz.utc.localize(dt).astimezone(pytz.timezone(self._de_tz_name())).date()

    def _de_config(self, company):
        return {
            'rate_mode': company.x_de_rate_mode or 'auto',
            'rate_window_days': company.x_de_rate_window_days or 15,
            'fixed_daily_rate': company.x_de_fixed_daily_rate or 0.0,
            'max_idle_days': company.x_de_max_idle_days,
            'anomaly_low_pct': company.x_de_anomaly_low_pct,
            'anomaly_high_pct': company.x_de_anomaly_high_pct,
            'qc_pdi_buffer_days': company.x_de_qc_pdi_buffer_days,
            'dispatch_buffer_days': company.x_de_dispatch_buffer_days,
            'transit_days': company.x_de_transit_days,
            'overdue_slip_days': company.x_de_overdue_slip_days,
            'procurement_buffer_days': company.x_de_procurement_buffer_days,
            'incoming_yield_pct': company.x_de_incoming_yield_pct or 100.0,
        }

    def _de_calendar(self, company, today):
        cal = company.resource_calendar_id
        weekdays = set()
        if cal:
            for att in cal.attendance_ids:
                if getattr(att, 'display_type', False):
                    continue                # section lines of two-week calendars
                weekdays.add(int(att.dayofweek))
        holidays = set()
        if cal:
            start = datetime.combine(today - timedelta(days=60), datetime.min.time())
            end = datetime.combine(today + timedelta(days=E.HORIZON_DAYS + 30), datetime.min.time())
            leaves = self.env['resource.calendar.leaves'].search([
                ('resource_id', '=', False),
                ('calendar_id', 'in', [cal.id, False]),
                ('date_to', '>=', start),
                ('date_from', '<=', end),
            ])
            for leave in leaves:
                d = self._de_local_date(leave.date_from)
                last = self._de_local_date(leave.date_to)
                while d and last and d <= last:
                    holidays.add(d)
                    d += timedelta(days=1)
        return E.WorkCalendar(weekdays or (0, 1, 2, 3, 4), holidays)

    def _de_variants(self, variants_rs):
        Bom = self.env['mrp.bom']
        bom_by_product = Bom._bom_find(variants_rs, bom_type='normal') if variants_rs else {}
        variants = {}
        component_ids = set()
        for product in variants_rs:
            colour = ', '.join(product.product_template_attribute_value_ids.mapped('name'))
            bom = bom_by_product.get(product) if bom_by_product else None
            bom_qty = None
            if bom:
                bom_qty = self._de_explode(bom, product, 1.0)
                component_ids.update(bom_qty)
            variants[product.id] = E.Variant(
                pid=product.id,
                tmpl_id=product.product_tmpl_id.id,
                model=product.product_tmpl_id.name,
                colour=colour,
                bom=bom_qty,
                bom_name=bom.display_name if bom else '',
                produce_delay=int(bom.produce_delay or 0) if bom else 0,
            )
        return variants, component_ids

    def _de_explode(self, bom, product, qty):
        """{component product id: qty in its own UoM} for `qty` units of
        `product` (in the BoM's UoM). Phantom kits are flattened by explode().

        explode() is ~90% of a snapshot's cost (118-line BoMs x ~45 variants),
        so the per-unit result is cached per worker. The key carries the
        write_date of the BoM, its lines and the variant, so any edit to them
        misses the cache; entries also expire after _EXPLODE_TTL to catch
        edits to nested kit BoMs. Pure derived data: a stale or missing entry
        only costs a recompute."""
        line_stamp = max(bom.bom_line_ids.mapped('write_date') or [None], default=None)
        key = (self.env.cr.dbname, bom.id, product.id,
               str(bom.write_date), str(line_stamp), str(product.write_date))
        now = time.monotonic()
        hit = _EXPLODE_CACHE.get(key)
        if hit and now - hit[0] < _EXPLODE_TTL:
            per_unit = hit[1]
        else:
            _boms, lines = bom.explode(product, 1.0 / (bom.product_qty or 1.0))
            acc = defaultdict(float)
            for bom_line, line_data in lines:
                comp = bom_line.product_id
                if not comp.is_storable:
                    continue
                acc[comp.id] += bom_line.product_uom_id._compute_quantity(line_data['qty'], comp.uom_id)
            per_unit = dict(acc)
            if len(_EXPLODE_CACHE) > _EXPLODE_MAX:
                _EXPLODE_CACHE.clear()
            _EXPLODE_CACHE[key] = (now, per_unit)
        return {cid: q * qty for cid, q in per_unit.items()}

    def _de_fg_stock(self, variants, variants_rs):
        fg_loc = self.env.ref('elegomotors_setup.location_ego_fg', raise_if_not_found=False)
        if not fg_loc or not variants_rs:
            return
        quants = self.env['stock.quant'].search([
            ('location_id', 'child_of', fg_loc.id),
            ('product_id', 'in', variants_rs.ids),
        ])
        for q in quants:
            v = variants.get(q.product_id.id)
            if not v:
                continue
            if q.lot_id and q.lot_id.x_blacklisted:
                v.fg_blacklisted += q.quantity
            else:
                v.fg_usable += q.quantity

    def _de_backlog(self, variants_rs):
        if not variants_rs:
            return []
        lines = self.env['sale.order.line'].search([
            ('order_id.state', '=', 'sale'),
            ('order_id.pending_approval', '=', False),
            ('product_id', 'in', variants_rs.ids),
            ('display_type', '=', False),
        ])
        out = []
        for line in lines:
            remaining = line.product_uom_qty - line.qty_delivered
            remaining = line.product_uom._compute_quantity(remaining, line.product_id.uom_id)
            if remaining <= 1e-6:
                continue
            order = line.order_id
            out.append(E.BacklogLine(
                so=order.name, pid=line.product_id.id, qty=remaining,
                approved_at=fields.Datetime.to_string(order.x_approved_at or order.date_order),
            ))
        return out

    def _de_wip(self, variants_rs):
        if not variants_rs:
            return []
        mos = self.env['mrp.production'].search([
            ('state', 'in', OPEN_MO_STATES),
            ('product_id', 'in', variants_rs.ids),
        ])
        out = []
        for mo in mos:
            remaining = mo.product_qty - mo.qty_produced
            if remaining <= 1e-6:
                continue
            out.append(E.WipOrder(mo=mo.name, pid=mo.product_id.id, qty=remaining,
                                  due=self._de_local_date(mo.date_finished)))
        return out

    def _de_daily_output(self, start, today):
        tz = pytz.timezone(self._de_tz_name())
        start_utc = tz.localize(datetime.combine(start, datetime.min.time())) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        rows = self.env['mrp.production'].search_read([
            ('state', '=', 'done'),
            ('product_id.product_tmpl_id.x_is_ego_bike', '=', True),
            ('date_finished', '>=', start_utc),
        ], ['date_finished', 'qty_produced'])
        out = defaultdict(float)
        for row in rows:
            d = self._de_local_date(row['date_finished'])
            if d and d < today:
                out[d] += row['qty_produced'] or 0.0
        return dict(out)

    def _de_components(self, component_ids, today):
        if not component_ids:
            return {}
        Product = self.env['product.product']
        products = Product.browse(sorted(component_ids))

        # On hand: internal locations, quarantine excluded.
        on_hand = defaultdict(float)
        domain = [('product_id', 'in', products.ids), ('location_id.usage', '=', 'internal')]
        quarantine = self.env.ref('elegomotors_setup.location_ego_quarantine', raise_if_not_found=False)
        if quarantine:
            domain += ['!', ('location_id', 'child_of', quarantine.id)]
        for product, qty in self.env['stock.quant']._read_group(domain, ['product_id'], ['quantity:sum']):
            on_hand[product.id] += qty or 0.0

        # Spoken for: open raw-material demand of every open MO.
        moves = self.env['stock.move'].search([
            ('raw_material_production_id.state', 'in', OPEN_MO_STATES),
            ('state', 'not in', ('done', 'cancel')),
            ('product_id', 'in', products.ids),
        ])
        for mv in moves:
            on_hand[mv.product_id.id] -= mv.product_qty

        receipts = self._de_receipts(set(products.ids))

        out = {}
        for p in products:
            seller = p.seller_ids[:1]
            out[p.id] = E.Component(
                pid=p.id, name=p.display_name, on_hand=on_hand.get(p.id, 0.0),
                receipts=receipts.get(p.id, []),
                seller_delay=int(seller.delay) if seller else None,
            )
        return out

    def _de_receipts(self, component_ids):
        lines = self.env['purchase.order.line'].search([
            ('order_id.state', 'in', ('purchase', 'done')),
            ('display_type', '=', False),
            ('x_qty_remaining', '>', 0),
        ])
        out = defaultdict(list)
        kit_candidates = lines.filtered(lambda l: l.product_id.id not in component_ids).mapped('product_id')
        kit_boms = self.env['mrp.bom']._bom_find(kit_candidates, bom_type='phantom') if kit_candidates else {}
        for line in lines:
            product = line.product_id
            when = self._de_local_date(line.date_planned)
            if not when:
                continue
            remaining = line.product_uom._compute_quantity(line.x_qty_remaining, product.uom_id)
            ref = line.order_id.name
            if product.id in component_ids:
                out[product.id].append(E.Receipt(when, remaining, ref))
                continue
            kit = kit_boms.get(product) if kit_boms else None
            if not kit:
                continue
            for comp_id, qty in self._de_explode(kit, product, remaining).items():
                if comp_id in component_ids:
                    out[comp_id].append(E.Receipt(when, qty, f'{ref} (kit {product.display_name})'))
        return out
