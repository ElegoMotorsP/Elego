# Dealer PO Delivery-Estimate API — Plan

> **Status:** first implementation in place (elego_connect v18.0.1.1.0). The engine is
> verified with 32 plain-pytest tests. The Odoo collector, controller and Odoo tests
> have **not yet run against a database**, because there is no local Odoo checkout.
> **Module:** `custom_modules/elego_connect` (extends the existing Elego Connect API)

### Implementation map

| Piece | File |
|---|---|
| Simulation engine (pure Python, no Odoo imports) | `elego_connect/models/delivery_engine.py` |
| ERP snapshot collector (`elegomotors.delivery.estimator`) | `elego_connect/models/delivery_estimator.py` |
| Settings fields (`x_de_*` on `res.company`) | `elego_connect/models/res_company_extension.py` |
| Approval timestamp `sale.order.x_approved_at` | `elego_connect/models/sale_order_extension.py` |
| Routes | `elego_connect/controllers/connect_delivery_api.py` |
| Settings screen (Elego Connect ▸ Delivery Estimate Settings) | `elego_connect/views/delivery_estimate_views.xml` |
| Engine tests: `python -m pytest tests/unit` | `tests/unit/test_delivery_engine.py` |
| Odoo tests: `--test-tags /elego_connect` | `elego_connect/tests/test_delivery_estimator.py` |

Differences from the plan below:
- A sub-assembly with its own *normal* BoM is treated as a plain component
  (stock + POs). It is not recursed into yet.
- Build lead time `produce_delay` and the QC/PDI and dispatch buffers are all
  counted in **working** days. Transit is calendar days.
- The approval-time queue key is the new `x_approved_at`. Orders approved
  before it existed fall back to `date_order`.
> **Odoo:** 18.0 Community on odoo.sh

---

## Context

When a dealer builds a PO in the Elego Connect app, they should see **when each
vehicle model can be delivered** before they submit. Today the catalogue
endpoint only exposes `atpQty = qty_available`
(`elego_connect/controllers/connect_catalogue_api.py`). That number is wrong
twice over: it ignores orders already accepted against that stock, and it says
nothing about *when* a unit will exist if there is none.

The estimate has to take into account:

| Input | Where it lives today |
|---|---|
| **FG stock** | `stock.quant` in `EGO/Finished Goods` (`data/stock_locations_data.xml`), with `stock.lot.x_blacklisted` (QC-failed) units left out |
| **Currently accepted POs** (backlog) | `sale.order` in state **`sale` only**, meaning approved by Accounts or MD, with undelivered `sale.order.line` qty. Orders still in `accepted` (`pending_approval = True`) are **not** counted. Dealer POs arrive as SOs through `create_from_connect_po` |
| **Work in progress** | `mrp.production` in `confirmed` / `progress` / `to_close` for bike templates (`x_is_ego_bike`) |
| **Production rate** | **Actual output over the last 15 working days**: done bike MOs (`mrp.production`, `state = done`, `x_is_ego_bike`) summed on `qty_produced` by `date_finished` (§1.1). The workcenter and routing figures are seed values and are not used. `mrp.bom.produce_delay` still sets build lead time |
| **Raw-material availability** | `stock.quant` of BOM components in internal locations, minus what open MOs have already reserved or will consume |
| **Material order delivery dates** | Open `purchase.order.line` (`product_qty − qty_received`, `date_planned`). CKD kit lines explode into components at `qty_per_kit` (`models/ckd_kit.py`, phantom kit BoM) |

---

## 1. Approach: one time-phased allocation simulation

Looking at each model separately gives wrong answers. Components such as the
frame, motor, controller and the CKD parts shared across kits are common to
several models, and the assembly line is one shared resource. So the estimator
simulates **all outstanding demand at once, in priority order**, against
time-phased supply, and then places the dealer's prospective order at the
**back of the queue**.

```
Supply timeline                       Demand queue (FIFO)
───────────────                       ───────────────────
FG on hand (per variant)  ── day 0    1. open SO lines, oldest first
WIP MOs  ── at date_finished          2. (quote only) the dealer's cart
Components on hand        ── day 0
Open PO lines  ── at date_planned
Production slots ── N units / working day
```

For each demand unit, in order:

1. **FG**: take a free FG unit of that variant if there is one. ETA = today.
2. **WIP**: otherwise take a free unit from an open MO for that variant.
   ETA = MO `date_finished` (or today + remaining lead time if that date has
   passed).
3. **New build**: otherwise schedule a build.
   - **Material date** = the earliest day on which *every* exploded component
     (`bom._explode()`, which handles phantom kits and variant-specific lines)
     has unconsumed supply. Supply is on-hand plus PO receipts up to that day.
     Consume the components.
   - **Capacity date** = the first production slot on or after the material
     date that still has room. The plant has N slots per working day, where N
     is the trailing production rate (§1.1). Working days come from the company
     `resource.calendar`. Slots are shared by every model.
   - **Ready date** = capacity date + build lead time + QC/PDI buffer.
4. **Dispatch date** = ready date + dispatch buffer.
   **Delivery date** = dispatch date + **2 days transit**, the same for every
   dealer (`x_de_transit_days`, default 2). These are calendar days, because
   trucks also run on non-working days.

**Granularity: the simulation runs per variant, the answers are per model.**
FG stock, backlog SO lines and CKD kits are all colour-specific, so the
simulation tracks each variant separately. Otherwise a red bike in stock would
be promised against a blue order. The API rolls the results up to the model
(`product.template`), as described in §4.

Running the backlog first is what puts "currently accepted POs" into the
estimate. Each **approved** order consumes FG, WIP, material and slots before
the new dealer order gets any. The queue is ordered by approval time (the
moment the SO entered `sale`, read from the state-change tracking), then by
`date_order`. Orders waiting for Accounts/MD approval do not hold stock or
slots.

> **Consequence to accept:** an estimate is optimistic by however many
> pending-approval orders get approved before this one. Two dealers quoting the
> same last FG unit both see "from stock" until one of them is approved. The
> confidence level does not try to model this.

### 1.1 Production rate: trailing 15 working days, fixed-rate fallback

The rate is normally the actual output of the last 15 working days. When that
window is unusual, for example a shutdown, a run of idle days, or MOs closed in
bulk, the estimator uses a **fixed planned rate** set by HQ instead.

```
window        = the last 15 working days before today (company resource.calendar;
                weekends and public holidays skipped, today excluded as it is partial)
produced      = Σ qty_produced of done bike MOs with date_finished in window
trailing_rate = produced / 15
idle_days     = working days in the window with zero bikes done
fixed_rate    = x_de_fixed_daily_rate            (HQ's planned bikes/day)

anomalous = idle_days      >  x_de_max_idle_days            (default 4)
         or trailing_rate  <  fixed_rate × x_de_anomaly_low_pct  / 100   (default 50)
         or trailing_rate  >  fixed_rate × x_de_anomaly_high_pct / 100   (default 150)

rate = fixed_rate     if x_de_rate_mode == 'fixed' or anomalous
       trailing_rate  otherwise
```

- **Why these anomaly checks.** Idle days catch a shutdown or stoppage even when
  the rest of the window was busy. The low band catches a slow fortnight that
  would otherwise push every date far out. The high band catches MOs being
  marked done in bulk, which would make the line look faster than it is.
- **Override.** `x_de_rate_mode = fixed` forces the fixed rate, e.g. during a
  planned shutdown or right after go-live before 15 days of history exist.
  The default is `auto`.
- **Fixed rate is required** before the API returns new-build dates. If it is
  not set and the trailing window is anomalous, new-build lines return
  `estimatedDate: null`, `reason: rate_not_configured`, rather than guessing.
- **The response does not include the rate or why it was chosen.** The rate,
  whether it was trailing or fixed, and what caused a fallback go only into the
  internal `elegomotors.connect.api.log` summary, for debugging.
- **Confidence.** A fallback alone doesn't lower confidence, since the fixed
  rate is a deliberate planning figure. Material and PO rules still apply.

- **Plant-wide, not per model.** The line builds whatever is scheduled, so the
  past model mix says little about future capacity. One shared rate feeds the
  shared slots.
- **Fractional rates are fine.** 2.4/day means slots fill 2, 3, 2, 3, 2... The
  simulation carries the fraction over between days instead of rounding each
  day.
- **Counted at MO done, not at QC pass.** QC and PDI are covered by their own
  buffer. Units that later fail QC still used line time.
- **Known bias.** Past output was also held back by past material shortages,
  so the trailing rate can understate what the line can do. The simulation
  then counts material twice: once inside the rate and once as an explicit
  constraint. That pushes estimates late, which is the safer direction. A
  severe case trips the low band and falls back to the fixed rate anyway.
- Calculated once per request with a single `read_group` grouped by day. That
  gives both `produced` and `idle_days`.

**Avoiding double-counting:** use *total* FG (reserved and unreserved) and
*total* undelivered backlog. Subtracting reservations as well would count
accepted orders twice. In the same way, components already reserved for or
consumed by WIP MOs are taken off on-hand before the simulation starts, because
WIP output is counted as supply in its own right.

### Edge rules

| Situation | Rule |
|---|---|
| PO line overdue (`date_planned` < today, not received) | Treat it as arriving today + `overdue_slip_days` (config, default 7). Mark the result `confidence: low` |
| Component short with no open PO at all | Fall back to today + vendor lead time (`product.supplierinfo.delay` of the first seller) + `procurement_buffer_days`. Mark `confidence: low`, `reason: material_not_on_order` |
| Component short with no seller either | Return `estimatedDate: null`, `reason: unavailable` |
| Incoming QC rejects | Optional yield factor on PO supply (config `incoming_yield_pct`, default 100). A historical rate from `po_tracking` could replace it later |
| Sub-assembly with its own *normal* BoM (e.g. a battery pack built in-house) | Use sub-assembly stock first, then recurse into its components and add its `produce_delay` |
| Horizon | Stop at 365 days. Anything beyond that returns `null` / `beyond_horizon` |
| No BoM for a variant | `null`, `reason: no_bom` (logged so HQ can fix the data) |

The simulation reads data only. It never reserves or writes anything.

---

## 2. Code layout (in `elego_connect`)

```
elego_connect/
├── models/
│   ├── delivery_estimator.py       elegomotors.delivery.estimator (AbstractModel)
│   │     _collect_supply()  _collect_backlog()  _simulate(extra_demand)
│   │     estimate_catalogue()  estimate_cart(lines, partner)
│   └── res_company_extension.py    capacity / buffer config fields
├── controllers/
│   └── connect_delivery_api.py     2 routes, same bearer auth as the rest
├── views/res_config_settings_views.xml   "Delivery Estimates" settings block
└── tests/test_delivery_estimator.py
```

The estimator is an `AbstractModel` with no HTTP code, following the
`vehicle_lookup.py` pattern. That makes it unit-testable, and the backend can
reuse it (§6).

---

## 3. Configuration (new fields)

On `res.company`, shown in Settings ▸ Manufacturing ▸ Delivery Estimates
(admin only):

| Field | Default | Purpose |
|---|---|---|
| `x_de_rate_mode` | `auto` | `auto` = trailing rate with fixed fallback. `fixed` = always use the fixed rate (§1.1) |
| `x_de_rate_window_days` | 15 | Working days of done MOs averaged for the trailing rate |
| `x_de_fixed_daily_rate` | — (required) | HQ's planned bikes per working day, used for fallback and fixed mode |
| `x_de_max_idle_days` | 4 | More zero-output working days than this in the window counts as an anomaly |
| `x_de_anomaly_low_pct` | 50 | A trailing rate below this % of the fixed rate counts as an anomaly |
| `x_de_anomaly_high_pct` | 150 | A trailing rate above this % of the fixed rate counts as an anomaly |
| `x_de_qc_pdi_buffer_days` | 1 | Mark-as-Done → QC pass → FG transfer → PDI |
| `x_de_dispatch_buffer_days` | 1 | FG → loaded on truck |
| `x_de_overdue_slip_days` | 7 | Slip assumed for overdue PO lines |
| `x_de_procurement_buffer_days` | 3 | Added to vendor lead time for material that is not yet on order |
| `x_de_incoming_yield_pct` | 100 | Expected share of incoming parts that pass QC |
| `x_de_transit_days` | 2 | Fixed dispatch → dealer transit, calendar days, the same for all dealers |

Build lead time comes from the existing `mrp.bom.produce_delay`.

---

## 4. API

Both routes use `require_connect_bearer_token()` and `log_connect_call()` from
`controllers/connect_auth.py`, use the same JSON helpers, and follow the same
200-with-error-body convention.

### 4.1 `GET /elegomotors/connect/delivery-estimates`

Gives one row per bike **model**: the date a single unit ordered now would
arrive, placed at the back of the current backlog. The catalogue / PO-builder
screen shows this.

The model's date is the **earliest** across its colours ("from 2 Dec"). A
dealer who picks a specific colour gets that colour's exact date from §4.2.

```json
{
  "asOf": "2026-11-28T10:15:00+05:30",
  "items": [
    {
      "odooTemplateId": 12,
      "model": "Elego 1.1",
      "freeStockQty": 3,
      "estimatedDispatchDate": "2026-11-29",
      "estimatedDeliveryDate": "2026-12-01",
      "leadDays": 3,
      "basis": "fg_stock",
      "confidence": "high"
    },
    {
      "odooTemplateId": 15,
      "model": "Elego 2.0+",
      "freeStockQty": 0,
      "estimatedDispatchDate": "2026-12-19",
      "estimatedDeliveryDate": "2026-12-21",
      "leadDays": 23,
      "basis": "new_build",
      "limitingFactor": "material",
      "confidence": "medium"
    }
  ]
}
```

`freeStockQty` = FG minus approved backlog, summed across the model's colours
and floored at 0 per colour. It replaces the catalogue's current `atpQty`.
`basis`, `limitingFactor` and `confidence` describe the variant that set the
date.

### 4.2 `POST /elegomotors/connect/delivery-estimates/quote`

Gives an estimate for a whole cart. Lines in the cart compete with each other
for the same material and slots, so this is **not** the sum of per-line
lookups.

The request lines are variants, because that is what a PO line is and what
`orders/confirm` already takes. The response groups them **per model**.

```json
// request
{ "lines": [ {"odooProductId": 41, "quantity": 6},     // Elego 1.1 Red
             {"odooProductId": 42, "quantity": 4},     // Elego 1.1 Blue
             {"odooProductId": 44, "quantity": 5} ] }  // Elego 2.0+ Blue
// response
{
  "asOf": "...",
  "models": [
    { "odooTemplateId": 12, "model": "Elego 1.1", "quantity": 10,
      "fromStock": 3, "fromProduction": 7,
      "firstUnitDate": "2026-12-01", "lastUnitDate": "2026-12-11",
      "basis": "new_build", "limitingFactor": "capacity", "confidence": "high" }
  ],
  "orderCompleteDate": "2026-12-21"
}
```

A model's `lastUnitDate` is the latest date across its colours in the cart, and
`limitingFactor` / `confidence` come from the line that set it. All dates
include the 2-day transit.

**Coarse reason only.** Dealers see `limitingFactor`, one of
`stock | wip | capacity | material | material_not_on_order`, and nothing finer.
The response **never names components, suppliers or POs**. That detail goes to
the internal log and backend view only.

### 4.3 Debug trace (development only)

While the estimator is being built and tuned, both endpoints can return the
full working behind every date: each input value, each formula, and each
decision.

**Two switches, both required:**

| Switch | Where | Default |
|---|---|---|
| `elego_connect.delivery_estimate_debug` | System parameter (Settings ▸ Technical ▸ System Parameters) | unset = **off** |
| `debug=1` | Request: query string on the GET, `"debug": true` in the POST body | off |

If the parameter is off, `debug` in the request is silently ignored and the
response is byte-for-byte the normal one. The parameter is server-side, so a
dealer app build can't turn it on, and production stays clean even if the app
ships with the flag set. On odoo.sh, set it on dev and staging branches only.

> **Why the extra gate:** the trace deliberately breaks the §4.2 rule. It names
> components, PO numbers, SO numbers and expected supplier dates. It must never
> be reachable from production.

**Shape.** When on, the response gains a `debug` object with two views of the
same calculation: `trace` for reading and `values` for checking in scripts or
tests.

```json
"debug": {
  "trace": [
    "RATE  window 2026-11-07..2026-11-27 (15 working days, today excluded)",
    "RATE  produced = 38 bikes; idle days = 2",
    "RATE  trailing = 38 / 15 = 2.53/day",
    "RATE  checks: idle 2 <= 4 OK; 2.53 >= 50% x 3.00 = 1.50 OK; 2.53 <= 150% x 3.00 = 4.50 OK",
    "RATE  -> using trailing 2.53/day",
    "QUEUE approved backlog ahead: 41 units across 9 SOs (oldest SO/0031, approved 2026-11-02)",
    "Elego 2.0+ Blue (product 44):",
    "  FG    on hand 4 (1 blacklisted excluded) = 3 usable",
    "  FG    backlog for this colour 6 (SO/0031 x2, SO/0038 x4) -> free 3 - 6 = 0",
    "  WIP   MO/0107 x2 due 2026-12-03 -> taken by SO/0038",
    "  BUILD need 1; components (BoM 'Elego 2.0+ Blue', exploded 34 lines):",
    "        Controller 48V   need 1 | on hand 0 | P00412 +20 on 2026-12-12 -> 2026-12-12",
    "        Hub motor 1.2kW  need 1 | on hand 7 after backlog -> today",
    "        ... (32 more covered today)",
    "  BUILD material date = max(component dates) = 2026-12-12 (Controller 48V)",
    "  BUILD capacity: 37 units queued before this one at 2.53/day -> first free slot 2026-12-15",
    "  BUILD start = max(2026-12-12, 2026-12-15) = 2026-12-15",
    "  READY 2026-12-15 + produce_delay 7 wd + QC/PDI 1 wd = 2026-12-25",
    "  SHIP  2026-12-25 + dispatch 1 wd = 2026-12-26",
    "  DELIV 2026-12-26 + transit 2 cd = 2026-12-28",
    "  RESULT basis=new_build limitingFactor=capacity confidence=medium",
    "Elego 2.0+ -> earliest colour Red 2026-12-21 (Blue 2026-12-28)"
  ],
  "values": {
    "rate": { "windowStart": "2026-11-07", "windowEnd": "2026-11-27",
              "produced": 38, "idleDays": 2, "trailing": 2.53, "fixed": 3.0,
              "lowBound": 1.5, "highBound": 4.5, "mode": "auto",
              "anomaly": null, "used": 2.53, "source": "trailing" },
    "config": { "qcPdiBufferDays": 1, "dispatchBufferDays": 1, "transitDays": 2,
                "overdueSlipDays": 7, "procurementBufferDays": 3, "incomingYieldPct": 100 },
    "variants": {
      "44": { "fgOnHand": 4, "fgBlacklisted": 1, "backlogQty": 6,
              "backlogLines": [ {"so": "SO/0031", "qty": 2, "approvedAt": "..."} ],
              "wipTaken": [ {"mo": "MO/0107", "qty": 2, "due": "2026-12-03", "takenBy": "SO/0038"} ],
              "components": [ {"product": "Controller 48V", "need": 1, "onHand": 0,
                               "receipts": [ {"po": "P00412", "qty": 20, "date": "2026-12-12", "overdue": false} ],
                               "coveredOn": "2026-12-12"} ],
              "materialDate": "2026-12-12", "bottleneck": "Controller 48V",
              "queuedBefore": 37, "slotDate": "2026-12-15",
              "readyDate": "2026-12-25", "dispatchDate": "2026-12-26",
              "deliveryDate": "2026-12-28", "basis": "new_build",
              "limitingFactor": "capacity", "confidence": "medium" }
    }
  }
}
```

Rules:

- **Use the same code path, not a copy.** The simulation takes a `tracer`
  object. Normally it is a no-op. In debug it records each step as it happens,
  so the trace can't drift away from the logic it describes.
- **Show the full component list only for the component that set the date,
  and for any component that isn't covered today.** Components covered today
  collapse to a count (`... 32 more covered today`). `values.components` keeps
  them all.
- **Units are explicit**: `wd` = working days, `cd` = calendar days.
- **Quote endpoint:** traces each cart line after the backlog and shows what
  earlier cart lines consumed. That is the only way to see why line 2 is later
  than line 1.
- **Cap:** at most 2,000 trace lines. Past that the trace is cut off with
  `"... truncated"` and `values` stays complete.
- Debug calls are logged with `debug=1` in the log summary, so it is easy to
  check they stopped once development ends.

### 4.4 Recording the promise

When the PO is later submitted through `POST /elegomotors/connect/orders/confirm`,
accept an optional `promisedDate` and write it to the standard
`sale.order.commitment_date`. That gives HQ promise-vs-actual tracking. The
queue stays ordered by approval time (§1), so a promise can't jump the queue.

---

## 5. Performance

The backlog is hundreds of units at most and each BoM has about 30–60 lines,
so a full simulation is a few thousand dict operations after roughly 6 batched
`read_group` / `search_read` calls. Run it **live on every request**. Don't
loop the ORM per unit: prefetch quants, PO lines, MOs, SO lines and the
exploded BoMs once, then simulate in plain Python.

If profiling shows more than about 500 ms, add a snapshot model refreshed by a
cron every 15 minutes. Cache in the database, not in process memory, because
odoo.sh runs several workers. Hold this until it is shown to be needed.

---

## 6. Backend visibility (optional, same estimator)

- A **"Delivery Estimates"** list under Sales ▸ Reporting showing the §4.1
  output plus the internal detail: the blocking component and the PO it is
  waiting on.
- An "Estimated delivery" banner on the quotation form, using the
  `estimate_cart()` result for that order's lines. It helps the sales team
  quote retail orders the same way.

---

## 7. Tests (`tests/test_delivery_estimator.py`)

Estimator (unit, no HTTP):
1. FG covers the request → today + buffers, `basis=fg_stock`.
2. FG exists but all of it is taken by accepted SOs → falls through to WIP or build.
3. A pending-approval SO (`accepted`) is ignored. The same order once approved (`sale`) takes stock first. Queue order follows approval time, not order date.
4. A blacklisted lot in FG is not counted.
5. A WIP MO supplies units at its `date_finished`.
6. Component short, PO arriving on day 10 → build on day 10 or later.
7. A CKD kit PO line explodes into components at `qty_per_kit`.
8. A component shared between two models: the older SO of model A starves the
   new order for model B.
9. Capacity-bound: no material shortage, 75 bikes done in the last 15 working days (rate 5/day), backlog of 50 → about 10 working days, skipping non-working days.
9a. Rate window: the window covers exactly the last 15 working days, and today's output is left out. An MO finished on a weekend or holiday that falls inside the window still counts. The divisor stays 15.
9b. Fractional rate (2.4/day) fills slots 2, 3, 2, 3, 2 rather than 2 every day.
9c. Fallback to the fixed rate, one case per trigger: 6 idle days (`idle_days`), trailing 1/day against fixed 4 (`below_band`), trailing 9/day against fixed 4 (`above_band`). In each case the estimator uses the fixed rate, checked on the estimator's return value rather than the API response.
9d. A normal window inside the band and under the idle limit → the trailing rate is used.
9e. `x_de_rate_mode = fixed` → the fixed rate is used even when the window is normal.
9f. Fixed rate not set and window anomalous → new-build lines return `null` / `rate_not_configured`, while stock and WIP lines still get dates.
10. Overdue PO line → slip applied, `confidence=low`.
11. No PO and no seller → `null`, `reason=unavailable`.
12. Cart lines compete with each other (the quote differs from the sum of single lookups).
12a. Per-model rollup: in the catalogue, a model with Red in stock and Blue on a new build shows the Red date. In a quote with both colours, the model shows the Blue date as `lastUnitDate`.
12b. Red stock is never used for a Blue backlog line or a Blue cart line.
12c. Transit: delivery = dispatch + 2 calendar days, including across a weekend.
13. Read-only guarantee: patch `create`/`write` on stock/mrp/purchase/sale models to fail, then run every branch (same technique as `test_lookup_never_writes_erp_data`).

HTTP: auth required, malformed body → 400, unknown product → per-line error at
HTTP 200, responses keyed by `odooTemplateId`, response contains no component,
supplier or PO names, call logged.

Debug (§4.3):
- Parameter unset plus `debug=1` → response identical to a non-debug call, no `debug` key.
- Parameter on, no `debug=1` → no `debug` key.
- Parameter on plus `debug=1` → `debug.trace` and `debug.values` present. Every
  date in `values` equals the matching date in the normal response, and the
  rate values reproduce `used`.
- Turning the tracer on does not change any estimate (same inputs, debug on
  vs off → identical non-debug fields).

---

## 8. Rollout

1. Build the estimator and tests, then validate against a copy of the live DB.
   For a handful of recent SOs, compare what the estimator would have said with
   what actually happened.
2. **Data clean-up first.** The estimate is only as good as `date_planned` on
   open POs, BoM completeness for all 7 models, and MOs being marked done on the
   day the bikes are actually built. A backlog of MOs closed in bulk would
   distort the trailing rate.
   Ship a backend report of open PO lines with past `date_planned` so Purchase
   (Prashant) can correct them.
3. Expose the API, then the app shows it in the PO builder (app repo, separate
   ticket). Use the debug trace (§4.3) on dev and staging to tune buffers and
   thresholds against real data.
4. **Before go-live:** confirm `elego_connect.delivery_estimate_debug` is unset
   on production. Check the request log for any debug calls there.
5. Later: wire `promisedDate` → `commitment_date`, and the backend banner.

---

## Decisions (2026-11-28)

- **Production rate** comes from actual output over the trailing 15 working
  days. If that window is anomalous (idle days, or outside 50–150 % of plan), it
  falls back to a fixed planned rate, and HQ can force the fixed rate (§1.1).
- **Only approved SOs** (`sale`) count toward the backlog. Pending-approval
  orders are ignored.
- **The rate used and why are not exposed** in the API. They are internal log only.
- **Per-model display.** The simulation still tracks each colour separately for
  correctness (§1).
- **Transit** is a fixed 2 calendar days for every dealer.
- **Dealers see a date plus a coarse reason** (`limitingFactor`).
- **A debug trace** of every formula value is available during development
  behind a server-side system parameter plus a request flag (§4.3). It must be
  off in production.

No open decisions remain. Next step is implementation (§8).
