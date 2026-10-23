# -*- coding: utf-8 -*-
"""Give the new "Inventory: Scan Bike Serials (Deliveries)" permission to
everyone who can scan bikes today.

The Scan Bike Serials button on a delivery used to be shown to the holders of
"Inventory: Inbound / Issue Operator" and to ERP Managers. It is now its own
permission. So nobody loses the button when this version installs, the
permission is given to every current holder of either of those two groups,
and added to the Admin and Store Manager role templates (those records are
noupdate, so the XML change does not reach the existing ones). Safe to run
more than once. A problem here is logged and never stops the module update;
the permission can then be ticked by hand in Settings > Access Matrix.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            group = env.ref('elegomotors_setup.group_scan_bike_operator', raise_if_not_found=False)
            if not group:
                return
            for xmlid in ('elegomotors_setup.access_role_admin', 'elegomotors_setup.access_role_store_manager'):
                role = env.ref(xmlid, raise_if_not_found=False)
                if role:
                    role.write({'group_ids': [(4, group.id)]})
            source = env.ref('elegomotors_setup.group_inbound_operator') | env.ref('base.group_erp_manager')
            users = env['res.users'].with_context(active_test=False).search([('groups_id', 'in', source.ids)])
            users.write({'groups_id': [(4, group.id)]})
            _logger.info('Scan Bike Serials permission given to %d user(s)', len(users))
    except Exception:  # noqa: BLE001
        _logger.exception('Could not give the Scan Bike Serials permission to the current scanners - '
                          'tick it in Settings > Access Matrix instead')
