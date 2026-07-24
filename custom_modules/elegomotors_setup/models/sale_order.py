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
    x_quotation_number = fields.Char(
        string="Quotation Number", copy=False, readonly=True,
        help="The original quotation number (EGO-QUO-…), preserved for "
             "traceability once the record's own name is renamed to the "
             "Sales Order number on approval.",
    )

    def write(self, vals):
        result = super().write(vals)
        # Fallback only: the normal UI path assigns the Sales Order Number
        # in action_mark_accepted(), the moment the customer accepts the
        # quotation, so the record already carries its final SO number
        # throughout the Manohar/Rajshri approval window — not just after
        # approval. This catches the remaining paths that skip 'accepted'
        # entirely and confirm directly (portal signature, tests, API);
        # _assign_sale_order_number() is idempotent so it's a no-op for
        # orders numbered earlier.
        if vals.get('state') == 'sale':
            self._assign_sale_order_number()
        return result

    def _assign_sale_order_number(self):
        """Assign the Sales Order Number and rename the record to it —
        so the SO number becomes the primary identifier everywhere: page
        title, breadcrumbs, and downstream documents' Source Document /
        origin fields created from this point on. Idempotent: no-ops for
        an order that already has a sale_order_number.
        """
        for order in self:
            if order.sale_order_number:
                continue
            old_name = order.name
            new_number = (
                self.env['ir.sequence'].sudo().next_by_code('sale.order.confirmed') or '/'
            )
            order.sale_order_number = new_number
            order.x_quotation_number = old_name
            order.name = new_number
            order._rename_linked_origin_refs(old_name, new_number)

    def _rename_linked_origin_refs(self, old_name, new_name):
        """Propagate the EGO-QUO- → EGO-SO- rename to every document already
        created (delivery, invoice) that stored a plain-text copy of the old
        quotation number as its origin/reference at creation time. Those
        fields are NOT live-linked to sale.order.name — without this they'd
        keep showing the retired quotation number forever, and any lookup
        matching sale.order by name against that stored string (e.g. the
        serial-sync fallback in stock_picking.py, or the invoice_origin
        fallback in account_move.py) would silently stop finding this order.
        """
        self.ensure_one()
        if not old_name or old_name == new_name:
            return
        self.env['stock.picking'].sudo().search([
            ('origin', '=', old_name)
        ]).write({'origin': new_name})
        invoices = self.env['account.move'].sudo().search([
            ('invoice_origin', '=', old_name)
        ])
        for inv in invoices:
            inv.invoice_origin = ','.join(
                new_name if part.strip() == old_name else part.strip()
                for part in inv.invoice_origin.split(',')
            )

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

    @api.model
    def _backfill_accepted_sale_order_numbers(self):
        """One-time (idempotent) fix for orders already sitting in
        'Quotation Accepted' (pending_approval already armed) from before
        the SO number was assigned at acceptance time — e.g. an order still
        displaying its old EGO-QUO-… / legacy EGO-SO-… quotation number
        while "Awaiting Approval". Brings them in line with new acceptances
        by assigning/renaming now instead of waiting for approval. Called
        from company_config_data.xml on every upgrade.
        """
        orders = self.search([
            ('state', '=', 'accepted'),
            ('sale_order_number', '=', False),
        ])
        orders._assign_sale_order_number()

    @api.model
    def _backfill_rename_confirmed_orders(self):
        """One-time (idempotent) fix for orders confirmed under the earlier
        version of this feature, which only recorded sale_order_number
        without actually renaming the record — e.g. EGO-QUO-00001 whose
        page title/breadcrumbs still show the quotation number even though
        sale_order_number already holds EGO-SO-00020. Brings them in line
        with new confirmations, which rename on write() (see write() above):
        preserves the original quotation number in x_quotation_number, then
        renames the record and cascades the change to already-created
        deliveries/invoices' origin fields. Called from
        company_config_data.xml on every upgrade.
        """
        orders = self.search([
            ('state', '=', 'sale'),
            ('sale_order_number', '!=', False),
        ])
        orders = orders.filtered(lambda o: o.name != o.sale_order_number)
        for order in orders:
            old_name = order.name
            new_name = order.sale_order_number
            order.x_quotation_number = old_name
            order.name = new_name
            order._rename_linked_origin_refs(old_name, new_name)

    def _ensure_quotation_sequence_prefix(self):
        """Defensively force the Quotation Number sequence's prefix to
        EGO-QUO- right before a new quotation draws its number.

        company_config_data.xml already does this via a noupdate="0"
        <record> write on every module upgrade — but that only takes
        effect once that specific upgrade has actually run on a given
        database. New quotations kept drawing the old EGO-SO- prefix on
        deployments where it hadn't (yet). Checking/fixing it here, right
        at creation time, makes the correct prefix guaranteed rather than
        dependent on upgrade timing — cheap (one read, at most one write)
        and a no-op once the prefix is already correct.
        """
        seq = self.env.ref(
            'elegomotors_setup.seq_elegomotors_sale', raise_if_not_found=False
        )
        if seq and seq.sudo().prefix != 'EGO-QUO-':
            seq.sudo().prefix = 'EGO-QUO-'

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
        self._ensure_quotation_sequence_prefix()
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

    @api.model
    def _redirect_default_quotation_report(self):
        """Point the standard Preview / Send by Email / Print quotation PDF
        at our fully custom template (report_elegomotors_quotation) instead
        of Odoo's base sale.report_saleorder_document — needed so bike-combo
        battery/charger lines fold into their parent bike's row ("same box")
        there too, matching the Tax Invoice.

        Deliberately a data-driven search on report_name rather than an
        env.ref() on a guessed xmlid: inheriting/patching the base template
        via xpath already proved unsafe (a wrong guess at its internal row
        structure broke the entire module install — see report_saleorder.xml
        history). If Odoo's report_name convention for the base quotation
        report ever differs from 'sale.report_saleorder', this search simply
        finds nothing and no-ops — it can never break install.
        """
        report_action = self.env['ir.actions.report'].search(
            [('report_name', '=', 'sale.report_saleorder')], limit=1
        )
        if report_action and report_action.report_name != 'elegomotors_setup.report_elegomotors_quotation':
            report_action.write({
                'report_name': 'elegomotors_setup.report_elegomotors_quotation',
                'report_file': 'elegomotors_setup.report_elegomotors_quotation',
            })

    def action_open_bike_combo_wizard(self):
        """Add a bike + battery + charger combo priced from the dealer
        combo price list (Sales → Configuration → Bike Combo Prices)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Bike Combo',
            'res_model': 'elegomotors.bike.combo.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_mark_accepted(self):
        """Salesperson records that the customer accepted the quotation.
        This immediately creates the Sales Order: the record is renamed to
        its SO number (EGO-SO-…) right here via _assign_sale_order_number(),
        so it carries that number throughout the approval window rather than
        still showing its old quotation number (EGO-QUO-…) while pending. It
        stays in 'Quotation Accepted' with pending_approval = True; the
        Approve click by Rajshri (Accounts) or Manohar (MD) is what confirms
        it into state 'sale' (see _on_approval_recorded)."""
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
            order._assign_sale_order_number()
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
                    f"<b>{self.env.user.name}</b>. This order is now "
                    f"<b>{order.name}</b>, awaiting SO confirmation: "
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

            # Same restriction as action_create_invoice() below, enforced here
            # too: the standard "Create Invoice" button on a Sales Order opens
            # Odoo's own sale.advance.payment.inv wizard, which calls this
            # method directly and never goes through action_create_invoice() —
            # so that check alone doesn't actually stop a salesperson from
            # creating a faulty invoice this way.
            if not self.env.user.has_group('account.group_account_invoice'):
                raise AccessError(
                    'Only accounting users (Amit / Rajshri / Manohar) can create '
                    'invoices from Sales Orders.'
                )

            # Delivery + serial gate: a Sales Order carrying a bike unit must
            # have its outgoing delivery validated, with serials scanned via
            # "Scan Bike Serials", before it can be invoiced — otherwise the
            # invoice describes stock that was never actually confirmed shipped.
            bike_tmpls = self.env['mrp.production']._get_ego_templates()
            if bike_tmpls:
                for order in self:
                    has_bike = any(
                        line.product_id.product_tmpl_id in bike_tmpls
                        for line in order.order_line
                    )
                    if not has_bike:
                        continue
                    deliveries = order.picking_ids.filtered(
                        lambda p: p.picking_type_code == 'outgoing' and p.state != 'cancel'
                    )
                    if not deliveries or any(p.state != 'done' for p in deliveries):
                        raise UserError(
                            f'{order.name}: the outgoing delivery must be validated '
                            f'before an invoice can be created.'
                        )
                    if any(not p.x_bike_serials_scanned for p in deliveries):
                        raise UserError(
                            f'{order.name}: bike serial numbers must be scanned on '
                            f'the delivery ("Scan Bike Serials") before an invoice '
                            f'can be created.'
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
