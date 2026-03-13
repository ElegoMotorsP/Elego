# ACCESS_MATRIX

updated: 13 march 9 am 

# ElegoMotors — Unified Access Matrix

## Legend

| Symbol | Meaning |
| --- | --- |
| `✓` | Full access (view, create, edit, delete) |
| `R` | Read / View Only |
| `—` | No Access (menu hidden or Access Error) |
| `★` | Exclusive — only this user has this right |
| `r` | Read-Only Field (visible but locked) |

---

## Matrix

| Domain | Capability | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Settings** | Open Settings | ✓ | — | — | — | — | — | — |
| **Purchase** | View POs | ✓ | R | ✓ | R | — | — | — |
|  | Create PO | ✓ | — | ✓ | — | — | — | — |
|  | Edit PO (before confirm) | ✓ | — | ✓ | — | — | — | — |
|  | Confirm / Submit PO | ✓ | — | ✓ | — | — | — | — |
|  | Approve PO (2-step) | ★ | — | — | — | — | — | — |
|  | Send PO by Email | ✓ | — | ✓ | — | — | — | — |
| **Sales / CRM** | View SOs | ✓ | R | — | ✓ | — | — | ✓ |
|  | Create Quotation | ✓ | — | — | — | — | — | ✓ |
|  | Edit Quotation | ✓ | — | — | — | — | — | ✓ |
|  | Submit SO for Approval | ✓ | — | — | — | — | — | ✓ |
|  | Approve SO (2-step) | ✓ | — | — | ✓ | — | — | — |
|  | Create Invoice from SO | ✓ | ✓ | — | ✓ | — | — | — |
|  | Mark Opportunity Won | ✓ | — | — | ✓ | — | — | ✓ |
| **Inventory** | View stock products | ✓ | ✓ | ✓ | R | — | ✓ | R |
|  | View all transfers | ✓ | ✓ | ✓ | R | — | — | R |
|  | Validate Gate Entry receipt | ✓ | ✓ | — | — | — | — | — |
|  | Validate QC Pass to Store | ✓ | —  | — | — | — | ✓ | — |
|  | Validate QC Fail to Quarantine | ✓ | ✓ | — | — | — | ✓ | — |
|  | Issue to Production | ✓ | ✓ | — | — | — | — | — |
|  | RM to FG | ✓ | — | ✓ | — | — | ✓ | — |
|  | Validate Delivery (PDI + Dispatch) | ✓ | ✓ | — | — | — | ✓ | — |
|  | Return to Vendor (RTV) | ✓ | ✓ | ✓ | — | — | ✓ | — |
|  | Warehouse / Location config | ✓ | ✓ | — | — | — | — | — |
|  | Inventory adjustment (Physical) | ✓ | — | — | — | — | — | — |
| **Manufacturing** | View MOs | ✓ | ✓ | ✓ | — | — | ✓ | — |
|  | Create MO | ✓ | — | ✓ | — | — | ✓ | — |
|  | Confirm MO | ✓ | —  | ✓ | — | — | ✓ | — |
|  | View Work Orders | ✓ | ✓ | ✓ | — | — | — | — |
|  | Produce All / Mark as Done | — | — | ✓ | — | — | ★ | — |
|  | Create / Edit BOM | ✓ | — | ✓ | — | — | — | — |
|  | Issue Material to Production | ✓ | ✓ | — | — | — | — | — |
| **Accounting** | View Customer Invoices | ✓ | ✓ | — | ✓ | — | — | — |
|  | Create / Edit Customer Invoice | ✓ | ✓ | — | ✓ | — | — | — |
|  | Price & Discount fields on Invoice | ✓ | r | — | ✓ | — | — | — |
|  | Post (Confirm) Customer Invoice | ✓ | — | — | ✓ | — | — | — |
|  | View Vendor Bills | ✓ | ✓ | ✓ | ✓ | — | — | — |
|  | Create / Edit Vendor Bill | ✓ | — | — | ✓ | — | — | — |
|  | Post Vendor Bill | ✓ | — | — | ✓ | — | — | — |
|  | Register Payment | ✓ | — | — | ★ | — | — | — |
|  | Raise Debit Note on Vendor Bill | ✓ | — | — | ✓ | — | — | — |
|  | Journal Entries (manual JV) | ✓ | — | — | ✓ | — | — | — |
|  | P&L / Financial Reports | ✓ | — | — | ✓ | — | — | — |
| **HR** | View Employees | ✓ | — | — | — | ✓ | — | — |
|  | Manage Attendance | — | — | — | — | ✓ | — | — |
|  | Approve / Refuse Leave | — | — | — | — | ★ | — | — |
| **Quality** | Open Quality module | ✓ | — | — | — | — | ✓ | — |
|  | Create Product | ✓ | — | — | — | — | — | — |

create product should be in inventory, only rights to manohar sir 

FG QC Points check INward QC checks QC Parameter product wise set view only manohar sir.