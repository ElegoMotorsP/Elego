# Sales Order (SO) Process — ElegoMotors

## Overview
Sales Orders require **approval from either Rajshri (Accounts) or Manohar (MD)** before they are confirmed and reach the Store.
Tushar (Sales) raises the order; any one approver signing off is sufficient to confirm.

---

## Roles & Permissions

| Person | Login | Role | SO Permission |
|--------|-------|------|--------------|
| Tushar | leads@elegomotors.com | Sales | Creates Quotations / SOs (`sale_salesman`). Cannot approve. |
| Rajshri | elegoac@gmail.com | Accounts | Approves (Accounts) only. Cannot create SOs (`group_sale_approver` blocks creation). |
| Manohar | manohar.kalbhor@elegomotors.com | MD / Admin | Approves (MD) only. Cannot see Accounts approval button. |
| Amit | storeelegomotors@gmail.com | Store | Read-only view of confirmed SOs (`group_sale_viewer`). No approval buttons. |

---

## Step-by-Step Flow

### Step 1 — Tushar: Create Quotation
- Navigate: Sales → Orders → New
- Fill: Customer, Product (ElegoMotors EV Scooter EGO-S1), Quantity
- Click **Confirm**
- **Result:** SO stays in **Draft / Quotation** state (`pending_approval = True`)
- Chatter posts: *"This Sales Order is awaiting your approval…"* — Rajshri and Manohar are @mentioned

### Step 2 — Rajshri OR Manohar: Approve
Either approver can independently confirm the SO — only one approval is needed.

**Option A — Rajshri: Approve (Accounts)**
- Open the SO (she is auto-subscribed as a follower; inbox notification sent)
- Button visible: **Approve (Accounts)** (green) — only visible to `group_sale_approver`
- Click it
- **Result:** `approval_accounts = True` → SO state changes to **Sales Order** (`sale`)

**Option B — Manohar: Approve (MD)**
- Open the same SO (he is also auto-subscribed; inbox notification sent)
- Button visible: **Approve (MD)** (green) — only visible to `base.group_erp_manager`
- Click it
- **Result:** `approval_manohar = True` → SO state changes to **Sales Order** (`sale`)

In both cases:
- Chatter records the individual approval
- Existing automation `auto_so_confirmed` fires → Tushar and Amit are notified: *"Sales Order Confirmed — verify FG availability"*

### Step 4 — Store Check (Amit)
- Amit receives notification and checks `EGO/Finished Goods` stock
- If FG available → proceed to Delivery
- If FG not available → raise a Manufacturing Order

---

## Rejection Flow

Either Rajshri **or** Manohar can reject at any point while the SO is pending.

- Button visible: **Reject Order** (red) — visible to both approvers when `pending_approval = True`
- Clicking shows a confirmation dialog
- **Result:**
  - `pending_approval`, `approval_accounts`, `approval_manohar` all reset to `False`
  - SO state reset to **Draft** (cancel → draft)
  - Chatter records *"Sales Order rejected by {name} — returned to draft"*
- Tushar can re-confirm the SO, which re-triggers the approval flow from scratch

---

## Re-confirm After Rejection
- Tushar opens the rejected (Draft) SO
- Clicks **Confirm** again
- Flow restarts from Step 1 — one approval required again

---

## Approval Panel (UI)
While `pending_approval = True` an amber warning banner appears on the SO form:

```
Awaiting Approval — this Sales Order needs approval from either
Accounts (Rajshri) or MD (Manohar).
  • Accounts (Rajshri):  ✓ Approved  |  Pending…
  • MD (Manohar):        ✓ Approved  |  Pending…
```

The banner disappears once the SO is fully confirmed or rejected.

---

## Button Visibility Rules

| Button | Visible to | Condition |
|--------|-----------|-----------|
| Confirm | Tushar, Manohar | SO in Draft, `pending_approval = False` |
| Approve (Accounts) | Rajshri only (`group_sale_approver`) | `pending_approval = True` AND `approval_accounts = False` |
| Approve (MD) | Manohar only (`base.group_erp_manager`) | `pending_approval = True` AND `approval_manohar = False` |
| Reject Order | Rajshri or Manohar | `pending_approval = True` |
| None of the above | Tushar, Amit | Always — they have no approval buttons |

---

## Fields on `sale.order`

| Field | Type | Purpose |
|-------|------|---------|
| `pending_approval` | Boolean | True while waiting for approval (either approver); False after confirm or reject |
| `approval_accounts` | Boolean | True after Rajshri approves |
| `approval_manohar` | Boolean | True after Manohar approves |

All three fields are `copy=False` (not duplicated when SO is copied).

---

## Implementation Files

| File | What it does |
|------|-------------|
| `models/sale_order.py` | Fields + `action_confirm()` override + `action_approve_accounts()` + `action_approve_manohar()` + `action_reject()` + `_try_confirm_if_approved()` |
| `views/sale_order_views.xml` | Form view inheritance — adds approval buttons and pending-status banner |
| `security/groups.xml` | `group_sale_approver` (Rajshri) restricts button visibility and blocks SO creation |
| `data/notification_rules.xml` | `auto_so_confirmed` fires when state → `sale`; notifies Tushar + Amit |

---

## Notifications Summary

| Event | Who is notified | How |
|-------|----------------|-----|
| SO confirmed by Tushar (enters pending) | Rajshri, Manohar | Chatter @mention (Python `message_post`) |
| Rajshri approves | Nobody extra | Chatter note only |
| Either approver approves (completes approval) | Tushar, Amit | `auto_so_confirmed` automation |
| Either rejects | Nobody extra | Chatter note only (Tushar sees it as a follower) |

---

## Test Coverage (Suite 12 in `tests/test_elegomotors_workflow.py`)

| ID | Test | What it verifies |
|----|------|-----------------|
| P-SO1 | `test_p_so1_tushar_confirm_triggers_pending` | Confirm keeps SO in Draft + shows banner |
| P-SO2 | `test_p_so2_rajshri_approves_accounts` | Rajshri's approval alone confirms SO → state = 'sale' |
| P-SO3 | `test_p_so3_manohar_approves_md_so_confirmed` | Manohar's approval alone confirms SO → state = 'sale' |
| P-SO4 | `test_p_so4_confirmed_so_visible_to_tushar_and_amit` | Confirmed SO visible to Tushar + Amit |
| P-SO5 | `test_p_so5_reverse_approval_order` | Either approver alone can confirm |
| R-SO1 | `test_r_so1_rajshri_rejects` | Rajshri rejection → SO back to Draft |
| R-SO2 | `test_r_so2_manohar_rejects` | Manohar rejection → SO back to Draft |
| R-SO3 | `test_r_so3_reconfirm_after_rejection` | Re-confirm re-triggers pending |
| N-SO1 | `test_n_so1_amit_no_approval_buttons` | Amit sees no buttons |
| N-SO2 | `test_n_so2_tushar_no_approval_buttons` | Tushar sees no buttons |
| N-SO3 | `test_n_so3_rajshri_sees_only_accounts_button` | Rajshri: Accounts + Reject only |
| N-SO4 | `test_n_so4_manohar_sees_only_md_button` | Manohar: MD + Reject only |
| N-SO5 | `test_n_so5_single_approval_confirms` | 1 approval is sufficient to confirm SO |
| C-SO1 | `test_c_so1_chatter_pending_notification` | Chatter shows awaiting-approval message |
| C-SO2 | `test_c_so2_approvers_are_followers` | Rajshri + Manohar auto-subscribed |
| C-SO3 | `test_c_so3_chatter_records_individual_approvals` | Each approval logged in chatter |
| SI-SO1 | `test_si_so1_confirmed_so_no_buttons` | Confirmed SO has no approval buttons |
| SI-SO2 | `test_si_so2_fields_reset_on_rejection` | All three fields reset on rejection |
