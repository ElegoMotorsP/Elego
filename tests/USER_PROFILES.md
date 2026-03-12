# ElegoMotors — User Profile Cards

---

## 1. Manohar Kalbhor
**Login:** manohar.kalbhor@elegomotors.com | **Dept:** Admin / Approvals

**Groups:** ERP Manager · Purchase Manager · Sales Manager · Stock Manager · MRP User + Routings · Accounting User

✅ **Can Do**
- Open and manage all modules (Settings, Purchase, Sales, Inventory, Manufacturing, Accounting)
- Approve Purchase Orders (2-step — exclusive among non-Pratik users)
- Approve Sales Orders (2-step, shared with Rajshri)
- Full accounting: post invoices, register payments, journal entries, financial reports
- Full inventory: all transfers, warehouse config, physical adjustments

🚫 **Cannot Do**
- Access HR / Employees module
- Click Produce All / Mark as Done on MOs

⭐ **Exclusive:** Only Purchase Manager — sole PO approver

---

## 2. Amit Kale
**Login:** storeelegomotors@gmail.com | **Dept:** Store Manager

**Groups:** Stock Manager · Purchase User (view only) · MRP User + Routings · Sale Salesman (view only) · Billing User (group_account_invoice) · group_store_billing

✅ **Can Do**
- Full inventory management: all transfers, Gate Entry, QC, Issue to Production, Delivery, RTV, warehouse config, physical adjustments
- View Purchase Orders (read only)
- View Sales Orders (read only)
- Create and edit Customer Invoices and Vendor Bills
- View Customer Invoices and Vendor Bills
- Create Manufacturing Orders, confirm MOs, view work orders, create/edit BOMs
- Issue material to Production

🚫 **Cannot Do**
- Create or edit Purchase Orders
- Create Sales Orders
- Approve (post) any invoice or bill
- Register payments
- Edit price or discount fields on invoices (read-only field restriction)
- Click Produce All / Mark as Done on MOs
- Open Quality module
- Create new Products

⭐ **Exclusive:** None — primary operator for store/warehouse operations

---

## 3. Prashant Khedkar
**Login:** NPD@elegomotors.com | **Dept:** Purchase

**Groups:** Purchase User · MRP User · Stock User

✅ **Can Do**
- Create, edit, confirm, and send Purchase Orders by email
- View and browse inventory / stock products (read only)
- View Manufacturing Orders, create MOs, confirm MOs, create/edit BOMs
- Process Returns to Vendor (RTV)

🚫 **Cannot Do**
- Approve Purchase Orders (Purchase Manager required)
- Create or view Sales Orders
- Open Accounting or view invoices / bills
- Issue material to Production
- Produce All / Mark as Done on MOs
- Open Quality module

⭐ **Exclusive:** None

---

## 4. Rajshri Kadam
**Login:** elegoac@gmail.com | **Dept:** Accounts

**Groups:** Accounting User · Purchase User (view only) · Sales Manager · Stock User

✅ **Can Do**
- Full accounting: view/create/edit/post Customer Invoices and Vendor Bills, register payments, raise debit notes, manual journal entries, P&L and financial reports
- Approve Sales Orders (2-step, shared with Manohar)
- Create Quotations and Sales Orders
- View Purchase Orders (read only)
- View stock products (read only)

🚫 **Cannot Do**
- Create or edit Purchase Orders
- Approve Purchase Orders
- Open Manufacturing module
- Open Quality module
- Produce All / Mark as Done on MOs

⭐ **Exclusive:** Register Payment (sole payment registrar; Manohar can also but Rajshri is the designated finance user)

---

## 5. Srushti Gund
**Login:** hrelegomotors@gmail.com | **Dept:** HR

**Groups:** HR Manager · Attendance Manager · Time Off Responsible

✅ **Can Do**
- View and manage Employee records
- Manage Attendance records
- Approve or refuse Leave / Time Off requests

🚫 **Cannot Do**
- Open Inventory, Manufacturing, Purchase, Sales, Accounting, or Quality modules

⭐ **Exclusive:** Approve / Refuse Leave (Time Off Responsible — only approver)

---

## 6. Pratik Gund
**Login:** quality.elego23@gmail.com | **Dept:** Quality / Manufacturing

**Groups:** group_manufacturing_operator (implies MRP User) · MRP Routings · Stock Manager · Quality Manager

✅ **Can Do**
- Full inventory: all transfers, Gate Entry validation, QC Pass to Store, QC Fail to Quarantine, Issue to Production, FG to Finished Goods, RTV
- Full manufacturing: view/create/confirm MOs, view work orders, create/edit BOMs, issue material
- Click **Produce All / Mark as Done** on confirmed MOs
- Open and manage Quality module

🚫 **Cannot Do**
- Open Purchase module or create POs
- Open Sales module or create SOs
- Open Accounting module
- Open HR module

⭐ **Exclusive:** Produce All / Mark as Done on MOs (group_manufacturing_operator — only Pratik can mark production complete)

---

## 7. Tushar Gaikwad
**Login:** leads@elegomotors.com | **Dept:** Sales / CRM

**Groups:** Sale Salesman · Stock User

✅ **Can Do**
- Open CRM pipeline, create and manage Leads/Opportunities
- Create and edit Quotations
- Submit Quotations as Sales Orders (goes to To Approve state)
- Create Customer Invoice from SO
- Mark Opportunity as Won
- View stock products (read only)

🚫 **Cannot Do**
- Approve his own or any Sales Order (Sales Manager required)
- Approve Purchase Orders
- Create Manufacturing Orders
- Open Accounting module
- Open Purchase module

⭐ **Exclusive:** None
