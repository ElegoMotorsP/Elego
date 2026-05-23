# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class BatchMoWizard(models.TransientModel):
    """Batch MO Creation Wizard — creates one mrp.production per selected variant row.

    Flow:
      1. User selects a Product Template (e.g. EGO-S1).
      2. Wizard auto-loads one line per Color value defined on the template.
      3. User configures Battery Type / Side Guards per line, sets quantities,
         and unchecks any variants they don't need.
      4. Confirm → one MO per included line, all stamped with a shared x_batch_mo_ref.
    """

    _name = 'elegomotors.batch.mo.wizard'
    _description = 'Batch MO Creation Wizard'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        required=True,
        domain=[('sale_ok', '=', True), ('type', 'in', ('consu', 'product'))],
    )
    line_ids = fields.One2many(
        'elegomotors.batch.mo.wizard.line',
        'wizard_id',
        string='Variants to Produce',
    )

    # Color values available on the selected template (drives variant selection)
    valid_color_value_ids = fields.Many2many(
        'product.attribute.value',
        compute='_compute_valid_attribute_values',
        string='Valid Colors',
    )

    @api.depends('product_tmpl_id', 'product_tmpl_id.attribute_line_ids')
    def _compute_valid_attribute_values(self):
        Pav = self.env['product.attribute.value']
        for wizard in self:
            color_ids = Pav
            if wizard.product_tmpl_id:
                for attr_line in wizard.product_tmpl_id.attribute_line_ids:
                    if attr_line.attribute_id.name == 'Color':
                        color_ids = attr_line.value_ids
            wizard.valid_color_value_ids = color_ids

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        self.line_ids = [(5,)]
        if not self.product_tmpl_id:
            return
        # Start with one blank row — user picks Color + Battery Type + Side Guards per row
        # and uses "Add a line" to add more combinations
        self.line_ids = [(0, 0, {'qty': 1, 'create_mo': True})]

    def action_confirm(self):
        self.ensure_one()
        active_lines = self.line_ids.filtered(lambda l: l.create_mo and l.qty > 0)
        if not active_lines:
            raise UserError(
                'Please include at least one variant row with a quantity greater than 0.'
            )

        from datetime import datetime
        batch_ref = 'BATCH-' + datetime.now().strftime('%Y%m%d-%H%M%S')

        created_mos = self.env['mrp.production']
        for line in active_lines:
            product = line._resolve_product_variant()
            if not product:
                label = line.variant_display or (line.color_value_id.name if line.color_value_id else '(base)')
                raise UserError(
                    f'Could not find a matching product variant for: {label}\n'
                    f'Please verify that the product attributes are fully configured in Odoo.'
                )

            # Prefer variant-specific BOM; fall back to template BOM.
            # OR-with-limit-1 returns whichever has the lower DB ID (usually the
            # older template BOM), so use two explicit searches instead.
            bom = self.env['mrp.bom'].search([
                ('type', '=', 'normal'),
                ('product_tmpl_id', '=', self.product_tmpl_id.id),
                ('product_id', '=', product.id),
            ], limit=1) or self.env['mrp.bom'].search([
                ('type', '=', 'normal'),
                ('product_tmpl_id', '=', self.product_tmpl_id.id),
                ('product_id', '=', False),
            ], limit=1)

            color_name = line.color_value_id.name.lower() if line.color_value_id else ''
            mo = self.env['mrp.production'].create({
                'product_id': product.id,
                'product_qty': line.qty,
                'product_uom_id': product.uom_id.id,
                'bom_id': bom.id if bom else False,
                'x_batch_mo_ref': batch_ref,
                'x_color': color_name,
                'x_battery_type': line.battery_type or '',
            })
            created_mos |= mo

        return {
            'type': 'ir.actions.act_window',
            'name': f'Manufacturing Orders — {batch_ref}',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('x_batch_mo_ref', '=', batch_ref)],
            'context': {'search_default_x_batch_mo_ref': batch_ref},
        }


class BatchMoWizardLine(models.TransientModel):
    _name = 'elegomotors.batch.mo.wizard.line'
    _description = 'Batch MO Wizard Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'elegomotors.batch.mo.wizard', required=True, ondelete='cascade'
    )
    sequence = fields.Integer(default=10)
    create_mo = fields.Boolean(string='Include', default=True)

    color_value_id = fields.Many2one(
        'product.attribute.value',
        string='Color',
        domain="[('attribute_id.name', '=', 'Color')]",
    )
    battery_type = fields.Selection([
        ('Lithium 60V30Ah',   'Lithium 60V30Ah'),
        ('Lithium 60V39Ah',   'Lithium 60V39Ah'),
        ('Lead Acid 60V32Ah', 'Lead Acid 60V32Ah'),
        ('Lead Acid 72V32Ah', 'Lead Acid 72V32Ah'),
        ('Without Battery',   'Without Battery'),
    ], string='Battery Type')
    qty = fields.Float(string='Quantity', default=1.0)

    variant_display = fields.Char(
        string='Variant Summary',
        compute='_compute_variant_display',
    )

    @api.depends('color_value_id', 'battery_type')
    def _compute_variant_display(self):
        for line in self:
            parts = []
            if line.color_value_id:
                parts.append(line.color_value_id.name)
            if line.battery_type:
                parts.append(line.battery_type)
            line.variant_display = ' | '.join(parts) if parts else '(base product)'

    def _resolve_product_variant(self):
        """Match Color attribute to the correct product.product variant.
        Battery Type is a free-text label stored as x_battery_type on the MO — not a variant.
        """
        tmpl = self.wizard_id.product_tmpl_id
        if not tmpl:
            return False

        color_val_id = self.color_value_id.id if self.color_value_id else None

        for variant in tmpl.product_variant_ids:
            variant_color_ids = set(
                variant.product_template_attribute_value_ids.filtered(
                    lambda ptav: ptav.attribute_id.name == 'Color'
                ).mapped('product_attribute_value_id.id')
            )
            if color_val_id and variant_color_ids == {color_val_id}:
                return variant
            if not color_val_id and not variant_color_ids:
                return variant

        # Single variant template with no Color attribute — use it directly
        if not color_val_id and len(tmpl.product_variant_ids) == 1:
            return tmpl.product_variant_ids[0]

        return False
