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
  2. This wizard's bulk BOM import — hand-adding a few hundred component
     lines per colour through Odoo's raw Bill of Materials screen isn't
     practical for a non-technical user, so it reads an Excel (.xlsx) or CSV
     sheet with the columns Component Name, Quantity, Colour. Colour blank =
     common to every colour's BOM; a specific colour name = only that colour's
     BOM gets the line — matches the shape every existing model's BOMs
     already have (see product_template.py's _elego_11_bom_color_components
     and siblings), just entered far more efficiently. A ready-made template
     (with a drop-down of every existing component) is served by
     controllers/bom_template.py.

Two steps, so a wrong or duplicate part is never created silently:

  Step 1  "Check Components" — every distinct component name in the sheet is
          compared with the products already in Odoo:
            * same name (ignoring case / extra spaces) -> matched automatically
            * very similar name(s)                     -> the creator must pick
              the existing part, or tick "Create as new part"
            * nothing similar                          -> will be created
  Step 2  "Create" — builds the model / colour variants and one Bill of
          Materials per colour from the creator's choices.
"""
import base64
from collections import OrderedDict, defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError

from .bom_sheet_utils import (
    SheetError, clean_name, find_candidates, name_key, parse_bom_table, read_table,
)

_DIALOG = {'dialog_size': 'extra-large'}


class NewBikeModelWizard(models.TransientModel):
    _name = 'elegomotors.new.bike.model.wizard'
    _description = 'New Bike Model'

    state = fields.Selection([
        ('setup', 'Setup'),
        ('review', 'Review Components'),
    ], default='setup', required=True)
    mode = fields.Selection([
        ('new_model', 'Create New Bike Model'),
        ('add_variant', 'Add Colour Variant to Existing Model'),
    ], default='new_model', required=True)
    product_tmpl_id = fields.Many2one(
        'product.template', string='Existing Bike Model',
        domain=[('x_is_ego_bike', '=', True)],
        help='Add a new colour variant (with its own Bill of Materials) to '
             'this model without touching its existing colours.',
    )
    name = fields.Char(string='Model Name', help='e.g. "Elego 4.0"')
    colour_names = fields.Char(
        string='Colours',
        help='Comma-separated, e.g. "Red, Black, White, Gray". Each becomes '
             'a variant of the model, with its own Bill of Materials. Leave '
             'empty for a model that has no colour options (one variant).',
    )
    x_serial_prefix = fields.Char(
        string='Serial Number Prefix',
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
        string='BOM File (Excel or CSV)',
        help='Excel (.xlsx) or CSV with columns: Component Name, Quantity, '
             'Colour. Leave Colour blank for a component common to every '
             'colour; name a specific colour (one of the Colours above) for a '
             'component only that colour\'s BOM should include. Download the '
             'BOM template to fill it in.',
    )
    bom_filename = fields.Char(string='File Name')

    line_ids = fields.One2many(
        'elegomotors.new.bike.model.wizard.line', 'wizard_id', string='Components')
    # Same records as line_ids, split for the two lists on the review screen.
    decision_line_ids = fields.One2many(
        'elegomotors.new.bike.model.wizard.line', 'wizard_id',
        string='Needs your decision', domain=[('match_type', '!=', 'exact')])
    auto_line_ids = fields.One2many(
        'elegomotors.new.bike.model.wizard.line', 'wizard_id',
        string='Matched automatically', domain=[('match_type', '=', 'exact')])
    review_summary = fields.Text(readonly=True)
    undecided_count = fields.Integer(compute='_compute_undecided_count')
    new_part_categ_id = fields.Many2one(
        'product.category', string='Category for NEW parts',
        default=lambda self: self._default_new_part_categ(),
        help='The product category given to the parts this wizard creates. Parts that '
             'are imported / used in a CKD kit should be in an Average-cost category '
             '(e.g. Imported CKD Components): then the PO price becomes the part\'s value '
             'and import duty can be added to it. A category with Standard costing values '
             'every receipt at the part\'s fixed standard cost instead.')

    @api.depends('decision_line_ids.product_tmpl_id', 'decision_line_ids.create_new')
    def _compute_undecided_count(self):
        # Same-name (exact) lines are decided from the start, so only the
        # lists shown on the review screen can be undecided.
        for wiz in self:
            wiz.undecided_count = len(wiz.decision_line_ids.filtered(
                lambda l: not l.product_tmpl_id and not l.create_new))

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _color_attr(self):
        attr = self.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        if not attr:
            raise UserError('The "Color" product attribute (attr_ego_color) is missing.')
        return attr

    def _parse_colours(self, required=True):
        """Colour names typed in the wizard, spelled the way an existing
        Color value is spelled if one matches ignoring case ("red" -> "Red"),
        so a typo in capitalisation never creates a second "red" value."""
        self.ensure_one()
        raw = [clean_name(c) for c in (self.colour_names or '').split(',')]
        raw = [c for c in raw if c]
        if not raw and required:
            raise UserError('Enter at least one colour.')
        seen, colours = set(), []
        existing = {}
        if raw:
            for val in self._color_attr().sudo().value_ids:
                existing.setdefault(val.name.strip().casefold(), val.name)
        for c in raw:
            if c.casefold() in seen:
                raise UserError(f'Colour "{c}" is listed twice.')
            seen.add(c.casefold())
            colours.append(existing.get(c.casefold(), c))
        return colours

    def _validate_setup(self):
        """Everything that can be checked before reading the BOM file.
        Returns the list of colours (empty = a model with no colour options)."""
        self.ensure_one()
        Template = self.env['product.template']
        if not self.bom_file:
            raise UserError('Upload the BOM file (Excel or CSV).')

        if self.mode == 'add_variant':
            tmpl = self.product_tmpl_id
            if not tmpl:
                raise UserError('Select the existing bike model to add a colour variant to.')
            if not tmpl.x_is_ego_bike:
                raise UserError(f'"{tmpl.name}" is not marked as an Elego Bike Model.')
            colours = self._parse_colours(required=True)
            color_attr = self._color_attr()
            attr_line = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == color_attr)
            existing_names = {v.name.strip().casefold() for v in attr_line.value_ids} if attr_line else set()
            duplicates = [c for c in colours if c.casefold() in existing_names]
            if duplicates:
                raise UserError(
                    f'"{tmpl.name}" already has a variant for: {", ".join(duplicates)}. '
                    f'Pick a different colour name, or check spelling against the existing variant.'
                )
            return colours

        if not self.name:
            raise UserError('Enter a model name.')
        if not self.x_serial_prefix:
            raise UserError('Enter a Serial Number Prefix.')
        if Template.search_count([('name', '=', self.name)]):
            raise UserError(f'A product named "{self.name}" already exists.')
        if Template.search_count([('x_serial_prefix', '=', self.x_serial_prefix)]):
            raise UserError(
                f'Serial Number Prefix "{self.x_serial_prefix}" is already used '
                f'by another model — pick a different one.'
            )
        return self._parse_colours(required=False)

    def _parse_bom_rows(self, colours):
        """Return (common_rows, rows_by_colour) — each a list of
        (component_name, qty) tuples — or raise UserError with every
        row-level problem found, instead of failing on the first one."""
        self.ensure_one()
        try:
            table = read_table(base64.b64decode(self.bom_file), self.bom_filename or '')
            rows, errors = parse_bom_table(table)
        except SheetError as e:
            raise UserError(str(e))

        canonical = {c.casefold(): c for c in colours}
        common_rows = []
        rows_by_colour = {c: [] for c in colours}
        for r in rows:
            colour = r['colour']
            if not colour:
                common_rows.append((r['name'], r['qty']))
            elif colour.casefold() in canonical:
                rows_by_colour[canonical[colour.casefold()]].append((r['name'], r['qty']))
            elif colours:
                errors.append(
                    f'Row {r["row"]} ({r["name"]}): Colour "{colour}" doesn\'t match any '
                    f'of the Colours entered above ({", ".join(colours)}).'
                )
            else:
                errors.append(
                    f'Row {r["row"]} ({r["name"]}): Colour "{colour}" given, but no '
                    f'Colours were entered above. Enter the colours, or leave the '
                    f'Colour column blank.'
                )
        if errors:
            raise UserError('Fix these rows in the BOM file and try again:\n\n' + '\n'.join(errors))
        if not common_rows and not any(rows_by_colour.values()):
            raise UserError('The BOM file has no usable component rows.')
        return common_rows, rows_by_colour

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Bike Model',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(_DIALOG),
        }

    # ------------------------------------------------------------------
    # Step 1 — check components
    # ------------------------------------------------------------------

    def action_check(self):
        """Compare every sheet component with the parts already in Odoo and
        open the review screen."""
        self.ensure_one()
        self = self.sudo()
        colours = self._validate_setup()
        common_rows, rows_by_colour = self._parse_bom_rows(colours)

        # key -> {'name', 'colours' (set, '' = common), 'qtys' (set)}
        components = OrderedDict()
        for colour, rows in [('', common_rows)] + list(rows_by_colour.items()):
            for name, qty in rows:
                comp = components.setdefault(
                    name_key(name), {'name': name, 'colours': set(), 'qtys': set()})
                comp['colours'].add(colour)
                comp['qtys'].add(qty)

        self.line_ids.unlink()
        Line = self.env['elegomotors.new.bike.model.wizard.line']
        lines = Line.create(self._review_line_vals(components, colours))
        counts = defaultdict(int)
        for line in lines:
            counts[line.match_type] += 1
        self.write({
            'state': 'review',
            'review_summary': (
                f'{len(components)} different components in the sheet: '
                f'{counts["exact"]} matched automatically (same name), '
                f'{counts["similar"]} with a similar name in Odoo (you choose), '
                f'{counts["new"]} not found (will be created as new parts).'
            ),
        })
        return self._reopen()

    def _review_line_vals(self, components, colours):
        # Archived parts are included: a sheet name that matches one is
        # reactivated on use, as the old exact-name import always did.
        Template = self.env['product.template'].with_context(active_test=False)
        recs = Template.search_read([('x_is_ego_bike', '=', False)], ['name', 'active'])
        by_key = defaultdict(list)
        pool = []
        for r in recs:
            key = name_key(r['name'])
            label = r['name'] + ('' if r['active'] else ' (archived)')
            by_key[key].append((r['id'], label))
            pool.append((r['id'], key, label))

        rank = {'similar': 0, 'new': 1, 'exact': 2}
        vals_list = []
        for key, comp in components.items():
            exact = by_key.get(key, [])
            product_id, create_new, suggestions = False, False, []
            if len(exact) == 1:
                match_type, product_id = 'exact', exact[0][0]
            elif len(exact) > 1:
                # Same name twice in Odoo — never pick one silently.
                match_type = 'similar'
                suggestions = [(i, label, 1.0) for i, label in exact[:3]]
            else:
                suggestions = find_candidates(key, pool)
                match_type = 'similar' if suggestions else 'new'
                create_new = not suggestions
            if '' in comp['colours'] or not colours:
                used_in = 'All colours'
            else:
                used_in = ', '.join(sorted(comp['colours']))
            qtys = sorted(comp['qtys'])
            vals_list.append({
                'wizard_id': self.id,
                'sheet_name': comp['name'],
                'name_key': key,
                'used_in': used_in,
                'qty_text': ' / '.join(f'{q:g}' for q in qtys),
                'match_type': match_type,
                'match_rank': rank[match_type],
                'suggestions': ' | '.join(
                    f'{label} ({round(score * 100)}%)' for _i, label, score in suggestions),
                'suggestion_ids': [(6, 0, [i for i, _l, _s in suggestions])],
                'top_tmpl_id': suggestions[0][0] if suggestions else False,
                'product_tmpl_id': product_id,
                'create_new': create_new,
            })
        return vals_list

    def action_back(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.write({'state': 'setup', 'review_summary': False})
        return self._reopen()

    # ------------------------------------------------------------------
    # Step 2 — create
    # ------------------------------------------------------------------

    def action_create(self):
        self.ensure_one()
        # Reaching this point already required mrp.group_mrp_routings (the
        # wizard's own menu/ir.model.access gate) — elevate for the actual
        # product/attribute/BOM writes below, which native Odoo restricts to
        # Manufacturing/Administrator, so a routings-only user (e.g. Manohar)
        # can still use this self-service flow without being made a full
        # Manufacturing Administrator.
        self = self.sudo()
        if self.state != 'review':
            raise UserError('Press "Check Components" first.')
        colours = self._validate_setup()
        common_rows, rows_by_colour = self._parse_bom_rows(colours)
        components, created = self._resolve_components(common_rows, rows_by_colour)
        if self.mode == 'add_variant':
            return self._action_add_variant(colours, common_rows, rows_by_colour, components, created)
        return self._action_create_new_model(colours, common_rows, rows_by_colour, components, created)

    def _resolve_components(self, common_rows, rows_by_colour):
        """({name_key: product.product}, [names of parts created]) from the
        creator's review choices. Existing parts are reused; parts marked
        "Create as new part" are created here — exactly once each."""
        self.ensure_one()
        keys = OrderedDict()
        for name, _qty in common_rows + [r for rows in rows_by_colour.values() for r in rows]:
            keys.setdefault(name_key(name), name)

        lines = {l.name_key: l for l in self.line_ids}
        if any(k not in lines for k in keys):
            raise UserError(
                'The BOM file is different from the one that was checked. '
                'Press Back and run "Check Components" again.')
        undecided = [lines[k].sheet_name for k in keys
                     if not lines[k].product_tmpl_id and not lines[k].create_new]
        if undecided:
            raise UserError(
                'Choose an existing part, or tick "Create as new part", for:\n\n'
                + '\n'.join(undecided))
        conflicting = [lines[k].sheet_name for k in keys
                       if lines[k].product_tmpl_id and lines[k].create_new]
        if conflicting:
            raise UserError(
                'Both an existing part and "Create as new part" are set for:\n\n'
                + '\n'.join(conflicting) + '\n\nKeep only one.')

        resolved, created = {}, []
        for key in keys:
            line = lines[key]
            if line.product_tmpl_id:
                resolved[key] = self._use_existing_component(line.product_tmpl_id)
            else:
                resolved[key] = self._create_component(line.sheet_name)
                created.append(line.sheet_name)
        return resolved, created

    def _use_existing_component(self, tmpl):
        tmpl = tmpl.sudo().with_context(active_test=False)
        if not tmpl.active:
            tmpl.write({'active': True})
        # Reactivating a template does not bring back its archived variant,
        # and BOM lines then point at an archived product (stock shows 0 in the
        # product views). Always reactivate the variants of a BOM component.
        tmpl.product_variant_ids.filtered(lambda v: not v.active).write({'active': True})
        if not tmpl.is_storable:
            tmpl.write({'is_storable': True})
        return tmpl.product_variant_ids[:1]

    @api.model
    def _default_new_part_categ(self):
        """Imported CKD Components if the company has it, else any Average-cost
        category; empty (Odoo's default category) when there is neither."""
        Category = self.env['product.category']
        return (
            Category.search([('name', '=', 'Imported CKD Components')], limit=1)
            or Category.search([('property_cost_method', '=', 'average')], order='id', limit=1)
        )

    def _create_component(self, name):
        vals = {
            'name': name,
            'is_storable': True,
            'purchase_ok': True,
            'sale_ok': False,
        }
        if self.new_part_categ_id:
            vals['categ_id'] = self.new_part_categ_id.id
        tmpl = self.env['product.template'].sudo().create(vals)
        return tmpl.product_variant_ids[:1]

    @staticmethod
    def _parts_note(components, created):
        return f'{len(components) - len(created)} existing part(s) reused, {len(created)} new part(s) created'

    def _action_create_new_model(self, colours, common_rows, rows_by_colour, components, created):
        self.ensure_one()
        Template = self.env['product.template']

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

        if colours:
            self._setup_colour_variants(tmpl, colours)
        bom_count = self._create_colour_boms(
            tmpl, colours, common_rows, rows_by_colour, components)

        tmpl.message_post(
            body=f'Created via New Bike Model wizard: '
                 f'{len(colours) or "no"} colour variant(s), {bom_count} Bill(s) of Materials; '
                 f'{self._parts_note(components, created)}.',
        )
        return self._open_template(tmpl)

    def _action_add_variant(self, colours, common_rows, rows_by_colour, components, created):
        """Add new colour(s) — each with its own Bill of Materials — to a
        bike model that already exists, without touching its existing
        colours/BOMs. Components legitimately differ across a model's own
        colour variants (different panel/decal part numbers, etc.), so the
        new colour's BOM is built entirely from what's uploaded here, same
        as every other colour's BOM already is."""
        self.ensure_one()
        tmpl = self.product_tmpl_id
        color_attr = self._color_attr()
        attr_line = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == color_attr)

        self._add_colour_variants(tmpl, color_attr, attr_line, colours)
        bom_count = self._create_colour_boms(
            tmpl, colours, common_rows, rows_by_colour, components)

        tmpl.message_post(
            body=f'New colour variant(s) added via New Bike Model wizard: '
                 f'{", ".join(colours)} ({bom_count} new Bill(s) of Materials; '
                 f'{self._parts_note(components, created)}).',
        )
        return self._open_template(tmpl)

    def _open_template(self, tmpl):
        return {
            'type': 'ir.actions.act_window',
            'name': tmpl.name,
            'res_model': 'product.template',
            'res_id': tmpl.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _ensure_colour_values(self, color_attr, colours):
        """Resolve or create a product.attribute.value for each colour name
        under the shared Color attribute."""
        AttrValue = self.env['product.attribute.value']
        value_ids = []
        for name in colours:
            val = AttrValue.search([('attribute_id', '=', color_attr.id), ('name', '=', name)], limit=1)
            if not val:
                val = AttrValue.create({'attribute_id': color_attr.id, 'name': name})
            value_ids.append(val.id)
        return value_ids

    def _setup_colour_variants(self, tmpl, colours):
        """Set up the Color attribute line so one variant per colour name
        exists — reuses the same 'attr_ego_color' attribute every existing
        model uses, generalized from product_template.py's
        _ensure_new_model_attributes (which only ever ran for a hardcoded
        template list) to work for any template."""
        color_attr = self._color_attr()
        value_ids = self._ensure_colour_values(color_attr, colours)
        self.env['product.template.attribute.line'].create({
            'product_tmpl_id': tmpl.id,
            'attribute_id': color_attr.id,
            'value_ids': [(6, 0, value_ids)],
        })

    def _add_colour_variants(self, tmpl, color_attr, attr_line, colours):
        """Append new colour value(s) to an existing Color attribute line —
        (4, id) so pre-existing colours/variants/BOMs are left untouched."""
        value_ids = self._ensure_colour_values(color_attr, colours)
        if attr_line:
            attr_line.write({'value_ids': [(4, vid) for vid in value_ids]})
        else:
            self.env['product.template.attribute.line'].create({
                'product_tmpl_id': tmpl.id,
                'attribute_id': color_attr.id,
                'value_ids': [(6, 0, value_ids)],
            })

    def _bom_lines(self, rows, components):
        return [(0, 0, {
            'product_id': components[name_key(name)].id,
            'product_qty': qty,
            'product_uom_id': components[name_key(name)].uom_id.id,
        }) for name, qty in rows]

    def _create_colour_boms(self, tmpl, colours, common_rows, rows_by_colour, components):
        """One mrp.bom per colour variant (matching the existing per-colour
        record structure every current model already uses — confirmed not a
        single attribute-scoped BOM), each with the common rows plus that
        colour's own specific rows. A model with no colours gets a single
        BOM for its one variant. Components come from the creator's review
        choices (`components`), never from a name search, so a re-used part
        can't turn into a duplicate."""
        Bom = self.env['mrp.bom']
        if not colours:
            lines = self._bom_lines(common_rows, components)
            if not lines:
                raise UserError('The BOM file has no usable component rows.')
            Bom.create({
                'product_tmpl_id': tmpl.id,
                'product_qty': 1,
                'type': 'normal',
                'bom_line_ids': lines,
            })
            return 1

        created, missing = 0, []
        for colour in colours:
            variant = tmpl.product_variant_ids.filtered(
                lambda v, c=colour: c in v.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id.name'
                )
            )[:1]
            lines = self._bom_lines(common_rows + rows_by_colour.get(colour, []), components)
            if not variant or not lines:
                missing.append(colour)
                continue
            Bom.create({
                'product_tmpl_id': tmpl.id,
                'product_id': variant.id,
                'product_qty': 1,
                'type': 'normal',
                'bom_line_ids': lines,
            })
            created += 1
        if missing:
            raise UserError(
                'No Bill of Materials could be built for: ' + ', '.join(missing)
                + '. Check that the Colour column values match the colour(s) '
                  'entered above, and that each colour has component rows.')
        return created


class NewBikeModelWizardLine(models.TransientModel):
    """One distinct component name from the BOM sheet and what to do with it."""
    _name = 'elegomotors.new.bike.model.wizard.line'
    _description = 'New Bike Model - component review line'
    _order = 'match_rank, id'

    wizard_id = fields.Many2one(
        'elegomotors.new.bike.model.wizard', required=True, ondelete='cascade')
    sheet_name = fields.Char(string='Name in sheet', readonly=True)
    name_key = fields.Char(readonly=True)
    used_in = fields.Char(string='Used in', readonly=True)
    qty_text = fields.Char(string='Qty', readonly=True)
    match_type = fields.Selection([
        ('exact', 'Same name'),
        ('similar', 'Similar name'),
        ('new', 'Not found'),
    ], string='Match', readonly=True)
    match_rank = fields.Integer(readonly=True)
    suggestions = fields.Char(string='Similar parts in Odoo', readonly=True)
    suggestion_ids = fields.Many2many(
        'product.template', 'elegomotors_bike_wizard_line_suggestion_rel',
        'line_id', 'tmpl_id', readonly=True)
    top_tmpl_id = fields.Many2one('product.template', readonly=True)
    product_tmpl_id = fields.Many2one(
        'product.template', string='Use existing part',
        domain=[('x_is_ego_bike', '=', False)])
    create_new = fields.Boolean(string='Create as new part')

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        if self.product_tmpl_id:
            self.create_new = False

    @api.onchange('create_new')
    def _onchange_create_new(self):
        if self.create_new:
            self.product_tmpl_id = False

    def action_use_top(self):
        for line in self:
            if line.top_tmpl_id:
                line.write({'product_tmpl_id': line.top_tmpl_id.id, 'create_new': False})
        return True
