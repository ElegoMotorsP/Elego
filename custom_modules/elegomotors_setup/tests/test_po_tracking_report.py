# -*- coding: utf-8 -*-
"""PO Tracking report: QC figures and the stage for real receipts (the warehouse's
"GRN" operation type, not the module's own Gate Entry type)."""
import base64
import io
import zipfile

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

    # ------------------------------------------------------------- part rows / Excel

    def _kit_po(self):
        """A PO with an ordinary kit (5 kits = 5 chassis + 10 wheels) and a plain line (3),
        received: chassis in full, only 6 of the 10 wheels, the plain part in full."""
        env = self.env
        chassis = env['product.product'].create({
            'name': 'ZZ Test Kit Chassis', 'type': 'consu', 'is_storable': True, 'purchase_ok': True})
        wheel = env['product.product'].create({
            'name': 'ZZ Test Kit Wheel', 'type': 'consu', 'is_storable': True, 'purchase_ok': True})
        kit = env['product.product'].create({
            'name': 'ZZ Test Plain Kit', 'type': 'consu', 'is_storable': False, 'purchase_ok': True})
        bom = env['mrp.bom'].create({
            'product_tmpl_id': kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1.0,
            'bom_line_ids': [
                Command.create({'product_id': chassis.id, 'product_qty': 1.0}),
                Command.create({'product_id': wheel.id, 'product_qty': 2.0}),
            ],
        })
        po = env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [
                Command.create({'product_id': kit.id, 'product_qty': 5, 'price_unit': 100.0, 'name': kit.name}),
                Command.create({'product_id': self.plain.id, 'product_qty': 3, 'price_unit': 5.0,
                                'name': self.plain.name}),
            ],
        })
        po.button_confirm()
        kit_line, plain_line = po.order_line
        supplier = env.ref('stock.stock_location_suppliers')
        stock = self.warehouse.lot_stock_id

        def move(line, product, qty, bom_line=None):
            vals = {
                'name': product.name, 'product_id': product.id, 'product_uom': product.uom_id.id,
                'product_uom_qty': qty, 'purchase_line_id': line.id,
                'location_id': supplier.id, 'location_dest_id': stock.id,
            }
            if bom_line:
                vals['bom_line_id'] = bom_line.id
            return Command.create(vals)

        picking = env['stock.picking'].create({
            'picking_type_id': self.warehouse.in_type_id.id, 'partner_id': self.vendor.id,
            'location_id': supplier.id, 'location_dest_id': stock.id, 'x_source_po_id': po.id,
            'move_ids_without_package': [
                move(kit_line, chassis, 5, bom.bom_line_ids[0]),
                move(kit_line, wheel, 10, bom.bom_line_ids[1]),
                move(plain_line, self.plain, 3),
            ],
        })
        picking.action_confirm()
        for m in picking.move_ids:
            m.quantity = 6.0 if m.product_id == wheel else m.product_uom_qty
            m.picked = True
        picking.with_context(cancel_backorder=True)._action_done()
        po.invalidate_recordset()
        return po

    def test_part_rows_list_the_parts_of_a_kit_and_the_ordinary_lines(self):
        po = self._kit_po()
        rows = {r['name']: r for r in po._trk_part_rows()}
        self.assertEqual(len(rows), 3, 'two kit parts and one ordinary line')
        chassis = next(r for n, r in rows.items() if 'Kit Chassis' in n)
        wheel = next(r for n, r in rows.items() if 'Kit Wheel' in n)
        plain = next(r for n, r in rows.items() if 'Plain Part' in n)
        self.assertAlmostEqual(chassis['ordered'], 5.0)
        self.assertAlmostEqual(chassis['received'], 5.0)
        self.assertAlmostEqual(chassis['pending'], 0.0)
        self.assertAlmostEqual(wheel['ordered'], 10.0, msg='5 kits x 2 wheels')
        self.assertAlmostEqual(wheel['received'], 6.0)
        self.assertAlmostEqual(wheel['pending'], 4.0)
        self.assertAlmostEqual(plain['ordered'], 3.0)
        self.assertAlmostEqual(plain['received'], 3.0)
        self.assertAlmostEqual(plain['stock'], 3.0)

    def _two_kit_po_sharing_a_part(self):
        """Two kits on one PO (e.g. a Red CKD kit and a Black CKD kit) sharing one
        part (a wiring harness): Red orders 5 kits (= 10 harnesses, 2/kit),
        receives 6; Black orders 5 kits (= 15 harnesses, 3/kit), receives 9.
        Combined the harness should read 25 ordered / 15 received, in ONE row."""
        env = self.env
        harness = env['product.product'].create({
            'name': 'ZZ Test Shared Harness', 'type': 'consu', 'is_storable': True, 'purchase_ok': True})
        red_only = env['product.product'].create({
            'name': 'ZZ Test Red-Only Part', 'type': 'consu', 'is_storable': True, 'purchase_ok': True})
        red_kit = env['product.product'].create({
            'name': 'ZZ Test Red CKD Kit', 'type': 'consu', 'is_storable': False, 'purchase_ok': True})
        black_kit = env['product.product'].create({
            'name': 'ZZ Test Black CKD Kit', 'type': 'consu', 'is_storable': False, 'purchase_ok': True})
        red_bom = env['mrp.bom'].create({
            'product_tmpl_id': red_kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1.0,
            'bom_line_ids': [
                Command.create({'product_id': harness.id, 'product_qty': 2.0}),
                Command.create({'product_id': red_only.id, 'product_qty': 1.0}),
            ],
        })
        black_bom = env['mrp.bom'].create({
            'product_tmpl_id': black_kit.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1.0,
            'bom_line_ids': [
                Command.create({'product_id': harness.id, 'product_qty': 3.0}),
            ],
        })
        po = env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [
                Command.create({'product_id': red_kit.id, 'product_qty': 5, 'price_unit': 100.0,
                                'name': red_kit.name}),
                Command.create({'product_id': black_kit.id, 'product_qty': 5, 'price_unit': 100.0,
                                'name': black_kit.name}),
            ],
        })
        po.button_confirm()
        red_line, black_line = po.order_line
        supplier = env.ref('stock.stock_location_suppliers')
        stock = self.warehouse.lot_stock_id

        def move(line, product, qty, bom_line):
            return Command.create({
                'name': product.name, 'product_id': product.id, 'product_uom': product.uom_id.id,
                'product_uom_qty': qty, 'purchase_line_id': line.id, 'bom_line_id': bom_line.id,
                'location_id': supplier.id, 'location_dest_id': stock.id,
            })

        picking = env['stock.picking'].create({
            'picking_type_id': self.warehouse.in_type_id.id, 'partner_id': self.vendor.id,
            'location_id': supplier.id, 'location_dest_id': stock.id, 'x_source_po_id': po.id,
            'move_ids_without_package': [
                move(red_line, harness, 6, red_bom.bom_line_ids[0]),
                move(red_line, red_only, 5, red_bom.bom_line_ids[1]),
                move(black_line, harness, 9, black_bom.bom_line_ids[0]),
            ],
        })
        picking.action_confirm()
        for m in picking.move_ids:
            m.picked = True
        picking.with_context(cancel_backorder=True)._action_done()
        po.invalidate_recordset()
        return po, red_kit, black_kit

    def test_part_rows_merge_a_part_shared_by_two_kits(self):
        po, red_kit, black_kit = self._two_kit_po_sharing_a_part()
        rows = {r['name']: r for r in po._trk_part_rows()}
        self.assertEqual(len(rows), 2, 'one row for the shared harness, one for the Red-only part')
        harness = rows['ZZ Test Shared Harness']
        self.assertAlmostEqual(harness['ordered'], 25.0, msg='5 kits x 2 (Red) + 5 kits x 3 (Black)')
        self.assertAlmostEqual(harness['received'], 15.0, msg='6 (Red) + 9 (Black)')
        self.assertIn(red_kit.name, harness['used_in'])
        self.assertIn(black_kit.name, harness['used_in'])
        red_only = rows['ZZ Test Red-Only Part']
        self.assertEqual(red_only['used_in'], '', 'used by only one kit needs no "Used In" clutter')
        self.assertAlmostEqual(red_only['ordered'], 5.0)
        self.assertAlmostEqual(red_only['received'], 5.0)

    def test_client_excel_has_a_row_per_po_and_per_part(self):
        po = self._kit_po()
        wizard = self.env['elegomotors.po.tracking.export'].create({'order_ids': [Command.set(po.ids)]})
        action = wizard.action_download()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        attachment = self.env['ir.attachment'].browse(
            int(action['url'].split('/web/content/')[1].split('?')[0]))
        book = zipfile.ZipFile(io.BytesIO(base64.b64decode(attachment.datas)))
        text = book.read('xl/sharedStrings.xml').decode()
        for expected in ('Order Reference', 'Part Name', 'PO Value', 'Currency',
                         'Elego Purchase Invoice', po.name, 'ZZ Test Kit Wheel'):
            self.assertIn(expected, text)
        # without the parts: one row per PO only
        wizard.include_parts = False
        plain = zipfile.ZipFile(io.BytesIO(base64.b64decode(
            self.env['ir.attachment'].browse(int(
                wizard.action_download()['url'].split('/web/content/')[1].split('?')[0])).datas)))
        self.assertNotIn('ZZ Test Kit Wheel', plain.read('xl/sharedStrings.xml').decode())
