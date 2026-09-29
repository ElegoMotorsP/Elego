# -*- coding: utf-8 -*-
"""Access Role Templates — reusable permission bundles for onboarding.

Lets the admin (Manohar) pick a role (e.g. "Store Manager") on a user and
instantly grant that role's whole group bundle instead of ticking each
permission by hand. Applying a role is ADDITIVE ONLY — it adds the role's
groups but never removes a group the user already has — so picking a role
can never silently revoke something granted individually via the Access
Matrix (Settings → Access Matrix). See models/res_users_access.py.
"""
from odoo import fields, models


class ElegomotorsAccessRole(models.Model):
    _name = 'elegomotors.access.role'
    _description = 'Access Role Template'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    group_ids = fields.Many2many(
        'res.groups', string='Grants',
        help='Selecting this role on a user adds all of these groups to '
             'them. Groups the user already has that are not in this list '
             'are left untouched.',
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'A role with this name already exists.'),
    ]
