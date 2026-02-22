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
| **Tushar Gaikwad** | Sales / CRM | leads@elegomotors.com | Sale Salesman, Stock User | Own quotations/SO only; read FG stock. No approval. |

---

## 2. Rules Set for Users

- **Passwords**: Temporary first-login; users should change via Settings → My Profile.
- **Data**: `noupdate="1"` on user records — passwords and groups are not overwritten on module upgrade after first creation.
- **Notifications**: All use `notification_type="inbox"`.
- **Company**: All users on `base.main_company` (ElegoMotors).

---

## 3. Who Has Access to Which Orders

| Document | Who can create/edit | Who can view | Who is notified (subscribed / @mentioned) |
|----------|---------------------|--------------|------------------------------------------|
| **Sale Order (SO)** | Tushar (own); Manohar, Rajshri (approve) | Tushar (own), Amit, Rajshri, Manohar | Created: Tushar, Amit, Rajshri, Manohar (subscribed). To approve: Rajshri, Manohar, Tushar. Confirmed (approved): Tushar, Amit. Invoice posted: Rajshri, Amit, Tushar. |
| **Purchase Order (PO)** | Prashant; Manohar (all + approve) | Prashant, Amit, Rajshri, Manohar | Created: Prashant. To approve: Prashant. Approved: Prashant, Amit. Bill posted: Rajshri, Prashant, Amit. |
| **Manufacturing Order (MO)** | System / MRP; Manohar, Prashant (BOM); Pratik (QC) | Amit, Pratik, Rajshri, Manohar | Created: Pratik, Amit. Confirmed: Pratik, Amit. Done: Amit, Pratik, Tushar. |
| **Stock Picking** | Amit (primary); Pratik (QC/scrap) | Amit, Pratik, others per stock group | Created: Amit. Gate Entry done: Amit, Prashant. |
| **Customer Invoice** | Rajshri (accounting); **Amit (billing)** | Rajshri, Amit, Tushar, Manohar | Created: Rajshri, Amit, Tushar (subscribed). Posted: Rajshri, Amit, Tushar. |
| **Vendor Bill** | Rajshri; **Amit (billing)** | Rajshri, Amit, Prashant, Manohar | Created: Rajshri, Amit, Prashant (subscribed). Posted: Rajshri, Amit, Prashant. |
| **Payments** | **Rajshri only** (Accounting User) | Rajshri, Manohar | Rajshri books and pays; no other user has payment creation rights. |

---

## 4. Order Flow (High Level)

### Sales / CRM pipeline (stages)

Inquiry → Quotation Sent → Negotiation → **Sales Order (To Approve)** → **SO Approved** → Won (or Lost).

- **Tushar**: leads, quotations, SO submission for approval; checks FG availability (read-only stock).
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
3. **MO done** → Pratik (production QC); Amit moves FG to Finished Goods (after QC); Tushar (delivery prep).
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
| **Sales Order (2-step)** | **Rajshri Kadam** or **Manohar Kalbhor** | Both hold `group_sale_manager`. Company: `sale_order_approval = True`, `sale_order_approval_min_amount = 0.0` (all SOs). Tushar (salesman) submits; SO goes to 'to approve'; approver confirms. |
| **Purchase Order (2-step)** | **Manohar Kalbhor** | Only user with `group_purchase_manager`. Company: `po_double_validation = two_step`, `po_lock = lock`. |
| Manufacturing Order | No separate approval | Confirmed per MRP rules; QC by Pratik. |
| Stock / transfers | No separate approval | Validated by Amit (Stock Manager) or Pratik where applicable. |
| **Payments** | **Rajshri Kadam** (Accounting User) | Post and pay; exclusive right — Amit has only Billing access (no payment creation). |
| Leave / time off | **Srushti Gund** | `group_hr_holidays_responsible`. |

---

## 6. Notification Rules (Workflow Triggers)

| Event | Notified (@mention + chatter) |
|-------|------------------------------|
| SO created | Tushar, Amit, Rajshri, Manohar (subscribed) |
| **SO to approve** | **Rajshri, Manohar** (approvers), Tushar (submitter — for awareness) |
| SO confirmed (approved) | Tushar, Amit |
| PO created | Prashant (subscribed) |
| PO to approve | Prashant |
| PO approved | Prashant, Amit |
| MO created | Pratik, Amit (subscribed) |
| MO confirmed | Pratik, Amit |
| MO done | Amit, Pratik, Tushar |
| Gate Entry validated | Amit, Prashant |
| Customer invoice created | Rajshri, Amit, Tushar (subscribed) |
| Customer invoice posted | Rajshri, Amit, Tushar |
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
| Tushar Gaikwad | Sales/CRM | Own SO (submit for approval); FG stock read | — |
