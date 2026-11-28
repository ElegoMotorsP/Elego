# -*- coding: utf-8 -*-
"""Odoo-side tests for the delivery estimator: the ERP snapshot and the HTTP
surface. The allocation logic itself is covered without a database by
tests/unit/test_delivery_engine.py at the repo root.

    odoo-bin -d <db> -u elego_connect --test-enable --test-tags /elego_connect --stop-after-init
"""
import json

from odoo.tests import HttpCase, TransactionCase, tagged

from ..models.delivery_estimator import DEBUG_PARAM


def _bike_variant(env):
    return env['product.product'].search([
        ('product_tmpl_id.x_is_ego_bike', '=', True),
        ('active', '=', True),
        ('sale_ok', '=', True),
    ], limit=1)


@tagged('post_install', '-at_install')
class TestDeliveryEstimator(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.variant = _bike_variant(cls.env)
        cls.Estimator = cls.env['elegomotors.delivery.estimator']
        cls.dealer = cls.env['res.partner'].create({'name': 'DE Test Dealer'})

    def setUp(self):
        super().setUp()
        if not self.variant:
            self.skipTest('no bike variant in this database')

    def _backlog_sos(self):
        return {b.so for b in self.Estimator._de_snapshot().backlog}

    def test_pending_order_ignored_until_approved(self):
        order, _created = self.env['sale.order'].create_from_connect_po({
            'poNumber': 'DE-TEST-PO-1',
            'odooPartnerId': self.dealer.id,
            'lines': [{'odooProductId': self.variant.id, 'quantity': 2, 'unitPrice': 1000}],
        })
        self.assertTrue(order.pending_approval)
        self.assertNotIn(order.name, self._backlog_sos())

        error = order.connect_record_decision('approve', approver='accounts')
        self.assertFalse(error)
        self.assertFalse(order.pending_approval)
        self.assertTrue(order.x_approved_at)
        self.assertIn(order.name, self._backlog_sos())

    def test_snapshot_covers_every_bike_variant(self):
        snap = self.Estimator._de_snapshot()
        variants = self.env['product.product'].search([
            ('product_tmpl_id.x_is_ego_bike', '=', True),
            ('active', '=', True), ('sale_ok', '=', True),
        ])
        self.assertEqual(set(snap.variants), set(variants.ids))
        result, tracer = self.Estimator.estimate_catalogue()
        self.assertIsNone(tracer)
        self.assertEqual({i['odooTemplateId'] for i in result['items']},
                         set(variants.product_tmpl_id.ids))

    def test_fg_quant_counted(self):
        fg = self.env.ref('elegomotors_setup.location_ego_fg')
        before = self.Estimator._de_snapshot().variants[self.variant.id].fg_usable
        self.env['stock.quant']._update_available_quantity(self.variant, fg, 2)
        after = self.Estimator._de_snapshot().variants[self.variant.id].fg_usable
        self.assertEqual(after - before, 2)

    def test_company_settings_reach_engine(self):
        self.env.company.write({'x_de_transit_days': 5, 'x_de_fixed_daily_rate': 3})
        cfg = self.Estimator._de_snapshot().config
        self.assertEqual(cfg['transit_days'], 5)
        self.assertEqual(cfg['fixed_daily_rate'], 3)

    def test_estimator_does_not_write(self):
        """Read-only guarantee: no ERP record changes while estimating."""
        watched = ['sale.order', 'sale.order.line', 'stock.quant', 'stock.move',
                   'mrp.production', 'purchase.order.line', 'stock.lot']
        before = {m: max(self.env[m].search([], order='write_date desc', limit=1).mapped('write_date') or [None])
                  for m in watched}
        self.Estimator.estimate_catalogue(debug=True)
        if self.variant:
            self.Estimator.estimate_cart([(self.variant.id, 3)], debug=True)
        self.env.flush_all()
        after = {m: max(self.env[m].search([], order='write_date desc', limit=1).mapped('write_date') or [None])
                 for m in watched}
        self.assertEqual(before, after)


@tagged('post_install', '-at_install')
class TestDeliveryApiHttp(HttpCase):

    def setUp(self):
        super().setUp()
        Client = self.env['elegomotors.connect.api.client']
        client = Client.create({'name': 'DE test client'})
        client.action_generate_credentials()
        token, _ttl = Client.issue_token(client.client_id)
        self.headers = {'Authorization': f'Bearer {token}'}
        self.variant = _bike_variant(self.env)
        self.env['ir.config_parameter'].sudo().set_param(DEBUG_PARAM, '')

    def _get(self, query='', headers=None):
        return self.url_open('/elegomotors/connect/delivery-estimates' + query,
                             headers=self.headers if headers is None else headers)

    def _post(self, body):
        return self.url_open('/elegomotors/connect/delivery-estimates/quote',
                             data=json.dumps(body),
                             headers=dict(self.headers, **{'Content-Type': 'application/json'}))

    def test_requires_token(self):
        self.assertEqual(self._get(headers={}).status_code, 401)

    def test_catalogue_shape_has_no_internal_detail(self):
        res = self._get()
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertNotIn('debug', body)
        allowed = {'odooTemplateId', 'model', 'freeStockQty', 'estimatedDispatchDate',
                   'estimatedDeliveryDate', 'leadDays', 'basis', 'limitingFactor',
                   'confidence', 'reason'}
        for item in body['items']:
            self.assertLessEqual(set(item), allowed)

    def test_debug_needs_system_parameter(self):
        self.assertNotIn('debug', self._get('?debug=1').json())
        self.env['ir.config_parameter'].sudo().set_param(DEBUG_PARAM, '1')
        self.assertNotIn('debug', self._get().json())
        body = self._get('?debug=1').json()
        self.assertIn('debug', body)
        self.assertTrue(any(line.startswith('RATE') for line in body['debug']['trace']))
        self.assertIn('rate', body['debug']['values'])

    def test_quote_validation_and_unknown_product(self):
        self.assertEqual(self._post({}).status_code, 400)
        self.assertEqual(self._post({'lines': [{'odooProductId': 'x'}]}).status_code, 400)
        body = self._post({'lines': [{'odooProductId': 999999999, 'quantity': 1}]}).json()
        self.assertEqual(body['errors'][0]['error'], 'unknown_product')

    def test_quote_happy_path(self):
        if not self.variant:
            self.skipTest('no bike variant in this database')
        body = self._post({'lines': [{'odooProductId': self.variant.id, 'quantity': 2}]}).json()
        self.assertEqual(len(body['models']), 1)
        m = body['models'][0]
        self.assertEqual(m['odooTemplateId'], self.variant.product_tmpl_id.id)
        self.assertEqual(m['quantity'], 2)
        self.assertIn('orderCompleteDate', body)
