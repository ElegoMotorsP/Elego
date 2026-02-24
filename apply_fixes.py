#!/usr/bin/env python3
"""
Apply stock picking type fixes directly via XML-RPC
"""

import xmlrpc.client

url = "http://localhost:8069"
db = "elegomotors"
username = "admin"
password = "admin"

print("Connecting to Odoo...")
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, username, password, {})
print(f"Authenticated as user ID: {uid}\n")

models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# Get location and warehouse IDs
ego_quarantine = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'elegomotors_setup'], ['name', '=', 'location_ego_quarantine']]],
    {'fields': ['res_id']})[0]['res_id']

suppliers_loc = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'stock'], ['name', '=', 'stock_location_suppliers']]],
    {'fields': ['res_id']})[0]['res_id']

warehouse = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'stock'], ['name', '=', 'warehouse0']]],
    {'fields': ['res_id']})[0]['res_id']

gate_entry = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'elegomotors_setup'], ['name', '=', 'picking_type_gate_entry']]],
    {'fields': ['res_id']})[0]['res_id']

delivery = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'elegomotors_setup'], ['name', '=', 'picking_type_delivery']]],
    {'fields': ['res_id']})[0]['res_id']

ego_qc_inward = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'elegomotors_setup'], ['name', '=', 'location_ego_qc_inward']]],
    {'fields': ['res_id']})[0]['res_id']

ego_fg = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'elegomotors_setup'], ['name', '=', 'location_ego_fg']]],
    {'fields': ['res_id']})[0]['res_id']

print(f"Found locations and operation types:")
print(f"  - EGO/Quarantine: {ego_quarantine}")
print(f"  - Suppliers: {suppliers_loc}")
print(f"  - Gate Entry operation: {gate_entry}")
print(f"  - Delivery operation: {delivery}")
print(f"  - Warehouse: {warehouse}\n")

# Step 1: Create "Returns to Vendors" operation type
print("1. Creating 'Returns to Vendors' operation type...")
try:
    vendor_returns_id = models.execute_kw(db, uid, password,
        'stock.picking.type', 'create',
        [{
            'name': 'Returns to Vendors',
            'code': 'outgoing',
            'sequence_code': 'RTV',
            'warehouse_id': warehouse,
            'default_location_src_id': ego_quarantine,
            'default_location_dest_id': suppliers_loc,
            'color': 1,
            'sequence': 22,
        }])
    print(f"   Created vendor returns operation type (ID {vendor_returns_id})")

    # Create XML ID for it
    models.execute_kw(db, uid, password,
        'ir.model.data', 'create',
        [{
            'module': 'elegomotors_setup',
            'name': 'picking_type_vendor_returns',
            'model': 'stock.picking.type',
            'res_id': vendor_returns_id,
        }])
except Exception as e:
    print(f"   ERROR: {e}")
    # Try to find existing one
    existing = models.execute_kw(db, uid, password,
        'stock.picking.type', 'search',
        [[['name', '=', 'Returns to Vendors']]])
    if existing:
        vendor_returns_id = existing[0]
        print(f"   Found existing vendor returns (ID {vendor_returns_id})")
    else:
        print("   Could not create vendor returns operation type")
        exit(1)

# Step 2: Update Gate Entry return type
print("\n2. Updating Gate Entry return type...")
models.execute_kw(db, uid, password,
    'stock.picking.type', 'write',
    [[gate_entry], {'return_picking_type_id': vendor_returns_id}])
print(f"   Set Gate Entry return type -> Returns to Vendors")

# Step 3: Update Delivery return type
print("\n3. Updating Delivery return type...")
models.execute_kw(db, uid, password,
    'stock.picking.type', 'write',
    [[delivery], {'return_picking_type_id': gate_entry}])
print(f"   Set Delivery return type -> Gate Entry")

# Step 4: Update warehouse to use Gate Entry as primary receipt
print("\n4. Updating warehouse configuration...")
models.execute_kw(db, uid, password,
    'stock.warehouse', 'write',
    [[warehouse], {
        'in_type_id': gate_entry,
        'out_type_id': delivery,
    }])
print(f"   Set warehouse in_type -> Gate Entry")
print(f"   Set warehouse out_type -> Delivery (PDI)")

# Step 5: Update default Receipts and Delivery operation types
print("\n5. Updating default operation types as fallback...")
default_in = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'stock'], ['name', '=', 'picking_type_in']]],
    {'fields': ['res_id']})[0]['res_id']

default_out = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'stock'], ['name', '=', 'picking_type_out']]],
    {'fields': ['res_id']})[0]['res_id']

models.execute_kw(db, uid, password,
    'stock.picking.type', 'write',
    [[default_in], {
        'default_location_dest_id': ego_qc_inward,
        'return_picking_type_id': vendor_returns_id,
    }])
print(f"   Updated default Receipts destination -> EGO/QC Inward")

models.execute_kw(db, uid, password,
    'stock.picking.type', 'write',
    [[default_out], {
        'default_location_src_id': ego_fg,
        'return_picking_type_id': gate_entry,
    }])
print(f"   Updated default Delivery source -> EGO/Finished Goods")

print("\n" + "="*60)
print("All fixes applied successfully!")
print("="*60)
print("\nWhat changed:")
print("  1. Created 'Returns to Vendors' operation type (RTV)")
print("  2. Gate Entry returns now go to 'Returns to Vendors'")
print("  3. Delivery returns now go to 'Gate Entry'")
print("  4. Warehouse uses Gate Entry for all PO receipts")
print("  5. All receipts go to 'EGO/QC Inward' location")
print("\nRefresh browser and test:")
print("  1. Create a PO -> Confirm")
print("  2. Receipt should be 'Gate Entry (Inward)' type")
print("  3. Receipt destination: 'WH/Stock/EGO/QC Inward'")
print("  4. Validate receipt -> Stock moves to QC Inward")
print("  5. Create internal transfer: QC Inward -> Store")
