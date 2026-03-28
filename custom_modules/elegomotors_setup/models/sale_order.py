# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pending_approval = fields.Boolean(
        string="Pending Approval", default=False, copy=False
    )
    approval_accounts = fields.Boolean(
        string="Accounts Approved", default=False, copy=False
    )
    approval_manohar = fields.Boolean(
        string="MD Approved", default=False, copy=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        # group_sale_viewer holders (Amit) can read SOs/Quotations but not
        # create new ones. Superuser and sudo() environments are exempt so
        # Odoo's own test suite can still create SOs freely.
        if (
            not self.env.su
            and self.env.user.has_group('elegomotors_setup.group_sale_viewer')
        ):
            raise AccessError(
                'Sales viewers cannot create new Sales Orders or Quotations. '
                'Ask Tushar (Sales) or Manohar (Admin) to raise the order.'
            )
        # group_sale_approver holders (Rajshri) can APPROVE SOs but not create them.
        # Rajshri retains sales_team.group_sale_manager for the approval button but
        # this check prevents her from raising new Quotations/SOs (13-Mar update).
        if (
            not self.env.su
            and self.env.user.has_group('elegomotors_setup.group_sale_approver')
        ):
            raise AccessError(
                'Sales approvers cannot create new Sales Orders or Quotations. '
                'Ask Tushar (Sales) or Manohar (Admin) to raise the order.'
            )
        return super().create(vals_list)

    def action_confirm(self):
        for order in self:
            # Already pending — do not re-trigger; approvers need to act
            if order.pending_approval:
                return False
            # No approval yet — hold in draft and notify
            if not (order.approval_accounts or order.approval_manohar):
                order.pending_approval = True
                # Mention approvers in chatter so they receive an inbox notification
                rajshri = self.env.ref(
                    'elegomotors_setup.user_ego_rajshri', raise_if_not_found=False
                )
                manohar = self.env.ref(
                    'elegomotors_setup.user_ego_manohar', raise_if_not_found=False
                )
                partner_ids = []
                if rajshri:
                    partner_ids.append(rajshri.partner_id.id)
                if manohar:
                    partner_ids.append(manohar.partner_id.id)
                order.message_post(
                    body=Markup(
                        "This Sales Order is awaiting approval before it can be confirmed. "
                        "Please review and click <b>Approve (Accounts)</b> or <b>Approve (MD)</b> — either approval is sufficient."
                    ),
                    partner_ids=partner_ids,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
                return False
        return super().action_confirm()

    def action_approve_accounts(self):
        self.ensure_one()
        if not (
            self.env.su
            or self.env.user.has_group('elegomotors_setup.group_sale_approver')
        ):
            raise AccessError('Only the Accounts approver (Rajshri) can record Accounts approval.')
        if not self.pending_approval:
            raise AccessError('This Sales Order is not pending approval.')
        self.approval_accounts = True
        self.message_post(
            body=f"Accounts approval recorded by {self.env.user.name}.",
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        self._try_confirm_if_approved()

    def action_approve_manohar(self):
        self.ensure_one()
        if not (
            self.env.su
            or self.env.user.has_group('base.group_erp_manager')
        ):
            raise AccessError('Only the MD (Manohar) can record MD approval.')
        if not self.pending_approval:
            raise AccessError('This Sales Order is not pending approval.')
        self.approval_manohar = True
        self.message_post(
            body=f"MD approval recorded by {self.env.user.name}.",
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        self._try_confirm_if_approved()

    def _try_confirm_if_approved(self):
        self.ensure_one()
        if self.approval_accounts or self.approval_manohar:
            self.pending_approval = False
            super(SaleOrder, self).action_confirm()

    def action_reject(self):
        self.ensure_one()
        if not (
            self.env.su
            or self.env.user.has_group('elegomotors_setup.group_sale_approver')
            or self.env.user.has_group('base.group_erp_manager')
        ):
            raise AccessError('Only the designated approvers can reject a Sales Order.')
        if not self.pending_approval:
            raise AccessError('This Sales Order is not pending approval.')
        self.write({
            'pending_approval': False,
            'approval_accounts': False,
            'approval_manohar': False,
        })
        self.message_post(
            body=f"Sales Order rejected by {self.env.user.name} — returned to draft.",
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        if self.state not in ('draft', 'cancel'):
            self.action_cancel()
        if self.state == 'cancel':
            self.action_draft()
