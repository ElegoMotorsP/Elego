# -*- coding: utf-8 -*-
"""Give the new "Inventory: Cancel Transfers" permission to the admins.

The Cancel button on a transfer is now hidden from everyone without this
group. access_role_data.xml is noupdate, so the existing Admin role template
does not pick the new group up by itself, and the people who hold it today
must not lose the button the moment this version is installed. This adds the
group to the Admin role and to every ERP Manager (Manohar and the
Administrator). Safe to run more than once. A problem here is logged and
never stops the module update; the permission can then be ticked by hand in
Settings > Access Matrix.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            group = env.ref('elegomotors_setup.group_cancel_transfer_operator', raise_if_not_found=False)
            if not group:
                return
            role = env.ref('elegomotors_setup.access_role_admin', raise_if_not_found=False)
            if role:
                role.write({'group_ids': [(4, group.id)]})
            managers = env['res.users'].with_context(active_test=False).search(
                [('groups_id', 'in', env.ref('base.group_erp_manager').ids)])
            managers.write({'groups_id': [(4, group.id)]})
            _logger.info('Cancel Transfers permission given to %d admin user(s)', len(managers))
    except Exception:  # noqa: BLE001
        _logger.exception('Could not give the Cancel Transfers permission to the admins - '
                          'tick it in Settings > Access Matrix instead')
