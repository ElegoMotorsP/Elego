# -*- coding: utf-8 -*-
"""ElegoMotors Access Matrix — per-user permission checkboxes on res.users.

Each x_access_* field below is a thin Boolean mirror of one res.groups
membership, keyed here by the group's XML ID. They exist so Settings →
Access Matrix (views/access_matrix_views.xml) can show every internal user
as a row and every permission as an editable checkbox column, instead of the
admin opening each user's Access Rights tab one at a time.

The matrix's row list is never hardcoded — it's whatever res.users search
returns — so a newly created user appears there automatically.

Keep _ACCESS_MATRIX_FIELDS in sync with the field declarations below AND
with the column list in views/access_matrix_views.xml.
"""
from odoo import api, fields, models

# (field_name, group xml id, section, column label)
_ACCESS_MATRIX_FIELDS = [
    ('x_access_administrator', 'base.group_system', 'Settings',
     'Administrator (Settings menu access)'),
    ('x_access_erp_manager', 'base.group_erp_manager', 'Settings',
     'ERP Manager (admin rights within installed apps)'),

    ('x_access_purchase_create', 'purchase.group_purchase_user', 'Purchase',
     'Create / Edit / Confirm PO, Send by Email'),
    ('x_access_purchase_approve', 'purchase.group_purchase_manager', 'Purchase',
     'Approve PO (2-step)'),
    ('x_access_purchase_view', 'elegomotors_setup.group_purchase_viewer', 'Purchase',
     'View POs (read-only)'),
    ('x_access_vendor_bill_view', 'elegomotors_setup.group_purchase_vendor_bill_viewer', 'Purchase',
     'View Vendor Bills (read-only)'),

    ('x_access_sale_create', 'sales_team.group_sale_salesman', 'Sales / CRM',
     'Create / Edit Quotations, Submit SO'),
    ('x_access_sale_approve', 'sales_team.group_sale_manager', 'Sales / CRM',
     'Approve SO (2-step), full pipeline'),
    ('x_access_sale_view', 'elegomotors_setup.group_sale_viewer', 'Sales / CRM',
     'View SOs (read-only)'),
    ('x_access_sale_approve_only', 'elegomotors_setup.group_sale_approver', 'Sales / CRM',
     'Approve SO only (no create)'),

    ('x_access_stock_view', 'stock.group_stock_user', 'Inventory',
     'View stock / transfers (read-only)'),
    ('x_access_stock_manage', 'stock.group_stock_manager', 'Inventory',
     'Full inventory management'),
    ('x_access_inbound_operator', 'elegomotors_setup.group_inbound_operator', 'Inventory',
     'Gate Entry + Issue to Production'),
    ('x_access_qc_pass_operator', 'elegomotors_setup.group_qc_pass_operator', 'Inventory',
     'QC Pass → Store'),
    ('x_access_fg_transfer_operator', 'elegomotors_setup.group_fg_transfer_operator', 'Inventory',
     'FG to Finished Goods transfer'),
    ('x_access_delivery_change_operator', 'elegomotors_setup.group_delivery_change_operator', 'Inventory',
     'Modify Delivery (qty / serial / bike)'),
    ('x_access_unbuild_rebuild_operator', 'elegomotors_setup.group_unbuild_rebuild_operator', 'Inventory',
     'Unbuild / Rebuild bike by serial'),

    ('x_access_mrp_view', 'mrp.group_mrp_user', 'Manufacturing',
     'View / Create / Confirm MOs'),
    ('x_access_mrp_manage', 'mrp.group_mrp_manager', 'Manufacturing',
     'Manufacturing Manager'),
    ('x_access_mrp_routings', 'mrp.group_mrp_routings', 'Manufacturing',
     'Work Orders tab + Create/Edit BOM'),
    ('x_access_manufacturing_operator', 'elegomotors_setup.group_manufacturing_operator', 'Manufacturing',
     'Produce All / Mark as Done (exclusive gate)'),

    ('x_access_account_full', 'account.group_account_user', 'Accounting',
     'Full accounting (invoices, bills, payments, reports)'),
    ('x_access_account_invoice', 'account.group_account_invoice', 'Accounting',
     'Create / edit invoices & bills'),
    ('x_access_store_billing', 'elegomotors_setup.group_store_billing', 'Accounting',
     'Store Billing (customer invoices, read-only price)'),

    ('x_access_hr_view', 'hr.group_hr_user', 'HR',
     'View Employees'),
    ('x_access_hr_manage', 'hr.group_hr_manager', 'HR',
     'Manage Employees'),
    ('x_access_hr_attendance', 'hr_attendance.group_hr_attendance_manager', 'HR',
     'Manage Attendance'),
    ('x_access_hr_leave_approve', 'hr_holidays.group_hr_holidays_responsible', 'HR',
     'Approve / Refuse Leave'),

    ('x_access_quality_view', 'quality.group_quality_user', 'Quality',
     'View QC control points / checks'),
    ('x_access_quality_manage', 'quality.group_quality_manager', 'Quality',
     'Manage QC configuration'),
    ('x_access_warranty_manage', 'elegomotors_setup.group_warranty_manager', 'Quality',
     'Approve / Reject Warranty Claims'),

    ('x_access_allow_export', 'base.group_allow_export', 'Other',
     'Allow Export (xlsx / csv)'),
]


class ResUsersAccessMatrix(models.Model):
    _inherit = 'res.users'

    x_access_role_id = fields.Many2one(
        'elegomotors.access.role', string='Access Role',
        help="Picking a role grants that role's permission bundle to this "
             "user. It only ADDS groups — it never removes a permission the "
             "user already has. Fine-tune individual permissions below or "
             "in Settings → Access Matrix.",
    )

    x_access_administrator = fields.Boolean(string='Administrator (Settings menu access)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_erp_manager = fields.Boolean(string='ERP Manager (admin rights within installed apps)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_purchase_create = fields.Boolean(string='Create / Edit / Confirm PO, Send by Email', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_purchase_approve = fields.Boolean(string='Approve PO (2-step)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_purchase_view = fields.Boolean(string='View POs (read-only)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_vendor_bill_view = fields.Boolean(string='View Vendor Bills (read-only)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_sale_create = fields.Boolean(string='Create / Edit Quotations, Submit SO', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_sale_approve = fields.Boolean(string='Approve SO (2-step), full pipeline', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_sale_view = fields.Boolean(string='View SOs (read-only)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_sale_approve_only = fields.Boolean(string='Approve SO only (no create)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_stock_view = fields.Boolean(string='View stock / transfers (read-only)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_stock_manage = fields.Boolean(string='Full inventory management', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_inbound_operator = fields.Boolean(string='Gate Entry + Issue to Production', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_qc_pass_operator = fields.Boolean(string='QC Pass → Store', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_fg_transfer_operator = fields.Boolean(string='FG to Finished Goods transfer', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_delivery_change_operator = fields.Boolean(string='Modify Delivery (qty / serial / bike)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_unbuild_rebuild_operator = fields.Boolean(string='Unbuild / Rebuild bike by serial', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_mrp_view = fields.Boolean(string='View / Create / Confirm MOs', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_mrp_manage = fields.Boolean(string='Manufacturing Manager', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_mrp_routings = fields.Boolean(string='Work Orders tab + Create/Edit BOM', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_manufacturing_operator = fields.Boolean(string='Produce All / Mark as Done (exclusive gate)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_account_full = fields.Boolean(string='Full accounting (invoices, bills, payments, reports)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_account_invoice = fields.Boolean(string='Create / edit invoices & bills', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_store_billing = fields.Boolean(string='Store Billing (customer invoices, read-only price)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_hr_view = fields.Boolean(string='View Employees', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_hr_manage = fields.Boolean(string='Manage Employees', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_hr_attendance = fields.Boolean(string='Manage Attendance', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_hr_leave_approve = fields.Boolean(string='Approve / Refuse Leave', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_quality_view = fields.Boolean(string='View QC control points / checks', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_quality_manage = fields.Boolean(string='Manage QC configuration', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_warranty_manage = fields.Boolean(string='Approve / Reject Warranty Claims', compute='_compute_access_matrix', inverse='_inverse_access_matrix')
    x_access_allow_export = fields.Boolean(string='Allow Export (xlsx / csv)', compute='_compute_access_matrix', inverse='_inverse_access_matrix')

    @api.depends('groups_id')
    def _compute_access_matrix(self):
        groups_by_field = {
            fname: self.env.ref(xmlid, raise_if_not_found=False)
            for fname, xmlid, _section, _label in _ACCESS_MATRIX_FIELDS
        }
        for user in self:
            user_group_ids = set(user.groups_id.ids)
            for fname, group in groups_by_field.items():
                user[fname] = bool(group) and group.id in user_group_ids

    def _inverse_access_matrix(self):
        # Shared by every x_access_* field: Odoo calls this once per write
        # with the new values already cached on self. Read every field for a
        # user FIRST, then issue a single groups_id write for that user —
        # writing groups_id mutates the very relation these fields depend
        # on, so interleaving reads and writes here would risk one field's
        # write invalidating another field's not-yet-read cached value.
        groups_by_field = {
            fname: self.env.ref(xmlid, raise_if_not_found=False)
            for fname, xmlid, _section, _label in _ACCESS_MATRIX_FIELDS
        }
        for user in self:
            add_ids = [g.id for fname, g in groups_by_field.items() if g and user[fname]]
            remove_ids = [g.id for fname, g in groups_by_field.items() if g and not user[fname]]
            user.write({
                'groups_id': [(4, gid) for gid in add_ids] + [(3, gid) for gid in remove_ids],
            })

    def _apply_access_role(self, role):
        """Grant every group in `role` to self, plus base.group_user so the
        user is at least an Internal User. Additive only — never removes a
        group the user already holds (see the module docstring)."""
        if not role:
            return
        base_group = self.env.ref('base.group_user', raise_if_not_found=False)
        group_ids = role.group_ids.ids + ([base_group.id] if base_group else [])
        if not group_ids:
            return
        self.write({'groups_id': [(4, gid) for gid in group_ids]})

    @api.onchange('x_access_role_id')
    def _onchange_access_role_id(self):
        if self.x_access_role_id:
            self._apply_access_role(self.x_access_role_id)

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        for user, vals in zip(users, vals_list):
            role_id = vals.get('x_access_role_id')
            if role_id:
                user._apply_access_role(self.env['elegomotors.access.role'].browse(role_id))
        return users

    def write(self, vals):
        res = super().write(vals)
        role_id = vals.get('x_access_role_id')
        if role_id:
            self._apply_access_role(self.env['elegomotors.access.role'].browse(role_id))
        return res
