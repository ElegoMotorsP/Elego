# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class InvoiceBikeScanWizardLine(models.TransientModel):
    _name = 'elegomotors.invoice.bike.scan.wizard.line'
    _description = 'Invoice Bike Scan Wizard Line'
    _order = 'invoice_line_id, unit_index'

    wizard_id = fields.Many2one(
        'elegomotors.invoice.bike.scan.wizard',
        required=True,
        ondelete='cascade',
    )
    invoice_line_id = fields.Many2one('account.move.line', required=True)
    product_id = fields.Many2one(
        'product.product',
        related='invoice_line_id.product_id',
        store=False,
        readonly=True,
    )
    unit_index = fields.Integer(default=1)
    scanned_serial = fields.Char(string='Scan Serial No.')
    lot_id = fields.Many2one(
        'stock.lot',
        string='Resolved Lot',
        compute='_compute_lot_id',
        store=False,
    )
    status = fields.Char(compute='_compute_lot_id', store=False)

    @api.depends('scanned_serial', 'product_id')
    def _compute_lot_id(self):
        fg_location = self.env.ref(
            'elegomotors_setup.location_ego_fg', raise_if_not_found=False
        )
        for line in self:
            serial = (line.scanned_serial or '').strip()
            if not serial:
                line.lot_id = False
                line.status = ''
                continue
            lot = self.env['stock.lot'].search(
                [('name', '=', serial),
                 ('product_id.product_tmpl_id', '=',
                  line.product_id.product_tmpl_id.id)],
                limit=1,
            )
            if not lot:
                # Try without product filter — serial may be globally unique
                lot = self.env['stock.lot'].search(
                    [('name', '=', serial)], limit=1
                )
            if not lot:
                line.lot_id = False
                line.status = 'Not found'
                continue
            if lot.x_blacklisted:
                line.lot_id = lot
                line.status = 'Blacklisted'
                continue
            if fg_location:
                quant = self.env['stock.quant'].search(
                    [('lot_id', '=', lot.id),
                     ('location_id', 'child_of', fg_location.id),
                     ('quantity', '>', 0)],
                    limit=1,
                )
                if not quant:
                    line.lot_id = lot
                    line.status = 'Not in FG'
                    continue
            line.lot_id = lot
            line.status = 'OK'


class InvoiceBikeScanWizard(models.TransientModel):
    _name = 'elegomotors.invoice.bike.scan.wizard'
    _description = 'Assign Bike Serials to Invoice'

    invoice_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        'elegomotors.invoice.bike.scan.wizard.line',
        'wizard_id',
        string='Bike Units',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        invoice_id = res.get('invoice_id') or self.env.context.get('default_invoice_id')
        if not invoice_id:
            return res
        invoice = self.env['account.move'].browse(invoice_id)
        bike_tmpls = invoice._get_bike_templates()
        lines = []
        for inv_line in invoice.invoice_line_ids:
            if not inv_line.product_id:
                continue
            if inv_line.product_id.product_tmpl_id not in bike_tmpls:
                continue
            qty = max(1, int(inv_line.quantity))
            for i in range(1, qty + 1):
                lines.append((0, 0, {
                    'invoice_line_id': inv_line.id,
                    'unit_index': i,
                    'scanned_serial': '',
                }))
        if 'line_ids' in fields_list:
            res['line_ids'] = lines
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError('No bike lines to assign. Invoice may not contain bike products.')

        fg_location = self.env.ref(
            'elegomotors_setup.location_ego_fg', raise_if_not_found=False
        )
        resolved_lots = self.env['stock.lot']
        errors = []

        for line in self.line_ids:
            serial = (line.scanned_serial or '').strip()
            label = f'Unit #{line.unit_index} ({line.product_id.display_name})'

            if not serial:
                errors.append(f'{label}: Serial number not scanned.')
                continue

            lot = self.env['stock.lot'].search(
                [('name', '=', serial),
                 ('product_id.product_tmpl_id', '=',
                  line.product_id.product_tmpl_id.id)],
                limit=1,
            )
            if not lot:
                lot = self.env['stock.lot'].search(
                    [('name', '=', serial)], limit=1
                )

            if not lot:
                errors.append(f'{label}: Serial "{serial}" not found in the system.')
                continue

            if lot.x_blacklisted:
                errors.append(
                    f'{label}: Serial "{serial}" is blacklisted (QC failed). '
                    'Use a different unit.'
                )
                continue

            if fg_location:
                quant = self.env['stock.quant'].search(
                    [('lot_id', '=', lot.id),
                     ('location_id', 'child_of', fg_location.id),
                     ('quantity', '>', 0)],
                    limit=1,
                )
                if not quant:
                    errors.append(
                        f'{label}: Serial "{serial}" is not currently available '
                        'in Finished Goods store.'
                    )
                    continue

            if lot in resolved_lots:
                errors.append(
                    f'{label}: Serial "{serial}" is assigned more than once in this invoice.'
                )
                continue

            resolved_lots |= lot

        if errors:
            raise UserError('\n'.join(errors))

        self.invoice_id.x_assigned_lot_ids = [(6, 0, resolved_lots.ids)]
        self.invoice_id._refresh_serial_blocks_from_lots()
        return {'type': 'ir.actions.act_window_close'}
