# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpDailyProductionPlan(models.Model):
    """One record per product variant defining how many units to manufacture daily.

    The cron job (and the manual 'Create Today's MOs' action) iterate over all
    active plan lines and create one Manufacturing Order per variant,
    skipping any variant that already has an MO created today.
    """

    _name = 'mrp.daily.production.plan'
    _description = 'Daily Manufacturing Production Plan'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    product_variant_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        required=True,
        domain=[('product_tmpl_id.name', 'ilike', 'EGO-S1')],
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        related='product_variant_id.product_tmpl_id',
        store=True,
        readonly=True,
    )
    planned_qty = fields.Integer(
        string='Daily Qty',
        default=1,
        required=True,
    )
    active = fields.Boolean(default=True)

    def action_create_daily_mos(self):
        """Create one MO per active plan line for today.

        Skips variants that already have an MO created today to prevent duplicates
        when triggered multiple times (e.g., cron + manual button on same day).
        """
        today = fields.Date.today()
        for plan in self.filtered('active'):
            existing = self.env['mrp.production'].search([
                ('product_id', '=', plan.product_variant_id.id),
                ('create_date', '>=', today),
            ], limit=1)
            if existing:
                continue
            bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', plan.product_variant_id.product_tmpl_id.id),
            ], limit=1)
            self.env['mrp.production'].create({
                'product_id': plan.product_variant_id.id,
                'product_qty': plan.planned_qty,
                'bom_id': bom.id if bom else False,
            })

    @api.model
    def _create_initial_plans(self):
        """Seed default daily plan records for each EGO-S1 color variant.

        Called once via <function> in cron_data.xml (noupdate=1 block so it runs
        only on first install). Managers can adjust planned quantities afterward.
        """
        tmpl = self.env['product.template'].search(
            [('name', '=', 'ElegoMotors EV Scooter EGO-S1')], limit=1
        )
        if not tmpl:
            return

        default_qtys = {'Black': 5, 'White': 3, 'Blue': 2, 'Red': 2}
        for variant in tmpl.product_variant_ids:
            color_values = variant.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_id.name == 'Color'
            )
            if not color_values:
                continue
            color_name = color_values[0].name
            planned_qty = default_qtys.get(color_name, 1)
            existing = self.search([('product_variant_id', '=', variant.id)], limit=1)
            if not existing:
                self.create({
                    'product_variant_id': variant.id,
                    'planned_qty': planned_qty,
                })
