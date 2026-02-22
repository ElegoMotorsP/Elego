#!/usr/bin/env python3
"""
Enable Work Orders feature (mrp.group_mrp_routings) for all users
"""

import xmlrpc.client

url = "http://localhost:8069"
db = "elegomotors"
username = "admin"
password = "admin"

# Authenticate
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, username, password, {})
print(f"Authenticated as user ID: {uid}")

# Connect to object endpoint
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

# Find base.group_user via ir.model.data
user_group_ref = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'base'], ['name', '=', 'group_user']]],
    {'fields': ['res_id']})

if not user_group_ref:
    print("ERROR: Could not find 'base.group_user' XML ID")
    exit(1)

user_group_id = user_group_ref[0]['res_id']
print(f"Found 'base.group_user' group: ID {user_group_id}")

# Find mrp.group_mrp_routings via ir.model.data
routing_group_ref = models.execute_kw(db, uid, password,
    'ir.model.data', 'search_read',
    [[['module', '=', 'mrp'], ['name', '=', 'group_mrp_routings']]],
    {'fields': ['res_id']})

if not routing_group_ref:
    print("ERROR: Could not find 'mrp.group_mrp_routings' XML ID")
    print("Make sure the MRP module is installed.")
    exit(1)

routing_group_id = routing_group_ref[0]['res_id']
print(f"Found 'mrp.group_mrp_routings' group: ID {routing_group_id}")

# Get current implied_ids of user_group
user_group = models.execute_kw(db, uid, password,
    'res.groups', 'read',
    [user_group_id], {'fields': ['implied_ids']})

current_implied = user_group[0]['implied_ids']
print(f"Current implied groups: {current_implied}")

# Add routing_group to implied_ids if not already present
if routing_group_id in current_implied:
    print("\n✓ 'mrp.group_mrp_routings' is already implied by 'base.group_user'")
    print("Work Orders feature is already enabled!")
else:
    # Use (4, id) to add link without removing existing
    models.execute_kw(db, uid, password,
        'res.groups', 'write',
        [[user_group_id], {'implied_ids': [(4, routing_group_id, 0)]}])

    print(f"\n✓ Added 'mrp.group_mrp_routings' (ID {routing_group_id}) to 'base.group_user' implied groups")
    print("\n🎉 Work Orders feature is now enabled!")
    print("\n📌 Next steps:")
    print("   1. Refresh your browser (Ctrl+Shift+R)")
    print("   2. Go to Manufacturing → Operations → Manufacturing Orders")
    print("   3. Create a new MO for product 'ElegoMotors EV Scooter EGO-S1'")
    print("   4. The 'Work Center' field should now be populated automatically!")
