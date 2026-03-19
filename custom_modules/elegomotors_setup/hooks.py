# Temporary first-login passwords for elegomotors_setup users (change after first login).
_USER_PASSWORDS = {
    "elegomotors_setup.user_ego_manohar": "manohar@123",
    "elegomotors_setup.user_ego_amit": "amitkale@123",
    "elegomotors_setup.user_ego_prashant": "prashant@123",
    "elegomotors_setup.user_ego_rajshri": "rajshri@123",
    "elegomotors_setup.user_ego_srushti": "srusti@123",
    "elegomotors_setup.user_ego_pratik": "pratik@123",
    "elegomotors_setup.user_ego_tushar": "tushar@123",
}


def post_init_hook(env):
    for xml_id, password in _USER_PASSWORDS.items():
        try:
            user = env.ref(xml_id, raise_if_not_found=False)
            if user:
                user.password = password
        except Exception:
            pass

    # Set company currency to INR via SQL to bypass the ORM guard that blocks
    # currency changes when journal items already exist (l10n_in creates them
    # during its own installation, before this module's data files run).
    env.cr.execute("""
        UPDATE res_company
        SET currency_id = (SELECT id FROM res_currency WHERE name = 'INR' LIMIT 1)
        WHERE id = (SELECT res_company_id FROM res_users WHERE id = 1)
          AND EXISTS (SELECT 1 FROM res_currency WHERE name = 'INR')
    """)
