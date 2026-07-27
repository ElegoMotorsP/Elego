# -*- coding: utf-8 -*-
import re

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

    x_assigned_lot_ids = fields.Many2many(
        'stock.lot',
        'account_move_bike_lot_rel',
        'move_id',
        'lot_id',
        string='Assigned Bike Serials',
    )

    # Traceability columns shown in the invoice list and form
    x_so_ref = fields.Char(
        string='Sales Order',
        compute='_compute_so_delivery_info',
        store=False,
    )

    def _ego_gst_breakdown(self):
        """GST summary rows for the Tax Invoice report, grouped by GST rate.

        Returns a list of dicts: taxable value per rate with the CGST /
        SGST(UTGST) / IGST split (rates and amounts), plus a 'total' entry.
        Handles both the module's individual CGST/SGST/IGST percent taxes
        and l10n_in group taxes (flattened to their children).
        """
        self.ensure_one()
        groups = {}
        for line in self.invoice_line_ids:
            if line.display_type in ('line_section', 'line_note'):
                continue
            taxes = line.tax_ids
            if hasattr(taxes, 'flatten_taxes_hierarchy'):
                taxes = taxes.flatten_taxes_hierarchy()
            cgst = sgst = igst = other = 0.0
            for tax in taxes:
                if tax.amount_type != 'percent':
                    continue
                name = (tax.name or '').upper()
                if 'CGST' in name:
                    cgst += tax.amount
                elif 'SGST' in name or 'UTGST' in name:
                    sgst += tax.amount
                elif 'IGST' in name:
                    igst += tax.amount
                else:
                    other += tax.amount  # unnamed generic GST → IGST column
            igst += other
            rate = round(cgst + sgst + igst, 4)
            group = groups.setdefault(rate, {
                'rate': rate,
                'cgst_rate': cgst, 'sgst_rate': sgst, 'igst_rate': igst,
                'taxable': 0.0,
            })
            group['taxable'] += line.price_subtotal
        rows = []
        for rate in sorted(groups):
            g = groups[rate]
            g['cgst_amount'] = g['taxable'] * g['cgst_rate'] / 100.0
            g['sgst_amount'] = g['taxable'] * g['sgst_rate'] / 100.0
            g['igst_amount'] = g['taxable'] * g['igst_rate'] / 100.0
            g['total_tax'] = g['cgst_amount'] + g['sgst_amount'] + g['igst_amount']
            rows.append(g)
        return rows
    x_delivery_ref = fields.Char(
        string='Delivery Ref',
        compute='_compute_so_delivery_info',
        store=False,
    )
    x_serial_nos = fields.Char(
        string='Serial No(s)',
        compute='_compute_so_delivery_info',
        store=False,
    )

    @api.depends(
        'move_type',
        'invoice_origin',
        'invoice_line_ids',
        'invoice_line_ids.sale_line_ids',
    )
    def _compute_so_delivery_info(self):
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                move.x_so_ref = ''
                move.x_delivery_ref = ''
                move.x_serial_nos = ''
                continue

            # Collect linked SOs via invoice line → sale order link
            so_set = self.env['sale.order']
            for line in move.invoice_line_ids:
                for sol in getattr(line, 'sale_line_ids', []):
                    if sol.order_id:
                        so_set |= sol.order_id

            # Fallback: parse invoice_origin for SO name(s)
            if not so_set and move.invoice_origin:
                for name in [s.strip() for s in move.invoice_origin.split(',') if s.strip()]:
                    so = self.env['sale.order'].search([('name', '=', name)], limit=1)
                    if so:
                        so_set |= so

            delivery_set = self.env['stock.picking']
            serial_set = set()
            for so in so_set:
                done_deliveries = so.picking_ids.filtered(
                    lambda p: p.picking_type_code == 'outgoing' and p.state == 'done'
                )
                delivery_set |= done_deliveries
                for ml in done_deliveries.mapped('move_line_ids'):
                    if ml.lot_id:
                        serial_set.add(ml.lot_id.name)

            move.x_so_ref = ', '.join(sorted(so_set.mapped('name'))) if so_set else ''
            move.x_delivery_ref = ', '.join(sorted(delivery_set.mapped('name'))) if delivery_set else ''
            move.x_serial_nos = ', '.join(sorted(serial_set)) if serial_set else ''

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
                # Preferred path: serials scanned by the Store on the delivery.
                # The legacy name-block injection below no-ops when lots were
                # synced (it skips when x_assigned_lot_ids is set).
                move._sync_assigned_lots_from_deliveries()
                move._append_ego_serial_to_lines()
        return result

    def _sync_assigned_lots_from_deliveries(self):
        """Pull the bike serials scanned by the Store on the SO's validated
        deliveries into x_assigned_lot_ids (rendered as Page 2 of the Tax
        Invoice). This replaces the manual invoice-side scanning by Accounts.
        Returns True when at least one invoice received lots."""
        synced = False
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue
            bike_tmpls = move._get_bike_templates()
            if not bike_tmpls:
                continue
            sales = self.env['sale.order']
            if 'sale_line_ids' in move.invoice_line_ids._fields:
                sales = move.invoice_line_ids.sale_line_ids.order_id
            if not sales and move.invoice_origin:
                sales = self.env['sale.order'].search(
                    [('name', '=', move.invoice_origin)], limit=1
                )
            if not sales:
                continue
            lots = sales.picking_ids.filtered(
                lambda p: p.state == 'done' and p.picking_type_code == 'outgoing'
            ).move_line_ids.filtered(
                lambda ml: ml.lot_id
                and ml.product_id.product_tmpl_id in bike_tmpls
                and ml.qty_done > 0
            ).lot_id
            if lots:
                move.x_assigned_lot_ids = [(6, 0, lots.ids)]
                move._refresh_serial_blocks_from_lots()
                synced = True
        return synced

    def action_refresh_ego_serials(self):
        """Manual refresh button — re-injects serial block on already-posted invoices."""
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue
            # Serials already assigned from the delivery scan (or wizard):
            # details live on Page 2 of the report — keep line names clean
            # instead of injecting the serial text block.
            if move.x_assigned_lot_ids:
                move._refresh_serial_blocks_from_lots()
                continue
            bike_tmpls = move._get_bike_templates()
            if not bike_tmpls:
                continue
            for line in move.invoice_line_ids:
                if not line.product_id or line.product_id.product_tmpl_id not in bike_tmpls:
                    continue
                qty = max(1, int(line.quantity))
                lots = move._find_ego_lots_for_line(line, qty=qty)
                if not lots:
                    continue
                if len(lots) == 1:
                    serial_block = move._format_ego_serial_block(lots[0])
                else:
                    serial_block = '\n'.join(
                        move._format_ego_serial_block(lot, number=i)
                        for i, lot in enumerate(lots, 1)
                    )
                if not serial_block:
                    continue
                # Strip any existing serial block then re-append fresh
                base_name = (line.name or '')
                for marker in ('\nChassis No', '\nSerial No.', '\n1 :', '\nVariant:'):
                    base_name = base_name.split(marker)[0]
                base_name = base_name.rstrip()
                line.name = base_name + '\n' + serial_block

    def action_open_bike_scan_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assign Bike Serials',
            'res_model': 'elegomotors.invoice.bike.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_invoice_id': self.id},
        }

    def _refresh_serial_blocks_from_lots(self):
        """Strip any serial block from line.name for bike lines — serial details live on
        Page 2 of the custom report via x_assigned_lot_ids, not in the description."""
        bike_tmpls = self._get_bike_templates()
        if not bike_tmpls:
            return
        for move in self:
            for line in move.invoice_line_ids:
                if not line.product_id or line.product_id.product_tmpl_id not in bike_tmpls:
                    continue
                base_name = (line.name or '')
                for marker in ('\nChassis No', '\nSerial No.', '\n1 :', '\nVariant:'):
                    base_name = base_name.split(marker)[0]
                base_name = base_name.rstrip()
                if base_name != (line.name or '').rstrip():
                    line.name = base_name

    def _get_bike_templates(self):
        """Return recordset of all ElegoMotors bike product templates."""
        refs = [
            'elegomotors_setup.tmpl_ego_scooter',
            'elegomotors_setup.tmpl_elego_11',
            'elegomotors_setup.tmpl_elego_12',
            'elegomotors_setup.tmpl_elego_20p',
            'elegomotors_setup.tmpl_elego_30',
        ]
        result = self.env['product.template']
        for ref in refs:
            t = self.env.ref(ref, raise_if_not_found=False)
            if t:
                result |= t
        return result

    def _append_ego_serial_to_lines(self):
        """Append serial/chassis/component numbers to ElegoMotors bike invoice lines.
        Skips if lots are already assigned via the scan wizard (x_assigned_lot_ids set) —
        in that case serial details are shown on Page 2 of the report, not in line.name.
        Idempotent: skips lines that already have the serial block.
        """
        if self.x_assigned_lot_ids:
            return
        bike_tmpls = self._get_bike_templates()
        if not bike_tmpls:
            return
        for line in self.invoice_line_ids:
            if not line.product_id or line.product_id.product_tmpl_id not in bike_tmpls:
                continue
            name = line.name or ''
            if 'Chassis No' in name:
                continue  # already injected
            qty = max(1, int(line.quantity))
            lots = self._find_ego_lots_for_line(line, qty=qty)
            if not lots:
                continue
            if len(lots) == 1:
                block = self._format_ego_serial_block(lots[0])
            else:
                block = '\n'.join(
                    self._format_ego_serial_block(lot, number=i)
                    for i, lot in enumerate(lots, 1)
                )
            if block:
                line.name = name + '\n' + block

    def _find_ego_lots_for_line(self, line, qty=1):
        """Return up to `qty` lots linked to this invoice line."""
        product = line.product_id
        qty = max(1, int(qty))

        def _lots_from_sale(sale):
            done_deliveries = sale.picking_ids.filtered(
                lambda p: p.state == 'done' and p.picking_type_code == 'outgoing'
            )
            return done_deliveries.mapped('move_line_ids').filtered(
                lambda ml: ml.product_id == product and ml.lot_id
            ).mapped('lot_id')

        # Path 0: manually scanned and assigned via wizard
        if self.x_assigned_lot_ids:
            assigned = self.x_assigned_lot_ids.filtered(
                lambda l: l.product_id.product_tmpl_id == product.product_tmpl_id
            )
            if assigned:
                return assigned[:qty]

        # Path 1: sale_line_ids (standard)
        sale_lines = getattr(line, 'sale_line_ids', False)
        if sale_lines:
            lots = _lots_from_sale(sale_lines[0].order_id)
            if lots:
                return lots[:qty]

        # Path 2: invoice origin → SO name
        for so_name in [s.strip() for s in (self.invoice_origin or '').split(',') if s.strip()]:
            sale = self.env['sale.order'].search([('name', '=', so_name)], limit=1)
            if sale:
                lots = _lots_from_sale(sale)
                if lots:
                    return lots[:qty]

        return self.env['stock.lot']

    def _find_ego_lot_for_line(self, line):
        lots = self._find_ego_lots_for_line(line, qty=1)
        return lots[0] if lots else False

    def _ego_battery_type_display(self, lot):
        """Descriptive Battery Type text for the Vehicle Serial Details
        table. Prefers the combo Battery Pack product actually sold on this
        invoice (the x_is_combo_item line whose product name contains
        "battery") — that reflects what this specific customer/order really
        got. Falls back to the manufacturing-recorded type on the lot only
        when the invoice has no combo battery line: production is
        produce-to-stock and FIFO-allocated to orders only at delivery/scan
        time (see global_scan_wizard.py), so a given bike's lot may carry
        whatever battery type the production planner entered when the MO
        was created — which can differ from what this particular order
        combo actually included. Otherwise the column just prints '-' for
        any bike with neither a combo line nor a battery type recorded.
        For Lead Acid packs only, appends a "(12V x N)" cell-count hint
        parsed from the battery's voltage (e.g. 60V -> 5, 72V -> 6) — these
        packs are physically built from that many 12V cells (see
        battery_kit_data.xml's phantom BOMs: 5 cells for 60V32Ah, 6 for
        72V32Ah). Lithium packs are sealed single units, not built from
        12V sub-cells, so no cell count is shown for them.
        """
        self.ensure_one()
        text = ''
        battery_line = self.invoice_line_ids.filtered(
            lambda l: l.x_is_combo_item
            and 'battery' in (l.product_id.name or '').lower()
        )[:1]
        if battery_line:
            text = battery_line.product_id.display_name
        if not text:
            text = lot.x_battery_type
        if not text:
            return '-'
        if 'lead' not in text.lower():
            return text
        match = re.search(r'(\d+)\s*V', text, re.IGNORECASE)
        if match:
            cells = int(match.group(1)) // 12
            if cells:
                return f'{text} (12V x {cells})'
        return text

    def _format_ego_serial_block(self, lot, number=None):
        """Build the serial annotation block appended to the invoice line name.

        Format: [N : ]Serial No. : S, Chassis No : X, Motor No : Y, Controller : Z[, Battery No : B][, Charger No : C]
        Second line: Variant: Color: Red  |  Battery: Lithium 60V30Ah
        """
        parts = []
        # Bike serial first — the primary traceability key.
        # Spelled "Serial No." to match the strip markers used when
        # rebuilding/removing the block, keeping the injection idempotent.
        if lot.name:
            parts.append(f'Serial No. : {lot.name}')
        if lot.x_chassis_serial:
            parts.append(f'Chassis No : {lot.x_chassis_serial}')
        if lot.x_motor_serial:
            parts.append(f'Motor No : {lot.x_motor_serial}')
        if lot.x_controller_serial:
            parts.append(f'Controller : {lot.x_controller_serial}')
        if lot.x_battery_serial:
            parts.append(f'Battery No : {lot.x_battery_serial}')
        if lot.x_charger_serial:
            parts.append(f'Charger No : {lot.x_charger_serial}')
        if not parts:
            return ''
        serial_line = ', '.join(parts)
        if number is not None:
            serial_line = f'{number} : {serial_line}'

        variant_parts = []
        if lot.x_color:
            variant_parts.append(f'Color: {lot.x_color.capitalize()}')
        elif lot.product_id:
            for ptav in lot.product_id.product_template_attribute_value_ids:
                if ptav.attribute_id.name == 'Color':
                    variant_parts.append(f'Color: {ptav.name}')
        # Same priority as _ego_battery_type_display(): prefer the combo
        # Battery Pack actually sold on this invoice over the lot's own
        # recorded x_battery_type, which reflects whatever the production
        # planner picked when the MO was created — not necessarily what
        # this specific order's combo included (production is
        # produce-to-stock, FIFO-allocated to orders only at scan time).
        battery_line = self.invoice_line_ids.filtered(
            lambda l: l.x_is_combo_item
            and 'battery' in (l.product_id.name or '').lower()
        )[:1]
        battery_text = battery_line.product_id.display_name if battery_line else lot.x_battery_type
        if battery_text:
            variant_parts.append(f'Battery: {battery_text}')
        if variant_parts:
            return serial_line + '\nVariant: ' + '  |  '.join(variant_parts)
        return serial_line
