# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class AccountMove(models.Model):
    _inherit = 'account.move'

    # True only for users in group_store_billing (Amit).
    # @api.depends_context('uid') ensures each user gets their own value —
    # the field is non-stored so it never persists or breaks other users' views.
    store_billing_readonly = fields.Boolean(
        compute='_compute_store_billing_readonly',
    )

    @api.depends_context('uid')
    def _compute_store_billing_readonly(self):
        is_store_billing = self.env.user.has_group(
            'elegomotors_setup.group_store_billing'
        )
        for record in self:
            record.store_billing_readonly = is_store_billing

    @api.model_create_multi
    def create(self, vals_list):
        # group_purchase_vendor_bill_viewer holders (Prashant) can read vendor
        # bills but must not create new accounting entries.
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
        # Req 8: inject EGO-S1 serial numbers into customer invoice line descriptions
        for move in result:
            if move.move_type in ('out_invoice', 'out_refund'):
                move._append_ego_serial_to_lines()
        return result

    def _append_ego_serial_to_lines(self):
        """Append chassis/component serial numbers to EGO-S1 invoice lines.
        Sequence: Chassis No. → Motor No. → Controller No. → Battery No. → Charger No.
        """
        ego_tmpl = self.env.ref(
            'elegomotors_setup.tmpl_ego_scooter', raise_if_not_found=False
        )
        if not ego_tmpl:
            return
        for line in self.invoice_line_ids:
            if not line.product_id or line.product_id.product_tmpl_id != ego_tmpl:
                continue
            lot = self._find_ego_lot_for_line(line)
            if not lot:
                continue
            serial_block = self._format_ego_serial_block(lot)
            if serial_block and serial_block not in (line.name or ''):
                line.name = (line.name or '') + '\n' + serial_block

    def _find_ego_lot_for_line(self, line):
        """Trace invoice line → sale order → done outgoing deliveries → EGO-S1 lot."""
        sale_lines = getattr(line, 'sale_line_ids', False)
        if not sale_lines:
            return False
        sale = sale_lines[0].order_id
        done_deliveries = sale.picking_ids.filtered(
            lambda p: p.state == 'done' and p.picking_type_code == 'outgoing'
        )
        lots = done_deliveries.mapped('move_line_ids').filtered(
            lambda ml: ml.product_id == line.product_id and ml.lot_id
        ).mapped('lot_id')
        return lots[:1] if lots else False

    def _format_ego_serial_block(self, lot):
        """Build the serial number annotation block in required sequence.
        Line 1: Chassis | Motor | Controller | Battery | Charger
        Line 2: Variant: Color | Battery Type | Side Guards (if product has variants)
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

        # Append variant attributes (Color, Battery Type, Side Guards, etc.) when present
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
