# -*- coding: utf-8 -*-
"""New Bike Model wizard — lets Manohar (or whoever Manohar grants
mrp.group_mrp_routings to) launch a brand-new bike model + its colour-variant
Bills of Materials directly from the UI: no developer, no XML data file, no
module upgrade. Two things make this possible together with the rest of this
change:

  1. product.template.x_is_ego_bike / x_serial_prefix (product_template.py) —
     every "which templates are Elego bikes" check in this module now reads
     these instead of a hardcoded template list, so a model created here
     shows up everywhere a bike model is expected to, immediately.
  2. This wizard's bulk CSV import for the BOM step — hand-adding a few
     hundred component lines per colour through Odoo's raw Bill of Materials
     screen isn't practical for a non-technical user, so this reads a CSV
     (Component Name, Quantity, Colour) instead. Colour blank = common to
     every colour's BOM; a specific colour name = only that colour's BOM
     gets the line — matches the shape every existing model's BOMs already
     have (see product_template.py's _elego_11_bom_color_components and
     siblings), just entered far more efficiently.

Reuses product.template._get_or_rename_bom_component() so a component name
that already exists as a product maps to that same record instead of
creating a duplicate part.
"""
import base64
import csv
import io

from odoo import api, fields, models
from odoo.exceptions import UserError


class NewBikeModelWizard(models.TransientModel):
    _name = 'elegomotors.new.bike.model.wizard'
    _description = 'New Bike Model'

    name = fields.Char(string='Model Name', required=True, help='e.g. "Elego 4.0"')
    colour_names = fields.Char(
        string='Colours', required=True,
        help='Comma-separated, e.g. "Red, Black, White, Gray". Each becomes '
             'a variant of the new model, with its own Bill of Materials.',
    )
    x_serial_prefix = fields.Char(
        string='Serial Number Prefix', required=True,
        help='e.g. EL40. Used to build every unit\'s serial number '
             '(<prefix>-<YYMM>-<counter>) and as its Global Production Scan '
             'barcode code. Must be unique — not already used by another model.',
    )
    list_price = fields.Float(string='Sale Price', digits='Product Price')
    standard_price = fields.Float(string='Cost', digits='Product Price')
    x_material_code = fields.Char(
        string='Finance API Material Code',
        help='Optional — can also be set later directly on the product form.',
    )
    bom_file = fields.Binary(
        string='BOM CSV File', required=True,
        help='CSV with columns: Component Name, Quantity, Colour. Leave '
             'Colour blank for a component common to every colour; name a '
             'specific colour (matching one of the Colours above exactly) '
             'for a component only that colour\'s BOM should include. '
             'Save an Excel sheet as CSV before uploading if needed.',
    )
    bom_filename = fields.Char(string='File Name')

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _parse_colours(self):
        self.ensure_one()
        colours = [c.strip() for c in (self.colour_names or '').split(',')]
        colours = [c for c in colours if c]
        if not colours:
            raise UserError('Enter at least one colour.')
        return colours

    def _parse_bom_rows(self, colours):
        """Return (common_rows, rows_by_colour) — each a list of
        (component_name, qty) tuples — or raise UserError with every
        row-level problem found, instead of failing on the first one."""
        self.ensure_one()
        try:
            decoded = base64.b64decode(self.bom_file).decode('utf-8-sig')
        except Exception as e:
            raise UserError(f'Could not read the BOM file as CSV/UTF-8 text: {e}')

        reader = csv.DictReader(io.StringIO(decoded))
        expected = {'component name', 'quantity', 'colour'}
        headers = {(h or '').strip().lower() for h in (reader.fieldnames or [])}
        if not expected.issubset(headers):
            raise UserError(
                f'The BOM file must have columns: Component Name, Quantity, '
                f'Colour. Found: {", ".join(reader.fieldnames or []) or "(none)"}.'
            )

        common_rows = []
        rows_by_colour = {c: [] for c in colours}
        errors = []
        for i, row in enumerate(reader, start=2):  # header is row 1
            norm = {(k or '').strip().lower(): (v or '').strip() for k, v in row.items()}
            comp_name = norm.get('component name', '')
            qty_raw = norm.get('quantity', '')
            colour = norm.get('colour', '')
            if not comp_name and not qty_raw and not colour:
                continue  # blank row, skip silently
            if not comp_name:
                errors.append(f'Row {i}: missing Component Name.')
                continue
            try:
                qty = float(qty_raw)
                if qty <= 0:
                    raise ValueError()
            except ValueError:
                errors.append(f'Row {i} ({comp_name}): Quantity "{qty_raw}" is not a positive number.')
                continue
            if colour and colour not in rows_by_colour:
                errors.append(
                    f'Row {i} ({comp_name}): Colour "{colour}" doesn\'t match any '
                    f'of the Colours entered above ({", ".join(colours)}).'
                )
                continue
            if colour:
                rows_by_colour[colour].append((comp_name, qty))
            else:
                common_rows.append((comp_name, qty))

        if errors:
            raise UserError('Fix these rows in the BOM file and try again:\n\n' + '\n'.join(errors))
        if not common_rows and not any(rows_by_colour.values()):
            raise UserError('The BOM file has no usable component rows.')
        return common_rows, rows_by_colour

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------

    def action_create(self):
        self.ensure_one()
        Template = self.env['product.template']

        if Template.search_count([('name', '=', self.name)]):
            raise UserError(f'A product named "{self.name}" already exists.')
        if Template.search_count([('x_serial_prefix', '=', self.x_serial_prefix)]):
            raise UserError(
                f'Serial Number Prefix "{self.x_serial_prefix}" is already used '
                f'by another model — pick a different one.'
            )

        colours = self._parse_colours()
        common_rows, rows_by_colour = self._parse_bom_rows(colours)

        tmpl = Template.create({
            'name': self.name,
            'is_storable': True,
            'sale_ok': True,
            'purchase_ok': False,
            'categ_id': self.env.ref('product.product_category_all').id,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
            'uom_po_id': self.env.ref('uom.product_uom_unit').id,
            'list_price': self.list_price,
            'standard_price': self.standard_price,
            'route_ids': [(4, self.env.ref('mrp.route_warehouse0_manufacture').id)],
            'x_is_ego_bike': True,
            'x_serial_prefix': self.x_serial_prefix,
            'x_material_code': self.x_material_code or False,
        })

        self._setup_colour_variants(tmpl, colours)
        bom_count = self._create_colour_boms(tmpl, colours, common_rows, rows_by_colour)

        tmpl.message_post(
            body=f'Created via New Bike Model wizard: {len(colours)} colour '
                 f'variant(s), {bom_count} Bill(s) of Materials.',
        )
        return {
            'type': 'ir.actions.act_window',
            'name': tmpl.name,
            'res_model': 'product.template',
            'res_id': tmpl.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _setup_colour_variants(self, tmpl, colours):
        """Set up the Color attribute line so one variant per colour name
        exists — reuses the same 'attr_ego_color' attribute every existing
        model uses, generalized from product_template.py's
        _ensure_new_model_attributes (which only ever ran for a hardcoded
        template list) to work for any template."""
        color_attr = self.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        if not color_attr:
            raise UserError('The "Color" product attribute (attr_ego_color) is missing.')
        AttrValue = self.env['product.attribute.value']
        value_ids = []
        for name in colours:
            val = AttrValue.search([('attribute_id', '=', color_attr.id), ('name', '=', name)], limit=1)
            if not val:
                val = AttrValue.create({'attribute_id': color_attr.id, 'name': name})
            value_ids.append(val.id)
        self.env['product.template.attribute.line'].create({
            'product_tmpl_id': tmpl.id,
            'attribute_id': color_attr.id,
            'value_ids': [(6, 0, value_ids)],
        })

    def _create_colour_boms(self, tmpl, colours, common_rows, rows_by_colour):
        """One mrp.bom per colour variant (matching the existing per-colour
        record structure every current model already uses — confirmed not a
        single attribute-scoped BOM), each with the common rows plus that
        colour's own specific rows. Component names are resolved via the
        existing _get_or_rename_bom_component() helper so a re-used part
        name maps to the same product instead of creating a duplicate."""
        Bom = self.env['mrp.bom']
        Template = self.env['product.template']
        created = 0
        for colour in colours:
            variant = tmpl.product_variant_ids.filtered(
                lambda v, c=colour: c in v.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id.name'
                )
            )[:1]
            if not variant:
                continue
            lines = []
            for comp_name, qty in common_rows + rows_by_colour.get(colour, []):
                component = Template._get_or_rename_bom_component(comp_name)
                if not component:
                    continue
                lines.append((0, 0, {
                    'product_id': component.id,
                    'product_qty': qty,
                    'product_uom_id': component.uom_id.id,
                }))
            if not lines:
                continue
            Bom.create({
                'product_tmpl_id': tmpl.id,
                'product_id': variant.id,
                'product_qty': 1,
                'type': 'normal',
                'bom_line_ids': lines,
            })
            created += 1
        return created
