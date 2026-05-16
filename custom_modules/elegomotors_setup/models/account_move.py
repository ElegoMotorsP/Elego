# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class AccountMove(models.Model):
    _inherit = 'account.move'

    store_billing_readonly = fields.Boolean(
        compute='_compute_store_billing_readonly',
    )

    x_transport_name = fields.Char(string='Transporter Name')
    x_lr_number = fields.Char(string='LR Number')
    x_lr_date = fields.Date(string='LR Date')

    @api.depends_context('uid')
    def _compute_store_billing_readonly(self):
        is_store_billing = self.env.user.has_group(
            'elegomotors_setup.group_store_billing'
        )
        for record in self:
            record.store_billing_readonly = is_store_billing

    @api.model_create_multi
    def create(self, vals_list):
        if (
            not self.env.su
            and self.env.user.has_group(
                'elegomotors_setup.group_purchase_vendor_bill_viewer'
            )
        ):
            raise AccessError(
                'Purchase viewers cannot create new accounting entries. '
                'Ask Rajshri (Accounts) or Manohar (Admin) to create the bill.'
            )
        result = super().create(vals_list)
        for move in result:
            if move.move_type in ('out_invoice', 'out_refund'):
                move._append_ego_serial_to_lines()
        return result

    def action_post(self):
        """Also inject serials at confirm time — covers invoices created before delivery."""
        result = super().action_post()
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund'):
                move._append_ego_serial_to_lines()
        return result

    def action_refresh_ego_serials(self):
        """Manual refresh button — re-injects serial block on already-posted invoices."""
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue
            ego_tmpl = self.env.ref(
                'elegomotors_setup.tmpl_ego_scooter', raise_if_not_found=False
            )
            if not ego_tmpl:
                continue
            for line in move.invoice_line_ids:
                if not line.product_id or line.product_id.product_tmpl_id != ego_tmpl:
                    continue
                lot = move._find_ego_lot_for_line(line)
                if not lot:
                    continue
                serial_block = move._format_ego_serial_block(lot)
                if not serial_block:
                    continue
                # Strip any existing serial block and re-append fresh
                base_name = (line.name or '').split('\nChassis No.:')[0].split('\nVariant:')[0].rstrip()
                line.name = base_name + '\n' + serial_block

    def _append_ego_serial_to_lines(self):
        """Append chassis/component serial numbers to EGO-S1 invoice lines.
        Sequence: Chassis → Motor → Controller → Battery → Charger, then Variant line.
        Idempotent: skips lines that already have the serial block.
        """
        ego_tmpl = self.env.ref(
            'elegomotors_setup.tmpl_ego_scooter', raise_if_not_found=False
        )
        if not ego_tmpl:
            return
        for line in self.invoice_line_ids:
            if not line.product_id or line.product_id.product_tmpl_id != ego_tmpl:
                continue
            if 'Chassis No.:' in (line.name or ''):
                continue  # already injected
            lot = self._find_ego_lot_for_line(line)
            if not lot:
                continue
            serial_block = self._format_ego_serial_block(lot)
            if serial_block:
                line.name = (line.name or '') + '\n' + serial_block

    def _find_ego_lot_for_line(self, line):
        """Trace invoice line → EGO-S1 lot via three paths.

          1. sale_line_ids → sale order → done outgoing deliveries (standard flow).
          2. invoice_origin → SO name search (edge-case fallback).
          3. FG store quants — for proforma/invoices raised before delivery is done
             (bike already in FG stock but delivery not yet validated).
        """
        product = line.product_id

        def _lots_from_sale(sale):
            done_deliveries = sale.picking_ids.filtered(
                lambda p: p.state == 'done' and p.picking_type_code == 'outgoing'
            )
            return done_deliveries.mapped('move_line_ids').filtered(
                lambda ml: ml.product_id == product and ml.lot_id
            ).mapped('lot_id')

        # Path 1: sale_line_ids (standard)
        sale_lines = getattr(line, 'sale_line_ids', False)
        if sale_lines:
            lots = _lots_from_sale(sale_lines[0].order_id)
            if lots:
                return lots[0]

        # Path 2: invoice origin → SO name
        origin = self.invoice_origin or ''
        if origin:
            for so_name in [s.strip() for s in origin.split(',')]:
                sale = self.env['sale.order'].search(
                    [('name', '=', so_name)], limit=1
                )
                if sale:
                    lots = _lots_from_sale(sale)
                    if lots:
                        return lots[0]

        # Path 3: FG store quants — bike is in FG stock but delivery not yet done.
        # Matches product.product exactly so the correct variant's serial is returned.
        ego_tmpl = self.env.ref(
            'elegomotors_setup.tmpl_ego_scooter', raise_if_not_found=False
        )
        fg_location = self.env.ref(
            'elegomotors_setup.location_ego_fg', raise_if_not_found=False
        )
        if ego_tmpl and fg_location and product.product_tmpl_id == ego_tmpl:
            quants = self.env['stock.quant'].search(
                [
                    ('product_id', '=', product.id),
                    ('location_id', 'child_of', fg_location.id),
                    ('lot_id', '!=', False),
                    ('quantity', '>', 0),
                ],
                limit=1,
            )
            if quants:
                return quants.lot_id

        return False

    def _format_ego_serial_block(self, lot):
        """Build the serial annotation block:
        Line 1 — Chassis No. | Motor No. | Controller No. | Battery No. | Charger No.
        Line 2 — Variant: Color | Side Guards | Battery Type
        """
        parts = []
        if lot.name:
            parts.append(f'Chassis No.: {lot.name}')
        if lot.x_motor_serial:
            parts.append(f'Motor No.: {lot.x_motor_serial}')
        if lot.x_controller_serial:
            parts.append(f'Controller No.: {lot.x_controller_serial}')
        if lot.x_battery_serial:
            parts.append(f'Battery No.: {lot.x_battery_serial}')
        if lot.x_charger_serial:
            parts.append(f'Charger No.: {lot.x_charger_serial}')
        serial_line = '  |  '.join(parts) if parts else ''

        variant_line = ''
        if lot.product_id and lot.product_id.product_template_attribute_value_ids:
            variant_parts = [
                f'{ptav.attribute_id.name}: {ptav.name}'
                for ptav in lot.product_id.product_template_attribute_value_ids
            ]
            if variant_parts:
                variant_line = 'Variant: ' + '  |  '.join(variant_parts)

        if serial_line and variant_line:
            return serial_line + '\n' + variant_line
        return serial_line or variant_line
