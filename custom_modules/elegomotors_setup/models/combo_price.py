# -*- coding: utf-8 -*-
"""Bike Combo pricing + "Add Bike Combo" quotation wizard.

Business rule (July-2026 dealer price list): a bike sold together with a
battery + charger is priced as ONE combo — the bike line carries the whole
dealer price (5% GST), while the battery and charger lines are added at ₹0
with no tax, marked as included in the combo. Sold standalone, batteries and
chargers keep their own price with 18% GST (set on the products).

The combo dealer prices (INCLUDING 5% GST, exactly as printed on the price
list) live in Sales → Configuration → Bike Combo Prices, editable by Sales
Managers / Admin — no code change needed when the price list is revised.
"""
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

GST_COMBO_RATE = 0.05  # bike combos are billed at 5% GST


class BikeComboPrice(models.Model):
    _name = 'elegomotors.combo.price'
    _description = 'Bike Combo Dealer Price'
    _order = 'bike_tmpl_id, battery_tmpl_id'
    _rec_name = 'display_label'

    bike_tmpl_id = fields.Many2one(
        'product.template', string='Bike Model', required=True,
        ondelete='cascade',
    )
    battery_tmpl_id = fields.Many2one(
        'product.template', string='Battery Option',
        ondelete='cascade',
        help='Leave empty for the "without battery & charger" price.',
    )
    price_incl_gst = fields.Float(
        string='Dealer Price (incl. 5% GST)', required=True,
        help='Exactly as printed on the dealer price list. The quotation '
             'line stores the ex-GST unit price (this ÷ 1.05).',
    )
    active = fields.Boolean(default=True)
    display_label = fields.Char(compute='_compute_display_label')

    @api.depends('bike_tmpl_id', 'battery_tmpl_id', 'price_incl_gst')
    def _compute_display_label(self):
        for rec in self:
            battery = rec.battery_tmpl_id.name or 'Without Battery & Charger'
            rec.display_label = f'{rec.bike_tmpl_id.name or ""} — {battery}'

    def _price_ex_gst(self):
        self.ensure_one()
        return round(self.price_incl_gst / (1 + GST_COMBO_RATE), 2)


class BikeComboWizard(models.TransientModel):
    _name = 'elegomotors.bike.combo.wizard'
    _description = 'Add Bike Combo to Quotation'

    order_id = fields.Many2one(
        'sale.order', required=True, readonly=True, ondelete='cascade',
    )
    bike_tmpl_id = fields.Many2one(
        'product.template', string='Bike Model', required=True,
    )
    # Populated via default (not compute): this set is static — it never
    # changes based on user input — and a compute field with no @api.depends
    # is not guaranteed to run before the web client evaluates domains on a
    # brand-new (unsaved) wizard record, which left the Bike Model dropdown
    # showing "No records".
    allowed_bike_tmpl_ids = fields.Many2many(
        'product.template',
        default=lambda self: self.env['mrp.production']._get_ego_templates().ids,
    )
    color_value_id = fields.Many2one(
        'product.attribute.value', string='Colour',
    )
    valid_color_value_ids = fields.Many2many(
        'product.attribute.value', compute='_compute_valid_color_value_ids',
    )
    battery_tmpl_id = fields.Many2one(
        'product.template', string='Battery Pack',
        help='Leave empty to sell the bike without battery & charger.',
    )
    allowed_battery_tmpl_ids = fields.Many2many(
        'product.template', compute='_compute_allowed_battery_tmpl_ids',
        help='Battery options that have a combo price row for this model.',
    )
    charger_product_id = fields.Many2one(
        'product.product', string='Charger',
        domain=[('sale_ok', '=', True), ('name', 'ilike', 'charger')],
    )
    qty = fields.Integer(string='Quantity', default=1)
    combo_price_display = fields.Char(
        compute='_compute_combo_price_display', string='Combo Price',
    )

    @api.depends('bike_tmpl_id')
    def _compute_valid_color_value_ids(self):
        for wiz in self:
            values = self.env['product.attribute.value']
            if wiz.bike_tmpl_id:
                for line in wiz.bike_tmpl_id.attribute_line_ids:
                    if line.attribute_id.name == 'Color':
                        values = line.value_ids
                        break
            wiz.valid_color_value_ids = values

    @api.depends('bike_tmpl_id')
    def _compute_allowed_battery_tmpl_ids(self):
        Combo = self.env['elegomotors.combo.price']
        for wiz in self:
            rows = Combo.search([
                ('bike_tmpl_id', '=', wiz.bike_tmpl_id.id),
                ('battery_tmpl_id', '!=', False),
            ]) if wiz.bike_tmpl_id else Combo
            wiz.allowed_battery_tmpl_ids = rows.mapped('battery_tmpl_id')

    @api.depends('bike_tmpl_id', 'battery_tmpl_id')
    def _compute_combo_price_display(self):
        for wiz in self:
            row = wiz._find_combo_row()
            if row:
                wiz.combo_price_display = (
                    f'₹ {row.price_incl_gst:,.2f} incl. 5% GST '
                    f'(₹ {row._price_ex_gst():,.2f} + GST)'
                )
            else:
                wiz.combo_price_display = (
                    'No combo price configured for this model + battery' if wiz.bike_tmpl_id else ''
                )

    def _find_combo_row(self):
        self.ensure_one()
        if not self.bike_tmpl_id:
            return self.env['elegomotors.combo.price']
        return self.env['elegomotors.combo.price'].search([
            ('bike_tmpl_id', '=', self.bike_tmpl_id.id),
            ('battery_tmpl_id', '=', self.battery_tmpl_id.id or False),
        ], limit=1)

    def _resolve_bike_variant(self):
        """Match the chosen Colour to the product.product variant."""
        self.ensure_one()
        tmpl = self.bike_tmpl_id
        color_id = self.color_value_id.id if self.color_value_id else None
        for variant in tmpl.product_variant_ids:
            variant_colors = set(
                variant.product_template_attribute_value_ids.filtered(
                    lambda ptav: ptav.attribute_id.name == 'Color'
                ).mapped('product_attribute_value_id.id')
            )
            if color_id and variant_colors == {color_id}:
                return variant
            if not color_id and not variant_colors:
                return variant
        if not color_id and len(tmpl.product_variant_ids) == 1:
            return tmpl.product_variant_ids[0]
        return self.env['product.product']

    def action_add_combo(self):
        self.ensure_one()
        if self.qty <= 0:
            raise UserError('Quantity must be at least 1.')
        if self.valid_color_value_ids and not self.color_value_id:
            raise UserError('Please select the bike colour.')
        row = self._find_combo_row()
        if not row:
            battery = self.battery_tmpl_id.name or 'Without Battery & Charger'
            raise UserError(
                f'No combo price configured for {self.bike_tmpl_id.name} + '
                f'{battery}.\nAdd it under Sales → Configuration → '
                f'Bike Combo Prices (Sales Manager / Admin).'
            )
        variant = self._resolve_bike_variant()
        if not variant:
            raise UserError(
                f'No product variant found for {self.bike_tmpl_id.name} '
                f'({self.color_value_id.name or "no colour"}). Check the '
                f'product attribute configuration.'
            )

        SOL = self.env['sale.order.line']
        # Bike line: carries the full combo price; 5% GST comes from the
        # bike product's default taxes (fiscal position still remaps
        # intra/inter-state automatically).
        SOL.create({
            'order_id': self.order_id.id,
            'product_id': variant.id,
            'product_uom_qty': self.qty,
            'price_unit': row._price_ex_gst(),
        })
        included_note = ' (Included in bike combo — price & GST in bike line)'
        if self.battery_tmpl_id:
            battery_variant = self.battery_tmpl_id.product_variant_ids[:1]
            SOL.create({
                'order_id': self.order_id.id,
                'product_id': battery_variant.id,
                'product_uom_qty': self.qty,
                'price_unit': 0.0,
                'tax_id': [(6, 0, [])],
                'name': battery_variant.display_name + included_note,
                'x_is_combo_item': True,
            })
        if self.charger_product_id:
            SOL.create({
                'order_id': self.order_id.id,
                'product_id': self.charger_product_id.id,
                'product_uom_qty': self.qty,
                'price_unit': 0.0,
                'tax_id': [(6, 0, [])],
                'name': self.charger_product_id.display_name + included_note,
                'x_is_combo_item': True,
            })
        return {'type': 'ir.actions.act_window_close'}


class SaleOrderLineCombo(models.Model):
    _inherit = 'sale.order.line'

    # True for the battery/charger line added at ₹0 by "Add Bike Combo" —
    # lets the quotation/invoice reports render it as a numbered sub-item
    # (1.1, 1.2, …) under its bike line instead of its own top-level Sr.No.
    x_is_combo_item = fields.Boolean(
        string='Included In Combo', default=False, copy=False,
    )

    def _prepare_invoice_line(self, **optional_values):
        vals = super()._prepare_invoice_line(**optional_values)
        vals['x_is_combo_item'] = self.x_is_combo_item
        return vals


class AccountMoveLineCombo(models.Model):
    _inherit = 'account.move.line'

    x_is_combo_item = fields.Boolean(
        string='Included In Combo', default=False, copy=False,
    )

    # Lead Acid battery packs are physically built from 12V cells — e.g. a
    # 60V32Ah pack is 5 cells, a 72V32Ah pack is 6 (see battery_kit_data.xml's
    # phantom BOMs). Shown on the invoice's own combo Battery Pack line so
    # Store/Accounts see the cell count at a glance, matching the same hint
    # already shown on the delivery (stock_move.py) and on the invoice's
    # Vehicle Serial Details table (_ego_battery_type_display below).
    x_battery_cell_hint = fields.Char(
        string='Cells',
        compute='_compute_battery_cell_hint',
    )

    @api.depends('product_id')
    def _compute_battery_cell_hint(self):
        for line in self:
            line.x_battery_cell_hint = ''
            name = line.product_id.name or ''
            name_lower = name.lower()
            if 'battery pack' not in name_lower or 'lead' not in name_lower:
                continue
            match = re.search(r'(\d+)\s*V', name, re.IGNORECASE)
            if match:
                cells = int(match.group(1)) // 12
                if cells:
                    line.x_battery_cell_hint = f'12V x {cells}'
