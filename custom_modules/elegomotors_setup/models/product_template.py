# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_qc_required = fields.Boolean(
        string='Requires QC Inward',
        default=False,
        help='If enabled, units of this product must pass QC Inward inspection '
             'before entering Store. Leave unchecked for direct-to-store items.',
    )
    x_qc_parameter_ids = fields.One2many(
        'elegomotors.qc.parameter', 'product_tmpl_id',
        string='QC Parameters',
        help='Define the inspection checklist for this product. '
             'Each row becomes a line Pratik must fill during QC inward inspection.',
    )

    @api.model
    def _ensure_ego_s1_variant_attributes(self):
        """Idempotent setup of EGO-S1 variant attributes — safe on every upgrade.

        Ensures the EGO-S1 product template has:
          - Color attribute line with values: Red, Black, Grey, White
          - Side Guards attribute line with values: Black Coating, Zinc Coating

        Finds existing attribute lines and adds missing values rather than
        re-creating, so existing variants (and MOs referencing them) are preserved.
        """
        ego_tmpl = self.env.ref(
            'elegomotors_setup.tmpl_ego_scooter', raise_if_not_found=False
        )
        if not ego_tmpl:
            return

        AttrValue = self.env['product.attribute.value']
        AttrLine = self.env['product.template.attribute.line']

        def _ensure_line(attribute, value_names):
            """Ensure attribute line exists on template with all required values."""
            value_ids = []
            for name in value_names:
                val = AttrValue.search(
                    [('attribute_id', '=', attribute.id), ('name', '=', name)], limit=1
                )
                if not val:
                    val = AttrValue.create({'attribute_id': attribute.id, 'name': name})
                value_ids.append(val.id)

            line = ego_tmpl.attribute_line_ids.filtered(
                lambda l: l.attribute_id == attribute
            )
            if line:
                missing = set(value_ids) - set(line.value_ids.ids)
                if missing:
                    line.write({'value_ids': [(4, vid) for vid in missing]})
            else:
                AttrLine.create({
                    'product_tmpl_id': ego_tmpl.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(4, vid) for vid in value_ids],
                })

        # Color: Red, Black, Grey, White
        color_attr = self.env.ref(
            'elegomotors_setup.attr_ego_color', raise_if_not_found=False
        )
        if color_attr:
            _ensure_line(color_attr, ['Red', 'Black', 'Grey', 'White'])

        # Side Guards: Black Coating, Zinc Coating
        side_guards_attr = self.env.ref(
            'elegomotors_setup.attr_side_guards', raise_if_not_found=False
        )
        if side_guards_attr:
            _ensure_line(side_guards_attr, ['Black Coating', 'Zinc Coating'])

    @api.model_create_multi
    def create(self, vals_list):
        # group_store_billing holders (Amit) can view products but not create
        # new ones. Superuser and sudo() environments are exempt so Odoo's
        # own test suite can still create products freely.
        if (
            not self.env.su
            and self.env.user.has_group('elegomotors_setup.group_store_billing')
        ):
            raise AccessError(
                'Store billing users cannot create new Products. '
                'Ask Manohar (Admin) to create the product.'
            )
        return super().create(vals_list)
