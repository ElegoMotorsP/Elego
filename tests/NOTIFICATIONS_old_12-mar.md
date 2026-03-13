# ElegoMotors — Notification & Subscription Reference

## Legend

| Symbol | Meaning |
|--------|---------|
| `N` | Notified (receives chatter message / email notification) |
| `S` | Auto-Subscribed (follower on the record) |
| `—` | Not notified |

---

## Notification Matrix

| # | Event | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
|---|-------|---------|------|----------|---------|---------|--------|--------|
| **Sales** |||||||||
| 1 | SO Created | N | N | — | N | — | — | N (salesman) |
| 2 | SO → To Approve | N (approver) | — | — | N (approver) | — | — | N (submitter) |
| 3 | SO Confirmed (Approved) | — | N | — | — | — | — | N |
| **Purchase** |||||||||
| 4 | PO Created | — | — | N | — | — | — | — |
| 5 | PO → To Approve | — | — | N | — | — | — | — |
| 6 | PO Approved | — | N | N | — | — | — | — |
| **Manufacturing** |||||||||
| 7 | MO Created | — | N | — | — | — | N | — |
| 8 | MO Confirmed | — | N | — | — | — | N | — |
| 9 | MO Marked as Done | — | N | — | — | — | N | N |
| **Inventory** |||||||||
| 10 | Gate Entry Validated | — | N | N | — | — | — | — |
| 11 | Stock Picking Created | — | N | — | — | — | — | — |
| **Accounting** |||||||||
| 12 | Customer Invoice Created | — | N | — | N | — | — | N |
| 13 | Customer Invoice Posted | — | N | — | N | — | — | N |
| 14 | Vendor Bill Created | — | N | N | N | — | — | — |
| 15 | Vendor Bill Posted | — | N | N | N | — | — | — |

---

## Per-User Summary

| User | Notified On |
|------|------------|
| **Manohar** | SO Created, SO To Approve (as approver) |
| **Amit** | SO Confirmed, PO Approved, MO Created, MO Confirmed, MO Done, Gate Entry Validated, Stock Picking Created, Customer Invoice Created/Posted, Vendor Bill Created/Posted |
| **Prashant** | PO Created, PO To Approve, PO Approved, Gate Entry Validated, Vendor Bill Created/Posted |
| **Rajshri** | SO Created, SO To Approve (as approver), Customer Invoice Created/Posted, Vendor Bill Created/Posted |
| **Srushti** | None |
| **Pratik** | MO Created, MO Confirmed, MO Done |
| **Tushar** | SO Created, SO To Approve (submitter awareness), SO Confirmed, MO Done, Customer Invoice Created/Posted |

---

## Notes

- **SO To Approve:** Both Rajshri and Manohar are notified as approvers; Tushar is notified as the submitter (awareness only — he cannot approve).
- **PO flow:** Prashant is notified at every PO step (created, to approve, approved) — he is the submitter and needs to know when it clears. Amit is notified only on PO Approved, as it triggers the Gate Entry he handles.
- **MO Done:** Amit (store — to prepare FG transfer), Pratik (QC sign-off), and Tushar (sales — to know FG is ready for delivery) are all notified.
- **Accounting events:** Amit is notified on all invoice/bill events due to his `group_store_billing` role — he creates them but cannot post. Prashant is on vendor bill events as the PO originator.
- **Srushti** receives no operational notifications — her scope is HR only.
- Notification rules are defined in `notification_rules.xml` with `active=True`. Tests in Suite 8 verify each event and gracefully skip if the mail server is not configured.
