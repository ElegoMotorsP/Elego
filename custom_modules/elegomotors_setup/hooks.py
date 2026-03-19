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
