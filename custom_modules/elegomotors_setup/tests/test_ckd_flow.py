# -*- coding: utf-8 -*-
"""CKD kit purchasing end to end: kit approval, frozen allocation, GRN parts,
kit pricing (full and short delivery), PO tracking, Bill of Entry landed cost
and the reconciliation. Runs on every Odoo.sh build."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCkdFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.category = env['product.category'].create({
            'name': 'ZZ Test CKD parts',
            'property_cost_method': 'average',
            'property_valuation': 'manual_periodic',
        })
        Product = env['product.product']

        def part(name):
            return Product.create({
                'name': name, 'type': 'consu', 'is_storable': True,
                'categ_id': cls.category.id, 'purchase_ok': True,
            })

        cls.chassis = part('ZZ Test Chassis Red')      # 1 per kit, 50%
        cls.motor = part('ZZ Test Motor')              # 1 per kit, 30%
        cls.suspension = part('ZZ Test Rear Suspension')  # 2 per kit, 20%
        cls.kit = Product.create({
            'name': 'ZZ Test CKD Kit Red', 'type': 'consu', 'is_storable': False,
            'purchase_ok': True,
        })
        cls.bom = env['mrp.bom'].create({
            'product_tmpl_id': cls.kit.product_tmpl_id.id,
            'type': 'phantom',
            'product_qty': 1.0,
            'x_is_ckd_kit': True,
            'bom_line_ids': [
                Command.create({'product_id': cls.chassis.id, 'product_qty': 1.0, 'cost_share': 50.0}),
                Command.create({'product_id': cls.motor.id, 'product_qty': 1.0, 'cost_share': 30.0}),
                Command.create({'product_id': cls.suspension.id, 'product_qty': 2.0, 'cost_share': 20.0}),
            ],
        })
        cls.vendor = env['res.partner'].create({'name': 'ZZ Test CKD Vendor'})
        cls.warehouse = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)

    # ------------------------------------------------------------------ helpers

    def _po(self, kits=10, price=1000.0):
        return self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [Command.create({
                'product_id': self.kit.id, 'product_qty': kits, 'price_unit': price,
                'name': self.kit.name,
            })],
        })

    def _approved_confirmed_po(self, kits=10, price=1000.0):
        self.bom.action_approve_cost_share()
        po = self._po(kits, price)
        po.button_confirm()
        return po

    def _grn(self, po, drop_links=True, picking_type=None):
        """A receipt filled the way the GRN screen does: the picker's parts —
        with the PO link fields dropped, as the web client drops them."""
        Picking = self.env['stock.picking']
        picking_type = picking_type or self.warehouse.in_type_id
        dest = (picking_type.default_location_dest_id
                if picking_type != self.warehouse.in_type_id and picking_type.default_location_dest_id
                else self.warehouse.lot_stock_id)
        draft = Picking.new({
            'picking_type_id': picking_type.id,
            'partner_id': self.vendor.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': dest.id,
            'x_source_po_id': po.id,
        })
        draft._onchange_x_source_po_id()
        parts = []
        for move in draft.move_ids_without_package:
            vals = {
                'name': move.name, 'product_id': move.product_id.id,
                'product_uom': move.product_uom.id, 'product_uom_qty': move.product_uom_qty,
                'location_id': draft.location_id.id, 'location_dest_id': draft.location_dest_id.id,
                'picking_type_id': picking_type.id,
            }
            if not drop_links:
                vals.update({
                    'purchase_line_id': move.purchase_line_id.id,
                    'bom_line_id': move.bom_line_id.id,
                    'cost_share': move.cost_share,
                })
            parts.append(Command.create(vals))
        return Picking.create({
            'picking_type_id': picking_type.id,
            'partner_id': self.vendor.id,
            'location_id': draft.location_id.id,
            'location_dest_id': draft.location_dest_id.id,
            'x_source_po_id': po.id,
            'move_ids_without_package': parts,
        })

    def _receive(self, picking, quantities=None, cancel_remainder=False):
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = (quantities or {}).get(move.product_id, move.product_uom_qty)
            move.picked = True
        picking.with_context(cancel_backorder=cancel_remainder)._action_done()

    def _value(self, picking_moves, product):
        layers = self.env['stock.valuation.layer'].search([
            ('stock_move_id', 'in', picking_moves.ids), ('product_id', '=', product.id),
        ])
        return sum(layers.mapped('value'))

    # -------------------------------------------------------------------- tests

    def test_kit_needs_approval_before_po_confirm(self):
        po = self._po()
        with self.assertRaises(UserError):
            po.button_confirm()
        self.bom.action_approve_cost_share()
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        alloc = po.order_line._ckd_allocation()
        self.assertTrue(alloc, 'The allocation is frozen when the PO is confirmed')
        self.assertEqual(alloc.version, 1)
        self.assertAlmostEqual(alloc.total_share, 100.0)

    def test_total_must_be_100_to_approve(self):
        self.bom.bom_line_ids[0].cost_share = 40.0   # 40 + 30 + 20 = 90
        with self.assertRaises(UserError):
            self.bom.action_approve_cost_share()

    def test_editing_a_part_withdraws_approval_but_po_keeps_frozen_copy(self):
        po = self._approved_confirmed_po()
        self.assertTrue(self.bom.x_cost_share_approved)
        # change the live BoM after the PO was confirmed
        self.bom.bom_line_ids.filtered(lambda l: l.product_id == self.chassis).cost_share = 40.0
        self.bom.bom_line_ids.filtered(lambda l: l.product_id == self.motor).cost_share = 40.0
        self.assertFalse(self.bom.x_cost_share_approved, 'Editing withdraws the approval')
        shares = po.order_line._ckd_allocation()._shares_by_product()
        self.assertAlmostEqual(shares[self.chassis.id], 50.0)
        self.assertAlmostEqual(shares[self.motor.id], 30.0)

    def test_ordinary_kit_is_not_blocked(self):
        """A phantom BoM that is not a CKD kit (e.g. a battery pack) keeps working."""
        plain = self.env['product.product'].create({'name': 'ZZ Plain Kit', 'type': 'consu', 'is_storable': False})
        self.env['mrp.bom'].create({
            'product_tmpl_id': plain.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1.0,
            'bom_line_ids': [Command.create({'product_id': self.chassis.id, 'product_qty': 1.0})],
        })
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [Command.create({
                'product_id': plain.id, 'product_qty': 1, 'price_unit': 10.0, 'name': plain.name})],
        })
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')

    def test_grn_picker_lists_the_parts_not_the_kit(self):
        po = self._approved_confirmed_po(kits=10)
        draft = self.env['stock.picking'].new({
            'picking_type_id': self.warehouse.in_type_id.id,
            'partner_id': self.vendor.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
            'x_source_po_id': po.id,
        })
        draft._onchange_x_source_po_id()
        wanted = {self.chassis: 10.0, self.motor: 10.0, self.suspension: 20.0}
        got = {m.product_id: m.product_uom_qty for m in draft.move_ids_without_package}
        self.assertEqual(got, wanted)

    def test_server_links_dropped_part_fields(self):
        po = self._approved_confirmed_po(kits=10)
        picking = self._grn(po, drop_links=True)
        line = po.order_line
        for move in picking.move_ids:
            self.assertEqual(move.purchase_line_id, line, 'Part is tied to the kit PO line')
            self.assertTrue(move.bom_line_id)
        shares = {m.product_id: m.cost_share for m in picking.move_ids}
        self.assertAlmostEqual(shares[self.chassis], 50.0)
        self.assertAlmostEqual(shares[self.motor], 30.0)
        self.assertAlmostEqual(shares[self.suspension], 20.0)

    def test_full_receipt_values_parts_by_share_and_po_tracking(self):
        po = self._approved_confirmed_po(kits=10, price=1000.0)
        picking = self._grn(po)
        self._receive(picking)
        moves = picking.move_ids
        self.assertAlmostEqual(self._value(moves, self.chassis), 5000.0, places=2)
        self.assertAlmostEqual(self._value(moves, self.motor), 3000.0, places=2)
        self.assertAlmostEqual(self._value(moves, self.suspension), 2000.0, places=2)
        self.assertAlmostEqual(po.order_line.qty_received, 10.0)
        # tracking report
        po.invalidate_recordset()
        self.assertAlmostEqual(po.x_trk_po_qty, 10.0)
        self.assertAlmostEqual(po.x_trk_received_qty, 10.0)
        self.assertAlmostEqual(po.x_trk_pending_qty, 0.0)
        self.assertAlmostEqual(po.x_trk_stock_qty, 10.0)
        self.assertEqual(po.x_trk_stage, 'completed')
        self.assertIn(picking.name, po.x_trk_grn_refs)

    def test_short_delivery_is_valued_at_what_arrived(self):
        po = self._approved_confirmed_po(kits=10, price=1000.0)
        picking = self._grn(po)
        self._receive(picking, quantities={self.chassis: 6.0, self.motor: 6.0, self.suspension: 12.0},
                      cancel_remainder=True)
        done = picking.move_ids.filtered(lambda m: m.state == 'done')
        # 6 kits' worth: 6 x 1000 x share — NOT the whole 10 kits spread over the parts that came
        self.assertAlmostEqual(self._value(done, self.chassis), 3000.0, places=2)
        self.assertAlmostEqual(self._value(done, self.motor), 1800.0, places=2)
        self.assertAlmostEqual(self._value(done, self.suspension), 1200.0, places=2)
        po.invalidate_recordset()
        self.assertAlmostEqual(po.x_trk_received_qty, 6.0)
        self.assertAlmostEqual(po.x_trk_pending_qty, 4.0)
        self.assertEqual(po.x_trk_stage, 'partial')

    def test_import_flag_follows_the_vendor_country(self):
        home = self.company.account_fiscal_country_id or self.company.country_id
        other = self.env['res.country'].search([('id', '!=', home.id)], limit=1)
        po = self._po()
        self.assertEqual(po.x_po_type, 'domestic')
        self.vendor.country_id = other
        po.invalidate_recordset()
        self.assertEqual(po.x_po_type, 'import')
        self.vendor.country_id = False

    def test_bill_of_entry_landed_cost_and_reconciliation(self):
        po = self._approved_confirmed_po(kits=10, price=1000.0)
        picking = self._grn(po)
        self._receive(picking)
        duty = self.env['product.product'].create({
            'name': 'ZZ Test Customs Duty', 'type': 'service', 'landed_cost_ok': True,
            'split_method_landed_cost': 'by_current_cost_price',
        })
        boe = self.env['elegomotors.bill.of.entry'].create({
            'boe_number': 'TEST-BOE-1',
            'order_ids': [Command.set(po.ids)],
            'picking_ids': [Command.set(picking.ids)],
            'line_ids': [
                Command.create({'kind': 'bcd', 'name': 'BCD', 'product_id': duty.id,
                                'amount': 1000.0, 'capitalise': True}),
                Command.create({'kind': 'igst', 'name': 'IGST', 'amount': 500.0, 'capitalise': False}),
            ],
        })
        self.assertAlmostEqual(boe.capitalised_total, 1000.0)
        self.assertAlmostEqual(boe.igst_total, 500.0)
        boe.action_create_landed_cost()
        self.assertEqual(boe.state, 'landed')
        boe.action_validate_landed_cost()
        self.assertEqual(boe.state, 'done')
        layers = self.env['stock.valuation.layer'].search([
            ('stock_landed_cost_id', '=', boe.landed_cost_id.id)])
        by_product = {l.product_id: l.value for l in layers}
        self.assertAlmostEqual(by_product[self.chassis], 500.0, places=2)
        self.assertAlmostEqual(by_product[self.motor], 300.0, places=2)
        self.assertAlmostEqual(by_product[self.suspension], 200.0, places=2)
        # reconciliation agrees
        self.env['elegomotors.ckd.reconciliation'].open_for_order(po)
        rec = self.env['elegomotors.ckd.reconciliation'].search(
            [('order_id', '=', po.id)], order='id desc', limit=1)
        self.assertAlmostEqual(rec.landed_value, 1000.0, places=2)
        self.assertAlmostEqual(rec.boe_capitalised, 1000.0, places=2)
        self.assertAlmostEqual(rec.landed_difference, 0.0, places=2)
        self.assertAlmostEqual(rec.value_difference, 0.0, places=1)
        self.assertAlmostEqual(rec.inventory_value, 11000.0, places=1)

    def test_wizard_keeps_typed_shares_and_spreads_the_rest(self):
        bike = self.env['product.template'].search([('x_is_ego_bike', '=', True)], limit=1)
        if not bike:
            self.skipTest('No bike model on this database')
        extra = self.env['product.product'].create({
            'name': 'ZZ Test Extra Part', 'type': 'consu', 'is_storable': True,
            'categ_id': self.category.id})
        parts = [
            (self.chassis, 18.0, True),      # typed -> kept
            (self.motor, 15.0, True),        # typed -> kept
            (self.suspension, 0.0, False),   # share the rest
            (extra, 0.0, False),
        ]
        wiz = self.env['elegomotors.ckd.kit.wizard'].create({
            'bike_tmpl_id': bike.id,
            'kit_name': 'ZZ Test Wizard Kit',
            'line_ids': [Command.create({
                'product_id': p.id, 'product_qty': 1.0, 'uom_id': p.uom_id.id,
                'include': True, 'cost_share': share, 'fixed': fixed,
            }) for p, share, fixed in parts],
        })
        wiz.action_spread_rest()
        shares = {l.product_id: l.cost_share for l in wiz.line_ids}
        self.assertAlmostEqual(shares[self.chassis], 18.0)
        self.assertAlmostEqual(shares[self.motor], 15.0)
        self.assertAlmostEqual(shares[self.suspension], 33.5)
        self.assertAlmostEqual(shares[extra], 33.5)
        self.assertAlmostEqual(wiz.total_share, 100.0)
        wiz.action_create()
        bom = self.env['mrp.bom'].search([('product_tmpl_id.name', '=', 'ZZ Test Wizard Kit')])
        self.assertTrue(bom.x_is_ckd_kit)
        self.assertFalse(bom.x_cost_share_approved, 'A new kit waits for approval')
        self.assertAlmostEqual(bom.x_cost_share_total, 100.0)

    def test_spread_rest_refuses_more_than_100(self):
        bike = self.env['product.template'].search([('x_is_ego_bike', '=', True)], limit=1)
        if not bike:
            self.skipTest('No bike model on this database')
        wiz = self.env['elegomotors.ckd.kit.wizard'].create({
            'bike_tmpl_id': bike.id, 'kit_name': 'ZZ Test Wizard Kit 2',
            'line_ids': [
                Command.create({'product_id': self.chassis.id, 'uom_id': self.chassis.uom_id.id,
                                'include': True, 'cost_share': 70.0, 'fixed': True}),
                Command.create({'product_id': self.motor.id, 'uom_id': self.motor.uom_id.id,
                                'include': True, 'cost_share': 50.0, 'fixed': True}),
                Command.create({'product_id': self.suspension.id, 'uom_id': self.suspension.uom_id.id,
                                'include': True, 'cost_share': 0.0, 'fixed': False}),
            ],
        })
        with self.assertRaises(UserError):
            wiz.action_spread_rest()

    def test_gate_entry_qc_shows_in_tracking(self):
        """Goods booked at Gate Entry count as Received while QC is open; after QC
        the pass / reject figures are in kits (limiting part)."""
        gate = self.env.ref('elegomotors_setup.picking_type_gate_entry', raise_if_not_found=False)
        if not gate:
            self.skipTest('No Gate Entry operation type')
        self.chassis.product_tmpl_id.x_qc_required = True
        self.motor.product_tmpl_id.x_qc_required = True
        po = self._approved_confirmed_po(kits=10, price=1000.0)
        picking = self._grn(po, picking_type=gate)
        picking.action_confirm()
        po.invalidate_recordset()
        self.assertAlmostEqual(po.x_trk_received_qty, 10.0, msg='Booked at the gate = received')
        self.assertAlmostEqual(po.x_trk_pending_qty, 0.0)
        self.assertAlmostEqual(po.x_trk_qc_pending_qty, 10.0)
        self.assertEqual(po.x_trk_stage, 'quality')
        self.assertIn(picking.name, po.x_trk_qc_refs)
        # QC: 8 of 10 chassis pass, 9 of 10 motors pass
        for move in picking.move_ids:
            if move.product_id == self.chassis:
                move.x_qty_qc_passed = 8.0
            elif move.product_id == self.motor:
                move.x_qty_qc_passed = 9.0
        picking.action_gate_entry_approve_qc()
        po.invalidate_recordset()
        self.assertAlmostEqual(po.x_trk_qc_passed_qty, 8.0, msg='limited by the part with fewest passed')
        self.assertAlmostEqual(po.x_trk_qc_rejected_qty, 2.0)
        self.assertAlmostEqual(po.x_trk_qc_pending_qty, 0.0)
        self.assertEqual(po.x_trk_stage, 'partial_qc', 'Rejected parts wait for replacement')

    def _bike_with_bom(self):
        bike = self.env['product.template'].create({
            'name': 'ZZ Test Bike', 'type': 'consu', 'is_storable': True,
            'x_is_ego_bike': True, 'x_serial_prefix': 'ZZTB'})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': bike.id, 'type': 'normal', 'product_qty': 1.0,
            'bom_line_ids': [
                Command.create({'product_id': self.chassis.id, 'product_qty': 1.0}),
                Command.create({'product_id': self.motor.id, 'product_qty': 1.0}),
                Command.create({'product_id': self.suspension.id, 'product_qty': 2.0}),
            ]})
        return bike, bom

    def test_kit_is_linked_to_its_bike_and_can_be_updated_from_it(self):
        bike, bike_bom = self._bike_with_bom()
        Wizard = self.env['elegomotors.ckd.kit.wizard']
        wiz = Wizard.create({'bike_tmpl_id': bike.id, 'kit_name': 'ZZ Test Bike CKD Kit'})
        wiz._reload_parts()
        shares = {self.chassis: 50.0, self.motor: 30.0, self.suspension: 20.0}
        for line in wiz.line_ids:
            line.cost_share = shares[line.product_id]
        wiz.action_create()
        kit = self.env['mrp.bom'].search([('x_ckd_bike_tmpl_id', '=', bike.id)])
        self.assertEqual(len(kit), 1, 'The new kit remembers which bike it is for')
        self.assertTrue(kit.x_is_ckd_kit)
        kit.action_approve_cost_share()
        self.assertTrue(kit.x_cost_share_approved)

        # a second kit for the same bike + colour is refused: update the existing one
        again = Wizard.create({'bike_tmpl_id': bike.id, 'kit_name': 'ZZ Test Bike CKD Kit 2'})
        again._reload_parts()
        with self.assertRaises(UserError):
            again.action_create()

        # the bike's BoM changes: suspension gone, motor x2, a new part
        extra = self.env['product.product'].create({
            'name': 'ZZ Test New Part', 'type': 'consu', 'is_storable': True,
            'categ_id': self.category.id})
        bike_bom.bom_line_ids.filtered(lambda l: l.product_id == self.suspension).unlink()
        bike_bom.bom_line_ids.filtered(lambda l: l.product_id == self.motor).product_qty = 2.0
        bike_bom.write({'bom_line_ids': [Command.create({'product_id': extra.id, 'product_qty': 1.0})]})

        upd = Wizard.create({'mode': 'update', 'kit_bom_id': kit.id, 'bike_tmpl_id': bike.id})
        upd._reload_for_update()
        status = {l.product_id: (l.status, l.include, l.cost_share) for l in upd.line_ids}
        self.assertEqual(status[self.chassis][0], 'same')
        self.assertEqual(status[self.motor][0], 'qty')
        self.assertEqual(status[self.suspension][:2], ('removed', False))
        self.assertEqual(status[extra][:2], ('new', True))
        self.assertAlmostEqual(status[extra][2], 20.0, msg='What is left of 100% goes to the new part')
        self.assertAlmostEqual(upd.total_share, 100.0)
        upd.action_create()
        parts = {l.product_id: (l.product_qty, l.cost_share) for l in kit.bom_line_ids}
        self.assertEqual(set(parts), {self.chassis, self.motor, extra})
        self.assertEqual(parts[self.motor][0], 2.0)
        self.assertAlmostEqual(parts[self.chassis][1], 50.0)
        self.assertAlmostEqual(parts[extra][1], 20.0)
        self.assertFalse(kit.x_cost_share_approved, 'A changed kit must be approved again')

    def test_update_button_opens_the_wizard_on_the_kit(self):
        bike, _bike_bom = self._bike_with_bom()
        self.bom.write({'x_ckd_bike_tmpl_id': bike.id})
        action = self.bom.action_update_from_bike()
        wiz = self.env['elegomotors.ckd.kit.wizard'].browse(action['res_id'])
        self.assertEqual(wiz.mode, 'update')
        self.assertEqual(wiz.kit_bom_id, self.bom)
        self.assertTrue(wiz.line_ids, 'The comparison with the bike BoM is already loaded')

    def test_bill_of_entry_defaults_do_not_break(self):
        res = self.env['elegomotors.bill.of.entry'].default_get(
            ['line_ids', 'igst_debit_account_id', 'igst_journal_id'])
        self.assertEqual(len(res['line_ids']), 8)

    def test_kit_wizard_leaves_out_battery_and_charger_but_not_wires(self):
        Wizard = self.env['elegomotors.ckd.kit.wizard']
        Product = self.env['product.product']
        names = {
            'ZZ Battery Pack \u2014 Lead Acid 60V32Ah': True,
            'ZZ Battery Cell \u2014 Lead 12V32AH': True,
            'ZZ Lead charger 60v4amp': True,
            'ZZ BATTERY CONNECTION BIG WIRE': False,
            'ZZ 1.1/1.2 BATTERT CLAMP': False,
        }
        for name, separate in names.items():
            product = Product.create({'name': name, 'type': 'consu'})
            self.assertEqual(Wizard._is_separate_part(product), separate, name)
        # any other part can be marked "bought separately" by hand, no code needed
        odd = Product.create({'name': 'ZZ BAT-60-30 (new battery type)', 'type': 'consu'})
        self.assertFalse(Wizard._is_separate_part(odd))
        odd.product_tmpl_id.x_ckd_separate_line = True
        self.assertTrue(Wizard._is_separate_part(odd))

    def test_production_scan_knows_a_colour_added_later(self):
        Scan = self.env['elegomotors.global.scan.wizard']
        self.assertEqual(Scan._resolve_color_code('grey'), 'Gray', 'printed-label aliases still work')
        self.assertIsNone(Scan._resolve_color_code('Chartreuse'))
        attr = self.env.ref('elegomotors_setup.attr_ego_color')
        self.env['product.attribute.value'].create({'attribute_id': attr.id, 'name': 'Chartreuse'})
        self.assertEqual(Scan._resolve_color_code('CHARTREUSE'), 'Chartreuse')
        self.assertIn('CHARTREUSE', Scan._valid_color_codes_text())

    def test_new_bike_model_and_its_ckd_kit_need_no_developer(self):
        """A brand-new model with brand-new colours, made only through the wizards:
        New Bike Model (with a part list) -> New CKD Kit -> approve -> on a PO."""
        import base64
        csv_text = (
            'Component Name,Quantity,Colour\n'
            'ZZ DYN CHASSIS,1,\n'
            'ZZ DYN MOTOR,1,\n'
            'ZZ DYN WIRE,2,\n'
            'ZZ DYN PANEL TEALX,1,TealX\n'
            'ZZ DYN PANEL MAGENTAX,1,MagentaX\n'
        )
        model_wiz = self.env['elegomotors.new.bike.model.wizard'].create({
            'mode': 'new_model', 'name': 'ZZ Dynamic Bike 9.9', 'x_serial_prefix': 'ZZDYN99',
            'colour_names': 'TealX, MagentaX',
            'bom_file': base64.b64encode(csv_text.encode()), 'bom_filename': 'bom.csv',
        })
        model_wiz.action_check()
        model_wiz.new_part_categ_id = self.category          # Average costing
        model_wiz.line_ids.filtered(
            lambda l: not l.product_tmpl_id and not l.create_new).write({'create_new': True})
        model_wiz.action_create()
        bike = self.env['product.template'].search([('name', '=', 'ZZ Dynamic Bike 9.9')])
        self.assertTrue(bike.x_is_ego_bike, 'The new model is a bike model')
        new_part = self.env['product.product'].search([('name', '=', 'ZZ DYN CHASSIS')])
        self.assertEqual(new_part.categ_id, self.category, 'New parts go to the chosen category')
        self.assertEqual(new_part.cost_method, 'average')

        teal = bike.attribute_line_ids.value_ids.filtered(lambda v: v.name == 'TealX')
        kit_wiz = self.env['elegomotors.ckd.kit.wizard'].create({
            'bike_tmpl_id': bike.id, 'colour_value_id': teal.id})
        kit_wiz._reload_parts()
        self.assertEqual(kit_wiz.kit_name, 'ZZ Dynamic Bike 9.9 CKD Kit \u2013 TealX')
        parts = kit_wiz.line_ids.mapped('product_id.name')
        self.assertEqual(sorted(parts), ['ZZ DYN CHASSIS', 'ZZ DYN MOTOR', 'ZZ DYN PANEL TEALX', 'ZZ DYN WIRE'],
                         'Common parts plus the Teal-only panel, and not the Magenta panel')
        # type the shares we know, spread the rest, create, approve
        for line in kit_wiz.line_ids:
            if line.product_id.name == 'ZZ DYN CHASSIS':
                line.write({'cost_share': 40.0, 'fixed': True})
        kit_wiz.action_spread_rest()
        self.assertAlmostEqual(kit_wiz.total_share, 100.0)
        kit_wiz.action_create()
        kit = self.env['mrp.bom'].search([('x_ckd_bike_tmpl_id', '=', bike.id), ('x_ckd_colour_id', '=', teal.id)])
        self.assertEqual(len(kit), 1)
        kit.action_approve_cost_share()
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [Command.create({
                'product_id': kit.product_tmpl_id.product_variant_id.id, 'product_qty': 5,
                'price_unit': 1000.0, 'name': kit.product_tmpl_id.name})],
        })
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        self.assertTrue(po.order_line._ckd_allocation())
        # receive it: every part is valued from the PO price (not 0), 5 kits x 1000
        picking = self._grn(po)
        self._receive(picking)
        layers = self.env['stock.valuation.layer'].search([('stock_move_id', 'in', picking.move_ids.ids)])
        self.assertAlmostEqual(sum(layers.mapped('value')), 5000.0, places=2)
        # the other colour has its own kit, no clash
        magenta = bike.attribute_line_ids.value_ids.filtered(lambda v: v.name == 'MagentaX')
        other = self.env['elegomotors.ckd.kit.wizard'].create({
            'bike_tmpl_id': bike.id, 'colour_value_id': magenta.id})
        other._reload_parts()
        self.assertIn('ZZ DYN PANEL MAGENTAX', other.line_ids.mapped('product_id.name'))
        # the model's colours scan in the production wizard too
        self.assertEqual(
            self.env['elegomotors.global.scan.wizard']._resolve_color_code('tealx'), 'TealX')

    def test_bill_of_entry_needs_receipts_and_amounts(self):
        boe = self.env['elegomotors.bill.of.entry'].create({'boe_number': 'TEST-BOE-2'})
        with self.assertRaises(UserError):
            boe.action_create_landed_cost()
