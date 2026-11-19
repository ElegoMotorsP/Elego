# -*- coding: utf-8 -*-
"""Overseas suppliers: a purchase order to a vendor marked "Overseas Supplier"
carries no tax at all (no GST, IGST or reverse-charge tax), whichever way the
lines or the vendor are changed, and only the admin can set the mark."""
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOverseasPo(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.tax = env['account.tax'].create({
            'name': 'ZZ Test Purchase 5%',
            'amount': 5.0,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
            'company_id': cls.company.id,
        })

        def product(name):
            # "On ordered quantities" so a bill can be made without a receipt.
            return env['product.product'].create({
                'name': name, 'type': 'consu', 'purchase_ok': True,
                'purchase_method': 'purchase',
                'supplier_taxes_id': [Command.set(cls.tax.ids)],
            })

        cls.product_a = product('ZZ Test Overseas Part A')
        cls.product_b = product('ZZ Test Overseas Part B')
        cls.overseas = env['res.partner'].create({
            'name': 'ZZ Test Overseas Vendor', 'x_overseas_supplier': True,
        })
        cls.domestic = env['res.partner'].create({'name': 'ZZ Test Domestic Vendor'})
        if not env['account.journal'].search([
            ('type', '=', 'purchase'), ('company_id', '=', cls.company.id),
        ], limit=1):
            env['account.journal'].create({
                'name': 'ZZ Test Purchases', 'type': 'purchase', 'code': 'ZZPUR',
                'company_id': cls.company.id,
            })

    # ------------------------------------------------------------------ helpers

    def _po(self, vendor, product=None, qty=10, price=100.0):
        product = product or self.product_a
        return self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': [Command.create({
                'product_id': product.id, 'product_qty': qty,
                'price_unit': price, 'name': product.name,
            })],
        })

    def _user(self, login, extra_groups):
        groups = [
            self.env.ref('base.group_user'),
            self.env.ref('base.group_partner_manager'),
        ] + [self.env.ref(xmlid) for xmlid in extra_groups]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login,
            'groups_id': [Command.set([g.id for g in groups])],
        })

    # -------------------------------------------------------------------- tests

    def test_overseas_po_has_no_tax_at_all(self):
        po = self._po(self.overseas)
        self.assertFalse(po.order_line.taxes_id, 'The product\'s vendor tax must not be applied')
        self.assertEqual(po.amount_untaxed, 1000.0)
        self.assertEqual(po.amount_tax, 0.0)
        self.assertEqual(po.amount_total, po.amount_untaxed)

    def test_normal_vendor_still_gets_the_product_tax(self):
        po = self._po(self.domestic)
        line = po.order_line
        self.assertEqual(line.taxes_id, self.tax)
        self.assertAlmostEqual(po.amount_tax, 50.0)
        # The product onchange really does fill taxes for a normal vendor, so the
        # overseas test below is not passing just because nothing ever fills them.
        line.taxes_id = [Command.clear()]
        line._product_id_change()
        self.assertEqual(line.taxes_id, self.tax)

    def test_changing_the_product_keeps_the_line_tax_free(self):
        po = self._po(self.overseas)
        line = po.order_line
        line.product_id = self.product_b
        line._product_id_change()      # what the product onchange runs
        self.assertFalse(line.taxes_id)
        self.assertEqual(po.amount_tax, 0.0)

    def test_hand_picked_tax_is_stripped(self):
        po = self._po(self.overseas)
        line = po.order_line
        line.write({'taxes_id': [Command.set(self.tax.ids)]})
        self.assertFalse(line.taxes_id)
        self.assertEqual(po.amount_tax, 0.0)

    def test_line_created_with_a_tax_is_stripped(self):
        po = self._po(self.overseas)
        po.write({'order_line': [Command.create({
            'product_id': self.product_b.id, 'product_qty': 1, 'price_unit': 10.0,
            'name': 'extra', 'taxes_id': [Command.set(self.tax.ids)],
        })]})
        self.assertEqual(len(po.order_line), 2)
        self.assertFalse(po.order_line.taxes_id)
        # a line made straight from code, as the BoM wizard and CKD kit lines do
        line = self.env['purchase.order.line'].create({
            'order_id': po.id, 'product_id': self.product_a.id, 'product_qty': 1,
            'price_unit': 10.0, 'name': 'from code', 'taxes_id': [Command.set(self.tax.ids)],
        })
        self.assertFalse(line.taxes_id)

    def test_a_write_over_mixed_lines_only_strips_the_overseas_ones(self):
        overseas_line = self._po(self.overseas).order_line
        domestic_line = self._po(self.domestic).order_line
        domestic_line.taxes_id = [Command.clear()]
        (overseas_line | domestic_line).write({'taxes_id': [Command.set(self.tax.ids)]})
        self.assertFalse(overseas_line.taxes_id)
        self.assertEqual(domestic_line.taxes_id, self.tax)

    def test_switching_a_draft_po_to_an_overseas_vendor_clears_its_taxes(self):
        po = self._po(self.domestic)
        self.assertEqual(po.order_line.taxes_id, self.tax)
        po.write({'partner_id': self.overseas.id})
        self.assertFalse(po.order_line.taxes_id)
        self.assertEqual(po.amount_tax, 0.0)

    def test_only_the_erp_manager_can_tick_the_box(self):
        buyer = self._user('zz_overseas_buyer', ['purchase.group_purchase_user'])
        admin = self._user('zz_overseas_admin', ['base.group_erp_manager'])
        vendor = self.env['res.partner'].create({'name': 'ZZ Test Vendor To Tick'})
        with self.assertRaises(AccessError):
            vendor.with_user(buyer).write({'x_overseas_supplier': True})
        self.assertFalse(vendor.x_overseas_supplier)
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(buyer).create({
                'name': 'ZZ Test New Overseas', 'x_overseas_supplier': True})
        vendor.with_user(admin).write({'x_overseas_supplier': True})
        self.assertTrue(vendor.x_overseas_supplier)
        # a save that sends the box back unchanged is not a change
        vendor.with_user(buyer).write({'x_overseas_supplier': True})
        # and the buyer can still read it through the PO
        po = self._po(vendor)
        self.assertTrue(po.with_user(buyer).x_overseas_supplier)

    def test_ticking_the_box_clears_open_pos_but_never_a_confirmed_one(self):
        vendor = self.env['res.partner'].create({'name': 'ZZ Test Vendor Becoming Overseas'})
        draft_po = self._po(vendor)
        confirmed_po = self._po(vendor)
        confirmed_po.button_confirm()
        self.assertEqual(confirmed_po.state, 'purchase')
        self.assertEqual(draft_po.order_line.taxes_id, self.tax)
        self.assertEqual(confirmed_po.order_line.taxes_id, self.tax)

        vendor.write({'x_overseas_supplier': True})

        self.assertFalse(draft_po.order_line.taxes_id)
        self.assertEqual(draft_po.amount_tax, 0.0)
        self.assertEqual(confirmed_po.order_line.taxes_id, self.tax,
                         'A confirmed PO must not be touched')
        self.assertAlmostEqual(confirmed_po.amount_tax, 50.0)

    def test_vendor_bill_from_a_confirmed_overseas_po_has_no_tax(self):
        po = self._po(self.overseas)
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        po.action_create_invoice()
        bill = po.invoice_ids
        self.assertEqual(len(bill), 1)
        self.assertTrue(bill.invoice_line_ids)
        self.assertFalse(bill.invoice_line_ids.tax_ids)
        self.assertEqual(bill.amount_tax, 0.0)
        self.assertEqual(bill.amount_total, bill.amount_untaxed)
