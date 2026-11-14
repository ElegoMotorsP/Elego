# -*- coding: utf-8 -*-
"""New CKD Kit wizard — makes the kit product and its Kit BoM for one model +
colour, with the cost share of every part.

The parts are copied from the bike's own colour BoM (the same parts the scooter
is built from), so the kit and the Manufacturing BoM stay in step. Battery,
charger and cells are left out by default — the supplier order carries those as
their own PO lines — and any line can be switched on/off, added or re-weighted
before the kit is created. The kit is NOT approved here: its cost allocation is
approved afterwards on the BoM (maker / checker), and only an approved kit can
go on a Purchase Order.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

# Parts the supplier invoices as their own PO lines, not inside the kit.
_SEPARATE_LINE_RE = re.compile(r'battery|charger|\bcell\b', re.IGNORECASE)


class CkdKitWizard(models.TransientModel):
    _name = 'elegomotors.ckd.kit.wizard'
    _description = 'New CKD Kit'

    bike_tmpl_id = fields.Many2one(
        'product.template', string='Bike Model', required=True,
        domain=[('x_is_ego_bike', '=', True)])
    valid_colour_ids = fields.Many2many(
        'product.attribute.value', compute='_compute_valid_colour_ids')
    colour_value_id = fields.Many2one(
        'product.attribute.value', string='Colour',
        domain="[('id', 'in', valid_colour_ids)]")
    kit_name = fields.Char(
        string='Kit Name', required=True,
        help='The product that goes on the Purchase Order, e.g. "Elego 1.1 CKD Kit – Red".')
    source_bom_id = fields.Many2one('mrp.bom', string='Copied From', readonly=True)
    line_ids = fields.One2many('elegomotors.ckd.kit.wizard.line', 'wizard_id', string='Parts')
    total_share = fields.Float(
        string='Total Cost Share (%)', compute='_compute_totals', digits=(5, 2))
    included_count = fields.Integer(compute='_compute_totals')
    warning = fields.Text(compute='_compute_totals')

    # ------------------------------------------------------------------
    # Loading the parts
    # ------------------------------------------------------------------

    @api.depends('bike_tmpl_id')
    def _compute_valid_colour_ids(self):
        for wiz in self:
            values = self.env['product.attribute.value']
            for attr_line in wiz.bike_tmpl_id.attribute_line_ids:
                if attr_line.attribute_id.name == 'Color':
                    values = attr_line.value_ids
                    break
            wiz.valid_colour_ids = values

    @api.depends('line_ids.include', 'line_ids.cost_share', 'line_ids.cost_method')
    def _compute_totals(self):
        for wiz in self:
            included = wiz.line_ids.filtered('include')
            wiz.included_count = len(included)
            wiz.total_share = sum(included.mapped('cost_share'))
            no_duty = included.filtered(
                lambda l: l.product_id and l.cost_method not in ('average', 'fifo'))
            wiz.warning = _(
                'Import duty / landed cost can only be added to parts with Average or FIFO '
                'costing. These parts use another costing method and would be skipped: %s',
                ', '.join(no_duty.mapped('product_id.display_name')[:12]),
            ) if no_duty else False

    def _variant(self):
        self.ensure_one()
        tmpl = self.bike_tmpl_id
        if self.colour_value_id:
            return tmpl.product_variant_ids.filtered(
                lambda v: self.colour_value_id in v.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id')
            )[:1]
        return tmpl.product_variant_ids[:1] if len(tmpl.product_variant_ids) == 1 else tmpl.product_variant_ids[:0]

    def _find_source_bom(self):
        self.ensure_one()
        Bom = self.env['mrp.bom']
        variant = self._variant()
        bom = Bom
        if variant:
            bom = Bom.search([
                ('product_tmpl_id', '=', self.bike_tmpl_id.id), ('type', '=', 'normal'),
                ('product_id', '=', variant.id)], limit=1)
        return bom or Bom.search([
            ('product_tmpl_id', '=', self.bike_tmpl_id.id), ('type', '=', 'normal'),
            ('product_id', '=', False)], limit=1)

    @api.onchange('bike_tmpl_id')
    def _onchange_bike_tmpl_id(self):
        self.colour_value_id = False
        self._reload_parts()

    @api.onchange('colour_value_id')
    def _onchange_colour_value_id(self):
        self._reload_parts()

    def _reload_parts(self):
        self.ensure_one()
        tmpl = self.bike_tmpl_id
        if not tmpl:
            self.kit_name = False
            self.source_bom_id = False
            self.line_ids = [(5, 0, 0)]
            return
        colour = self.colour_value_id.name
        self.kit_name = f'{tmpl.name} CKD Kit – {colour}' if colour else f'{tmpl.name} CKD Kit'
        bom = self._find_source_bom() if (colour or not self.valid_colour_ids) else self.env['mrp.bom']
        self.source_bom_id = bom
        commands = [(5, 0, 0)]
        rows = []
        for bom_line in bom.bom_line_ids:
            rows.append({
                'product_id': bom_line.product_id.id,
                'product_qty': bom_line.product_qty,
                'uom_id': bom_line.product_uom_id.id,
                'include': not _SEPARATE_LINE_RE.search(bom_line.product_id.name or ''),
            })
        included = [r for r in rows if r['include']]
        for row in rows:
            row['cost_share'] = 0.0
        self._spread_equally(included)
        commands += [(0, 0, row) for row in rows]
        self.line_ids = commands

    @staticmethod
    def _spread_equally(rows, total=100.0):
        """Equal cost share over `rows` (dicts) adding up to `total`; the last
        one takes the rounding."""
        if not rows:
            return
        each = float_round(total / len(rows), precision_digits=2)
        for row in rows[:-1]:
            row['cost_share'] = each
        rows[-1]['cost_share'] = float_round(total - each * (len(rows) - 1), precision_digits=2)

    # ------------------------------------------------------------------
    # Share helpers (buttons)
    # ------------------------------------------------------------------

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('New CKD Kit'),
            'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
            'target': 'new', 'context': {'dialog_size': 'extra-large'},
        }

    def action_equal_split(self):
        self.ensure_one()
        included = self.line_ids.filtered('include')
        rows = [{'rec': l} for l in included]
        self._spread_equally(rows)
        for row in rows:
            row['rec'].cost_share = row.pop('cost_share')
        (self.line_ids - included).write({'cost_share': 0.0})
        self.line_ids.write({'fixed': False})
        return self._reopen()

    def action_spread_rest(self):
        """Keep the shares typed on the "Keep" parts (e.g. chassis 18, motor 15,
        controller 7) and share what is left of the 100% equally over the other
        ticked parts (e.g. the remaining 60% over everything else)."""
        self.ensure_one()
        included = self.line_ids.filtered('include')
        kept = included.filtered('fixed')
        others = included - kept
        rest = float_round(100.0 - sum(kept.mapped('cost_share')), precision_digits=2)
        if rest < 0:
            raise UserError(_('The shares you kept already add up to %.2f%% — more than 100%%.',
                              100.0 - rest))
        if not others:
            if rest:
                raise UserError(_('Every ticked part is marked "Keep" and they total %.2f%%. '
                                  'Untick "Keep" on the parts that should share the remaining %.2f%%.',
                                  100.0 - rest, rest))
            return self._reopen()
        rows = [{'rec': l} for l in others]
        self._spread_equally(rows, total=rest)
        for row in rows:
            row['rec'].cost_share = row.pop('cost_share')
        (self.line_ids - included).write({'cost_share': 0.0})
        return self._reopen()

    def action_split_by_cost(self):
        """Shares in proportion to each part's current cost x quantity."""
        self.ensure_one()
        included = self.line_ids.filtered('include')
        weights = {l.id: (l.product_id.standard_price or 0.0) * (l.product_qty or 0.0) for l in included}
        total = sum(weights.values())
        if not total:
            raise UserError(_('The selected parts have no cost recorded yet — use the equal split.'))
        rows = [{'rec': l, 'cost_share': 0.0} for l in included]
        running = 0.0
        for row in rows[:-1]:
            row['cost_share'] = float_round(100.0 * weights[row['rec'].id] / total, precision_digits=2)
            running += row['cost_share']
        rows[-1]['cost_share'] = float_round(100.0 - running, precision_digits=2)
        for row in rows:
            row['rec'].cost_share = row['cost_share']
        (self.line_ids - included).write({'cost_share': 0.0})
        self.line_ids.write({'fixed': False})
        return self._reopen()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def action_create(self):
        self.ensure_one()
        # Product / BoM creation is restricted by Odoo to Inventory / Manufacturing
        # administrators; the wizard's own menu is the access gate (same approach
        # as the New Bike Model wizard).
        self = self.sudo()
        included = self.line_ids.filtered('include')
        name = (self.kit_name or '').strip()
        if not name:
            raise UserError(_('Enter the kit name.'))
        if not included:
            raise UserError(_('Tick at least one part for the kit.'))
        if included.filtered(lambda l: not l.product_id or l.product_qty <= 0):
            raise UserError(_('Every ticked part needs a product and a quantity above 0.'))
        products = included.mapped('product_id')
        if len(products) != len(included):
            raise UserError(_('A part is listed twice. Merge the quantities into one line.'))
        zero = included.filtered(lambda l: l.cost_share <= 0)
        if zero:
            raise UserError(_('Every ticked part needs a cost share above 0%%: %s',
                              ', '.join(zero.mapped('product_id.display_name'))))
        if float_compare(self.total_share, 100.0, precision_digits=2) != 0:
            raise UserError(_('The cost shares total %.2f%% — they must total exactly 100%%. '
                              'Use "Equal Split" or "Split by Cost", or adjust the figures.',
                              self.total_share))
        Template = self.env['product.template']
        if Template.with_context(active_test=False).search_count([('name', '=', name)]):
            raise UserError(_('A product named "%s" already exists.', name))

        unit = self.env.ref('uom.product_uom_unit')
        category = self.env.ref('elegomotors_setup.product_category_ckd_kits', raise_if_not_found=False)
        kit = Template.create({
            'name': name,
            'type': 'consu',
            'is_storable': False,
            'purchase_ok': True,
            'sale_ok': False,
            'uom_id': unit.id,
            'uom_po_id': unit.id,
            **({'categ_id': category.id} if category else {}),
        })
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': kit.id,
            'type': 'phantom',
            'product_qty': 1.0,
            'x_is_ckd_kit': True,
            'bom_line_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'product_qty': line.product_qty,
                'product_uom_id': line.uom_id.id or line.product_id.uom_id.id,
                'cost_share': line.cost_share,
            }) for line in included],
        })
        bom.message_post(body=_(
            'CKD kit created with the New CKD Kit wizard%(src)s. Cost allocation is waiting for approval.',
            src=_(' from BoM %s', self.source_bom_id.display_name) if self.source_bom_id else ''))
        return {
            'type': 'ir.actions.act_window', 'name': kit.name,
            'res_model': 'mrp.bom', 'res_id': bom.id, 'view_mode': 'form', 'target': 'current',
        }


class CkdKitWizardLine(models.TransientModel):
    _name = 'elegomotors.ckd.kit.wizard.line'
    _description = 'New CKD Kit - part'
    _order = 'id'

    wizard_id = fields.Many2one(
        'elegomotors.ckd.kit.wizard', required=True, ondelete='cascade')
    include = fields.Boolean(string='In Kit', default=True)
    product_id = fields.Many2one('product.product', string='Part', required=True)
    product_qty = fields.Float(string='Qty per Kit', default=1.0, digits='Product Unit of Measure')
    uom_id = fields.Many2one('uom.uom', string='Unit')
    cost_share = fields.Float(string='Cost Share (%)', digits=(5, 2))
    fixed = fields.Boolean(
        string='Keep', default=False,
        help='Ticked automatically when you type a cost share. "Spread Rest" keeps '
             'these shares and splits what is left over the parts that are not kept.')
    cost_method = fields.Selection(related='product_id.cost_method', string='Costing')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id

    @api.onchange('cost_share')
    def _onchange_cost_share(self):
        self.fixed = True
