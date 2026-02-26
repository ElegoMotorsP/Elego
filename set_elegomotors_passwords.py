#!/usr/bin/env python3
"""
Set ElegoMotors user passwords (one-time for existing DBs where XML noupdate skipped them).

Run from Odoo shell so 'env' exists, e.g.:
  odoo-bin shell -d elegomotors-stage-main-28887221
  >>> exec(open('set_elegomotors_passwords.py').read())

On odoo.sh stage: DB name is elegomotors-stage-main-28887221 (see odoo.log).
If no "Set password for" lines appear, install ElegoMotors Workflow Setup from Apps first.
"""
_USER_PASSWORDS = {
    "elegomotors_setup.user_ego_manohar": "manohar@123",
    "elegomotors_setup.user_ego_amit": "amitkale@123",
    "elegomotors_setup.user_ego_prashant": "prashant@123",
    "elegomotors_setup.user_ego_rajshri": "rajshri@123",
    "elegomotors_setup.user_ego_srushti": "srusti@123",
    "elegomotors_setup.user_ego_pratik": "pratik@123",
    "elegomotors_setup.user_ego_tushar": "tushar@123",
}
for xml_id, password in _USER_PASSWORDS.items():
    try:
        user = env.ref(xml_id, raise_if_not_found=False)
        if user:
            user.password = password
            print("Set password for", user.login)
        else:
            print("User not found:", xml_id, "(install elegomotors_setup from Apps?)")
    except Exception as e:
        print("Skip", xml_id, e)
