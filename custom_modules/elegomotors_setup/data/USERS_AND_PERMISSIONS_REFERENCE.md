# ElegoMotors Users and Permissions Reference

From `custom_modules/elegomotors_setup/data/`: user rules, order access, order flow, and approvals.

---

## 1. Users and Permission Groups (Brief)

| User | Role | Login | Key groups | Order access |
|------|------|-------|------------|--------------|
| **Manohar Kalbhor** | Admin / Approvals | manohar.kalbhor@elegomotors.com | ERP Manager, Purchase Manager, Sales Manager, Stock Manager, MRP User+Routings, Accounting User | All: SO, PO, MO, stock, accounting. **Approves POs** (2-step). **Approves SOs** (2-step). |
| **Amit Kale** | Store Manager | storeelegomotors@gmail.com | Stock Manager, Purchase User, MRP User+Routings, Sale Salesman, **Billing User** | View PO, SO, MO; full stock (Gate Entry, QC, Issue to Prod, FG receipt, Delivery). **Create/edit Customer Invoices and Vendor Bills** (no payments). |
| **Prashant Khedkar** | Purchase | NPD@elegomotors.com | Purchase User, MRP User, Stock User | Create/manage PO; view MO, BOM, inventory. No approval. |
| **Rajshri Kadam** | Accounts | elegoac@gmail.com | Accounting User, Purchase User, **Sales Manager**, MRP User, Stock User | View PO, SO, MO, stock; full accounting (payments, JV, bills, reports). **Approves SOs** (2-step). **Exclusive payment access**. |
| **Srushti Gund** | HR | hrelegomotors@gmail.com | HR Manager, Attendance Manager, Time Off Responsible | HR only (employees, attendance, leave). No order access. |
| **Pratik Gund** | Quality / Warranty | quality.elego23@gmail.com | MRP User, MRP Routings, Stock Manager | MO (QC, work orders, scrap); stock (QC inward, quarantine, warranty). View SO for warranty. |
| **Priyanka Kul** | Sales / CRM | leads@elegomotors.com | Sale Salesman, Stock User | Own quotations/SO only; read FG stock. No approval. |

---

## 2. Rules Set for Users

- **Passwords**: Temporary first-login; users should change via Settings → My Profile.
- **Data**: `noupdate="1"` on user records — passwords and groups are not overwritten on module upgrade after first creation.
- **If login fails** (e.g. after deploy/restore where users already existed): run once from Odoo shell: `odoo-bin shell -d YOUR_DB` then `exec(open('set_elegomotors_passwords.py').read())` (from repo root). Passwords are also set by `post_init_hook` on first install.
- **Notifications**: All use `notification_type="inbox"`.
- **Company**: All users on `base.main_company` (ElegoMotors).

---

## 3. Who Has Access to Which Orders

| Document | Who can create/edit | Who can view | Who is notified (subscribed / @mentioned) |
|----------|---------------------|--------------|------------------------------------------|
| **Sale Order (SO)** | Priyanka (own); Manohar, Rajshri (approve) | Priyanka (own), Amit, Rajshri, Manohar | Created: Priyanka, Amit, Rajshri, Manohar (subscribed). To approve: Rajshri, Manohar, Priyanka. Confirmed (approved): Priyanka, Amit. Invoice posted: Rajshri, Amit, Priyanka. |
| **Purchase Order (PO)** | Prashant; Manohar (all + approve) | Prashant, Amit, Rajshri, Manohar | Created: Prashant. To approve: Prashant. Approved: Prashant, Amit. Bill posted: Rajshri, Prashant, Amit. |
| **Manufacturing Order (MO)** | System / MRP; Manohar, Prashant (BOM); Pratik (QC) | Amit, Pratik, Rajshri, Manohar | Created: Pratik, Amit. Confirmed: Pratik, Amit. Done: Amit, Pratik, Priyanka. |
| **Stock Picking** | Amit (primary); Pratik (QC/scrap) | Amit, Pratik, others per stock group | Created: Amit. Gate Entry done: Amit, Prashant. |
| **Customer Invoice** | Rajshri (accounting); **Amit (billing)** | Rajshri, Amit, Priyanka, Manohar | Created: Rajshri, Amit, Priyanka (subscribed). Posted: Rajshri, Amit, Priyanka. |
| **Vendor Bill** | Rajshri; **Amit (billing)** | Rajshri, Amit, Prashant, Manohar | Created: Rajshri, Amit, Prashant (subscribed). Posted: Rajshri, Amit, Prashant. |
| **Payments** | **Rajshri only** (Accounting User) | Rajshri, Manohar | Rajshri books and pays; no other user has payment creation rights. |
| **Unbuild Order / Rebuild MO** | **Manohar only** (`group_unbuild_rebuild_operator`) | Manohar | Manohar can extend this group to other users (e.g. Pratik) himself via Settings > Users — no code change needed. |

---

## 3a. Serial-Number-Wise Bike Unbuild & Rebuild

Manohar can take a specific bike serial apart (Unbuild Order), recovering its components to
EGO/Production WIP, and the system auto-creates a linked Rebuild MO that consumes those
components straight from WIP (no Issue-to-Production picking). The rebuild may reuse the
same bike/chassis serial (only once its stock is at zero) or be assigned a new one.

- **Access**: `elegomotors_setup.group_unbuild_rebuild_operator` — Manohar only initially.
  Enforced in Python (`models/mrp_unbuild.py`) since Odoo's core `mrp.group_mrp_user`
  (already held by Pratik/Prashant via Manufacturing Operator) would otherwise grant them
  model-level access to the native Unbuild Orders screen regardless of this group.
- **Entry point**: "Unbuild This Bike" button on the bike's serial (`stock.lot` form,
  Component Traceability tab).
- **Traceability**: Bike Serial → Original MO → Unbuild Order (with a snapshot of the
  component serials recovered) → Rebuild MO → Rebuilt Bike Serial — visible via smart
  buttons on the `stock.lot` form and a banner + Rebuild History tab on the MO form.

---

## 4. Order Flow (High Level)

### Sales / CRM pipeline (stages)

Inquiry → Quotation Sent → Negotiation → **Sales Order (To Approve)** → **SO Approved** → Won (or Lost).

- **Priyanka**: leads, quotations, SO submission for approval; checks FG availability (read-only stock).
- **Rajshri / Manohar**: approve the SO (2-step SO approval — both hold `group_sale_manager`).
- **Manohar**: full pipeline and SO oversight (Sales Manager + Admin).

### Purchase flow

1. **Prashant** creates PO → state "to approve".
2. **Manohar** approves (2-step PO approval; `po_double_validation = two_step`, `po_lock = lock`).
3. PO confirmed → Prashant sends to vendor; Amit prepares Gate Entry.
4. Material at QC Inward → Amit/QC: QC Pass → Store or QC Fail → Quarantine (RTV if needed).
5. Vendor bill → **Amit creates/edits**; **Rajshri posts and pays**; Finance + Purchase + Store notified when posted.

### Manufacturing flow

1. SO approved → Amit checks FG; if not available, MO is raised (manufacture-to-resupply).
2. **MO confirmed** → Pratik (QC prep); Amit issues materials (Issue to Production).
3. **MO done** → Pratik (production QC); Amit moves FG to Finished Goods (after QC); Priyanka (delivery prep).
4. Delivery (PDI + Dispatch): FG → Customer; Amit/Store executes.
5. Customer invoice → **Amit creates/edits**; **Rajshri posts**; Finance + Store + Sales notified.

### Stock operation types (who does what)

| Operation | Type | Responsible | Flow |
|-----------|------|-------------|------|
| Gate Entry (Inward) | incoming | Amit | Vendor → EGO/QC Inward |
| QC Pass → Store | internal | Amit / Pratik | QC Inward → EGO/Store |
| QC Fail → Quarantine | internal | Amit / Pratik | QC Inward → Quarantine |
| Issue to Production | internal | Amit | EGO/Store → Production WIP |
| FG to Finished Goods | internal | Amit (after Pratik QC) | Production → EGO/FG |
| Delivery (PDI + Dispatch) | outgoing | Amit | EGO/FG → Customer |
| Returns to Vendors | outgoing | Amit / Prashant (process) | Quarantine → Suppliers |

---

## 5. Who Approves What

| Approval | Approver | Rule / config |
|----------|----------|----------------|
| **Sales Order (2-step)** | **Rajshri Kadam** or **Manohar Kalbhor** | Both hold `group_sale_manager`. Company: `sale_order_approval = True`, `sale_order_approval_min_amount = 0.0` (all SOs). Priyanka (salesman) submits; SO goes to 'to approve'; approver confirms. |
| **Purchase Order (2-step)** | **Manohar Kalbhor** | Only user with `group_purchase_manager`. Company: `po_double_validation = two_step`, `po_lock = lock`. |
| Manufacturing Order | No separate approval | Confirmed per MRP rules; QC by Pratik. |
| Stock / transfers | No separate approval | Validated by Amit (Stock Manager) or Pratik where applicable. |
| **Payments** | **Rajshri Kadam** (Accounting User) | Post and pay; exclusive right — Amit has only Billing access (no payment creation). |
| Leave / time off | **Srushti Gund** | `group_hr_holidays_responsible`. |

---

## 6. Notification Rules (Workflow Triggers)

| Event | Notified (@mention + chatter) |
|-------|------------------------------|
| SO created | Priyanka, Amit, Rajshri, Manohar (subscribed) |
| **SO to approve** | **Rajshri, Manohar** (approvers), Priyanka (submitter — for awareness) |
| SO confirmed (approved) | Priyanka, Amit |
| PO created | Prashant (subscribed) |
| PO to approve | Prashant |
| PO approved | Prashant, Amit |
| MO created | Pratik, Amit (subscribed) |
| MO confirmed | Pratik, Amit |
| MO done | Amit, Pratik, Priyanka |
| Gate Entry validated | Amit, Prashant |
| Customer invoice created | Rajshri, Amit, Priyanka (subscribed) |
| Customer invoice posted | Rajshri, Amit, Priyanka |
| Vendor bill created | Rajshri, Amit, Prashant (subscribed) |
| Vendor bill posted | Rajshri, Amit, Prashant |
| Stock picking created | Amit (subscribed) |

---

## 7. One-Line Summary Table

| User | Department | Access | Approves |
|------|------------|--------|----------|
| Manohar Kalbhor | Admin | All modules, all orders | **PO (2-step)**, **SO (2-step)** |
| Amit Kale | Store | PO/SO/MO view; all stock ops; **Customer Invoice + Vendor Bill create/edit** (no payments) | — |
| Prashant Khedkar | Purchase | PO create/manage; MO/BOM/stock view | — |
| Rajshri Kadam | Accounts | All view; accounting full; **exclusive payments** | **SO (2-step)** |
| Srushti Gund | HR | HR only | Leave / time off |
| Pratik Gund | Quality | MO QC, work orders, scrap; QC/Quarantine stock | — |
| Priyanka Kul | Sales/CRM | Own SO (submit for approval); FG stock read | — |
