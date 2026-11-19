# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_dealer_code = fields.Char(
        string='Dealer Code (Finance API)',
        index=True,
        copy=False,
        help='Code finance partners (e.g. Bajaj Finance) use to identify this '
             'dealer as "dealerCode" in the serial-validation API. Must match '
             'the code the finance partner has on file for this dealership — '
             'get it from them, this field does not generate one.',
    )

    # No groups= on the field itself: Prashant raises the POs and must still be
    # able to read this through the PO. Who may CHANGE it is decided in create()
    # and write() below, and on the vendor form.
    x_overseas_supplier = fields.Boolean(
        string='Overseas Supplier (no GST on POs)',
        copy=False,
        tracking=True,
        help='An overseas vendor invoices us without any Indian tax, and the import '
             'IGST is booked separately through the Bill of Entry. Purchase orders '
             'to this vendor therefore carry no taxes at all: no GST, no IGST, no '
             'reverse-charge tax. Only the admin can change this.',
    )

    def _ego_check_can_set_overseas_supplier(self):
        # Superuser and sudo() are exempt so install/upgrade scripts and Odoo's
        # own tests can still set it.
        if self.env.su or self.env.user.has_group('base.group_erp_manager'):
            return
        raise AccessError(
            'Only the admin can mark a vendor as an Overseas Supplier (it removes '
            'all tax from that vendor\'s purchase orders). Ask Manohar (Admin).'
        )

    @api.model_create_multi
    def create(self, vals_list):
        # Creating a vendor with the box ticked is a change too. An unticked box
        # is just the default, so it is not checked.
        if any(vals.get('x_overseas_supplier') for vals in vals_list):
            self._ego_check_can_set_overseas_supplier()
        return super().create(vals_list)

    def write(self, vals):
        if 'x_overseas_supplier' in vals:
            wanted = bool(vals['x_overseas_supplier'])
            # Only a real change is blocked: a save that sends the box back as it
            # already is must not fail for someone who cannot change it.
            if any(partner.x_overseas_supplier != wanted for partner in self):
                self._ego_check_can_set_overseas_supplier()
        res = super().write(vals)
        if vals.get('x_overseas_supplier'):
            self.filtered('x_overseas_supplier')._ego_strip_taxes_from_open_pos()
        return res

    def _ego_strip_taxes_from_open_pos(self):
        """The box was just ticked: take the taxes off this vendor's POs that are
        still draft / sent / to approve. Confirmed and done POs, and bills that
        are already posted, are left exactly as they are."""
        # sudo(): the admin ticking the box may not be allowed to edit someone
        # else's PO lines directly, but this clean-up must not depend on that.
        orders = self.env['purchase.order'].sudo().search([
            ('partner_id', 'in', self.ids),
            ('state', 'in', ('draft', 'sent', 'to approve')),
        ])
        orders._ego_strip_overseas_taxes()
