# -*- coding: utf-8 -*-
from odoo import api, fields, models


class GeneratePiWizard(models.TransientModel):
    """Wizard triggered by the 'Generate Daily PIs' menu item.

    Calls ConsolidatedPiGenerator.generate_daily_pis(), displays a summary
    of the newly created pickings, and offers a button to open them.
    """

    _name = 'elegomotors.generate.pi.wizard'
    _description = 'Generate Daily Issue-to-Production Pickings'

    state = fields.Selection([
        ('ready', 'Ready'),
        ('done', 'Done'),
    ], default='ready', readonly=True)

    result_message = fields.Text(string='Result', readonly=True)
    picking_ids = fields.Many2many(
        'stock.picking',
        string='Generated Pickings',
        readonly=True,
    )
    picking_count = fields.Integer(
        compute='_compute_picking_count',
        string='# Pickings Created',
    )

    @api.depends('picking_ids')
    def _compute_picking_count(self):
        for rec in self:
            rec.picking_count = len(rec.picking_ids)

    def action_generate(self):
        self.ensure_one()
        # Find pickings before generation to detect which are new
        existing_ids = set(
            self.env['stock.picking'].search([
                ('x_pi_model_key', '!=', False),
                ('state', 'not in', ('done', 'cancel')),
            ]).ids
        )

        count = self.env['elegomotors.consolidated.pi.generator'].generate_daily_pis()

        new_pickings = self.env['stock.picking'].search([
            ('x_pi_model_key', '!=', False),
            ('state', 'not in', ('done', 'cancel')),
            ('id', 'not in', list(existing_ids)),
        ])

        if count == 0:
            msg = 'No new consolidated PIs were created. All pending MOs are either already assigned to a PI, marked urgent, or no confirmed MOs exist.'
        elif count == 1:
            msg = f'1 consolidated PI was created successfully.'
        else:
            msg = f'{count} consolidated PIs were created successfully.'

        self.write({
            'state': 'done',
            'result_message': msg,
            'picking_ids': [(6, 0, new_pickings.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Daily Issue to Production Pickings',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.picking_ids.ids)],
            'target': 'current',
        }
