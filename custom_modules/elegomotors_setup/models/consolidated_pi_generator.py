# -*- coding: utf-8 -*-
import logging
from collections import defaultdict
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ConsolidatedPiGenerator(models.AbstractModel):
    """Service model: generates consolidated Issue-to-Production pickings.

    Collects all confirmed, non-urgent bike MOs that have no PI yet, groups
    them by bike model, and creates ONE aggregated picking per model with
    section headers (color-specific parts first, then common parts).

    Called by:
      - ir.cron (daily at 08:00 IST)
      - elegomotors.generate.pi.wizard (manual button)
      - MrpProduction.action_confirm() when x_pi_urgent=True (_create_urgent_pi)
    """

    _name = 'elegomotors.consolidated.pi.generator'
    _description = 'Consolidated Daily PI Generator'

    # ------------------------------------------------------------------
    # Model configuration
    # ------------------------------------------------------------------

    @api.model
    def _get_bike_model_configs(self):
        """Return list of dicts describing each bike model.

        Each dict:
          tmpl_ref      : external ID of the product.template
          model_key     : short key used as x_pi_model_key on the picking
          label         : human-readable name for chatter / picking origin
          uses_color_boms: True for Elego 1.1 (variant-specific BOMs with color parts)
        """
        return [
            {
                'tmpl_ref': 'elegomotors_setup.tmpl_elego_11',
                'model_key': 'elego_11',
                'label': 'Elego 1.1',
                'uses_color_boms': True,
            },
            {
                'tmpl_ref': 'elegomotors_setup.tmpl_elego_12',
                'model_key': 'elego_12',
                'label': 'Elego 1.2',
                'uses_color_boms': False,
            },
            {
                'tmpl_ref': 'elegomotors_setup.tmpl_elego_20p',
                'model_key': 'elego_20p',
                'label': 'Elego 2.0+',
                'uses_color_boms': False,
            },
            {
                'tmpl_ref': 'elegomotors_setup.tmpl_elego_30',
                'model_key': 'elego_30',
                'label': 'Elego 3.0',
                'uses_color_boms': False,
            },
        ]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    @api.model
    def generate_daily_pis(self, force_date=None):
        """Generate one consolidated PI per bike model for all pending MOs.

        Called by the ir.cron and the manual wizard button.
        Returns the count of newly created pickings.
        """
        today = force_date or fields.Date.today()
        issue_type = self.env.ref(
            'elegomotors_setup.picking_type_production_issue', raise_if_not_found=False
        )
        if not issue_type:
            _logger.warning('EGO: picking_type_production_issue not found — skipping daily PI generation.')
            return 0

        created = 0
        for config in self._get_bike_model_configs():
            tmpl = self.env.ref(config['tmpl_ref'], raise_if_not_found=False)
            if not tmpl:
                continue

            mos = self._get_pending_mos_for_model(tmpl)
            if not mos:
                continue

            # Idempotency: skip if an open PI for this model already exists
            existing = self.env['stock.picking'].search([
                ('x_pi_model_key', '=', config['model_key']),
                ('picking_type_id', '=', issue_type.id),
                ('state', 'not in', ('done', 'cancel')),
            ], limit=1)
            if existing:
                _logger.info(
                    'EGO: Consolidated PI for %s already exists (%s) — skipping.',
                    config['label'], existing.name,
                )
                continue

            picking = self._build_consolidated_pi(
                mos=mos,
                issue_type=issue_type,
                config=config,
                for_date=today,
            )
            if picking:
                created += 1
                _logger.info(
                    'EGO: Created consolidated PI %s for %s (%d MOs).',
                    picking.name, config['label'], len(mos),
                )

        return created

    # ------------------------------------------------------------------
    # Urgent PI (called from action_confirm when x_pi_urgent=True)
    # ------------------------------------------------------------------

    @api.model
    def _create_urgent_pi(self, production):
        """Create a dedicated PI for a single urgent MO immediately."""
        issue_type = self.env.ref(
            'elegomotors_setup.picking_type_production_issue', raise_if_not_found=False
        )
        if not issue_type:
            return

        tmpl = production.product_id.product_tmpl_id

        # Classify this single MO's components (treat all as common for simplicity)
        classified = self._classify_components_template_bom([production], tmpl)

        picking = self._create_picking_from_classified(
            mos=production,
            issue_type=issue_type,
            classified=classified,
            uses_color_boms=False,
            origin=f'URGENT PI — {tmpl.name} — {production.name}',
            model_key=f'urgent_{production.id}',
            model_label=f'{tmpl.name} (Urgent)',
        )

        # Notify Amit urgently
        amit = self.env.ref('elegomotors_setup.user_ego_amit', raise_if_not_found=False)
        partner_ids = [amit.partner_id.id] if amit and amit.partner_id else []
        picking.message_post(
            body=Markup(
                f"<b>URGENT</b> Issue to Production for <b>{tmpl.name}</b> — "
                f"MO: <b>{production.name}</b>. "
                f"Please validate this picking as soon as possible."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    # ------------------------------------------------------------------
    # Pending MO query
    # ------------------------------------------------------------------

    @api.model
    def _get_pending_mos_for_model(self, tmpl):
        """Return confirmed, non-urgent MOs for this template that have no PI yet."""
        return self.env['mrp.production'].search([
            ('product_id.product_tmpl_id', '=', tmpl.id),
            ('state', '=', 'confirmed'),
            ('x_pi_urgent', '=', False),
            ('x_consolidated_picking_id', '=', False),
        ])

    # ------------------------------------------------------------------
    # Component classification
    # ------------------------------------------------------------------

    @api.model
    def _classify_components_elego_11(self, mos, tmpl):
        """Classify components for Elego 1.1 which has color-specific variant BOMs.

        Returns:
          {
            'color_groups': {
              'Red': [(product_rec, qty), ...],   # color-specific parts for Red
              'White': [...],
              ...
            },
            'common': [(product_rec, qty), ...],  # common parts summed across all MOs
          }
        """
        # Fetch all variant-specific BOMs for this template
        all_boms = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', tmpl.id),
            ('type', '=', 'normal'),
            ('product_id', '!=', False),
        ])

        if not all_boms:
            # Fallback to template BOM classification if no color BOMs found
            classified = self._classify_components_template_bom(mos, tmpl)
            return {'color_groups': {}, 'common': classified.get('common', [])}

        # Build product sets per BOM to identify color-specific vs common
        bom_product_sets = {}
        for bom in all_boms:
            bom_product_sets[bom.id] = set(bom.bom_line_ids.mapped('product_id.id'))

        all_product_ids = set()
        for pset in bom_product_sets.values():
            all_product_ids |= pset
        common_product_ids = all_product_ids.copy()
        for pset in bom_product_sets.values():
            common_product_ids &= pset
        color_specific_product_ids = all_product_ids - common_product_ids

        # Aggregate quantities from BOM lines × MO qty, grouped by (product, color)
        color_qtys = defaultdict(lambda: defaultdict(float))  # color → product_id → qty
        common_qtys = defaultdict(float)                       # product_id → qty
        product_cache = {}

        for mo in mos:
            if not mo.bom_id:
                continue
            mo_color = (mo.x_color or '').capitalize() or 'Unknown'
            for line in mo.bom_id.bom_line_ids:
                pid = line.product_id.id
                qty = line.product_qty * mo.product_qty
                product_cache[pid] = line.product_id
                if pid in color_specific_product_ids:
                    color_qtys[mo_color][pid] += qty
                else:
                    common_qtys[pid] += qty

        # Build ordered output: sort color groups alphabetically, products by BOM sequence
        color_groups = {}
        for color in sorted(color_qtys.keys()):
            color_groups[color] = [
                (product_cache[pid], qty)
                for pid, qty in sorted(color_qtys[color].items(), key=lambda x: x[0])
                if qty > 0
            ]

        common = [
            (product_cache[pid], qty)
            for pid, qty in sorted(common_qtys.items(), key=lambda x: x[0])
            if qty > 0
        ]

        return {'color_groups': color_groups, 'common': common}

    @api.model
    def _classify_components_template_bom(self, mos, tmpl):
        """Classify components for models with a single template-level BOM.

        All components are treated as common (no color distinction).
        Returns: {'common': [(product_rec, total_qty), ...]}
        """
        common_qtys = defaultdict(float)
        product_cache = {}

        for mo in mos:
            bom = mo.bom_id
            if not bom:
                # No BOM on MO — try to find template BOM as fallback
                bom = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', tmpl.id),
                    ('type', '=', 'normal'),
                    ('product_id', '=', False),
                ], limit=1)
            if not bom:
                continue
            for line in bom.bom_line_ids:
                pid = line.product_id.id
                common_qtys[pid] += line.product_qty * mo.product_qty
                product_cache[pid] = line.product_id

        common = [
            (product_cache[pid], qty)
            for pid, qty in sorted(common_qtys.items(), key=lambda x: x[0])
            if qty > 0
        ]
        return {'common': common}

    # ------------------------------------------------------------------
    # Picking builder
    # ------------------------------------------------------------------

    @api.model
    def _build_consolidated_pi(self, mos, issue_type, config, for_date):
        """Create one consolidated PI picking for the given MOs."""
        tmpl = self.env.ref(config['tmpl_ref'], raise_if_not_found=False)
        if not tmpl:
            return False

        if config['uses_color_boms']:
            classified = self._classify_components_elego_11(mos, tmpl)
        else:
            classified = self._classify_components_template_bom(mos, tmpl)

        return self._create_picking_from_classified(
            mos=mos,
            issue_type=issue_type,
            classified=classified,
            uses_color_boms=config['uses_color_boms'],
            origin=f"Daily PI — {config['label']} — {for_date}",
            model_key=config['model_key'],
            model_label=config['label'],
        )

    # ------------------------------------------------------------------
    # Batch PI (called from BatchMoWizard after confirming all MOs)
    # ------------------------------------------------------------------

    @api.model
    def _create_batch_pi(self, mos, batch_ref):
        """Create one consolidated PI for all MOs in a batch, across all models/colours.

        Builds section headers per model (and per colour for Elego 1.1), aggregates
        component quantities from BOMs, and links every MO to the single picking so
        the daily cron skips them.
        """
        issue_type = self.env.ref(
            'elegomotors_setup.picking_type_production_issue', raise_if_not_found=False
        )
        if not issue_type:
            return False

        # Build config lookup by template id
        config_by_tmpl = {}
        for config in self._get_bike_model_configs():
            tmpl = self.env.ref(config['tmpl_ref'], raise_if_not_found=False)
            if tmpl:
                config_by_tmpl[tmpl.id] = config

        section_header_product = self.env.ref(
            'elegomotors_setup.product_pi_section_header', raise_if_not_found=False
        )
        if not section_header_product:
            raise UserError(
                'PI Section Header product not found. '
                'Please upgrade the elegomotors_setup module.'
            )

        def _section(label):
            return {
                'name': label,
                'product_id': section_header_product.id,
                'product_uom': section_header_product.uom_id.id,
                'product_uom_qty': 0.0,
                'location_id': issue_type.default_location_src_id.id,
                'location_dest_id': issue_type.default_location_dest_id.id,
                'x_is_section_header': True,
                'x_section_label': label,
            }

        def _move(product, qty):
            return {
                'name': product.name,
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'product_uom_qty': qty,
                'location_id': issue_type.default_location_src_id.id,
                'location_dest_id': issue_type.default_location_dest_id.id,
            }

        # Group MOs by template, preserving the order they were created
        template_order = []
        template_mos = {}
        for mo in mos:
            tmpl_id = mo.product_id.product_tmpl_id.id
            if tmpl_id not in template_mos:
                template_order.append(mo.product_id.product_tmpl_id)
                template_mos[tmpl_id] = self.env['mrp.production']
            template_mos[tmpl_id] |= mo

        move_vals_list = []
        all_mo_count = len(mos)

        for tmpl in template_order:
            tmpl_mos = template_mos[tmpl.id]
            config = config_by_tmpl.get(tmpl.id)
            uses_color_boms = config['uses_color_boms'] if config else False
            model_label = config['label'] if config else tmpl.name
            mo_count = len(tmpl_mos)

            if uses_color_boms:
                classified = self._classify_components_elego_11(tmpl_mos, tmpl)
                color_groups = classified.get('color_groups', {})
                common = classified.get('common', [])

                for color, lines in color_groups.items():
                    if not lines:
                        continue
                    color_mo_count = sum(
                        1 for mo in tmpl_mos
                        if (mo.x_color or '').capitalize() == color
                    )
                    move_vals_list.append(_section(
                        f'{model_label} — {color} '
                        f'({color_mo_count} unit{"s" if color_mo_count != 1 else ""})'
                    ))
                    for product, qty in lines:
                        move_vals_list.append(_move(product, qty))

                if common:
                    move_vals_list.append(_section(
                        f'{model_label} — Common '
                        f'({mo_count} unit{"s" if mo_count != 1 else ""})'
                    ))
                    for product, qty in common:
                        move_vals_list.append(_move(product, qty))
            else:
                classified = self._classify_components_template_bom(tmpl_mos, tmpl)
                common = classified.get('common', [])
                if common:
                    move_vals_list.append(_section(
                        f'{model_label} — {mo_count} unit{"s" if mo_count != 1 else ""}'
                    ))
                    for product, qty in common:
                        move_vals_list.append(_move(product, qty))

        if not move_vals_list:
            _logger.warning(
                'EGO: No component moves for batch %s — no BOM data found. '
                'Skipping PI creation.',
                batch_ref,
            )
            return False

        picking = self.env['stock.picking'].create({
            'picking_type_id': issue_type.id,
            'location_id': issue_type.default_location_src_id.id,
            'location_dest_id': issue_type.default_location_dest_id.id,
            'origin': f'Batch PI — {batch_ref}',
            'x_pi_model_key': batch_ref,
            'x_consolidated_mo_ids': [(6, 0, mos.ids)],
            'move_ids': [(0, 0, v) for v in move_vals_list],
        })
        picking.action_confirm()

        # Link every MO to this picking so the daily cron skips them
        mos.write({'x_consolidated_picking_id': picking.id})

        amit = self.env.ref('elegomotors_setup.user_ego_amit', raise_if_not_found=False)
        partner_ids = [amit.partner_id.id] if amit and amit.partner_id else []
        model_names = ', '.join(t.name for t in template_order)
        picking.message_post(
            body=Markup(
                f"Batch Issue to Production — <b>{batch_ref}</b><br/>"
                f"<b>{all_mo_count}</b> MO{'s' if all_mo_count != 1 else ''} across: "
                f"<b>{model_names}</b>.<br/>"
                f"Please validate to issue materials to the production floor."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        _logger.info(
            'EGO: Created batch PI %s for %d MOs (%s) — batch ref %s.',
            picking.name, all_mo_count, model_names, batch_ref,
        )
        return picking

    @api.model
    def _create_picking_from_classified(
        self, mos, issue_type, classified, uses_color_boms,
        origin, model_key, model_label,
    ):
        """Create the actual stock.picking with section headers and aggregated moves."""
        section_header_product = self.env.ref(
            'elegomotors_setup.product_pi_section_header', raise_if_not_found=False
        )
        if not section_header_product:
            raise UserError(
                'PI Section Header product not found. '
                'Please upgrade the elegomotors_setup module.'
            )

        mo_ids = mos.ids if hasattr(mos, 'ids') else [mos.id]
        mo_count = len(mo_ids)

        move_vals_list = []

        def _section(label):
            return {
                'name': label,
                'product_id': section_header_product.id,
                'product_uom': section_header_product.uom_id.id,
                'product_uom_qty': 0.0,
                'location_id': issue_type.default_location_src_id.id,
                'location_dest_id': issue_type.default_location_dest_id.id,
                'x_is_section_header': True,
                'x_section_label': label,
            }

        def _move(product, qty):
            return {
                'name': product.name,
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'product_uom_qty': qty,
                'location_id': issue_type.default_location_src_id.id,
                'location_dest_id': issue_type.default_location_dest_id.id,
            }

        if uses_color_boms:
            color_groups = classified.get('color_groups', {})
            common = classified.get('common', [])

            for color, lines in color_groups.items():
                if not lines:
                    continue
                # Count MOs of this color
                color_mo_count = sum(
                    1 for mo in mos
                    if (mo.x_color or '').capitalize() == color
                )
                move_vals_list.append(_section(
                    f'{color} ({color_mo_count} unit{"s" if color_mo_count != 1 else ""})'
                ))
                for product, qty in lines:
                    move_vals_list.append(_move(product, qty))

            if common:
                move_vals_list.append(_section(
                    f'Common Components ({mo_count} total unit{"s" if mo_count != 1 else ""})'
                ))
                for product, qty in common:
                    move_vals_list.append(_move(product, qty))
        else:
            common = classified.get('common', [])
            if common:
                move_vals_list.append(_section(
                    f'{model_label} — {mo_count} unit{"s" if mo_count != 1 else ""}'
                ))
                for product, qty in common:
                    move_vals_list.append(_move(product, qty))

        if not move_vals_list:
            _logger.warning(
                'EGO: No component moves could be built for %s — no BOM data found. Skipping.',
                model_label,
            )
            return False

        picking = self.env['stock.picking'].create({
            'picking_type_id': issue_type.id,
            'location_id': issue_type.default_location_src_id.id,
            'location_dest_id': issue_type.default_location_dest_id.id,
            'origin': origin,
            'x_pi_model_key': model_key,
            'x_consolidated_mo_ids': [(6, 0, mo_ids)],
            'move_ids': [(0, 0, v) for v in move_vals_list],
        })
        picking.action_confirm()

        # Link each MO to this consolidated picking
        self.env['mrp.production'].browse(mo_ids).write(
            {'x_consolidated_picking_id': picking.id}
        )

        # Notify Amit
        amit = self.env.ref('elegomotors_setup.user_ego_amit', raise_if_not_found=False)
        partner_ids = [amit.partner_id.id] if amit and amit.partner_id else []
        picking.message_post(
            body=Markup(
                f"Consolidated Issue to Production generated for <b>{model_label}</b> — "
                f"<b>{mo_count}</b> MO{'s' if mo_count != 1 else ''}. "
                f"Please validate to issue materials to the production floor."
            ),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        return picking
