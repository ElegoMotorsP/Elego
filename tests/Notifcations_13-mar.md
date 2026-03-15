# NOTIFICATIONS

# ElegoMotors — Notification & Subscription Reference

### Updated: 13 Mar 8 AM

## Legend

| Symbol | Meaning |
| --- | --- |
| `N` | Notified (receives chatter message / email notification) |
| `S` | Auto-Subscribed (follower on the record) |
| `—` | Not notified |

---

## Notification Matrix

| # | Event | Manohar | Amit | Prashant | Rajshri | Srushti | Pratik | Tushar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Sales** |  |  |  |  |  |  |  |  |
| 1 | SO Created | N | N | — | N | — | — | N (salesman) |
| 2 | SO → To Approve | N (approver) | — | — | N (approver) | — | — | N (submitter) |
| 3 | SO Confirmed (Approved) | — | N | — | — | — | — | N |
| **Purchase** |  |  |  |  |  |  |  |  |
| 4 | PO Created | N | — | N | — | — | — | — |
| 5 | PO → To Approve | N | — | N | — | — | — | — |
| 6 | PO Approved | N | N | N | — | — | — | — |
| **Manufacturing** |  |  |  |  |  |  |  |  |
| 7 | MO Created | — | N | — | — | — | N | — |
| 8 | MO Confirmed | — | N | — | — | — | N | — |
| 9 | MO Marked as Done | — | N | N | — | — | N | — |
| **Inventory** |  |  |  |  |  |  |  |  |
| 10 | Gate Entry Validated | — | N | N | — | — | N | — |
| 11 | Stock Picking Created | — | N | N | — | — | N | — |
| **Accounting** |  |  |  |  |  |  |  |  |
| 12 | Customer Invoice Created | N | N | — | N | — | — | N |
| 13 | Customer Invoice Posted | N | N | — | N | — | — | N |
| 14 | Vendor Bill Created | N | N | N | N | — | — | — |
| 15 | Vendor Bill Posted | N | N | N | N | — | — | — |

---