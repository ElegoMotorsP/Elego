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
        domain=[('type', 'in', ('consu', 'product'))],
    )
    line_ids = fields.One2many(
        'elegomotors.batch.mo.wizard.line',
        'wizard_id',
        string='Variants to Produce',
    )

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        self.line_ids = [(5,)]
        if not self.product_tmpl_id:
            return

        color_attr = self.env.ref(
            'elegomotors_setup.attr_ego_color', raise_if_not_found=False
        )
        color_line = self.product_tmpl_id.attribute_line_ids.filtered(
            lambda al: al.attribute_id == color_attr
        ) if color_attr else False

        if color_line:
            self.line_ids = [
                (0, 0, {'color_value_id': val.id, 'qty': 1, 'create_mo': True})
                for val in color_line.value_ids
            ]
        else:
            # No Color attribute on template — create a single line for the base product
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
                label = line.variant_display or line.color_value_id.name or '(base)'
                raise UserError(
                    f'Could not find a matching product variant for: {label}\n'
                    f'Please verify that the product attributes are fully configured in Odoo.'
                )

            bom = self.env['mrp.bom'].search([
                ('type', '=', 'normal'),
                ('product_tmpl_id', '=', self.product_tmpl_id.id),
                '|',
                ('product_id', '=', product.id),
                ('product_id', '=', False),
            ], limit=1)

            mo = self.env['mrp.production'].create({
                'product_id': product.id,
                'product_qty': line.qty,
                'product_uom_id': product.uom_id.id,
                'bom_id': bom.id if bom else False,
                'x_batch_mo_ref': batch_ref,
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
    battery_value_id = fields.Many2one(
        'product.attribute.value',
        string='Battery Type',
        domain="[('attribute_id.name', '=', 'Battery Type')]",
    )
    side_guards_value_id = fields.Many2one(
        'product.attribute.value',
        string='Side Guards',
        domain="[('attribute_id.name', '=', 'Side Guards')]",
    )
    qty = fields.Float(string='Quantity', default=1.0)

    variant_display = fields.Char(
        string='Variant Summary',
        compute='_compute_variant_display',
    )

    @api.depends('color_value_id', 'battery_value_id', 'side_guards_value_id')
    def _compute_variant_display(self):
        for line in self:
            parts = []
            if line.color_value_id:
                parts.append(line.color_value_id.name)
            if line.battery_value_id:
                parts.append(line.battery_value_id.name)
            if line.side_guards_value_id:
                parts.append(f'Side Guards: {line.side_guards_value_id.name}')
            line.variant_display = ' | '.join(parts) if parts else '(base product)'

    def _resolve_product_variant(self):
        """Match selected attribute values to an existing product.product variant."""
        tmpl = self.wizard_id.product_tmpl_id
        if not tmpl:
            return False

        selected_val_ids = set()
        for fld in ('color_value_id', 'battery_value_id', 'side_guards_value_id'):
            val = getattr(self, fld)
            if val:
                selected_val_ids.add(val.id)

        for variant in tmpl.product_variant_ids:
            variant_val_ids = set(
                variant.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id.id'
                )
            )
            if selected_val_ids == variant_val_ids:
                return variant

        # No attributes selected and template has a single variant → use it
        if not selected_val_ids and len(tmpl.product_variant_ids) == 1:
            return tmpl.product_variant_ids[0]

        return False
