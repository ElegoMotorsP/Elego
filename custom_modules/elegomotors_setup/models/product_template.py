# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


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
    x_qc_sample_percent = fields.Float(
        string='QC Sample %',
        default=100.0,
        help='Percentage of received units actually inspected during QC '
             'Inward, for bulk deliveries where checking every unit is not '
             'practical (e.g. 20 = only the first 20% of units received get '
             'a QC checklist to fill; Pratik inspects that sample and '
             'enters the overall "QC Passed" quantity for the whole batch). '
             '100 = every unit inspected. Only Manohar (Admin) can change this.',
    )

    x_kit_price_default = fields.Float(
        string='Default Kit Price',
        digits='Product Price',
        help='Default per-unit price used to pre-fill the Kit Price field in the '
             'Load BOM Components wizard (Kit mode) when this model is selected. '
             'One value per model, shared across all its colours — always '
             'manually overridable at PO time.',
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
            """Ensure attribute line exists with EXACTLY the required values.
            Uses (6, 0, ids) to replace the full set — removes old/incorrect values."""
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
                # Replace entire value set — removes incorrect/extra values
                line.write({'value_ids': [(6, 0, value_ids)]})
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

        # Battery Type: Lead Acid Battery 60V32Ah, Lithium Battery 60V30Ah, Lithium Battery 60V38Ah
        battery_attr = self.env.ref(
            'elegomotors_setup.attr_battery_type', raise_if_not_found=False
        )
        if battery_attr:
            _ensure_line(battery_attr, [
                'Lead Acid Battery 60V32Ah',
                'Lithium Battery 60V30Ah',
                'Lithium Battery 60V38Ah',
            ])

    @api.model
    def _ensure_new_model_attributes(self):
        """Set up Color (Red/Gray/Black/White) as the variant attribute for Elego 1.1, 1.2, 2.0+.

        Each model gets 4 inventory-tracked variants by colour. Battery Type is NOT
        a product variant — it is recorded as x_battery_type on the MO and lot.
        Runs on every upgrade; safe to call repeatedly.
        """
        color_attr = self.env.ref(
            'elegomotors_setup.attr_ego_color', raise_if_not_found=False
        )
        battery_attr = self.env.ref(
            'elegomotors_setup.attr_battery_type', raise_if_not_found=False
        )
        if not color_attr:
            return

        AttrValue = self.env['product.attribute.value']
        AttrLine  = self.env['product.template.attribute.line']

        def _get_or_create_color_values(names):
            ids = []
            for name in names:
                val = AttrValue.search(
                    [('attribute_id', '=', color_attr.id), ('name', '=', name)], limit=1
                )
                if not val:
                    val = AttrValue.create({'attribute_id': color_attr.id, 'name': name})
                ids.append(val.id)
            return ids

        def _ensure_color_line(tmpl, value_ids):
            line = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == color_attr)
            if line:
                line.write({'value_ids': [(6, 0, value_ids)]})
            else:
                AttrLine.create({
                    'product_tmpl_id': tmpl.id,
                    'attribute_id':    color_attr.id,
                    'value_ids':       [(4, vid) for vid in value_ids],
                })

        color_ids = _get_or_create_color_values(['Red', 'Gray', 'Black', 'White'])

        for tmpl_ref in [
            'elegomotors_setup.tmpl_elego_11',
            'elegomotors_setup.tmpl_elego_12',
            'elegomotors_setup.tmpl_elego_20p',
            'elegomotors_setup.tmpl_elego_30',
        ]:
            tmpl = self.env.ref(tmpl_ref, raise_if_not_found=False)
            if not tmpl:
                continue
            # Remove Battery Type attribute line if present — not a variant for new models
            if battery_attr:
                bat_line = tmpl.attribute_line_ids.filtered(
                    lambda l: l.attribute_id == battery_attr
                )
                if bat_line:
                    bat_line.unlink()
            # Ensure Color attribute line with Red / Gray / Black / White
            _ensure_color_line(tmpl, color_ids)
            # Reactivate any Color variants archived during a prior Battery Type → Color
            # attribute transition. Odoo only auto-reactivates on _create_variant_ids()
            # when the attribute line actually changes; if the line is already correct the
            # write is a no-op and archived variants stay hidden.
            inactive_color = self.env['product.product'].with_context(active_test=False).search([
                ('product_tmpl_id', '=', tmpl.id),
                ('active', '=', False),
            ]).filtered(lambda v: v.product_template_attribute_value_ids.filtered(
                lambda ptav: ptav.attribute_id == color_attr
            ))
            if inactive_color:
                inactive_color.write({'active': True})

    @api.model
    def _ensure_elego_11_color_boms(self):
        """Create variant-specific BOMs for Elego 1.1 (Red, White, Gray, Black).

        One BOM per color variant: 9 color-specific body panels + 109 common components
        from the authoritative ELEGO_1.1_BOM_All_Variants.pdf (118 parts total).

        Runs on every upgrade (noupdate="0"). Deletes and recreates all variant BOMs
        so component list changes in code are always reflected.

        Also removes any template-level BOM (product_id=False) for Elego 1.1 — having
        both a template BOM and variant BOMs causes Odoo's MO auto-select to pick
        whichever has the lower database ID (usually the older template BOM with
        16 generic placeholder components), instead of the correct color-specific one.
        """
        tmpl = self.env.ref('elegomotors_setup.tmpl_elego_11', raise_if_not_found=False)
        color_attr = self.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        if not tmpl or not color_attr:
            _logger.warning('Elego 1.1 BOM: tmpl_elego_11 or attr_ego_color not found — skipping.')
            return

        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        uom_unit = self.env.ref('uom.product_uom_unit')

        # Remove template-level BOMs (product_id=False). The variant BOMs below are
        # the sole authoritative source; coexistence causes non-deterministic MO BOM selection.
        template_boms = Bom.search([('product_tmpl_id', '=', tmpl.id), ('product_id', '=', False)])
        if template_boms:
            _logger.info(
                'Elego 1.1 BOM: removing %d template-level BOM(s) — variant BOMs are authoritative.',
                len(template_boms),
            )
            template_boms.sudo().unlink()

        def _get_or_create_component(name):
            match = self.env['product.template'].sudo().with_context(active_test=False).search(
                [('name', '=', name)], limit=1
            )
            if match:
                if not match.active:
                    match.sudo().write({'active': True})
                if not match.is_storable:
                    match.sudo().write({'is_storable': True})
                return match.product_variant_ids[:1]
            new_tmpl = self.env['product.template'].sudo().create({
                'name': name,
                'is_storable': True,
                'purchase_ok': True,
                'sale_ok': False,
            })
            _logger.info('Elego 1.1 BOM: created component "%s"', name)
            return new_tmpl.product_variant_ids[:1]

        color_panels = {
            'Red': [
                ('ELEGO 1.1 FRONT FENDER RED', 1),
                ('ELEGO 1.1 FRONT PANEL RED', 1),
                ('ELEGO 1.1 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.1 HEAD HOOD RED', 1),
                ('ELEGO 1.1 SIDE BODY PANEL LH RED', 1),
                ('ELEGO 1.1 SIDE BODY PANEL RH RED', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP LH RED', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP RH RED', 1),
                ('ELEGO 1.1 REAR CONNECTION RED', 1),
            ],
            'White': [
                ('ELEGO 1.1 FRONT FENDER WHITE', 1),
                ('ELEGO 1.1 FRONT PANEL WHITE', 1),
                ('ELEGO 1.1 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.1 HEAD HOOD WHITE', 1),
                ('ELEGO 1.1 SIDE BODY PANEL LH WHITE', 1),
                ('ELEGO 1.1 SIDE BODY PANEL RH WHITE', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP LH WHITE', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP RH WHITE', 1),
                ('ELEGO 1.1 REAR CONNECTION WHITE', 1),
            ],
            'Gray': [
                ('ELEGO 1.1 FRONT FENDER GRAY', 1),
                ('ELEGO 1.1 FRONT PANEL GRAY', 1),
                ('ELEGO 1.1 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.1 HEAD HOOD GRAY', 1),
                ('ELEGO 1.1 SIDE BODY PANEL LH GRAY', 1),
                ('ELEGO 1.1 SIDE BODY PANEL RH GRAY', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP LH GRAY', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP RH GRAY', 1),
                ('ELEGO 1.1 REAR CONNECTION GRAY', 1),
            ],
            'Black': [
                ('ELEGO 1.1 FRONT FENDER BLACK', 1),
                ('ELEGO 1.1 FRONT PANEL BLACK', 1),
                ('ELEGO 1.1 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.1 HEAD HOOD BLACK', 1),
                ('ELEGO 1.1 SIDE BODY PANEL LH BLACK', 1),
                ('ELEGO 1.1 SIDE BODY PANEL RH BLACK', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP LH BLACK', 1),
                ('ELEGO 1.1 SIDE EDGE STRIP RH BLACK', 1),
                ('ELEGO 1.1 REAR CONNECTION BLACK', 1),
            ],
        }

        common_components = [
            # Common plastic / body
            ('ELEGO 1.1 BAG HOOK', 1),
            ('ELEGO 1.1 CHASSIS FENDER', 1),
            ('ELEGO 1.1 CONTROLLER CAP BIG', 1),
            ('ELEGO 1.1 CONTROLLER CAP SMALL', 1),
            ('ELEGO 1.1 CONTROLLER FENDER', 1),
            ('ELEGO 1.1 FOOT BOARD', 1),
            ('ELEGO 1.1 FOOT PLATE COVER', 1),
            ('ELEGO 1.1 FOOTMAT', 1),
            ('ELEGO 1.1 FRONT INNER FENDER', 1),
            ('ELEGO 1.1 FRONT PANEL NET', 1),
            ('ELEGO 1.1 GRIP DISTANCE PIECE', 1),
            ('ELEGO 1.1 INSTRUMENT CLUSTER COVER', 1),
            ('ELEGO 1.1 REAR FENDER', 1),
            ('ELEGO 1.1 REAR INNER FENDER', 1),
            ('ELEGO 1.1 ROUND REFLECTOR', 2),
            ('ELEGO 1.1 SEAT', 1),
            ('ELEGO 1.1 SEAT BARREL', 1),
            ('ELEGO 1.1 SEAT BARREL FRONT PANEL', 1),
            ('ELEGO 1.1 SQUARE REFLECTOR', 1),
            ('ELEGO 1.1 SWING ARM COVER LH', 1),
            ('ELEGO 1.1 SWING ARM COVER RH', 1),
            ('ELEGO 1.1 TOOL BOX', 1),
            ('ELEGO 1.1 TOOL BOX CABINATE COVER', 1),
            ('ELEGO 1.1 VIN COVER', 1),
            # Metal / frame
            ('ELEGO 1.1 MIRROR SET', 1),
            ('ELEGO 1.1 BATTERT CLAMP', 1),
            ('ELEGO 1.1 CHASSIS FRAME', 1),
            ('ELEGO 1.1 FRONT BRAKE CABLE HOLDER CLAMP', 1),
            ('ELEGO 1.1 FRONT GUARD BRAKET', 1),
            ('ELEGO 1.1 FRONT RIM', 1),
            ('ELEGO 1.1 HANDAL BAR', 1),
            ('ELEGO 1.1 MIDDLE STAND', 1),
            ('ELEGO 1.1 MIDDLE STAND RUBBER', 1),
            ('ELEGO 1.1 SEAT LATCH', 1),
            ('ELEGO 1.1 SEAT LATCH CABLE', 1),
            ('ELEGO 1.1 SIDE STAND', 1),
            ('ELEGO 1.1 SWING ARM', 1),
            # Brake / safety
            ('ELEGO 1.1 BRAKE LEVER WITH SENSOR', 1),
            ('ELEGO 1.1 FRONT DISC BRAKE PUMP', 1),
            ('ELEGO 1.1 FRONT DISC PLATE', 1),
            ('ELEGO 1.1 FRONT SIDE GUARD', 1),
            ('ELEGO 1.1 GRAB HANDLE', 1),
            ('ELEGO 1.1 GREEN CARD', 1),
            ('ELEGO 1.1 NUMBER PLATE', 1),
            ('ELEGO 1.1 REAR BRAKE CABLE', 1),
            ('ELEGO 1.1 REAR BRAKE DRUM PLATE', 1),
            ('ELEGO 1.1 SIDE GUARD BAR LH', 1),
            ('ELEGO 1.1 SIDE GUARD BAR RH', 1),
            # Electrical
            ('ELEGO 1.1 ANTI THEFT KIT', 1),
            ('ELEGO 1.1 BATTERY CONNECTION BIG WIRE', 1),
            ('ELEGO 1.1 BATTERY CONNECTION SMALL WIRE', 1),
            ('ELEGO 1.1 CONTROLLER', 1),
            ('ELEGO 1.1 DC CONVERTER', 1),
            ('ELEGO 1.1 DISPLY METER', 1),
            ('ELEGO 1.1 FLASHER', 1),
            ('ELEGO 1.1 FRONT INDICATOR (LH)', 1),
            ('ELEGO 1.1 FRONT INDICATOR (RH)', 1),
            ('ELEGO 1.1 HEAD LIGHT SWITCH', 1),
            ('ELEGO 1.1 HEADLAMP ASSY', 1),
            ('ELEGO 1.1 HEADLAMP BULB', 1),
            ('ELEGO 1.1 HORN SWITCH LH', 1),
            ('ELEGO 1.1 HORN SWITCH RH', 1),
            ('ELEGO 1.1 IGNITION LOCK', 1),
            ('ELEGO 1.1 INDICATOR SWITCH', 1),
            ('ELEGO 1.1 MAIN WIRE HARNESS', 1),
            ('ELEGO 1.1 MCB', 1),
            ('ELEGO 1.1 MOTOR', 1),
            ('ELEGO 1.1 NUMBER PLATE LIGHT', 1),
            ('ELEGO 1.1 REVERSE GEAR ASSY', 1),
            ('ELEGO 1.1 TAIL LIGHT ASSY', 1),
            ('ELEGO 1.1 THROTTLE + GRIP', 1),
            ('ELEGO 1.1 UPPER DIPPER SWITCH', 1),
            ('ELEGO 1.1 USB WIRE ASSY', 1),
            # Suspension / wheel
            ('ELEGO 1.1 CONE SET 7 PARTS', 1),
            ('ELEGO 1.1 FRONT FORK ASSY', 1),
            ('ELEGO 1.1 REAR SUSPENSION', 1),
            ('ELEGO 1.1 FRONT SUSPENSION LH', 1),
            ('ELEGO 1.1 FRONT SUSPENSION RH', 1),
            # Fasteners and hardware (names from authoritative BOM PDF)
            ('ROUND HEAD STAR BUTTON SCREW M3X25 HEAD OD 5mm', 1),
            ('ROUND HEAD STAR BUTTON SCREW M4X16 HEAD OD 8mm', 2),
            ('ROUND HEAD STAR BUTTON SCREW M6X12 HEAD OD 12mm', 2),
            ('HEX FLANGE BOLT M6X12', 3),
            ('HEX FLANGE BOLT M6X16', 3),
            ('HEX FLANGE BOLT M6X30', 3),
            ('HEX FLANGE BOLT M8X16', 4),
            ('HEX FLANGE BOLT M8X20', 1),
            ('HEX FLANGE BOLT M10X23 HALF THREAD HS-10.9 HEAD 10mm DRILLED M6', 1),
            ('HEX FLANGE BOLT M10X28 HALF THREAD HEAD 17mm', 2),
            ('HEX FLANGE BOLT M10X30', 2),
            ('HEX FLANGE BOLT M10X40', 4),
            ('HEX FLANGE BOLT M10X45', 1),
            ('HEX FLANGE BOLT M12X220 HALF THREAD', 1),
            ('HEX FLANGE BOLT M12X225 HALF THREAD', 1),
            ('HANDLE BAR BUSH', 1),
            ('FRONT AXELE BUSH 1 MS', 1),
            ('FRONT AXELE BUSH 2 MS', 47),
            ('SELF THREADING SCREW ST4X12mm', 30),
            ('SELF THREADING SCREW ST5X16mm', 2),
            ('PLAIN WASHER M6', 4),
            ('PLAIN WASHER', 25),
            ('SPRING CLIPS', 2),
            ('HEX FLANGE NUT M3', 2),
            ('HEX FLANGE NUT M4', 10),
            ('HEX FLANGE NUT M6', 2),
            ('HEX FLANGE NUT M8', 6),
            ('HEX FLANGE NUT M10', 2),
            ('HEX FLANGE NUT M12', 1),
            # Springs
            ('ELEGO 1.1 MAIN STAND SPRING', 1),
            ('ELEGO 1.1 SIDE STAND SPRING', 1),
        ]

        for color_name, panel_lines in color_panels.items():
            color_val = self.env['product.attribute.value'].search([
                ('attribute_id', '=', color_attr.id),
                ('name', '=', color_name),
            ], limit=1)
            if not color_val:
                _logger.warning('Elego 1.1 BOM: color attribute value "%s" not found — skipping.', color_name)
                continue

            variant = tmpl.with_context(active_test=False).product_variant_ids.filtered(
                lambda v, cv=color_val: cv in v.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id'
                )
            )[:1]
            if not variant:
                _logger.warning('Elego 1.1 BOM: no variant found for color "%s" — skipping.', color_name)
                continue
            if not variant.active:
                variant.write({'active': True})

            existing = Bom.search([
                ('product_tmpl_id', '=', tmpl.id),
                ('product_id', '=', variant.id),
            ], limit=1)
            if existing:
                try:
                    existing.sudo().unlink()
                except UserError:
                    _logger.warning(
                        'BOM for variant %s has running MOs — skipping recreation.',
                        variant.display_name,
                    )
                    continue

            bom = Bom.sudo().create({
                'product_tmpl_id': tmpl.id,
                'product_id': variant.id,
                'product_qty': 1.0,
                'product_uom_id': uom_unit.id,
                'type': 'normal',
            })

            seq = 10
            lines_added = 0
            for name, qty in panel_lines + common_components:
                comp = _get_or_create_component(name)
                if comp:
                    BomLine.sudo().create({
                        'bom_id': bom.id,
                        'product_id': comp.id,
                        'product_qty': float(qty),
                        'product_uom_id': uom_unit.id,
                        'sequence': seq,
                    })
                    seq += 10
                    lines_added += 1

            _logger.info(
                'Elego 1.1 BOM (%s): created with %d component lines.',
                color_name, lines_added,
            )

    @api.model
    def _ensure_elego_12_color_boms(self):
        """Create variant-specific BOMs for Elego 1.2 (Red, White, Gray, Black).

        9 color-specific body panels + 108 common components = 117 parts per variant.
        Source: 1.2 BOM XLSX files per color.

        Runs on every upgrade (noupdate="0"). Deletes and recreates all variant BOMs
        and removes any template-level BOM to prevent non-deterministic MO BOM selection.
        """
        tmpl = self.env.ref('elegomotors_setup.tmpl_elego_12', raise_if_not_found=False)
        color_attr = self.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        if not tmpl or not color_attr:
            _logger.warning('Elego 1.2 BOM: tmpl_elego_12 or attr_ego_color not found — skipping.')
            return

        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        uom_unit = self.env.ref('uom.product_uom_unit')

        template_boms = Bom.search([('product_tmpl_id', '=', tmpl.id), ('product_id', '=', False)])
        if template_boms:
            _logger.info(
                'Elego 1.2 BOM: removing %d template-level BOM(s) — variant BOMs are authoritative.',
                len(template_boms),
            )
            template_boms.sudo().unlink()

        def _get_or_create_component(name):
            match = self.env['product.template'].sudo().with_context(active_test=False).search(
                [('name', '=', name)], limit=1
            )
            if match:
                if not match.active:
                    match.sudo().write({'active': True})
                if not match.is_storable:
                    match.sudo().write({'is_storable': True})
                return match.product_variant_ids[:1]
            new_tmpl = self.env['product.template'].sudo().create({
                'name': name,
                'is_storable': True,
                'purchase_ok': True,
                'sale_ok': False,
            })
            _logger.info('Elego 1.2 BOM: created component "%s"', name)
            return new_tmpl.product_variant_ids[:1]

        color_panels = {
            'Red': [
                ('ELEGO 1.2 FRONT FENDER RED', 1),
                ('ELEGO 1.2 FRONT PANEL RED', 1),
                ('ELEGO 1.2 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.2 HEAD HOOD RED', 1),
                ('ELEGO 1.2 SIDE BODY PANEL LH RED', 1),
                ('ELEGO 1.2 SIDE BODY PANEL RH RED', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP LH RED', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP RH RED', 1),
                ('ELEGO 1.2 REAR CONNECTION RED', 1),
            ],
            'White': [
                ('ELEGO 1.2 FRONT FENDER WHITE', 1),
                ('ELEGO 1.2 FRONT PANEL WHITE', 1),
                ('ELEGO 1.2 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.2 HEAD HOOD WHITE', 1),
                ('ELEGO 1.2 SIDE BODY PANEL LH WHITE', 1),
                ('ELEGO 1.2 SIDE BODY PANEL RH WHITE', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP LH WHITE', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP RH WHITE', 1),
                ('ELEGO 1.2 REAR CONNECTION WHITE', 1),
            ],
            'Gray': [
                ('ELEGO 1.2 FRONT FENDER GRAY', 1),
                ('ELEGO 1.2 FRONT PANEL GRAY', 1),
                ('ELEGO 1.2 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.2 HEAD HOOD GRAY', 1),
                ('ELEGO 1.2 SIDE BODY PANEL LH GRAY', 1),
                ('ELEGO 1.2 SIDE BODY PANEL RH GRAY', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP LH GRAY', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP RH GRAY', 1),
                ('ELEGO 1.2 REAR CONNECTION GRAY', 1),
            ],
            'Black': [
                ('ELEGO 1.2 FRONT FENDER BLACK', 1),
                ('ELEGO 1.2 FRONT PANEL BLACK', 1),
                ('ELEGO 1.2 FRONT PANEL PART BLACK', 1),
                ('ELEGO 1.2 HEAD HOOD BLACK', 1),
                ('ELEGO 1.2 SIDE BODY PANEL LH BLACK', 1),
                ('ELEGO 1.2 SIDE BODY PANEL RH BLACK', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP LH BLACK', 1),
                ('ELEGO 1.2 SIDE EDGE STRIP RH BLACK', 1),
                ('ELEGO 1.2 REAR CONNECTION BLACK', 1),
            ],
        }

        common_components = [
            # Common plastic / body
            ('ELEGO 1.2 BAG HOOK', 1),
            ('ELEGO 1.2 CHASSIS FENDER', 1),
            ('ELEGO 1.2 CONTROLLER CAP BIG', 1),
            ('ELEGO 1.2 CONTROLLER CAP SMALL', 1),
            ('ELEGO 1.2 CONTROLLER FENDER', 1),
            ('ELEGO 1.2 FOOT BOARD', 1),
            ('ELEGO 1.2 FOOT PLATE COVER', 1),
            ('ELEGO 1.2 FOOTMAT', 1),
            ('ELEGO 1.2 FRONT INNER FENDER', 1),
            ('ELEGO 1.2 FRONT PANEL NET', 1),
            ('ELEGO 1.2 GRIP DISTANCE PIECE', 1),
            ('ELEGO 1.2 INSTRUMENT CLUSTER COVER', 1),
            ('ELEGO 1.2 REAR FENDER', 1),
            ('ELEGO 1.2 REAR INNER FENDER', 1),
            ('ELEGO 1.2 ROUND REFLECTOR', 2),
            ('ELEGO 1.2 SEAT', 1),
            ('ELEGO 1.2 SEAT BARREL', 1),
            ('ELEGO 1.2 SEAT BARREL FRONT PANEL', 1),
            ('ELEGO 1.2 SQUARE REFLECTOR', 1),
            ('ELEGO 1.2 SWING ARM COVER LH', 1),
            ('ELEGO 1.2 SWING ARM COVER RH', 1),
            ('ELEGO 1.2 TOOL BOX', 1),
            ('ELEGO 1.2 TOOL BOX CABINATE COVER', 1),
            ('ELEGO 1.2 VIN COVER', 1),
            # Metal / frame
            ('ELEGO 1.2 MIRROR SET', 1),
            ('ELEGO 1.2 BATTERT CLAMP', 1),
            ('ELEGO 1.2 CHASSIS FRAME', 1),
            ('ELEGO 1.2 FRONT BRAKE CABLE HOLDER CLAMP', 1),
            ('ELEGO 1.2 FRONT GUARD BRAKET', 1),
            ('ELEGO 1.2 FRONT RIM', 1),
            ('ELEGO 1.2 HANDAL BAR', 1),
            ('ELEGO 1.2 MIDDLE STAND', 1),
            ('ELEGO 1.2 MIDDLE STAND RUBBER', 1),
            ('ELEGO 1.2 SEAT LATCH', 1),
            ('ELEGO 1.2 SEAT LATCH CABLE', 1),
            ('ELEGO 1.2 SIDE STAND', 1),
            ('ELEGO 1.2 SWING ARM', 1),
            # Brake / safety
            ('ELEGO 1.2 BRAKE LEVER WITH SENSOR', 1),
            ('ELEGO 1.2 FRONT DISC BRAKE PUMP', 1),
            ('ELEGO 1.2 FRONT DISC PLATE', 1),
            ('ELEGO 1.2 FRONT SIDE GUARD', 1),
            ('ELEGO 1.2 GRAB HANDLE', 1),
            ('ELEGO 1.2 GREEN CARD', 1),
            ('ELEGO 1.2 NUMBER PLATE', 1),
            ('ELEGO 1.2 REAR BRAKE CABLE', 1),
            ('ELEGO 1.2 REAR BRAKE DRUM PLATE', 1),
            ('ELEGO 1.2 SIDE GUARD BAR LH', 1),
            ('ELEGO 1.2 SIDE GUARD BAR RH', 1),
            # Electrical
            ('ELEGO 1.2 ANTI THEFT KIT', 1),
            ('ELEGO 1.2 BATTERY CONNECTION BIG WIRE', 1),
            ('ELEGO 1.2 BATTERY CONNECTION SMALL WIRE', 4),
            ('ELEGO 1.2 CONTROLLER', 1),
            ('ELEGO 1.2 DC CONVERTER', 1),
            ('ELEGO 1.2 DISPLY METER', 1),
            ('ELEGO 1.2 FLASHER', 1),
            ('ELEGO 1.2 FRONT INDICATOR (LH)', 1),
            ('ELEGO 1.2 FRONT INDICATOR (RH)', 1),
            ('ELEGO 1.2 HEAD LIGHT SWITCH', 1),
            ('ELEGO 1.2 HEADLAMP ASSY', 1),
            ('ELEGO 1.2 HEADLAMP BULB', 1),
            ('ELEGO 1.2 HORN SWITCH LH', 1),
            ('ELEGO 1.2 HORN SWITCH RH', 1),
            ('ELEGO 1.2 IGNITION LOCK', 1),
            ('ELEGO 1.2 INDICATOR SWITCH', 1),
            ('ELEGO 1.2 MAIN WIRE HARNESS', 1),
            ('ELEGO 1.2 MCB', 1),
            ('ELEGO 1.2 MOTOR', 1),
            ('ELEGO 1.2 NUMBER PLATE LIGHT', 1),
            ('ELEGO 1.2 REVERSE GEAR ASSY', 1),
            ('ELEGO 1.2 TAIL LIGHT ASSY', 1),
            ('ELEGO 1.2 THROTTLE + GRIP', 1),
            ('ELEGO 1.2 UPPER DIPPER SWITCH', 1),
            ('ELEGO 1.2 USB WIRE ASSY', 1),
            # Suspension / wheel
            ('ELEGO 1.2 CONE SET 7 PARTS', 1),
            ('ELEGO 1.2 FRONT FORK ASSY', 1),
            ('ELEGO 1.2 REAR SUSPENSION', 2),
            ('ELEGO 1.2 FRONT SUSPENSION LH', 1),
            ('ELEGO 1.2 FRONT SUSPENSION RH', 1),
            # Fasteners and hardware
            ('ROUND HEAD STAR BUTTON SCREW M3X25 HEAD OD 5mm', 2),
            ('ROUND HEAD STAR BUTTON SCREW M4X16 HEAD OD 8mm', 2),
            ('ROUND HEAD STAR BUTTON SCREW M6X12 HEAD OD 12mm', 3),
            ('HEX FLANGE BOLT M6X12', 33),
            ('HEX FLANGE BOLT M6X16', 3),
            ('HEX FLANGE BOLT M6X30', 4),
            ('HEX FLANGE BOLT M8X16', 1),
            ('HEX FLANGE BOLT M8X20', 2),
            ('HEX FLANGE BOLT M10X23 HALF THREAD HS-10.9 Head 10mm Drilled -M6', 1),
            ('HEX FLANGE BOLT M10X28 HALF THREAD Head 17mm', 2),
            ('HEX FLANGE BOLT M10X30', 2),
            ('HEX FLANGE BOLT M10X 40', 4),
            ('HEX FLANGE BOLT M10X 45', 1),
            ('HEX FLANGE BOLT M12X220 HALF THREAD', 1),
            ('HEX FLANGE BOLT M12X225 HALF THREAD', 1),
            ('HANDLE BAR BUSH', 1),
            ('FRONT AXELE BUSH -1 MS', 1),
            ('FRONT AXELE BUSH-2 MS', 1),
            ('SELF THREADING ST4 STAR BUTTON SCREW ST4X12mm', 47),
            ('SELF THREADING ST4 STAR BUTTON SCREW ST5X16mm', 30),
            ('PLAIN WASHER M6', 2),
            ('SPRING CLIPS', 25),
            ('HEX FLANGE NUT M3', 2),
            ('HEX FLANGE NUT M4', 2),
            ('HEX FLANGE NUT M6', 10),
            ('HEX FLANGE NUT M8', 2),
            ('HEX FLANGE NUT M10', 6),
            ('HEX FLANGE NUT M12', 2),
            # Springs
            ('ELEGO 1.2 MAIN STAND SPRING', 1),
            ('ELEGO 1.2 SIDE STAND SPRING', 1),
        ]

        for color_name, panel_lines in color_panels.items():
            color_val = self.env['product.attribute.value'].search([
                ('attribute_id', '=', color_attr.id),
                ('name', '=', color_name),
            ], limit=1)
            if not color_val:
                _logger.warning('Elego 1.2 BOM: color attribute value "%s" not found — skipping.', color_name)
                continue

            variant = tmpl.with_context(active_test=False).product_variant_ids.filtered(
                lambda v, cv=color_val: cv in v.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id'
                )
            )[:1]
            if not variant:
                _logger.warning('Elego 1.2 BOM: no variant found for color "%s" — skipping.', color_name)
                continue
            if not variant.active:
                variant.write({'active': True})

            existing = Bom.search([
                ('product_tmpl_id', '=', tmpl.id),
                ('product_id', '=', variant.id),
            ], limit=1)
            if existing:
                try:
                    existing.sudo().unlink()
                except UserError:
                    _logger.warning(
                        'BOM for variant %s has running MOs — skipping recreation.',
                        variant.display_name,
                    )
                    continue

            bom = Bom.sudo().create({
                'product_tmpl_id': tmpl.id,
                'product_id': variant.id,
                'product_qty': 1.0,
                'product_uom_id': uom_unit.id,
                'type': 'normal',
            })

            seq = 10
            lines_added = 0
            for name, qty in panel_lines + common_components:
                comp = _get_or_create_component(name)
                if comp:
                    BomLine.sudo().create({
                        'bom_id': bom.id,
                        'product_id': comp.id,
                        'product_qty': float(qty),
                        'product_uom_id': uom_unit.id,
                        'sequence': seq,
                    })
                    seq += 10
                    lines_added += 1

            _logger.info(
                'Elego 1.2 BOM (%s): created with %d component lines.',
                color_name, lines_added,
            )

    @api.model
    def _ensure_elego_20p_color_boms(self):
        """Create variant-specific BOMs for Elego 2.0+ (Red, White, Gray, Black).

        10 color-specific body panels + 107 common components = 117 parts per variant.
        Source: 2.0+ BOM XLSX files per color.

        Runs on every upgrade (noupdate="0"). Deletes and recreates all variant BOMs
        and removes any template-level BOM to prevent non-deterministic MO BOM selection.
        """
        tmpl = self.env.ref('elegomotors_setup.tmpl_elego_20p', raise_if_not_found=False)
        color_attr = self.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        if not tmpl or not color_attr:
            _logger.warning('Elego 2.0+ BOM: tmpl_elego_20p or attr_ego_color not found — skipping.')
            return

        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        uom_unit = self.env.ref('uom.product_uom_unit')

        template_boms = Bom.search([('product_tmpl_id', '=', tmpl.id), ('product_id', '=', False)])
        if template_boms:
            _logger.info(
                'Elego 2.0+ BOM: removing %d template-level BOM(s) — variant BOMs are authoritative.',
                len(template_boms),
            )
            template_boms.sudo().unlink()

        def _get_or_create_component(name):
            match = self.env['product.template'].sudo().with_context(active_test=False).search(
                [('name', '=', name)], limit=1
            )
            if match:
                if not match.active:
                    match.sudo().write({'active': True})
                if not match.is_storable:
                    match.sudo().write({'is_storable': True})
                return match.product_variant_ids[:1]
            new_tmpl = self.env['product.template'].sudo().create({
                'name': name,
                'is_storable': True,
                'purchase_ok': True,
                'sale_ok': False,
            })
            _logger.info('Elego 2.0+ BOM: created component "%s"', name)
            return new_tmpl.product_variant_ids[:1]

        color_panels = {
            'Red': [
                ('ELEGO 2.0+ FRONT FENDER RED', 1),
                ('ELEGO 2.0+ FRONT PANEL RED', 1),
                ('ELEGO 2.0+ HEAD HOOD RED', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL LH RED', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL RH RED', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP LH RED', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP RH RED', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART LH', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART RH', 1),
                ('ELEGO 2.0+ REAR CONNECTION RED', 1),
            ],
            'White': [
                ('ELEGO 2.0+ FRONT FENDER WHITE', 1),
                ('ELEGO 2.0+ FRONT PANEL WHITE', 1),
                ('ELEGO 2.0+ HEAD HOOD WHITE', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL LH WHITE', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL RH WHITE', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP LH WHITE', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP RH WHITE', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART LH', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART RH', 1),
                ('ELEGO 2.0+ REAR CONNECTION WHITE', 1),
            ],
            'Gray': [
                ('ELEGO 2.0+ FRONT FENDER GRAY', 1),
                ('ELEGO 2.0+ FRONT PANEL GRAY', 1),
                ('ELEGO 2.0+ HEAD HOOD GRAY', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL LH GRAY', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL RH GRAY', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP LH GRAY', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP RH GRAY', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART LH', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART RH', 1),
                ('ELEGO 2.0+ REAR CONNECTION GRAY', 1),
            ],
            'Black': [
                ('ELEGO 2.0+ FRONT FENDER BLACK', 1),
                ('ELEGO 2.0+ FRONT PANEL BLACK', 1),
                ('ELEGO 2.0+ HEAD HOOD BLACK', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL LH BLACK', 1),
                ('ELEGO 2.0+ SIDE BODY PANEL RH BLACK', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP LH BLACK', 1),
                ('ELEGO 2.0+ SIDE EDGE STRIP RH BLACK', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART LH', 1),
                ('ELEGO 2.0+ SIDE PANEL CHROME PART RH', 1),
                ('ELEGO 2.0+ REAR CONNECTION BLACK', 1),
            ],
        }

        common_components = [
            # Common plastic / body
            ('ELEGO 2.0+ BAG HOOK', 1),
            ('ELEGO 2.0+ CHASSIS FENDER', 1),
            ('ELEGO 2.0+ CONTROLLER CAP BIG', 1),
            ('ELEGO 2.0+ CONTROLLER CAP SMALL', 1),
            ('ELEGO 2.0+ CONTROLLER FENDER', 1),
            ('ELEGO 2.0+ FOOT BOARD', 1),
            ('ELEGO 2.0+ FOOT PLATE COVER', 1),
            ('ELEGO 2.0+ FOOTMAT', 1),
            ('ELEGO 2.0+ FRONT INNER FENDER', 1),
            ('ELEGO 2.0+ GRIP DISTANCE PIECE', 1),
            ('ELEGO 2.0+ INSTRUMENT CLUSTER COVER', 1),
            ('ELEGO 2.0+ REAR FENDER', 1),
            ('ELEGO 2.0+ REAR INNER FENDER', 1),
            ('ELEGO 2.0+ ROUND REFLECTOR', 2),
            ('ELEGO 2.0+ SEAT', 1),
            ('ELEGO 2.0+ SEAT BARREL', 1),
            ('ELEGO 2.0+ SEAT BARREL FRONT PANEL', 1),
            ('ELEGO 2.0+ SQUARE REFLECTOR', 1),
            ('ELEGO 2.0+ SWING ARM COVER LH', 1),
            ('ELEGO 2.0+ SWING ARM COVER RH', 1),
            ('ELEGO 2.0+ TOOL BOX', 1),
            ('ELEGO 2.0+ TOOL BOX CABINATE COVER', 1),
            ('ELEGO 2.0+ VIN COVER', 1),
            # Metal / frame
            ('ELEGO 2.0+ MIRROR SET', 1),
            ('ELEGO 2.0+ BATTERT CLAMP', 1),
            ('ELEGO 2.0+ CHASSIS FRAME', 1),
            ('ELEGO 2.0+ FRONT BRAKE CABLE HOLDER CLAMP', 1),
            ('ELEGO 2.0+ FRONT GUARD BRAKET', 1),
            ('ELEGO 2.0+ FRONT RIM', 1),
            ('ELEGO 2.0+ HANDAL BAR', 1),
            ('ELEGO 2.0+ MIDDLE STAND', 1),
            ('ELEGO 2.0+ MIDDLE STAND RUBBER', 1),
            ('ELEGO 2.0+ SEAT LATCH', 1),
            ('ELEGO 2.0+ SEAT LATCH CABLE', 1),
            ('ELEGO 2.0+ SIDE STAND', 1),
            ('ELEGO 2.0+ SWING ARM', 1),
            # Brake / safety
            ('ELEGO 2.0+ BRAKE LEVER WITH SENSOR', 1),
            ('ELEGO 2.0+ FRONT DISC BRAKE PUMP', 1),
            ('ELEGO 2.0+ FRONT DISC PLATE', 1),
            ('ELEGO 2.0+ GRAB HANDLE', 1),
            ('ELEGO 2.0+ GREEN CARD', 1),
            ('ELEGO 2.0+ NUMBER PLATE', 1),
            ('ELEGO 2.0+ REAR BRAKE CABLE', 1),
            ('ELEGO 2.0+ REAR BRAKE DRUM PLATE', 1),
            ('ELEGO 2.0+ SIDE GUARD FRONT', 1),
            ('ELEGO 2.0+ SIDE GUARD REAR', 1),
            # Electrical
            ('ELEGO 2.0+ ANTI THEFT KIT', 1),
            ('ELEGO 2.0+ BATTERY CONNECTION BIG WIRE', 1),
            ('ELEGO 2.0+ BATTERY CONNECTION SMALL WIRE', 4),
            ('ELEGO 2.0+ CONTROLLER', 1),
            ('ELEGO 2.0+ DC CONVERTER', 1),
            ('ELEGO 2.0+ DISPLY METER', 1),
            ('ELEGO 2.0+ FLASHER', 1),
            ('ELEGO 2.0+ FRONT INDICATOR (LH)', 1),
            ('ELEGO 2.0+ FRONT INDICATOR (RH)', 1),
            ('ELEGO 2.0+ HEAD LIGHT SWITCH', 1),
            ('ELEGO 2.0+ HEADLAMP ASSY', 1),
            ('ELEGO 2.0+ HEADLAMP BULB', 1),
            ('ELEGO 2.0+ HORN SWITCH LH', 1),
            ('ELEGO 2.0+ HORN SWITCH RH', 1),
            ('ELEGO 2.0+ IGNITION LOCK', 1),
            ('ELEGO 2.0+ INDICATOR SWITCH', 1),
            ('ELEGO 2.0+ MAIN WIRE HARNESS', 1),
            ('ELEGO 2.0+ MCB', 1),
            ('ELEGO 2.0+ MOTOR', 1),
            ('ELEGO 2.0+ NUMBER PLATE LIGHT', 1),
            ('ELEGO 2.0+ REVERSE GEAR ASSY', 1),
            ('ELEGO 2.0+ TAIL LIGHT ASSY', 1),
            ('ELEGO 2.0+ THROTTLE + GRIP', 1),
            ('ELEGO 2.0+ UPPER DIPPER SWITCH', 1),
            ('ELEGO 2.0+ USB WIRE ASSY', 1),
            # Suspension / wheel
            ('ELEGO 2.0+ CONE SET 7 PARTS', 1),
            ('ELEGO 2.0+ FRONT FORK ASSY', 1),
            ('ELEGO 2.0+ REAR SUSPENSION', 2),
            ('ELEGO 2.0+ FRONT SUSPENSION LH', 1),
            ('ELEGO 2.0+ FRONT SUSPENSION RH', 1),
            ('ELEGO 2.0+ TYRE 3-00-10', 2),
            # Fasteners and hardware
            ('ROUND HEAD STAR BUTTON SCREW M3X25 HEAD OD 5mm', 2),
            ('ROUND HEAD STAR BUTTON SCREW M4X16 HEAD OD 8mm', 2),
            ('ROUND HEAD STAR BUTTON SCREW M6X12 HEAD OD 12mm', 4),
            ('HEX FLANGE BOLT M6X12', 32),
            ('HEX FLANGE BOLT M6X16', 3),
            ('HEX FLANGE BOLT M6X30', 4),
            ('HEX FLANGE BOLT M8X16', 1),
            ('HEX FLANGE BOLT M8X20', 2),
            ('HEX FLANGE BOLT M10X23 HALF THREAD HS-10.9 Head 10mm Drilled -M6', 1),
            ('HEX FLANGE BOLT M10X28 HALF THREAD Head 17mm', 2),
            ('HEX FLANGE BOLT M10X30', 2),
            ('HEX FLANGE BOLT M10X 40', 4),
            ('HEX FLANGE BOLT M10X 45', 1),
            ('HEX FLANGE BOLT M12X220 HALF THREAD', 1),
            ('HEX FLANGE BOLT M12X225 HALF THREAD', 1),
            ('HANDLE BAR BUSH', 1),
            ('FRONT AXELE BUSH -1 MS', 1),
            ('FRONT AXELE BUSH-2 MS', 1),
            ('SELF THREADING ST4 STAR BUTTON SCREW ST4X12mm', 42),
            ('SELF THREADING ST4 STAR BUTTON SCREW ST5X16mm', 35),
            ('PLAIN WASHER M6', 2),
            ('SPRING CLIPS', 25),
            ('HEX FLANGE NUT M3', 2),
            ('HEX FLANGE NUT M4', 2),
            ('HEX FLANGE NUT M6', 10),
            ('HEX FLANGE NUT M8', 2),
            ('HEX FLANGE NUT M10', 6),
            ('HEX FLANGE NUT M12', 2),
            # Springs
            ('ELEGO 2.0+ MAIN STAND SPRING', 1),
            ('ELEGO 2.0+ SIDE STAND SPRING', 1),
        ]

        for color_name, panel_lines in color_panels.items():
            color_val = self.env['product.attribute.value'].search([
                ('attribute_id', '=', color_attr.id),
                ('name', '=', color_name),
            ], limit=1)
            if not color_val:
                _logger.warning('Elego 2.0+ BOM: color attribute value "%s" not found — skipping.', color_name)
                continue

            variant = tmpl.with_context(active_test=False).product_variant_ids.filtered(
                lambda v, cv=color_val: cv in v.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id'
                )
            )[:1]
            if not variant:
                _logger.warning('Elego 2.0+ BOM: no variant found for color "%s" — skipping.', color_name)
                continue
            if not variant.active:
                variant.write({'active': True})

            existing = Bom.search([
                ('product_tmpl_id', '=', tmpl.id),
                ('product_id', '=', variant.id),
            ], limit=1)
            if existing:
                try:
                    existing.sudo().unlink()
                except UserError:
                    _logger.warning(
                        'BOM for variant %s has running MOs — skipping recreation.',
                        variant.display_name,
                    )
                    continue

            bom = Bom.sudo().create({
                'product_tmpl_id': tmpl.id,
                'product_id': variant.id,
                'product_qty': 1.0,
                'product_uom_id': uom_unit.id,
                'type': 'normal',
            })

            seq = 10
            lines_added = 0
            for name, qty in panel_lines + common_components:
                comp = _get_or_create_component(name)
                if comp:
                    BomLine.sudo().create({
                        'bom_id': bom.id,
                        'product_id': comp.id,
                        'product_qty': float(qty),
                        'product_uom_id': uom_unit.id,
                        'sequence': seq,
                    })
                    seq += 10
                    lines_added += 1

            _logger.info(
                'Elego 2.0+ BOM (%s): created with %d component lines.',
                color_name, lines_added,
            )

    @api.model
    def _ensure_qc_required_on_bike_components(self):
        """Flag every BOM component of the EGO/Elego bike variants as QC-required,
        so their PO receipts route through QC Inward (Pending QC -> In QC ->
        Approve QC) instead of bypassing straight to Store. Driven by each bike's
        active BOM lines rather than hardcoded component names, so color-specific
        components (created dynamically, without XML IDs) are covered automatically
        and any component added to a BOM later is picked up on the next upgrade.
        """
        refs = [
            'elegomotors_setup.tmpl_ego_scooter',
            'elegomotors_setup.tmpl_elego_11',
            'elegomotors_setup.tmpl_elego_12',
            'elegomotors_setup.tmpl_elego_20p',
            'elegomotors_setup.tmpl_elego_30',
        ]
        bike_tmpls = self.env['product.template']
        for ref in refs:
            tmpl = self.env.ref(ref, raise_if_not_found=False)
            if tmpl:
                bike_tmpls |= tmpl
        if not bike_tmpls:
            return
        boms = self.env['mrp.bom'].search([('product_tmpl_id', 'in', bike_tmpls.ids)])
        components = boms.bom_line_ids.product_id.product_tmpl_id
        components = components.filtered(lambda t: not t.x_qc_required)
        if components:
            components.write({'x_qc_required': True})
            _logger.info(
                'QC Required: flagged %d bike BOM component(s) for QC Inward.',
                len(components),
            )

    @api.model
    def _remove_reorder_rules_for_kit_battery_packs(self):
        """A product cannot have a kit-type (phantom) BOM while it also has
        an active reordering rule — Odoo blocks this outright ("You can not
        create a kit-type bill of materials for products that have at least
        one reordering rule"). The lead-acid battery pack products already
        had reordering rules configured on production before this feature
        existed (dev/staging never had that data, which is why this only
        surfaced against the real production database). Once a pack becomes
        a kit, its own stock is derived from its component cells, so
        replenishment belongs on the base cells instead — this removes the
        now-invalid rule on the pack itself so the phantom BOM can be
        created; a NEW reordering rule should be configured on the base
        cell product(s) if automatic replenishment is still wanted.

        Must run BEFORE the phantom BOM <record> tags in battery_kit_data.xml
        (see the <function> call placed just above them there). Runs on
        every upgrade; idempotent — a no-op once the rules are already gone.
        """
        refs = [
            'elegomotors_setup.prod_battery_lead_acid_60v32ah',
            'elegomotors_setup.prod_battery_lead_acid_72v32ah',
        ]
        products = self.env['product.template']
        for ref in refs:
            tmpl = self.env.ref(ref, raise_if_not_found=False)
            if tmpl:
                products |= tmpl
        if not products:
            return
        orderpoints = self.env['stock.warehouse.orderpoint'].sudo().search([
            ('product_id.product_tmpl_id', 'in', products.ids),
        ])
        if orderpoints:
            _logger.warning(
                'ElegoMotors: removing %d pre-existing reordering rule(s) on '
                '%s — required so their kit BOM (pack -> base cells) can be '
                'created. Set up a new reordering rule on the base cell '
                'product(s) instead if automatic replenishment is still needed.',
                len(orderpoints), ', '.join(products.mapped('name')),
            )
            orderpoints.unlink()

    @api.model
    def _ensure_kit_boms_for_battery_packs(self):
        """Create the lead-acid battery pack -> base cell phantom (kit) BOMs.

        Previously these were plain <record> tags in battery_kit_data.xml,
        which crashed the ENTIRE module registry load if Odoo's kit-BOM
        constraint ("You can not create a kit-type bill of materials for
        products that have at least one reordering rule.") fired for any
        reason — including a reordering rule recreated on prod after
        _remove_reorder_rules_for_kit_battery_packs last ran, or a rule on
        a pack not covered by that method. Idempotent (skips a pack that
        already has a phantom BOM) and resilient: a pack that still can't
        become a kit is logged and skipped instead of blocking every other
        module from loading — matching how BOM (re)creation is already
        handled for the bike color variants above.
        """
        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        uom_unit = self.env.ref('uom.product_uom_unit')
        cell = self.env.ref(
            'elegomotors_setup.prod_cell_lead_12v32ah', raise_if_not_found=False
        )
        if not cell:
            return
        kits = [
            ('elegomotors_setup.prod_battery_lead_acid_60v32ah', 5.0),
            ('elegomotors_setup.prod_battery_lead_acid_72v32ah', 6.0),
        ]
        for ref, qty in kits:
            tmpl = self.env.ref(ref, raise_if_not_found=False)
            if not tmpl:
                continue
            if Bom.search_count([
                ('product_tmpl_id', '=', tmpl.id), ('type', '=', 'phantom'),
            ]):
                continue
            try:
                bom = Bom.sudo().create({
                    'product_tmpl_id': tmpl.id,
                    'product_qty': 1.0,
                    'type': 'phantom',
                })
                BomLine.sudo().create({
                    'bom_id': bom.id,
                    'product_id': cell.id,
                    'product_qty': qty,
                    'product_uom_id': uom_unit.id,
                })
            except UserError:
                _logger.warning(
                    'Kit BOM for battery pack %s could not be created '
                    '(reordering rule still present?) — skipping.',
                    tmpl.display_name,
                )

    @api.model
    def _ensure_bike_gst_5_percent(self):
        """Bike units are always taxed at 5% GST (CGST 2.5% + SGST 2.5%,
        remapped to IGST 5% for inter-state customers by the existing fiscal
        position tax maps). The bike templates never had an explicit
        taxes_id, so every quotation/invoice line picked up whatever the
        database's generic default sale tax happened to be (observed: 15%)
        instead of 5%. Runs on every upgrade (noupdate="0" in
        data/bike_gst_fix.xml, loaded after gst_tax_data.xml); idempotent.
        """
        cgst = self.env.ref('elegomotors_setup.tax_cgst_2_5', raise_if_not_found=False)
        sgst = self.env.ref('elegomotors_setup.tax_sgst_2_5', raise_if_not_found=False)
        if not cgst or not sgst:
            return
        refs = [
            'elegomotors_setup.tmpl_ego_scooter',
            'elegomotors_setup.tmpl_elego_11',
            'elegomotors_setup.tmpl_elego_12',
            'elegomotors_setup.tmpl_elego_20p',
            'elegomotors_setup.tmpl_elego_30',
        ]
        bike_tmpls = self.env['product.template']
        for ref in refs:
            tmpl = self.env.ref(ref, raise_if_not_found=False)
            if tmpl:
                bike_tmpls |= tmpl
        if bike_tmpls:
            bike_tmpls.write({'taxes_id': [(6, 0, [cgst.id, sgst.id])]})
            _logger.info(
                'ElegoMotors: set 5%% GST (CGST 2.5 + SGST 2.5) as default '
                'tax on %d bike template(s).', len(bike_tmpls)
            )

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
