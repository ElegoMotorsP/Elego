from odoo import api, fields, models

_MODEL_REFS = {
    'elego_11': 'elegomotors_setup.tmpl_elego_11',
    'elego_12': 'elegomotors_setup.tmpl_elego_12',
    'elego_20p': 'elegomotors_setup.tmpl_elego_20p',
}


class ElegoMotorsPurchaseBomWizardLine(models.TransientModel):
    _name = 'elegomotors.purchase.bom.wizard.line'
    _description = 'Purchase BOM Wizard Line'

    wizard_id = fields.Many2one('elegomotors.purchase.bom.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(default=True)
    product_id = fields.Many2one('product.product', readonly=True, required=True)
    product_qty = fields.Float('Qty', digits='Product Unit of Measure')
    product_uom_id = fields.Many2one('uom.uom', readonly=True)


class ElegoMotorsPurchaseBomWizard(models.TransientModel):
    _name = 'elegomotors.purchase.bom.wizard'
    _description = 'Load BOM Components into Purchase Order'

    purchase_order_id = fields.Many2one('purchase.order', required=True, readonly=True)
    model_selection = fields.Selection([
        ('elego_11', 'Elego 1.1'),
        ('elego_12', 'Elego 1.2'),
        ('elego_20p', 'Elego 2.0+'),
    ], string='Model', required=True)
    color_selection = fields.Selection([
        ('Red', 'Red'),
        ('White', 'White'),
        ('Gray', 'Gray'),
        ('Black', 'Black'),
    ], string='Color', required=True)
    bike_qty = fields.Integer('Number of Bikes', default=1)
    line_ids = fields.One2many('elegomotors.purchase.bom.wizard.line', 'wizard_id')

    @api.onchange('model_selection', 'color_selection', 'bike_qty')
    def _onchange_populate_lines(self):
        self.line_ids = [(5, 0, 0)]
        if not self.model_selection or not self.color_selection:
            return
        bom = self._find_bom()
        if not bom:
            return
        qty_mult = max(self.bike_qty or 1, 1)
        lines = []
        for bom_line in bom.bom_line_ids:
            lines.append((0, 0, {
                'selected': True,
                'product_id': bom_line.product_id.id,
                'product_qty': bom_line.product_qty * qty_mult,
                'product_uom_id': bom_line.product_uom_id.id,
            }))
        self.line_ids = lines

    def _find_bom(self):
        tmpl_ref = _MODEL_REFS.get(self.model_selection)
        if not tmpl_ref:
            return False
        tmpl = self.env.ref(tmpl_ref, raise_if_not_found=False)
        if not tmpl:
            return False
        color_attr = self.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        if not color_attr:
            return False
        color_val = self.env['product.attribute.value'].search([
            ('attribute_id', '=', color_attr.id),
            ('name', '=', self.color_selection),
        ], limit=1)
        if not color_val:
            return False
        variant = tmpl.with_context(active_test=False).product_variant_ids.filtered(
            lambda v, cv=color_val: cv in v.product_template_attribute_value_ids.mapped(
                'product_attribute_value_id'
            )
        )[:1]
        if not variant:
            return False
        return self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', tmpl.id),
            ('product_id', '=', variant.id),
        ], limit=1)

    def action_load_components(self):
        po = self.purchase_order_id
        for line in self.line_ids.filtered('selected'):
            existing = po.order_line.filtered(lambda l: l.product_id == line.product_id)
            if existing:
                existing[0].product_qty += line.product_qty
            else:
                self.env['purchase.order.line'].create({
                    'order_id': po.id,
                    'product_id': line.product_id.id,
                    'product_qty': line.product_qty,
                    'product_uom': line.product_uom_id.id,
                    'price_unit': 0.0,
                    'date_planned': fields.Datetime.now(),
                })
        return {'type': 'ir.actions.act_window_close'}
