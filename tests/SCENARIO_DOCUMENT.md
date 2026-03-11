# ElegoMotors — Exhaustive Test Scenario Document

**Odoo 18 Community | ElegoMotors EV 2-Wheeler Manufacturing**
**Module:** `elegomotors_setup` | **Branch:** `shubham/workflow-setup-v2`

---

## 1. Users and Security Groups

| # | User | Login | Department | Key Odoo Groups |
|---|------|-------|------------|-----------------|
| 1 | **Manohar Kalbhor** | manohar.kalbhor@elegomotors.com | Admin / Approvals | ERP Manager, Purchase Manager, Sales Manager, Stock Manager, MRP User + Routings, Accounting User |
| 2 | **Amit Kale** | storeelegomotors@gmail.com | Store Manager | Stock Manager, Purchase User, MRP User + Routings, Sale Salesman, Billing User (account.group_account_invoice), **group_store_billing** |
| 3 | **Prashant Khedkar** | NPD@elegomotors.com | Purchase | Purchase User, MRP User, Stock User |
| 4 | **Rajshri Kadam** | elegoac@gmail.com | Accounts | Accounting User, Purchase User, Sales Manager, MRP User, Stock User |
| 5 | **Srushti Gund** | hrelegomotors@gmail.com | HR | HR Manager, Attendance Manager, Time Off Responsible |
| 6 | **Pratik Gund** | quality.elego23@gmail.com | Quality / Manufacturing | **group_manufacturing_operator** (implies MRP User), MRP Routings, Stock Manager, Quality Manager |
| 7 | **Tushar Gaikwad** | leads@elegomotors.com | Sales / CRM | Sale Salesman, Stock User |

---

## 2. Feature Access Matrix

> ✅ = Full access | 👁 = View/Read only | ➕ = Create only | ❌ = No access | 🔐 = Restricted (see notes)

### 2a. Module-Level Access

| Module | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|--------|---------|------|----------|---------|---------|--------|--------|
| **Settings** | ✅ (ERP Mgr) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Purchase** | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Sales / CRM** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ |
| **Inventory** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ (read) |
| **Manufacturing** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Accounting** | ✅ | 🔐 (invoices only) | ❌ | ✅ | ❌ | ❌ | ❌ |
| **HR / Employees** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Quality** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |

### 2b. Purchase Order (PO) Actions

| Action | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|--------|---------|------|----------|---------|---------|--------|--------|
| **View POs** | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Create PO** | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Confirm PO** (send to approve) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Approve PO** (2-step) | ✅ (Purchase Mgr) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Send PO by email** | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Receive goods against PO** | ✅ | ✅ (Gate Entry) | ❌ | ❌ | ❌ | ❌ | ❌ |

### 2c. Sales Order (SO) Actions

| Action | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|--------|---------|------|----------|---------|---------|--------|--------|
| **View SOs** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ (own) |
| **Create / Edit Quotation** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| **Submit SO for Approval** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| **Approve SO** (2-step) | ✅ (Sales Mgr) | ❌ | ❌ | ✅ (Sales Mgr) | ❌ | ❌ | ❌ |
| **Create Invoice from SO** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ |
| **Mark Opportunity Won** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |

### 2d. Manufacturing Order (MO) Actions

| Action | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|--------|---------|------|----------|---------|---------|--------|--------|
| **View MOs** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Create MO** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Confirm MO** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Produce All / Mark Done** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **EXCLUSIVE** | ❌ |
| **Create/Edit BOM** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Issue material to Production** | ✅ | ✅ (Amit primary) | ❌ | ❌ | ❌ | ✅ | ❌ |

### 2e. Stock / Inventory Actions

| Action | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|--------|---------|------|----------|---------|---------|--------|--------|
| **View all transfers** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ (read) |
| **Validate Gate Entry** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| **QC Pass → Store** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| **QC Fail → Quarantine** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Issue to Production** | ✅ | ✅ (primary) | ❌ | ❌ | ❌ | ✅ | ❌ |
| **FG → Finished Goods** | ✅ | ✅ (after QC) | ❌ | ❌ | ❌ | ✅ (QC) | ❌ |
| **Validate Delivery** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Return to Vendor (RTV)** | ✅ | ✅ | ✅ (process) | ❌ | ❌ | ✅ | ❌ |
| **Warehouse / Location config** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Inventory adjustment** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |

### 2f. Accounting / Invoice Actions

| Action | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|--------|---------|------|----------|---------|---------|--------|--------|
| **View Customer Invoices** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Create / Edit Customer Invoice** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Price / Discount fields** | ✅ | 🔐 **READ-ONLY** (group_store_billing) | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Post (Confirm) Customer Invoice** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **View Vendor Bills** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Create / Edit Vendor Bill** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Post Vendor Bill** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Register Payment** | ✅ | ❌ | ❌ | ✅ **EXCLUSIVE** | ❌ | ❌ | ❌ |
| **Vendor Bills (Debit Note)** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Journal Entries (JV)** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **P&L / Financial Reports** | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |

### 2g. HR Actions

| Action | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|--------|---------|------|----------|---------|---------|--------|--------|
| **View Employees** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Manage Attendance** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Approve Leave** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |

---

## 3. User and Action Access Table (Pass/Fail Scenarios)

### 3a. Access Positive Scenarios (Must PASS)

| # | User | Action | Expected Result |
|---|------|--------|----------------|
| P01 | Manohar | Login and open Settings | Settings page loads |
| P02 | Manohar | Open all 6 modules | No Missing Action |
| P03 | Manohar | Approve a PO (2-step) | PO moves to Purchase Order state |
| P04 | Manohar | Approve a SO (2-step) | SO moves to Sale state |
| P05 | Amit | Open Inventory | Inventory loads |
| P06 | Amit | Open Purchase | Purchase list loads |
| P07 | Amit | Open Accounting | Accounting loads (has Billing group) |
| P08 | Amit | View Customer Invoices | Invoice list visible |
| P09 | Amit | View Vendor Bills | Vendor bill list visible |
| P10 | Amit | Validate Gate Entry transfer | Transfer goes to Done |
| P11 | Prashant | Create Purchase Order | PO created in "To Approve" state |
| P12 | Prashant | Open Manufacturing | MO/BOM list loads |
| P13 | Prashant | View Inventory | Stock products visible |
| P14 | Rajshri | Open Accounting | Full accounting access |
| P15 | Rajshri | Approve SO | SO moves to Sale state |
| P16 | Rajshri | Register Payment on posted invoice | Payment registered successfully |
| P17 | Rajshri | Post Customer Invoice | Invoice state → Posted |
| P18 | Srushti | Open HR / Employees | Employee list loads |
| P19 | Srushti | Manage Attendance | Attendance records visible |
| P20 | Pratik | Open Manufacturing | MO list loads |
| P21 | Pratik | Open Inventory | Stock transfers visible |
| P22 | Pratik | Click "Produce All" on MO | MO marked as done (EXCLUSIVE) |
| P23 | Pratik | Validate QC Pass transfer | Transfer goes to Done |
| P24 | Pratik | Validate QC Fail → Quarantine | Transfer goes to Done |
| P25 | Tushar | Open CRM | Pipeline loads |
| P26 | Tushar | Create Quotation | Quotation created |
| P27 | Tushar | Submit SO for approval | SO state → "To Approve" |
| P28 | Tushar | View Inventory (FG check) | Stock/FG products visible |

### 3b. Access Negative Scenarios (Must BLOCK)

| # | User | Forbidden Action | Expected Enforcement |
|---|------|-----------------|---------------------|
| N01 | Amit | Click "Produce All" / "Mark Done" on MO | AccessError — only Pratik can produce |
| N02 | Amit | Register Payment on Customer Invoice | "Register Payment" button NOT shown |
| N03 | Amit | Edit price_unit on Customer Invoice | price_unit field is READ-ONLY |
| N04 | Amit | Approve PO | "Approve" button NOT visible |
| N05 | Prashant | Create Sales Order | "New" button absent on SO list |
| N06 | Prashant | Access Accounting / Invoices | Missing Action or Access Error |
| N07 | Rajshri | Click "Produce All" on MO | AccessError — only Pratik can produce |
| N08 | Manohar | Click "Produce All" on MO (if not in group) | AccessError (unless superuser override) |
| N09 | Srushti | Open Inventory | Missing Action or Access Error |
| N10 | Srushti | Open Manufacturing | Missing Action or Access Error |
| N11 | Srushti | Open Purchase | Missing Action or Access Error |
| N12 | Tushar | Approve SO | "Approve Order" button NOT visible |
| N13 | Tushar | Approve PO | "Approve" button NOT visible |
| N14 | Tushar | Create Manufacturing Order | No "New" button on MO list OR Access Error |
| N15 | Pratik | Create Purchase Order | No "New" button on PO list |
| N16 | Rajshri | Approve PO (only Manohar can) | "Approve" button NOT visible |

---

## 4. Workflow Scenarios (End-to-End)

### 4a. CRM → Sales Order → Delivery → Invoice

| Step | Actor | Action | State After |
|------|-------|--------|------------|
| 1 | Tushar | Create Inquiry (CRM Lead) | Lead: New |
| 2 | Tushar | Create Quotation from Lead | Quotation: Draft |
| 3 | Tushar | Submit Quotation as SO | SO: To Approve |
| 4 | Rajshri / Manohar | Approve SO | SO: Sale (confirmed) |
| 5 | Amit | Check Delivery order on SO | Delivery: Ready |
| 6 | Amit | Validate Delivery (PDI + Dispatch) | Delivery: Done |
| 7 | Amit / Tushar | Create Customer Invoice from SO | Invoice: Draft |
| 8 | Rajshri | Post (Confirm) Invoice | Invoice: Posted |
| 9 | Rajshri | Register Payment | Invoice: In Payment → Paid |
| 10 | Tushar | Mark Opportunity Won | Opportunity: Won |

### 4b. Purchase → Gate Entry → QC → Store → Production → FG

| Step | Actor | Action | State After |
|------|-------|--------|------------|
| 1 | Prashant | Create Purchase Order | PO: To Approve |
| 2 | Manohar | Approve PO (2-step) | PO: Purchase Order (confirmed) |
| 3 | Prashant | Send PO to Vendor | PO email sent |
| 4 | Amit | Validate Gate Entry receipt | GE Transfer: Done → Material at QC Inward |
| 5 | Pratik | Validate QC Pass → Store | QCS Transfer: Done → Material at Store |
| 6 | Amit | Issue Material to Production | PI Transfer: Done → Material at Production WIP |
| 7 | Pratik | Produce All on MO | MO: Done |
| 8 | Pratik / Amit | Validate FG → Finished Goods | FGS Transfer: Done → FG at Finished Goods |
| 9 | Rajshri | Create Vendor Bill from PO | Bill: Draft |
| 10 | Rajshri | Post Vendor Bill | Bill: Posted |
| 11 | Rajshri | Register Payment to vendor | Bill: In Payment → Paid |

### 4c. QC Fail Flow (Quarantine → RTV)

| Step | Actor | Action | State After |
|------|-------|--------|------------|
| 1 | Amit | Validate Gate Entry | Material at QC Inward |
| 2 | Pratik | Validate QC Fail → Quarantine | Material at Quarantine |
| 3 | Pratik / Amit | Validate Returns to Vendors (RTV) | Material returned to Vendor location |
| 4 | Rajshri | Raise Debit Note on Vendor Bill | Credit Note created |

---

## 5. Approval Matrix

| Document | Submitted By | Approved By | Config |
|----------|-------------|------------|--------|
| **Purchase Order** | Prashant | **Manohar only** (Purchase Manager) | `po_double_validation = two_step`, `po_lock = lock` |
| **Sales Order** | Tushar, Rajshri, Manohar | **Rajshri** or **Manohar** (Sales Manager) | `sale_order_approval = True`, min_amount = 0 (all SOs) |
| **Manufacturing Order** | Manohar, Prashant, Pratik | No separate approval — QC by Pratik | — |
| **Payments** | — | **Rajshri only** (Accounting User) | Exclusive; Amit has Billing (no payment creation) |
| **Leave / Time Off** | Any employee | **Srushti** (Time Off Responsible) | HR module |

---

## 6. Custom Stock Locations (EGO Warehouse)

| Location | Parent | Used For | Operation Type |
|----------|--------|---------|----------------|
| EGO/QC Inward | Physical Locations | Raw material inspection after Gate Entry | Gate Entry (dest) |
| EGO/Store | Physical Locations | Approved materials storage | QC Pass (dest), Issue to Production (src) |
| EGO/Production WIP | Physical Locations | Materials on manufacturing floor | Issue to Production (dest), FG (src) |
| EGO/Finished Goods | Physical Locations | Completed EV units | FG (dest), Delivery (src) |
| EGO/Quarantine | Physical Locations | Rejected/failed QC materials | QC Fail (dest), RTV (src) |

---

## 7. Custom Operation Types

| Name | Code | Sequence | From → To | Responsible |
|------|------|----------|-----------|-------------|
| Gate Entry (Inward) | GE | incoming | Vendors → QC Inward | Amit |
| QC Pass → Store | QCS | internal | QC Inward → Store | Amit / Pratik |
| QC Fail → Quarantine | QCQ | internal | QC Inward → Quarantine | Pratik |
| Issue to Production | PI | internal | Store → Production WIP | Amit |
| FG to Finished Goods Store | FGS | internal | Production WIP → FG | Pratik / Amit |
| Delivery (PDI + Dispatch) | DEL | outgoing | FG → Customers | Amit |
| Returns to Vendors | RTV | outgoing | Quarantine → Vendors | Amit / Prashant |

---

## 8. Notification / Subscription Events

| Event Trigger | Auto-Notified Users | Method |
|--------------|--------------------|----|
| SO created | Tushar (salesman), Amit (store), Rajshri, Manohar | Subscribed as followers |
| SO → To Approve | Rajshri, Manohar (approvers), Tushar | Chatter + inbox notification |
| SO confirmed (approved) | Tushar, Amit | Chatter + inbox notification |
| PO created | Prashant | Subscribed as follower |
| PO → To Approve | Prashant | Chatter + inbox notification |
| PO approved | Prashant, Amit | Chatter + inbox notification |
| MO created | Pratik, Amit | Subscribed as followers |
| MO confirmed | Pratik, Amit | Chatter + inbox notification |
| MO done | Amit, Pratik, Tushar | Chatter + inbox notification |
| Gate Entry validated | Amit, Prashant | Chatter + inbox notification |
| Customer Invoice created | Rajshri, Amit, Tushar | Subscribed as followers |
| Customer Invoice posted | Rajshri, Amit, Tushar | Chatter + inbox notification |
| Vendor Bill created | Rajshri, Amit, Prashant | Subscribed as followers |
| Vendor Bill posted | Rajshri, Amit, Prashant | Chatter + inbox notification |
| Stock picking created | Amit | Subscribed as follower |

---

## 9. Known Test Limitations

| Test | Status | Reason |
|------|--------|--------|
| Odoo built-in: `mrp_workorder_hr_account` | **Fixed** | `button_mark_done` now exempts superusers/admin (uid=1 and `env.su`) from the Manufacturing Operator check |
| Odoo built-in: `sale_purchase_stock.test_cross_dock_flow` | **Fixed** | Removed overrides of `stock.picking_type_in.default_location_dest_id` and `stock.picking_type_out.default_location_src_id` that were redirecting standard receipts to EGO locations |
| `test_notify_*` chatter tests | May skip | Notification automation rules must be active in Odoo; automated actions are `active=True` in `notification_rules.xml` but may need mail module configuration |
| `test_follower_*` tests | May skip | Follower subscriptions depend on automation rules; configuration required |

---

## 10. Pytest Test Coverage Matrix

| Suite | Test Name | Covers Scenario |
|-------|-----------|----------------|
| Suite 1 | `test_manohar_access_all_modules` | P01, P02 |
| Suite 1 | `test_amit_access_store_modules` | P05–P07 |
| Suite 1 | `test_prashant_access_purchase` | P11–P13 |
| Suite 1 | `test_rajshri_access_accounting` | P14 |
| Suite 1 | `test_srushti_access_hr` | P18 |
| Suite 1 | `test_pratik_access_quality` | P20, P21 |
| Suite 1 | `test_tushar_access_sales` | P25, P26, P28 |
| Suite 1 | `test_tushar_cannot_approve_po` | N13 |
| Suite 1 | `test_prashant_cannot_create_sales_order` | N05 |
| Suite 1 | `test_tushar_cannot_create_manufacturing_order` | N14 |
| Suite 1 | `test_pratik_cannot_create_purchase_order` | N15 |
| Suite 1 | `test_srushti_cannot_access_inventory` | N09 |
| Suite 1 | `test_rajshri_cannot_approve_po` | N16 |
| Suite 1 | `test_amit_can_access_customer_invoices` | P08 |
| Suite 1 | `test_amit_can_access_vendor_bills` | P09 |
| Suite 1 | `test_amit_cannot_register_payment` | N02 |
| Suite 1 | `test_rajshri_can_approve_so` | P15 |
| Suite 1 | `test_tushar_cannot_approve_so` | N12 |
| Suite 1 | `test_amit_invoice_price_readonly` | **N03 — MISSING** |
| Suite 1 | `test_amit_cannot_produce_mo` | **N01 — MISSING** |
| Suite 1 | `test_rajshri_can_register_payment` | **P16 — MISSING** |
| Suite 1 | `test_srushti_cannot_access_manufacturing` | **N10 — MISSING** |
| Suite 1 | `test_srushti_cannot_access_purchase` | **N11 — MISSING** |
| Suite 2 | `test_create_inquiry_lead` | 4a Step 1 |
| Suite 2 | `test_create_quotation_from_lead` | 4a Step 2 |
| Suite 2 | `test_confirm_sales_order_from_crm` | 4a Steps 3–4 |
| Suite 2 | `test_mark_opportunity_won` | 4a Step 10 |
| Suite 2b | `test_so_goes_to_approve_state` | 4a Step 3 |
| Suite 2b | `test_rajshri_approves_so` | 4a Step 4 |
| Suite 2b | `test_manohar_can_also_approve_so` | P04 |
| Suite 3 | `test_prashant_creates_purchase_order` | 4b Step 1 |
| Suite 3 | `test_po_goes_to_approve_state` | 4b Step 1 |
| Suite 3 | `test_manohar_approves_po` | P03, 4b Step 2 |
| Suite 4 | `test_gate_entry_created_from_po` | 4b Step 4 |
| Suite 4 | `test_amit_validates_gate_entry` | P10, 4b Step 4 |
| Suite 4 | `test_qc_pass_to_store` | P23, 4b Step 5 |
| Suite 4 | `test_qc_fail_to_quarantine` | P24, 4c Step 2 |
| Suite 4 | `test_return_to_vendor_rtv` | 4c Step 3 |
| Suite 4 | `test_raise_debit_note` | 4c Step 4 |
| Suite 5 | `test_create_manufacturing_order` | 4b |
| Suite 5 | `test_confirm_manufacturing_order` | 4b |
| Suite 5 | `test_issue_material_to_production` | 4b Step 6 |
| Suite 5 | `test_qc_check_produced_material_pass` | 4b Step 8 |
| Suite 6 | `test_tushar_creates_sales_order` | 4a Step 3 |
| Suite 6 | `test_so_approved_for_delivery` | 4a Step 4 |
| Suite 6 | `test_picking_slip_created` | 4a Step 5 |
| Suite 6 | `test_validate_delivery_pdi` | 4a Step 6 |
| Suite 6 | `test_post_sales_invoice` | P17, 4a Step 8 |
| Suite 7 | `test_full_e2e_inquiry_to_invoice` | Full 4a + 4b |
| Suite 8 | `test_notify_*` | Section 8 notifications |
| Suite 9 | `test_stock_locations_exist` | Section 6 |
| Suite 9 | `test_picking_types_exist` | Section 7 |
| Suite 9 | `test_gate_entry_routes_to_qc_inward` | Section 7 |

---

## 11. Running the Tests

```bash
# Run all tests against live Odoo.sh instance
cd Elego/tests
ODOO_URL="https://<branch>.odoo.sh" pytest test_elegomotors_workflow.py -v

# Run only Suite 1 (access control tests)
pytest test_elegomotors_workflow.py -k "access or cannot or can_access" -v

# Run Suite 1 negative tests
pytest test_elegomotors_workflow.py -k "cannot" -v

# Run only E2E test
pytest test_elegomotors_workflow.py -m e2e -v

# Run with screenshots enabled
EGO_SCREENSHOTS=1 pytest test_elegomotors_workflow.py -v
```

---

*Generated: 2026-03-11 | Branch: shubham/workflow-setup-v2*
