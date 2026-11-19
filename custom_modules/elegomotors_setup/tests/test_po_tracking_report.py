# -*- coding: utf-8 -*-
"""PO Tracking report: QC figures and the stage for real receipts (the warehouse's
"GRN" operation type, not the module's own Gate Entry type)."""
from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoTrackingReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.warehouse = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.vendor = env['res.partner'].create({'name': 'ZZ Test Tracking Vendor'})
        cls.part = env['product.product'].create({
            'name': 'ZZ Test QC Part', 'type': 'consu', 'is_storable': True,
            'purchase_ok': True, 'x_qc_required': True,
        })
        cls.plain = env['product.product'].create({
            'name': 'ZZ Test Plain Part', 'type': 'consu', 'is_storable': True,
            'purchase_ok': True,
        })

    def _po(self, qty=10):
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [
                Command.create({'product_id': self.part.id, 'product_qty': qty,
                                'price_unit': 5.0, 'name': self.part.name}),
                Command.create({'product_id': self.plain.id, 'product_qty': qty,
                                'price_unit': 5.0, 'name': self.plain.name}),
            ],
        })
        po.button_confirm()
        return po

    def _grn(self, po):
        """A receipt on the PO's own operation type, made the way the GRN screen does."""
        in_type = self.warehouse.in_type_id
        moves = [Command.create({
            'name': line.product_id.name, 'product_id': line.product_id.id,
            'product_uom': line.product_uom.id, 'product_uom_qty': line.product_qty,
            'purchase_line_id': line.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
        }) for line in po.order_line]
        return self.env['stock.picking'].create({
            'picking_type_id': in_type.id, 'partner_id': self.vendor.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
            'x_source_po_id': po.id, 'move_ids_without_package': moves,
        })

    def _figures(self, po):
        po.invalidate_recordset()
        return {
            'received': po.x_trk_received_qty, 'pass': po.x_trk_qc_passed_qty,
            'reject': po.x_trk_qc_rejected_qty, 'pending': po.x_trk_qc_pending_qty,
            'stock': po.x_trk_stock_qty, 'stage': po.x_trk_stage,
        }

    def test_qc_columns_work_on_an_ordinary_receipt(self):
        gate = self.env.ref('elegomotors_setup.picking_type_gate_entry', raise_if_not_found=False)
        po = self._po(10)
        picking = self._grn(po)
        self.assertNotEqual(picking.picking_type_id, gate, 'this is the real GRN type, not Gate Entry')
        picking.action_confirm()

        figures = self._figures(po)
        self.assertEqual(figures['stage'], 'awaiting', 'a GRN that is still a draft')
        self.assertAlmostEqual(figures['pending'], 0.0, msg='a draft GRN is not in QC yet')
        self.assertIn(picking.name, po.x_trk_qc_refs, 'the QC No. lists the receipt that has QC items')

        # Store sends it to QC: nothing is validated, the QC part is waiting
        picking.x_gate_entry_state = 'in_qc'
        figures = self._figures(po)
        self.assertAlmostEqual(figures['received'], 0.0)
        self.assertAlmostEqual(figures['pending'], 10.0, msg='QC Pending: the QC part sits in QC')
        self.assertEqual(figures['stage'], 'quality', 'material in QC is not "awaiting delivery"')
        self.assertIn(picking.name, po.x_trk_qc_refs)

        # QC passes 8 of 10
        qc_move = picking.move_ids.filtered(lambda m: m.product_id == self.part)
        qc_move.x_qty_qc_passed = 8.0
        picking.action_gate_entry_approve_qc()
        figures = self._figures(po)
        self.assertAlmostEqual(figures['pass'], 8.0)
        self.assertAlmostEqual(figures['reject'], 2.0)
        self.assertAlmostEqual(figures['pending'], 0.0)
        self.assertAlmostEqual(figures['stock'], 0.0, msg='nothing is in stock until Store validates')

        # Store validates what QC approved; the rest is not received
        for move in picking.move_ids:
            move.picked = True
        picking.with_context(cancel_backorder=True)._action_done()
        figures = self._figures(po)
        self.assertAlmostEqual(figures['pass'], 8.0)
        self.assertAlmostEqual(figures['reject'], 2.0)
        self.assertAlmostEqual(figures['stock'], 18.0, msg='8 QC-passed + 10 plain')
        self.assertEqual(figures['stage'], 'partial_qc', 'rejected goods wait for a replacement')

    def test_plain_part_without_qc_is_not_counted_in_qc(self):
        po = self._po(4)
        picking = self._grn(po)
        picking.action_confirm()
        picking.x_gate_entry_state = 'in_qc'
        figures = self._figures(po)
        self.assertAlmostEqual(figures['pending'], 4.0, msg='only the QC-required part counts')
