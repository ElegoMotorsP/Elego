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
            bike_tmpls = move._get_bike_templates()
            if not bike_tmpls:
                continue
            for line in move.invoice_line_ids:
                if not line.product_id or line.product_id.product_tmpl_id not in bike_tmpls:
                    continue
                lot = move._find_ego_lot_for_line(line)
                if not lot:
                    continue
                serial_block = move._format_ego_serial_block(lot)
                if not serial_block:
                    continue
                # Strip any existing serial block then re-append fresh
                base_name = (line.name or '')
                for marker in ('\nSerial No.:', '\nChassis No.:', '\nVariant:'):
                    base_name = base_name.split(marker)[0]
                base_name = base_name.rstrip()
                line.name = base_name + '\n' + serial_block

    def _get_bike_templates(self):
        """Return recordset of all ElegoMotors bike product templates."""
        refs = [
            'elegomotors_setup.tmpl_ego_scooter',
            'elegomotors_setup.tmpl_elego_11',
            'elegomotors_setup.tmpl_elego_12',
            'elegomotors_setup.tmpl_elego_20p',
        ]
        result = self.env['product.template']
        for ref in refs:
            t = self.env.ref(ref, raise_if_not_found=False)
            if t:
                result |= t
        return result

    def _append_ego_serial_to_lines(self):
        """Append serial/chassis/component numbers to ElegoMotors bike invoice lines.
        Idempotent: skips lines that already have the serial block.
        """
        bike_tmpls = self._get_bike_templates()
        if not bike_tmpls:
            return
        for line in self.invoice_line_ids:
            if not line.product_id or line.product_id.product_tmpl_id not in bike_tmpls:
                continue
            name = line.name or ''
            if 'Serial No.:' in name or 'Chassis No.:' in name:
                continue  # already injected
            lot = self._find_ego_lot_for_line(line)
            if not lot:
                continue
            serial_block = self._format_ego_serial_block(lot)
            if serial_block:
                line.name = name + '\n' + serial_block

    def _find_ego_lot_for_line(self, line):
        """Trace invoice line → bike lot via three paths.

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

        # Path 3: FG store quants — bike is in stock but delivery not yet done.
        bike_tmpls = self._get_bike_templates()
        fg_location = self.env.ref(
            'elegomotors_setup.location_ego_fg', raise_if_not_found=False
        )
        if bike_tmpls and fg_location and product.product_tmpl_id in bike_tmpls:
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
        """Build the serial annotation block appended to the invoice line name.

        Line 1: Serial No. | Chassis No. | Motor No. | Controller No. | Battery No. | Charger No.
        Line 2: Variant: Color | Battery Type
        """
        parts = []
        if lot.name:
            parts.append(f'Serial No.: {lot.name}')
        if lot.x_chassis_serial:
            parts.append(f'Chassis No.: {lot.x_chassis_serial}')
        if lot.x_motor_serial:
            parts.append(f'Motor No.: {lot.x_motor_serial}')
        if lot.x_controller_serial:
            parts.append(f'Controller No.: {lot.x_controller_serial}')
        if lot.x_battery_serial:
            parts.append(f'Battery No.: {lot.x_battery_serial}')
        if lot.x_charger_serial:
            parts.append(f'Charger No.: {lot.x_charger_serial}')
        serial_line = '  |  '.join(parts) if parts else ''

        variant_parts = []
        if lot.x_color:
            variant_parts.append(f'Color: {lot.x_color.capitalize()}')
        elif lot.product_id:
            for ptav in lot.product_id.product_template_attribute_value_ids:
                if ptav.attribute_id.name == 'Color':
                    variant_parts.append(f'Color: {ptav.name}')
        if lot.x_battery_type:
            variant_parts.append(f'Battery: {lot.x_battery_type}')
        variant_line = ('Variant: ' + '  |  '.join(variant_parts)) if variant_parts else ''

        if serial_line and variant_line:
            return serial_line + '\n' + variant_line
        return serial_line or variant_line
