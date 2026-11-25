# -*- coding: utf-8 -*-
"""SO Tracking report: one row per Sales Order line, Quotation -> Approval ->
Dispatch -> Invoice, mirroring PO Tracking on the sales side."""
import base64
import io
import zipfile

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSoTrackingReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.warehouse = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.customer = env['res.partner'].create({'name': 'ZZ Test Tracking Customer'})
        cls.product = env['product.product'].create({
            'name': 'ZZ Test Trackable Product', 'type': 'consu', 'is_storable': True,
            'sale_ok': True, 'invoice_policy': 'delivery', 'list_price': 100.0,
        })

    def _quotation(self, qty=10):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'x_actual_salesperson': 'priyanka_sutar',
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': qty, 'price_unit': 100.0,
            })],
        })

    def _line(self, order):
        return order.order_line.filtered(lambda l: l.product_id == self.product)

    def test_quotation_not_yet_submitted_is_quotation_pending(self):
        order = self._quotation()
        line = self._line(order)
        self.assertEqual(line.x_trk_stage, 'quotation')
        self.assertEqual(line.x_trk_approval_status, 'Not Submitted')
        self.assertEqual(line.x_trk_quotation_no, order.name)
        self.assertFalse(line.x_trk_so_no)

    def test_accept_and_approve_moves_through_the_stages(self):
        order = self._quotation()
        line = self._line(order)
        order.state = 'sent'  # skip the actual mail-send flow, not under test here
        order.action_mark_accepted()
        self.assertEqual(line.x_trk_stage, 'approval')
        self.assertEqual(line.x_trk_approval_status, 'Pending')
        self.assertTrue(line.x_trk_quotation_no, 'the quotation-era number is kept')
        self.assertTrue(line.x_trk_so_no, 'renamed to its SO number at acceptance')

        order.action_approve_accounts()
        self.assertEqual(order.state, 'sale')
        self.assertEqual(line.x_trk_approval_status, 'Approved')
        self.assertEqual(line.x_trk_approved_by, 'Accounts (Rajshri)')
        self.assertTrue(line.x_trk_approval_date)
        self.assertTrue(line.x_trk_so_date)
        self.assertEqual(line.x_trk_stage, 'dispatch_pending', 'approved, nothing delivered yet')
        self.assertEqual(line.x_trk_delivery_status, 'Not Created')

    def test_rejection_shows_as_rejected_until_resubmitted(self):
        order = self._quotation()
        line = self._line(order)
        order.state = 'sent'  # skip the actual mail-send flow, not under test here
        order.action_mark_accepted()
        order._do_reject('Price needs revision')
        self.assertEqual(order.state, 'draft')
        self.assertEqual(line.x_trk_stage, 'rejected')
        self.assertEqual(line.x_trk_approval_status, 'Rejected')

    def _delivered_order(self, qty=10, delivered=6):
        order = self._quotation(qty)
        order.state = 'sent'  # skip the actual mail-send flow, not under test here
        order.action_mark_accepted()
        order.action_approve_accounts()
        picking = order.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing')
        picking.move_ids.quantity = delivered
        picking.move_ids.picked = True
        picking.with_context(cancel_backorder=True)._action_done()
        return order, self._line(order)

    def test_partial_dispatch_then_full_dispatch_pending_invoice(self):
        order, line = self._delivered_order(qty=10, delivered=6)
        self.assertAlmostEqual(line.x_trk_gross_delivered_qty, 6.0)
        self.assertAlmostEqual(line.qty_delivered, 6.0)
        self.assertAlmostEqual(line.x_trk_pending_dispatch_qty, 4.0)
        self.assertEqual(line.x_trk_delivery_status, 'Partial')
        self.assertEqual(line.x_trk_stage, 'partial_dispatch')
        self.assertTrue(line.x_trk_do_refs)

    def test_fully_invoiced_line_is_completed(self):
        order, line = self._delivered_order(qty=10, delivered=10)
        self.assertEqual(line.x_trk_stage, 'invoice_pending')
        invoice = order._create_invoices()
        invoice.action_post()
        self.assertAlmostEqual(line.qty_invoiced, 10.0)
        self.assertEqual(line.x_trk_stage, 'completed')
        self.assertIn(invoice.name, line.x_trk_invoice_refs)

    def test_cancelled_order_line_is_cancelled_stage(self):
        order = self._quotation()
        line = self._line(order)
        order._action_cancel()
        self.assertEqual(line.x_trk_stage, 'cancelled')
        self.assertAlmostEqual(line.x_trk_pending_dispatch_qty, 0.0)

    def test_client_excel_has_a_row_per_line(self):
        order, line = self._delivered_order(qty=5, delivered=5)
        wizard = self.env['elegomotors.so.tracking.export'].create({'line_ids': [Command.set(line.ids)]})
        action = wizard.action_download()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        attachment = self.env['ir.attachment'].browse(
            int(action['url'].split('/web/content/')[1].split('?')[0]))
        book = zipfile.ZipFile(io.BytesIO(base64.b64decode(attachment.datas)))
        text = book.read('xl/sharedStrings.xml').decode()
        for expected in ('Quotation No.', 'Customer', 'Product Name', 'Current Stage',
                          order.x_trk_quotation_no, self.product.name):
            self.assertIn(expected, text)
