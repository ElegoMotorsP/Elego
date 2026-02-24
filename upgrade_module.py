#!/usr/bin/env python3
"""
Upgrade elegomotors_setup module via XML-RPC
"""

import xmlrpc.client

url = "http://localhost:8069"
db = "elegomotors"
username = "admin"
password = "admin"

print("Connecting to Odoo...")
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, username, password, {})
print(f"Authenticated as user ID: {uid}")

models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# Find elegomotors_setup module
module = models.execute_kw(db, uid, password,
    'ir.module.module', 'search_read',
    [[['name', '=', 'elegomotors_setup']]],
    {'fields': ['name', 'state']})

if not module:
    print("ERROR: elegomotors_setup module not found!")
    exit(1)

module_id = module[0]['id']
module_state = module[0]['state']
print(f"Found module 'elegomotors_setup' (ID {module_id}), state: {module_state}")

# Trigger upgrade
print("\nTriggering module upgrade...")
try:
    models.execute_kw(db, uid, password,
        'ir.module.module', 'button_immediate_upgrade',
        [[module_id]])
    print("Module upgrade completed successfully!")
    print("\nChanges applied:")
    print("  - Added 'Returns to Vendors' operation type")
    print("  - Fixed return types for Gate Entry and Delivery")
    print("  - Updated warehouse to use Gate Entry as primary receipt")
    print("\nRefresh your browser and verify:")
    print("  1. Create a PO and confirm it")
    print("  2. Receipt should appear with 'Gate Entry (Inward)' operation type")
    print("  3. Receipt destination location should be 'EGO/QC Inward'")
except Exception as e:
    print(f"ERROR during upgrade: {e}")
    print("\nTrying alternative upgrade method...")
    try:
        models.execute_kw(db, uid, password,
            'ir.module.module', 'button_upgrade',
            [[module_id]])
        print("Upgrade queued. The server may need to restart to apply changes.")
    except Exception as e2:
        print(f"ERROR: {e2}")
