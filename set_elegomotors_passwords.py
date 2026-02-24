#!/usr/bin/env python3
"""
Set ElegoMotors user passwords (one-time for existing DBs where XML noupdate skipped them).

Run from Odoo shell so 'env' exists, e.g.:
  odoo-bin shell -d YOUR_DATABASE
  >>> exec(open('set_elegomotors_passwords.py').read())

On odoo.sh: use the shell from the runbot/SSH or one-off job and same pattern.
"""
from elegomotors_setup.hooks import _USER_PASSWORDS

for xml_id, password in _USER_PASSWORDS.items():
    try:
        user = env.ref(xml_id, raise_if_not_found=False)
        if user:
            user.password = password
            print("Set password for", user.login)
    except Exception as e:
        print("Skip", xml_id, e)
