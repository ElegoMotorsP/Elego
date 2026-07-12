# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Extra quotation stage between "Quotation Sent" and "Sales Order":
    # the salesperson records the customer's acceptance explicitly, then
    # clicks Confirm to convert the quotation into a Sales Order.
    state = fields.Selection(
        selection_add=[('accepted', 'Quotation Accepted'), ('sale',)],
        ondelete={'accepted': 'set default'},
    )

    # One shared sales login is used by three people — this records which of
    # them actually created / is handling the order. Mandatory before the
    # quotation can be sent, accepted, or confirmed.
    x_actual_salesperson = fields.Selection([
        ('priyanka_kul', 'Priyanka Kul'),
        ('priyanka_sutar', 'Priyanka Sutar'),
        ('srushti_gund', 'Srushti Gund'),
    ], string='Handled By', copy=False, tracking=True,
       help='Which person on the shared sales account actually created / '
            'is handling this order.')

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
    def _backfill_accepted_pending_approval(self):
        """One-time (idempotent) fix for quotations marked 'accepted' before
        acceptance started arming the approval gate — without this they would
        be stuck with no visible action button. Called from
        company_config_data.xml on every upgrade.
        """
        orders = self.search([
            ('state', '=', 'accepted'),
            ('pending_approval', '=', False),
            ('approval_accounts', '=', False),
            ('approval_manohar', '=', False),
        ])
        orders.write({'pending_approval': True})

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
                'Ask Priyanka (Sales) or Manohar (Admin) to raise the order.'
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
                'Ask Priyanka (Sales) or Manohar (Admin) to raise the order.'
            )
        return super().create(vals_list)

    def _ensure_actual_salesperson(self):
        """The quotation cannot move forward until it records which person
        on the shared sales login is handling it."""
        for order in self:
            if not order.x_actual_salesperson:
                raise UserError(
                    'Please select who is handling this order in the '
                    '"Handled By" field (Priyanka Kul / Priyanka Sutar / '
                    'Srushti Gund) before proceeding.'
                )

    def action_quotation_send(self):
        self._ensure_actual_salesperson()
        return super().action_quotation_send()

    def action_mark_accepted(self):
        """Salesperson records that the customer accepted the quotation.
        This immediately sends the order for SO confirmation: it stays in
        'Quotation Accepted' with pending_approval = True, and the Approve
        click by Rajshri (Accounts) or Manohar (MD) is what confirms it
        into a Sales Order (see _on_approval_recorded)."""
        self._ensure_actual_salesperson()
        for order in self:
            if order.state != 'sent':
                raise UserError(
                    'Send the quotation to the customer first — only sent '
                    'quotations can be marked as accepted.'
                )
            order.state = 'accepted'
            order.pending_approval = True
            order.rejection_reason = False
            rajshri = self.env.ref(
                'elegomotors_setup.user_ego_rajshri', raise_if_not_found=False
            )
            manohar = self.env.ref(
                'elegomotors_setup.user_ego_manohar', raise_if_not_found=False
            )
            partner_ids = [
                u.partner_id.id for u in [rajshri, manohar] if u and u.partner_id
            ]
            order.message_post(
                body=Markup(
                    f"Quotation accepted by customer — recorded by "
                    f"<b>{self.env.user.name}</b>. Awaiting SO confirmation: "
                    f"please click <b>Approve (Accounts)</b> or <b>Approve (MD)</b> — "
                    f"either approval confirms the order."
                ),
                partner_ids=partner_ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def _confirmation_error_message(self):
        self.ensure_one()
        if self.state == 'accepted':
            # Base method only allows draft/sent; 'accepted' is our extra
            # pre-confirmation stage — mirror the base order-line validation.
            if any(
                not line.display_type
                and not line.is_downpayment
                and not line.product_id
                for line in self.order_line
            ):
                return "A line on these orders missing a product, you cannot confirm it."
            return False
        return super()._confirmation_error_message()

    def _compute_type_name(self):
        super()._compute_type_name()
        for order in self:
            if order.state == 'accepted':
                order.type_name = 'Quotation'

    def action_confirm(self):
        # Normal UI flow never reaches this directly: the Confirm buttons are
        # hidden and approval (via _on_approval_recorded) confirms the order
        # through the base method. This override covers the remaining direct
        # paths — customer portal signature, tests, API — where the order
        # confirms first; the approval gate is then armed on the confirmed SO
        # (delivery validation and invoicing stay blocked until approved).
        if not self.env.su:
            self._ensure_actual_salesperson()
        result = super().action_confirm()
        for order in self:
            if order.state != 'sale':
                continue
            if order.approval_accounts or order.approval_manohar:
                continue  # already approved earlier (e.g. re-confirm) — no gate
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
                    "This Sales Order has been confirmed and is awaiting approval. "
                    "Please review and click <b>Approve (Accounts)</b> or <b>Approve (MD)</b> — "
                    "either approval is sufficient. Delivery validation and invoicing "
                    "are blocked until then."
                ),
                partner_ids=partner_ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        return result

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
        self._on_approval_recorded()

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
        self._on_approval_recorded()

    def _on_approval_recorded(self):
        self.ensure_one()
        if not (self.approval_accounts or self.approval_manohar):
            return
        self.pending_approval = False
        if self.state != 'sale':
            # Normal path: order is in 'Quotation Accepted' (or a legacy
            # pre-confirmation draft) — the approval IS the SO confirmation.
            # Calls the base action_confirm directly so our override doesn't
            # re-arm the approval gate.
            super(SaleOrder, self).action_confirm()
        else:
            self.message_post(
                body=Markup(
                    f"Approval complete — recorded by <b>{self.env.user.name}</b>. "
                    f"Delivery validation and invoicing are now unblocked."
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

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

    def _create_invoices(self, grouped=False, final=False, date=None):
        # Approval gate: no customer invoice until Rajshri or Manohar has
        # approved the confirmed SO. Guarded here (rather than only on the
        # button) because every invoicing path — advance payment wizard,
        # Create Invoice button, batch invoicing — funnels through this method.
        if not self.env.su:
            pending = self.filtered('pending_approval')
            if pending:
                raise UserError(
                    f"Sales Order(s) {', '.join(pending.mapped('name'))} are "
                    f"awaiting approval from Rajshri (Accounts) or Manohar (MD). "
                    f"Invoicing is blocked until the approval is recorded."
                )
        return super()._create_invoices(grouped=grouped, final=final, date=date)

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
