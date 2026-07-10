from markupsafe import Markup
from odoo import api, fields, models

_MODEL_REFS = {
    'elego_11': 'elegomotors_setup.tmpl_elego_11',
    'elego_12': 'elegomotors_setup.tmpl_elego_12',
    'elego_20p': 'elegomotors_setup.tmpl_elego_20p',
}

_COLORS = ['Red', 'White', 'Gray', 'Black']


class ElegoMotorsPurchaseBomWizardLine(models.TransientModel):
    _name = 'elegomotors.purchase.bom.wizard.line'
    _description = 'Purchase BOM Wizard Line'

    wizard_id = fields.Many2one('elegomotors.purchase.bom.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(default=True)
    product_id = fields.Many2one('product.product', readonly=True, required=True)
    product_qty = fields.Float('Qty', digits='Product Unit of Measure')
    product_uom_id = fields.Many2one('uom.uom', readonly=True)


class ElegoMotorsPurchaseBomWizardColorLine(models.TransientModel):
    _name = 'elegomotors.purchase.bom.wizard.color.line'
    _description = 'Purchase BOM Wizard Color Line'

    wizard_id = fields.Many2one('elegomotors.purchase.bom.wizard', required=True, ondelete='cascade')
    color = fields.Selection([
        ('Red', 'Red'),
        ('White', 'White'),
        ('Gray', 'Gray'),
        ('Black', 'Black'),
    ], required=True, readonly=True)
    selected = fields.Boolean(default=False)
    bike_qty = fields.Integer('No. of Bikes', default=1)


class ElegoMotorsPurchaseBomWizard(models.TransientModel):
    _name = 'elegomotors.purchase.bom.wizard'
    _description = 'Load BOM Components into Purchase Order'

    purchase_order_id = fields.Many2one('purchase.order', required=True, readonly=True)
    model_selection = fields.Selection([
        ('elego_11', 'Elego 1.1'),
        ('elego_12', 'Elego 1.2'),
        ('elego_20p', 'Elego 2.0+'),
    ], string='Model', required=True)
    purchase_mode = fields.Selection([
        ('components', 'Components'),
        ('kit', 'Kit'),
    ], default='components', required=True,
       help='Components: itemize every BOM part on the PO, priced individually. '
            'Kit: add a single line per colour for the assembled bike itself, '
            'at a manually entered lump-sum price.')
    kit_price = fields.Float(
        'Kit Price', digits='Product Price',
        help='Per-unit price used for every Kit-mode line added in this run. '
             'Pre-filled from the model\'s Default Kit Price when you pick a '
             'Model, but always editable.',
    )
    color_line_ids = fields.One2many('elegomotors.purchase.bom.wizard.color.line', 'wizard_id')
    line_ids = fields.One2many('elegomotors.purchase.bom.wizard.line', 'wizard_id')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'color_line_ids' in fields_list and not res.get('color_line_ids'):
            res['color_line_ids'] = [
                (0, 0, {'color': color, 'selected': False, 'bike_qty': 1})
                for color in _COLORS
            ]
        return res

    @api.onchange('model_selection')
    def _onchange_model_selection(self):
        if not self.model_selection:
            return
        tmpl_ref = _MODEL_REFS.get(self.model_selection)
        tmpl = self.env.ref(tmpl_ref, raise_if_not_found=False) if tmpl_ref else False
        self.kit_price = tmpl.x_kit_price_default if tmpl else 0.0

    @api.onchange('model_selection', 'color_line_ids.selected', 'color_line_ids.bike_qty')
    def _onchange_populate_lines(self):
        # Component preview is shown for BOTH Components and Kit mode — a kit
        # IS its components, so Kit mode should list them too (informational;
        # the PO line(s) it actually creates are still the lump-sum kit lines).
        existing_selected = {line.product_id.id: line.selected for line in self.line_ids}
        self.line_ids = [(5, 0, 0)]
        if not self.model_selection:
            return
        merged = self._compute_merged_components()
        lines = [(0, 0, {
            # Preserve a component the user manually unchecked, even though a
            # different color/qty edit just rebuilt this whole table — only
            # brand-new components (never seen before) default to selected.
            'selected': existing_selected.get(product_id, True),
            'product_id': product_id,
            'product_qty': data['qty'],
            'product_uom_id': data['uom_id'],
        }) for product_id, data in merged.items()]
        self.line_ids = lines

    def _compute_merged_components(self):
        """Merge BOM component quantities across every selected colour row
        for the current model, using each row's live "No. of Bikes" value.
        Called both by the live preview onchange and again at confirm time
        so the PO always gets quantities matching the current field values,
        not whatever the preview table last rendered.
        """
        merged = {}
        for row in self.color_line_ids.filtered('selected'):
            bom = self._find_bom(row.color)
            if not bom:
                continue
            qty_mult = max(row.bike_qty or 1, 1)
            for bom_line in bom.bom_line_ids:
                entry = merged.setdefault(bom_line.product_id.id, {
                    'qty': 0.0,
                    'uom_id': bom_line.product_uom_id.id,
                })
                entry['qty'] += bom_line.product_qty * qty_mult
        return merged

    def _find_variant(self, color):
        tmpl_ref = _MODEL_REFS.get(self.model_selection)
        if not tmpl_ref:
            return self.env['product.product']
        tmpl = self.env.ref(tmpl_ref, raise_if_not_found=False)
        if not tmpl:
            return self.env['product.product']
        color_attr = self.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        if not color_attr:
            return self.env['product.product']
        color_val = self.env['product.attribute.value'].search([
            ('attribute_id', '=', color_attr.id),
            ('name', '=', color),
        ], limit=1)
        if not color_val:
            return self.env['product.product']
        return tmpl.with_context(active_test=False).product_variant_ids.filtered(
            lambda v, cv=color_val: cv in v.product_template_attribute_value_ids.mapped(
                'product_attribute_value_id'
            )
        )[:1]

    def _find_bom(self, color):
        tmpl_ref = _MODEL_REFS.get(self.model_selection)
        if not tmpl_ref:
            return False
        tmpl = self.env.ref(tmpl_ref, raise_if_not_found=False)
        if not tmpl:
            return False
        variant = self._find_variant(color)
        if not variant:
            return False
        return self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', tmpl.id),
            ('product_id', '=', variant.id),
        ], limit=1)

    def _add_or_merge_po_line(self, po, product, qty, price_unit):
        existing = po.order_line.filtered(lambda l: l.product_id == product)
        if existing:
            existing[0].product_qty += qty
        else:
            self.env['purchase.order.line'].create({
                'order_id': po.id,
                'product_id': product.id,
                'product_qty': qty,
                'product_uom': product.uom_id.id,
                'price_unit': price_unit,
                'date_planned': fields.Datetime.now(),
            })

    def action_load_components(self):
        self.ensure_one()
        po = self.purchase_order_id
        tmpl_ref = _MODEL_REFS.get(self.model_selection)
        tmpl = self.env.ref(tmpl_ref, raise_if_not_found=False) if tmpl_ref else False
        model_name = dict(self._fields['model_selection'].selection).get(self.model_selection, '')
        summary_lines = []

        if self.purchase_mode == 'components':
            # Recompute fresh from the current color rows rather than trusting
            # self.line_ids as-is — guarantees quantities on the PO always match
            # the "No. of Bikes" values actually on screen right now. Still
            # honours any component the user manually unchecked in the preview.
            selected_map = {line.product_id.id: line.selected for line in self.line_ids}
            merged = self._compute_merged_components()
            for product_id, data in merged.items():
                if not selected_map.get(product_id, True):
                    continue
                product = self.env['product.product'].browse(product_id)
                self._add_or_merge_po_line(po, product, data['qty'], 0.0)
            for row in self.color_line_ids.filtered('selected'):
                bom = self._find_bom(row.color)
                if not bom:
                    continue
                summary_lines.append(
                    f"{model_name} ({row.color}) × {row.bike_qty} — "
                    f"{len(bom.bom_line_ids)} components added/updated"
                )
        else:
            symbol = po.currency_id.symbol or ''
            for row in self.color_line_ids.filtered('selected'):
                variant = self._find_variant(row.color)
                if not variant:
                    continue
                self._add_or_merge_po_line(po, variant, row.bike_qty, self.kit_price)
                subtotal = row.bike_qty * self.kit_price
                summary_lines.append(
                    f"{model_name} ({row.color}) × {row.bike_qty} — "
                    f"Kit price {symbol}{self.kit_price:,.2f}/unit, "
                    f"Subtotal {symbol}{subtotal:,.2f}"
                )

        if summary_lines:
            mode_label = 'Components' if self.purchase_mode == 'components' else 'Kit'
            po.message_post(
                body=Markup(
                    f"<b>Load BOM Components</b> — {mode_label}:<br/>"
                    + "<br/>".join(summary_lines)
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        return {'type': 'ir.actions.act_window_close'}
