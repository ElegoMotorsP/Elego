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
    invoice_line_id = fields.Many2one('account.move.line', required=True, readonly=True)
    unit_index = fields.Integer(default=1, readonly=True)
    scanned_serial = fields.Char(string='Scan Serial No.')
    status = fields.Char(readonly=True)

    @api.onchange('scanned_serial')
    def _onchange_scanned_serial(self):
        serial = (self.scanned_serial or '').strip()
        if not serial:
            self.status = ''
            return
        product_tmpl = self.invoice_line_id.product_id.product_tmpl_id
        lot = self.env['stock.lot'].search(
            [('name', '=', serial),
             ('product_id.product_tmpl_id', '=', product_tmpl.id)],
            limit=1,
        )
        if not lot:
            lot = self.env['stock.lot'].search([('name', '=', serial)], limit=1)
        if not lot:
            self.status = 'Not found'
            return
        if lot.x_blacklisted:
            self.status = 'Blacklisted'
            return
        fg_location = self.env.ref(
            'elegomotors_setup.location_ego_fg', raise_if_not_found=False
        )
        if fg_location:
            quant = self.env['stock.quant'].search(
                [('lot_id', '=', lot.id),
                 ('location_id', 'child_of', fg_location.id),
                 ('quantity', '>', 0)],
                limit=1,
            )
            if not quant:
                self.status = 'Not in FG'
                return
        self.status = 'OK'


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
            product = line.invoice_line_id.product_id
            label = f'Unit #{line.unit_index} ({product.display_name})'

            if not serial:
                errors.append(f'{label}: Serial number not scanned.')
                continue

            lot = self.env['stock.lot'].search(
                [('name', '=', serial),
                 ('product_id.product_tmpl_id', '=', product.product_tmpl_id.id)],
                limit=1,
            )
            if not lot:
                lot = self.env['stock.lot'].search([('name', '=', serial)], limit=1)

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
