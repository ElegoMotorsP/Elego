# ElegoMotors — Complete Business Workflow

## Actors


| Actor        | Login                                                                     | Primary Role       | Odoo Modules                                |
| ------------ | ------------------------------------------------------------------------- | ------------------ | ------------------------------------------- |
| **Priyanka** | [leads@elegomotors.com](mailto:leads@elegomotors.com)                     | Sales / CRM        | Sales, CRM                                  |
| **Rajshri**  | [elegoac@gmail.com](mailto:elegoac@gmail.com)                             | Accounts           | Accounting, Purchase, Sales (approver only) |
| **Manohar**  | [manohar.kalbhor@elegomotors.com](mailto:manohar.kalbhor@elegomotors.com) | MD / Admin         | All (final approver)                        |
| **Amit**     | [storeelegomotors@gmail.com](mailto:storeelegomotors@gmail.com)           | Store / Warehouse  | Inventory, Purchase, Billing                |
| **Prashant** | [NPD@elegomotors.com](mailto:NPD@elegomotors.com)                         | Purchase / NPD     | Purchase, MRP, Inventory                    |
| **Pratik**   | [quality.elego23@gmail.com](mailto:quality.elego23@gmail.com)             | QC + Manufacturing | Manufacturing, Quality, Inventory           |


---

## Workflow Paths

There are **5 distinct paths** depending on stock availability and quality outcomes. All paths begin with the same Sales flow (Path 0). The paths then branch based on finished-goods availability, raw-material availability, and quality-check results.

---

### Path 0 — Sales Order Creation & Dual Approval

**Trigger:** Customer inquiry received.


| Step | Actor   | Action                                                                                 | Odoo Object                        |
| ---- | ------- | -------------------------------------------------------------------------------------- | ---------------------------------- |
| 0.1  | Tushar  | Receives customer inquiry and creates a **Quotation**                                  | `sale.order` (draft)               |
| 0.2  | Tushar  | Finalizes quotation and clicks **Confirm**                                             | SO enters `pending_approval` state |
| 0.3  | Rajshri | Opens the SO and clicks **Approve (Accounts)**                                         | `approval_accounts = True`         |
| 0.4  | Manohar | Opens the SO and clicks **Approve (MD)**                                               | `approval_manohar = True`          |
| 0.5  | System  | Both approvals complete — SO state changes to **Sales Order** (`sale`)                 | Automatic state transition         |
| 0.6  | System  | Notification sent to Tushar and Amit: "Sales Order Confirmed — verify FG availability" | Chatter automation                 |


> **Note:** Steps 0.3 and 0.4 can happen in any order. Either approver can also **Reject**, which returns the SO to Draft for Tushar to revise and re-confirm. See [SO-process.md](SO-process.md) for full rejection/re-confirm details.

**Next decision:** Amit checks if Finished Goods (FG) are available in `EGO/Finished Goods` location.

---

### Path 1 — FG Available (Direct Delivery)

**Condition:** Finished goods (EGO-S1 scooter) are already in stock.


| Step | Actor  | Action                                                             | Odoo Object                  |
| ---- | ------ | ------------------------------------------------------------------ | ---------------------------- |
| 1.1  | Amit   | Checks FG stock — scooter is available                             | Stock check                  |
| 1.2  | Amit   | Creates / processes **Picking Slip** (delivery order)              | `stock.picking` (outgoing)   |
| 1.3  | Pratik | Performs **Pre-Delivery Inspection (PDI)** on the finished scooter | Quality check                |
| 1.4  | Amit   | Creates **Sales Invoice** and sends to customer                    | `account.move` (out_invoice) |


**End of path.** Order is fulfilled from existing stock.

---

### Path 2 — FG Not Available, Raw Material Available (Manufacture from Stock)

**Condition:** No finished scooters in stock, but all raw materials are available in the store.


| Step | Actor    | Action                                                                   | Odoo Object                |
| ---- | -------- | ------------------------------------------------------------------------ | -------------------------- |
| 2.1  | Amit     | Checks FG stock — scooter is NOT available                               | Stock check                |
| 2.2  | Prashant | Creates **Manufacturing Order (MO)**                                     | `mrp.production`           |
| 2.3  | System   | MO generates **Material Request to Store** (component demand)            | `stock.picking` (internal) |
| 2.4  | Amit     | Checks raw material availability — materials ARE available               | Stock check                |
| 2.5  | Amit     | Creates **Picking Slip** to issue raw materials from store to production | `stock.picking` (internal) |
| 2.6  | Amit     | Confirms **Material Issued to Production**                               | Transfer validated         |
| 2.7  | Pratik   | Performs **Manufacturing** (produces the scooter)                        | `mrp.production` → done    |
| 2.8  | Pratik   | Performs **QC Check of Produced Material**                               | Quality check              |


**QC Outcome branches here — see Path 2A and Path 2B.**

#### Path 2A — Produced Material Passes QC


| Step | Actor  | Action                                                         | Odoo Object                  |
| ---- | ------ | -------------------------------------------------------------- | ---------------------------- |
| 2A.1 | Pratik | QC result: **OK** — scooter passes quality check               | Quality check pass           |
| 2A.2 | Pratik | Performs additional **QC Checks** (final quality gate)         | Quality check                |
| 2A.3 | Amit   | Creates **Picking Slip** (delivery order for finished scooter) | `stock.picking` (outgoing)   |
| 2A.4 | Pratik | Performs **Pre-Delivery Inspection (PDI)**                     | Quality check                |
| 2A.5 | Amit   | Creates **Sales Invoice**                                      | `account.move` (out_invoice) |


**End of path.** Order fulfilled after manufacturing.

#### Path 2B — Produced Material Fails QC


| Step | Actor  | Action                                              | Odoo Object        |
| ---- | ------ | --------------------------------------------------- | ------------------ |
| 2B.1 | Pratik | QC result: **Not OK** — scooter fails quality check | Quality check fail |
| 2B.2 | Pratik | Moves unit to **WIP/Hold** status                   | MO rework / scrap  |
| 2B.3 | Pratik | Re-manufactures or reworks the unit                 | `mrp.production`   |
| 2B.4 | —      | Returns to step 2.8 (QC re-check)                   | Loop until pass    |


**End of sub-path.** Eventually merges back into Path 2A when QC passes.

---

### Path 3 — FG Not Available, Raw Material Not Available (Purchase + Manufacture)

**Condition:** No finished scooters in stock AND raw materials are missing. This is the longest path and involves procurement before manufacturing.


| Step | Actor    | Action                                                         | Odoo Object                |
| ---- | -------- | -------------------------------------------------------------- | -------------------------- |
| 3.1  | Amit     | Checks FG stock — scooter is NOT available                     | Stock check                |
| 3.2  | Prashant | Creates **Manufacturing Order (MO)**                           | `mrp.production`           |
| 3.3  | System   | MO generates **Material Request to Store**                     | `stock.picking` (internal) |
| 3.4  | Amit     | Checks raw material availability — materials are NOT available | Stock check                |


**→ Procurement sub-flow begins (Path 3A)**

#### Path 3A — Purchase Procurement


| Step | Actor    | Action                                                           | Odoo Object                 |
| ---- | -------- | ---------------------------------------------------------------- | --------------------------- |
| 3A.1 | Prashant | Creates **Purchase Quotation (RFQ)** for missing materials       | `purchase.order` (draft)    |
| 3A.2 | Manohar  | Reviews and **approves** the purchase quotation                  | `purchase.order` confirmed  |
| 3A.3 | Prashant | Converts to **Purchase Order**                                   | `purchase.order` (purchase) |
| 3A.4 | Prashant | **Sends PO to Vendor** (by email)                                | Email sent                  |
| 3A.5 | Amit     | Receives goods — records **Material Gate Entry**                 | `stock.picking` (incoming)  |
| 3A.6 | Pratik   | Performs **QC of Inward Material** (incoming quality inspection) | Quality check               |


**QC of inward material branches here — see Path 3B (pass) and Path 3C (fail).**

#### Path 3B — Inward Material Passes QC


| Step | Actor   | Action                                                   | Odoo Object                 |
| ---- | ------- | -------------------------------------------------------- | --------------------------- |
| 3B.1 | Pratik  | QC result: **OK** — incoming material passes             | Quality check pass          |
| 3B.2 | System  | Material **added to store** automatically                | Stock updated               |
| 3B.3 | Rajshri | Creates **Purchase Bill** (vendor bill)                  | `account.move` (in_invoice) |
| 3B.4 | —       | Flow returns to step 2.4 — raw material is now available | Continue manufacturing      |


**End of procurement sub-path.** Manufacturing flow (Path 2) continues from step 2.5 onward.

#### Path 3C — Inward Material Fails QC


| Step | Actor  | Action                                                     | Odoo Object        |
| ---- | ------ | ---------------------------------------------------------- | ------------------ |
| 3C.1 | Pratik | QC result: **Not OK** — incoming material fails inspection | Quality check fail |
| 3C.2 | Pratik | Material placed on **Hold / Reject**                       | Quality alert      |


**Decision: Return for Replacement OR Reject outright.**

##### Path 3C-i — Return for Replacement


| Step  | Actor | Action                                           | Odoo Object                         |
| ----- | ----- | ------------------------------------------------ | ----------------------------------- |
| 3Ci.1 | Amit  | Initiates **Return / Replacement to Supplier**   | `stock.picking` (return)            |
| 3Ci.2 | Amit  | Creates **Delivery Challan** for return shipment | `stock.picking` (outgoing)          |
| 3Ci.3 | —     | Waits for replacement material from vendor       | Re-enters at step 3A.5 (gate entry) |


##### Path 3C-ii — Reject (No Replacement)


| Step   | Actor   | Action                                      | Odoo Object                 |
| ------ | ------- | ------------------------------------------- | --------------------------- |
| 3Cii.1 | Rajshri | Raises **Debit Note** against the supplier  | `account.move` (debit note) |
| 3Cii.2 | —       | Procurement restarts — new PO may be needed | Re-enters at step 3A.1      |


---

## Path Summary Table


| Path      | Scenario                               | Key Steps                                                           | Ends With          |
| --------- | -------------------------------------- | ------------------------------------------------------------------- | ------------------ |
| **0**     | SO creation & dual approval            | Inquiry → Quotation → Confirm → Rajshri approves → Manohar approves | Confirmed SO       |
| **1**     | FG in stock                            | Picking Slip → PDI → Sales Invoice                                  | Customer delivery  |
| **2A**    | FG not in stock, RM available, QC pass | MO → Material issue → Manufacture → QC OK → PDI → Invoice           | Customer delivery  |
| **2B**    | FG not in stock, RM available, QC fail | Manufacture → QC fail → WIP/Hold → Rework → Re-QC                   | Loops until 2A     |
| **3A**    | RM not available — procurement         | RFQ → PO approval → Send to vendor → Gate entry                     | Inward QC          |
| **3B**    | Inward material QC pass                | QC OK → Stock updated → Purchase bill → Continue manufacturing      | Merges into Path 2 |
| **3C-i**  | Inward material QC fail — replacement  | Hold → Return to supplier → Delivery challan → Await replacement    | Re-enters 3A.5     |
| **3C-ii** | Inward material QC fail — reject       | Hold → Debit note → Re-procure                                      | Re-enters 3A.1     |


---

## Complete Happy Path (Worst Case — Nothing in Stock)

This is the full end-to-end flow when neither FG nor RM are available:

```
Tushar: Inquiry → Quotation → Confirm SO
Rajshri: Approve (Accounts)
Manohar: Approve (MD)
  → SO Confirmed
Amit: Check FG → Not available
Prashant: Create MO → Material Request
Amit: Check RM → Not available
Prashant: Create Purchase Quotation
Manohar: Approve PO
Prashant: Send PO to Vendor
  → Vendor ships materials
Amit: Material Gate Entry
Pratik: QC Inward Material → OK
  → Material added to store
Rajshri: Generate Purchase Bill
Amit: Issue material to production (Picking Slip)
Pratik: Manufacture scooter (Manufactured)
System: MO enters In QC — auto QC request created and notified to Pratik
Pratik: QC Produced Material → OK (In QC)
Pratik: Final QC Checks (In QC)
Pratik: Pass QC and Mark MO as Done (Done)
Amit: Picking Slip (delivery)
Pratik: Pre-Delivery Inspection (PDI)
Amit: Sales Invoice
  → Customer receives scooter
```

---

## Known Gaps / Issues (from workflow diagram)

These items are flagged in the original workflow diagram as requiring attention:

1. **"Issued to production" state missing** — There is no intermediate state between material request and manufacturing. Amit and Prashant can currently start production without confirming that materials have been picked/issued. A confirmation step for material receipt should be added.
2. **Supplier Invoice and invoice date not available** — The purchase bill (vendor invoice) creation step lacks clear timing. Rajshri needs the supplier invoice document and date before she can create the purchase bill in Odoo.

---

## Actor Responsibility Matrix


| Activity                      | Tushar    | Rajshri   | Manohar   | Amit      | Prashant  | Pratik    |
| ----------------------------- | --------- | --------- | --------- | --------- | --------- | --------- |
| Create Quotation / SO         | **Owner** |           |           |           |           |           |
| Approve SO (Accounts)         |           | **Owner** |           |           |           |           |
| Approve SO (MD)               |           |           | **Owner** |           |           |           |
| Check FG availability         |           |           |           | **Owner** |           |           |
| Create Manufacturing Order    |           |           |           |           | **Owner** |           |
| Check RM availability         |           |           |           | **Owner** |           |           |
| Issue material to production  |           |           |           | **Owner** |           |           |
| Create Purchase Quotation     |           |           |           |           | **Owner** |           |
| Approve Purchase Order        |           |           | **Owner** |           |           |           |
| Send PO to Vendor             |           |           |           |           | **Owner** |           |
| Material Gate Entry           |           |           |           | **Owner** |           |           |
| QC Inward Material            |           |           |           |           |           | **Owner** |
| Generate Purchase Bill        |           | **Owner** |           |           |           |           |
| Manufacturing                 |           |           |           |           |           | **Owner** |
| QC Produced Material          |           |           |           |           |           | **Owner** |
| Picking Slip (delivery)       |           |           |           | **Owner** |           |           |
| Pre-Delivery Inspection (PDI) |           |           |           |           |           | **Owner** |
| Sales Invoice                 |           |           |           | **Owner** |           |           |
| Return to Supplier            |           |           |           | **Owner** |           |           |
| Delivery Challan              |           |           |           | **Owner** |           |           |
| Raise Debit Note              |           | **Owner** |           |           |           |           |


