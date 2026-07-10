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
    rejection_reason = fields.Text(
        string="Rejection Reason", copy=False, readonly=True
    )
    sale_order_number = fields.Char(
        string="Sales Order Number", copy=False, readonly=True
    )

    def write(self, vals):
        result = super().write(vals)
        # Assign the Sales Order Number the first time an order is confirmed.
        # Hooked on write() rather than action_confirm()/_try_confirm_if_approved()
        # because every path that flips state to 'sale' ultimately persists
        # through write() — this is the one hook guaranteed to catch it.
        if vals.get('state') == 'sale':
            for order in self:
                if not order.sale_order_number:
                    order.sale_order_number = (
                        self.env['ir.sequence'].sudo().next_by_code('sale.order.confirmed') or '/'
                    )
        return result

    @api.model
    def _backfill_sale_order_numbers(self):
        """One-time (idempotent) fix for orders confirmed before this field
        existed. Called from company_config_data.xml on every upgrade.
        """
        orders = self.search([
            ('state', '=', 'sale'),
            ('sale_order_number', '=', False),
        ], order='create_date asc')
        for order in orders:
            order.sale_order_number = (
                self.env['ir.sequence'].sudo().next_by_code('sale.order.confirmed') or '/'
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
                # Clear any stale rejection banner now that the order is being
                # resubmitted for approval.
                order.rejection_reason = False
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

    def action_create_invoice(self):
        """Block invoice creation from salespeople.
        Only users with account.group_account_invoice (Amit, Rajshri, Manohar)
        may trigger the Create Invoice flow from a Sales Order.
        Using a Python override because the button name differs between
        Odoo 18 Community and Enterprise, making a view-level XPath unreliable.
        """
        if (
            not self.env.su
            and not self.env.user.has_group('account.group_account_invoice')
        ):
            raise AccessError(
                'Only accounting users (Amit / Rajshri / Manohar) can create '
                'invoices from Sales Orders.'
            )
        return super().action_create_invoice()

    def _do_reject(self, reason):
        """Reject a pending Sales Order with a mandatory reason.
        Called from sale.order.reject.wizard's confirm button — the wizard
        already enforces `reason` as required, this re-checks server-side.
        """
        self.ensure_one()
        if not (
            self.env.su
            or self.env.user.has_group('elegomotors_setup.group_sale_approver')
            or self.env.user.has_group('base.group_erp_manager')
        ):
            raise AccessError('Only the designated approvers can reject a Sales Order.')
        if not self.pending_approval:
            raise AccessError('This Sales Order is not pending approval.')
        if not reason or not reason.strip():
            raise AccessError('A rejection reason is required.')
        self.write({
            'pending_approval': False,
            'approval_accounts': False,
            'approval_manohar': False,
            'rejection_reason': reason,
        })
        self.message_post(
            body=Markup(
                f"Sales Order rejected by {self.env.user.name} — returned to draft.<br/>"
                f"<strong>Reason:</strong> {reason}"
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        if self.state not in ('draft', 'cancel'):
            # See action_request_changes() below for why _action_cancel() is
            # used instead of action_cancel().
            self._action_cancel()
        if self.state == 'cancel':
            self.action_draft()

    def action_request_changes(self):
        """Let the creator (or an approver/admin) reopen a confirmed Sales
        Order for editing. Resets it to draft and re-arms the approval gate
        so any change must be re-approved before the order can be confirmed
        again — mirrors the original confirm/approve flow.
        """
        self.ensure_one()
        if self.state != 'sale':
            raise AccessError('Only confirmed Sales Orders can have changes requested.')
        if not (
            self.env.su
            or self.env.uid == self.create_uid.id
            or self.env.user.has_group('elegomotors_setup.group_sale_approver')
            or self.env.user.has_group('base.group_erp_manager')
        ):
            raise AccessError('Only the Sales Order creator or an approver can request changes.')
        self.write({
            'pending_approval': False,
            'approval_accounts': False,
            'approval_manohar': False,
            'rejection_reason': False,
        })
        self.message_post(
            body=f"Changes requested by {self.env.user.name} — order reset to Draft for editing. "
                 "It will need approval again before it can be re-confirmed.",
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        # action_cancel() can return a confirmation-wizard action (instead of
        # writing state='cancel' synchronously) when the order has linked
        # deliveries/invoices — calling it here would silently no-op since
        # there's no user to click through that wizard. _action_cancel() is
        # the internal hook action_cancel() itself calls once past that
        # check, so this still runs the same cascade (e.g. cancelling linked
        # deliveries) — it just skips the "are you sure" prompt, which is
        # fine here since the "Request Changes" button already confirms with
        # the user.
        self._action_cancel()
        self.action_draft()
