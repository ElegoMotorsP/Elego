# -*- coding: utf-8 -*-
"""Self-service Access Control matrix — lets Manohar (base.group_system)
grant or revoke any of the 93 operations from
Elego_Odoo_Operation_Wise_Access_Matrix.xlsx for any employee directly,
with immediate effect (no developer, no code push, no module upgrade).

Each row's group_id is the ONE real Odoo security group that actually
enforces that operation — confirmed against an existing groups="..."
attribute on the real button/menu, or (for a handful of native rows) the
existing native group already relied on elsewhere in this module. Where no
such group exists yet, group_id is left empty and the row shows as "Not
Yet Enforced": toggling it would have no real effect, so the UI must not
let it pretend otherwise. A follow-up phase (see the "Backlog" section of
the New Bike Model / Access Control plan) adds the missing groups/rules
module by module and only then fills in group_id here.

granted_user_ids is not a separate permissions record — editing it directly
adds/removes the user from group_id.users. There is nothing to keep in
sync; the grid IS the group membership.
"""
from odoo import api, fields, models


class ElegomotorsAccessOperation(models.Model):
    _name = 'elegomotors.access.operation'
    _description = 'Access Control Operation'
    _order = 'sequence, id'

    sequence = fields.Integer(required=True)
    module = fields.Char(required=True)
    menu = fields.Char(string='Menu / View')
    name = fields.Char(string='Operation', required=True)
    access_type = fields.Selection([
        ('view', 'View'),
        ('report', 'Report'),
        ('operate', 'Operate'),
        ('approve', 'Approve'),
        ('admin', 'Admin'),
        ('export', 'Export'),
        ('delete', 'Delete'),
    ], required=True)
    sensitivity = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], required=True)
    business_purpose = fields.Text()
    group_id = fields.Many2one(
        'res.groups', string='Enforcing Group',
        help='The Odoo security group that actually grants this operation. '
             'Empty means nothing in the system enforces this split yet.',
    )
    is_wired = fields.Boolean(compute='_compute_status', store=True)
    not_implemented = fields.Boolean(
        string='Feature Not Built',
        help='The underlying feature does not exist in this system yet '
             '(e.g. Repair Orders) — access cannot be granted until it is built.',
    )
    status_label = fields.Char(compute='_compute_status', store=True)
    granted_user_ids = fields.Many2many(
        'res.users', string='Granted To',
        compute='_compute_granted_user_ids', inverse='_inverse_granted_user_ids',
        help='Add or remove a person here to grant or revoke this operation '
             'for them, immediately — this list IS their group membership, '
             'not a record of it.',
    )

    @api.depends('group_id', 'not_implemented')
    def _compute_status(self):
        for rec in self:
            rec.is_wired = bool(rec.group_id)
            if rec.not_implemented:
                rec.status_label = 'Feature Not Built'
            elif rec.group_id:
                rec.status_label = 'Live'
            else:
                rec.status_label = 'Not Yet Enforced'

    @api.depends('group_id', 'group_id.users')
    def _compute_granted_user_ids(self):
        for rec in self:
            rec.granted_user_ids = rec.group_id.users if rec.group_id else False

    def _inverse_granted_user_ids(self):
        for rec in self:
            if not rec.group_id:
                continue
            rec.group_id.sudo().write({'users': [(6, 0, rec.granted_user_ids.ids)]})
