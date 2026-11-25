# -*- coding: utf-8 -*-
"""CKD cost and quantity reconciliation — one screen per Purchase Order.

For every CKD kit on the PO, part by part:
  * QUANTITY  — what the kits ordered call for vs what was received;
  * VALUE     — what the part is worth in stock vs what the kit price x its
                frozen cost share says it should be worth (a gap means the
                allocation did not do what it should);
  * LANDED    — duty / charges added to the part (Bill of Entry), and the
                total set against the Bill of Entry amounts capitalised, so any
                duty that did not reach the parts (stock already consumed,
                parts on Standard costing) shows up as a difference.

Final inventory value = allocated kit value + landed cost.
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.tools import float_compare, float_is_zero


class CkdReconciliation(models.TransientModel):
    _name = 'elegomotors.ckd.reconciliation'
    _description = 'CKD Cost and Quantity Reconciliation'

    order_id = fields.Many2one('purchase.order', required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', related='order_id.company_id.currency_id')
    line_ids = fields.One2many('elegomotors.ckd.reconciliation.line', 'wizard_id')

    allocated_value = fields.Monetary(currency_field='currency_id', readonly=True)
    expected_value = fields.Monetary(currency_field='currency_id', readonly=True)
    value_difference = fields.Monetary(currency_field='currency_id', readonly=True)
    landed_value = fields.Monetary(currency_field='currency_id', readonly=True)
    boe_capitalised = fields.Monetary(
        currency_field='currency_id', readonly=True, string='Capitalised on Bills of Entry')
    landed_difference = fields.Monetary(currency_field='currency_id', readonly=True)
    inventory_value = fields.Monetary(currency_field='currency_id', readonly=True)
    status = fields.Char(readonly=True)

    @api.model
    def open_for_order(self, order):
        wizard = self.create({'order_id': order.id})
        wizard._compute_lines()
        return {
            'type': 'ir.actions.act_window', 'name': _('CKD Reconciliation — %s', order.name),
            'res_model': self._name, 'res_id': wizard.id, 'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------

    def _layers_for(self, moves):
        layers = self.env['stock.valuation.layer'].sudo().search([('stock_move_id', 'in', moves.ids)])
        base = sum(l.value for l in layers if not l.stock_landed_cost_id)
        landed = sum(l.value for l in layers if l.stock_landed_cost_id)
        return base, landed

    def _compute_lines(self):
        """One line per PART, not per kit: a part common to two kits on this PO
        (e.g. a Red CKD kit and a Black CKD kit sharing a wiring harness) is
        counted once, with its ordered/received/value figures summed across
        every kit that uses it — "Used In" lists which. Before this, the same
        part showed up once per kit it belonged to, which made the screen (and
        the client's Excel) far longer than the PO actually needed."""
        self.ensure_one()
        order = self.order_id
        company = order.company_id
        Line = self.env['elegomotors.ckd.reconciliation.line']
        totals = defaultdict(float)
        by_product = {}
        product_order = []
        for po_line in order._ckd_kit_lines():
            bom = po_line._ckd_kit_bom()
            alloc = po_line._ckd_allocation()
            kits = po_line.product_uom._compute_quantity(po_line.product_qty, bom.product_uom_id) / (
                bom.product_qty or 1.0)
            for bom_line in bom.bom_line_ids:
                moves = po_line.move_ids.filtered(
                    lambda m, bl=bom_line: m.bom_line_id == bl and m.state == 'done'
                    and m.location_id.usage == 'supplier')
                ordered = bom_line.product_qty * kits
                received = sum(
                    m.product_uom._compute_quantity(m.quantity, bom_line.product_uom_id) for m in moves)
                share = po_line._ckd_cost_share_for(bom_line, bom_line.cost_share) or 0.0
                per_kit = bom_line.product_qty / (bom.product_qty or 1.0)
                # What the part should be worth: kit price x share x kits' worth received,
                # converted at the rate of the day each receipt was validated.
                expected = 0.0
                for move in moves:
                    qty = move.product_uom._compute_quantity(move.quantity, bom_line.product_uom_id)
                    foreign = po_line.price_unit * (share / 100.0) * (qty / per_kit if per_kit else 0.0)
                    day = move.date.date() if move.date else fields.Date.context_today(self)
                    expected += order.currency_id._convert(foreign, company.currency_id, company, day)
                allocated, landed = self._layers_for(moves)

                pid = bom_line.product_id.id
                entry = by_product.get(pid)
                if entry is None:
                    entry = {
                        'qty_per_kit': per_kit, 'cost_share': share, 'frozen': True,
                        'ordered_qty': 0.0, 'received_qty': 0.0, 'allocated_value': 0.0,
                        'expected_value': 0.0, 'landed_value': 0.0, 'kits': [],
                    }
                    by_product[pid] = entry
                    product_order.append(pid)
                elif entry['qty_per_kit'] != per_kit or entry['cost_share'] != share:
                    # Differs between the kits sharing this part — no single figure
                    # describes it, so leave these two descriptive columns blank
                    # rather than show a number that only applies to one of them.
                    entry['qty_per_kit'] = 0.0
                    entry['cost_share'] = 0.0
                entry['kits'].append(po_line.product_id.display_name)
                entry['frozen'] = entry['frozen'] and bool(alloc)
                entry['ordered_qty'] += ordered
                entry['received_qty'] += received
                entry['allocated_value'] += allocated
                entry['expected_value'] += expected
                entry['landed_value'] += landed

                totals['allocated'] += allocated
                totals['expected'] += expected
                totals['landed'] += landed

        vals_list = []
        rounding = company.currency_id.rounding
        for pid in product_order:
            entry = by_product[pid]
            diff = entry['allocated_value'] - entry['expected_value']
            qty_diff = entry['received_qty'] - entry['ordered_qty']
            part_rounding = self.env['product.product'].browse(pid).uom_id.rounding
            notes = []
            if float_compare(qty_diff, 0.0, precision_rounding=part_rounding) < 0:
                notes.append(_('Short by %s', abs(qty_diff)))
            elif float_compare(qty_diff, 0.0, precision_rounding=part_rounding) > 0:
                notes.append(_('Over-received by %s', qty_diff))
            if abs(diff) > max(rounding * max(len(entry['kits']), 1), 1.0):
                notes.append(_('Value differs from kit price × share'))
            vals_list.append({
                'wizard_id': self.id,
                'kit_names': ', '.join(dict.fromkeys(entry['kits'])),
                'product_id': pid,
                'qty_per_kit': entry['qty_per_kit'],
                'cost_share': entry['cost_share'],
                'frozen': entry['frozen'],
                'ordered_qty': entry['ordered_qty'],
                'received_qty': entry['received_qty'],
                'allocated_value': entry['allocated_value'],
                'expected_value': entry['expected_value'],
                'landed_value': entry['landed_value'],
                'note': '; '.join(notes) or 'OK',
            })
        Line.create(vals_list)

        boes = self.env['elegomotors.bill.of.entry'].search([
            ('order_ids', 'in', order.id), ('state', 'in', ('landed', 'done'))])
        capitalised = sum(boes.mapped('capitalised_total'))
        value_diff = totals['allocated'] - totals['expected']
        landed_diff = totals['landed'] - capitalised
        rounding = company.currency_id.rounding
        status = []
        if not vals_list:
            status.append(_('No CKD kit on this order.'))
        else:
            if any(l['note'] != 'OK' for l in vals_list):
                status.append(_('Check the lines marked in the Note column.'))
            if not float_is_zero(landed_diff, precision_rounding=rounding) and boes:
                status.append(_('Landed cost in stock differs from the Bill of Entry amounts capitalised '
                                '(duty on parts already consumed, or parts on Standard costing).'))
        self.write({
            'allocated_value': totals['allocated'],
            'expected_value': totals['expected'],
            'value_difference': value_diff,
            'landed_value': totals['landed'],
            'boe_capitalised': capitalised,
            'landed_difference': landed_diff,
            'inventory_value': totals['allocated'] + totals['landed'],
            'status': ' '.join(status) or _('Reconciled: kit value and landed cost agree with the parts in stock.'),
        })

    def action_download_xlsx(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/elegomotors/ckd_reconciliation/%s.xlsx' % self.id,
            'target': 'self',
        }


class CkdReconciliationLine(models.TransientModel):
    _name = 'elegomotors.ckd.reconciliation.line'
    _description = 'CKD Reconciliation Line'
    _order = 'id'

    wizard_id = fields.Many2one(
        'elegomotors.ckd.reconciliation', required=True, ondelete='cascade')
    currency_id = fields.Many2one('res.currency', related='wizard_id.currency_id')
    kit_names = fields.Char(
        string='Used In',
        help='Every CKD kit on this PO that uses this part — the figures on '
             'this row are the sum across all of them.')
    product_id = fields.Many2one('product.product', string='Part')
    qty_per_kit = fields.Float(string='Per Kit', digits='Product Unit of Measure')
    cost_share = fields.Float(string='Cost Share (%)', digits=(5, 2))
    frozen = fields.Boolean(string='Frozen')
    ordered_qty = fields.Float(string='Ordered', digits='Product Unit of Measure')
    received_qty = fields.Float(string='Received', digits='Product Unit of Measure')
    allocated_value = fields.Monetary(currency_field='currency_id', string='Kit Value in Stock')
    expected_value = fields.Monetary(currency_field='currency_id', string='Expected Value')
    landed_value = fields.Monetary(currency_field='currency_id', string='Duty / Landed Cost')
    final_value = fields.Monetary(
        currency_field='currency_id', compute='_compute_final', string='Final Value')
    note = fields.Char()

    @api.depends('allocated_value', 'landed_value')
    def _compute_final(self):
        for line in self:
            line.final_value = line.allocated_value + line.landed_value


class PurchaseOrderCkdReconciliation(models.Model):
    _inherit = 'purchase.order'

    def action_open_ckd_reconciliation(self):
        self.ensure_one()
        return self.env['elegomotors.ckd.reconciliation'].open_for_order(self)
