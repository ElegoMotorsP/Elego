import io
import json
from odoo import fields, models, api
from odoo.tools import json_default
import logging

_logger = logging.getLogger(__name__)

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class VehicleTrackingXlsReport(models.TransientModel):
    _name = "vtr.xls.report"
    _description = "Vehicle Tracking Register Report V3"

    # sales_invoice_date_start = fields.Date(string="From Date")
    # sales_invoice_date_end = fields.Date(string="To Date")
    # customer_ids = fields.Many2many('res.partner', string="Customers")
    # invoice_ids = fields.Many2many('account.move', string="Invoices")
    # product_ids = fields.Many2many('product.product', string="Products")
    # location_ids = fields.Many2many('stock.location', string="Locations")

    # Filters
    sales_invoice_date_start = fields.Date(string="Sales Date From")
    sales_invoice_date_end = fields.Date(string="Sales Date To")
    customer_ids = fields.Many2many('res.partner', string="Customer(s)", domain=[
                                    ('customer_rank', '>', 0)])
    invoice_ids = fields.Many2many('account.move', string="Invoices", domain=[
                                   ('move_type', '=', 'out_invoice'), ('state', '=', 'posted')])
    product_ids = fields.Many2many('product.product', string="Items", domain=[
                                   ('sale_ok', '=', True)])
    location_ids = fields.Many2many(
        'stock.location', string="Delivery Locations", domain=[('usage', '=', 'customer')])

    # ---------------- Onchange handlers to keep filters in sync ----------------
    @api.onchange('customer_ids')
    def _onchange_customer_ids(self):
        if not self.customer_ids:
            # reset invoices and products to empty (means all)
            self.invoice_ids = [(6, 0, [])]
            self.product_ids = [(6, 0, [])]
            return
        # domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('partner_id', 'in', self.customer_ids.ids)]
        # invoices = self.env['account.move'].search(domain)
        # self.invoice_ids = [(6, 0, invoices.ids)]
        # prod_ids = invoices.mapped('invoice_line_ids.product_id').ids
        # self.product_ids = [(6, 0, prod_ids)]

    @api.onchange('invoice_ids')
    def _onchange_invoice_ids(self):
        if not self.invoice_ids:
            # reset customers/products if invoice cleared
            return
        # customers = self.invoice_ids.mapped('partner_id').ids
        # prods = self.invoice_ids.mapped('invoice_line_ids.product_id').ids
        # self.customer_ids = [(6, 0, customers)]
        # self.product_ids = [(6, 0, prods)]

    @api.onchange('product_ids')
    def _onchange_product_ids(self):
        if not self.product_ids:
            return
        # invoices = self.env['account.move'].search([
        #     ('move_type', '=', 'out_invoice'),
        #     ('state', '=', 'posted'),
        #     ('invoice_line_ids.product_id', 'in', self.product_ids.ids),
        # ])
        # self.invoice_ids = [(6, 0, invoices.ids)]
        # self.customer_ids = [(6, 0, invoices.mapped('partner_id').ids)]

    @api.onchange('location_ids')
    def _onchange_location_ids(self):
        # keep invoices filtered by delivery location if selected
        if not self.location_ids:
            return
        # find pickings to get related invoices (via sale orders)
        # pickings = self.env['stock.picking'].search([('location_dest_id', 'in', self.location_ids.ids)])
        # sale_orders = pickings.mapped('sale_id')
        # invoices = sale_orders.mapped('invoice_ids').filtered(lambda inv: inv.move_type == 'out_invoice' and inv.state == 'posted')
        # self.invoice_ids = [(6, 0, invoices.ids)]
        # self.customer_ids = [(6, 0, invoices.mapped('partner_id').ids)]
        # self.product_ids = [(6, 0, invoices.mapped('invoice_line_ids.product_id').ids)]

    # ---------------- Export action ----------------
    def export_xls(self):
        self.ensure_one()
        data = {
            'wizard_id': self.id,
            'sales_invoice_date_start': str(self.sales_invoice_date_start) if self.sales_invoice_date_start else False,
            'sales_invoice_date_end': str(self.sales_invoice_date_end) if self.sales_invoice_date_end else False,
            'customer_ids': self.customer_ids.ids,
            'invoice_ids': self.invoice_ids.ids,
            'product_ids': self.product_ids.ids,
            'location_ids': self.location_ids.ids,
        }
        return {
            'type': 'ir.actions.report',
            'data': {
                'model': 'vtr.xls.report',
                'options': json.dumps(data, default=json_default),
                'output_format': 'xlsx',
                'report_name': 'Vehicle Tracking Register V3',
            },
            'report_type': 'veh_tracking_xlsx',
        }

    # ---------------- Main report generator ----------------
    def get_xlsx_report(self, data, response):
        _logger.info("Vehicle XLS filters: %s", data)
        wiz = self.browse(data.get('wizard_id')) if data.get(
            'wizard_id') else self

        # Read filters (either from data or wizard)
        start_date = fields.Date.from_string(data.get('sales_invoice_date_start')) if data.get(
            'sales_invoice_date_start') else wiz.sales_invoice_date_start
        end_date = fields.Date.from_string(data.get('sales_invoice_date_end')) if data.get(
            'sales_invoice_date_end') else wiz.sales_invoice_date_end
        customer_ids = data.get('customer_ids') or wiz.customer_ids.ids
        invoice_ids = data.get('invoice_ids') or wiz.invoice_ids.ids
        product_ids = data.get('product_ids') or wiz.product_ids.ids
        location_ids = data.get('location_ids') or wiz.location_ids.ids

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Vehicle Tracking Register')

        fmt_title = workbook.add_format(
            {'bold': True, 'font_size': 14, 'align': 'center'})
        fmt_header = workbook.add_format(
            {'bold': True, 'bg_color': '#D9D9D9', 'border': 1, 'align': 'center'})
        fmt_text = workbook.add_format({'font_size': 10, 'border': 1})
        fmt_date = workbook.add_format(
            {'num_format': 'dd-mmm-yyyy', 'align': 'center', 'border': 1})

        sheet.merge_range(
            'A1:R1', 'Vehicle Tracking Register Report', fmt_title)

        # Filter summary
        filters = []
        if start_date and end_date:
            filters.append(f"Invoice Date: {start_date} → {end_date}")
        if customer_ids:
            comps = self.env['res.partner'].browse(customer_ids).mapped('name')
            filters.append("Customer(s): " + ', '.join(comps))
        if invoice_ids:
            invs = self.env['account.move'].browse(invoice_ids).mapped('name')
            filters.append("Invoices: " + ', '.join(invs))
        if product_ids:
            prods = self.env['product.product'].browse(
                product_ids).mapped('name')
            filters.append("Items: " + ', '.join(prods))
        if location_ids:
            locs = self.env['stock.location'].browse(
                location_ids).mapped('name')
            filters.append("Locations: " + ', '.join(locs))
        sheet.merge_range('A2:R2', '; '.join(filters)
                          if filters else 'No Filters', fmt_text)

        headers = [
            'Item (SN)', 'Model Name', 'Part No', 'Color',
            'Chassis No', 'Motor No', 'Battery SN', 'Controller SN',
            'Charger SN', 'Converter SN',
            'QAFG Date', 'QAFG No', 'Picking Slip Date', 'Picking Slip No',
            'Sales Invoice Date', 'Sales Invoice No', 'Customer Name', 'Customer Location'
        ]
        for col, name in enumerate(headers):
            sheet.write(4, col, name, fmt_header)

        row = 5

        # Build lot domain based on product and customers and location
        lot_domain = [('product_id.tracking', '=', 'serial')]
        if product_ids:
            lot_domain.append(('product_id', 'in', product_ids))
        if customer_ids or location_ids or invoice_ids:
            # we'll filter by invoices/customers later per lot; still fetch candidate lots
            pass
        chassis_lots = self.env['stock.lot'].search(lot_domain)

        for chassis in chassis_lots:
            # Find MO producing this lot (finished product)
            mo_move = self.env['stock.move'].search([
                ('lot_ids', 'in', chassis.id),
                ('product_id', '=', chassis.product_id.id),
                ('state', '=', 'done'),
                ('production_id', '!=', False)
            ], limit=1, order='date desc')
            mo = mo_move.production_id

            # Delivery move line and related sale / invoices
            delivery_move_line = self.env['stock.move.line'].search([
                ('lot_id', '=', chassis.id),
                ('state', '=', 'done'),
                ('move_id.picking_code', '=', 'outgoing'),
            ], limit=1, order='date desc')

            sale_order = delivery_move_line.move_id.sale_line_id.order_id if delivery_move_line.move_id.sale_line_id else None
            invoices = sale_order.invoice_ids.filtered(
                lambda inv: inv.move_type == 'out_invoice' and inv.state == 'posted') if sale_order else self.env['account.move']

            invoices_filtered = invoices

            # Apply filters in sync
            if start_date and end_date:
                invoices_filtered = invoices_filtered.filtered(
                    lambda inv: inv.invoice_date and start_date <= inv.invoice_date <= end_date)
            if customer_ids:
                invoices_filtered = invoices_filtered.filtered(
                    lambda inv: inv.partner_id.id in customer_ids)
            if invoice_ids:
                invoices_filtered = invoices_filtered.filtered(
                    lambda inv: inv.id in invoice_ids)
            if product_ids:
                invoices_filtered = invoices_filtered.filtered(lambda inv: any(
                    line.product_id.id in product_ids for line in inv.invoice_line_ids))
            if location_ids:
                # filter by pickings linked to sale order
                invoices_filtered = invoices_filtered.filtered(lambda inv: any(
                    p.location_dest_id.id in location_ids for p in inv.picking_ids))

            # If filters are applied and no matching invoice -> skip this chassis
            filters_applied = any(
                [start_date, end_date, customer_ids, invoice_ids, product_ids, location_ids])
            if filters_applied and not invoices_filtered:
                continue

            inv = invoices_filtered[:1] if invoices_filtered else None

            # get component serials from MO raw moves
            components = self._get_components_from_mo(mo)

            # Motor/Controller filter by component serials (if product filters requested)
            # Not needed now because we removed manual component filters; can be added if required.

            # Write row
            color_attr = chassis.product_id.product_template_attribute_value_ids.filtered(
                lambda a: a.attribute_id.name.lower() == 'color')
            color = color_attr.name if color_attr else ''
            sheet.write(row, 0, chassis.name or '', fmt_text)
            sheet.write(row, 1, chassis.product_id.name or '', fmt_text)
            sheet.write(
                row, 2, chassis.product_id.default_code or '', fmt_text)
            sheet.write(row, 3, color, fmt_text)
            sheet.write(row, 4, chassis.name or '', fmt_text)
            sheet.write(row, 5, components.get('Motor No', ''), fmt_text)
            sheet.write(row, 6, components.get('Battery No', ''), fmt_text)
            sheet.write(row, 7, components.get('Controller', ''), fmt_text)
            sheet.write(row, 8, components.get('Charger No', ''), fmt_text)
            sheet.write(row, 9, components.get('Converter', ''), fmt_text)

            if inv and inv.invoice_date:
                sheet.write_datetime(row, 14, inv.invoice_date, fmt_date)
            else:
                sheet.write(row, 14, '', fmt_text)
            sheet.write(row, 15, inv.name if inv else '', fmt_text)
            sheet.write(row, 16, inv.partner_id.name if inv else '', fmt_text)
            sheet.write(
                row, 17, inv.partner_id.city if inv and inv.partner_id.city else '', fmt_text)

            row += 1

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
        _logger.info(
            "Vehicle Tracking XLSX generated successfully (%s rows)", row - 5)

    # ---------------- Helper ----------------
    def _get_components_from_mo(self, mo):
        result = {}
        if not mo:
            return result
        # mo.move_raw_ids are stock.move (component moves); their move_line_ids hold lot
        for move in mo.move_raw_ids:
            comp_name = (move.product_id.name or '').lower()
            # move.move_line_ids may be empty; use search for move_line with move_id
            move_lines = move.move_line_ids or self.env['stock.move.line'].search(
                [('move_id', '=', move.id), ('lot_id', '!=', False)])
            for ml in move_lines:
                if not ml.lot_id:
                    continue
                lot_name = ml.lot_id.name
                if 'chassis' in comp_name:
                    result['Chassis'] = lot_name
                elif 'motor' in comp_name:
                    result['Motor No'] = lot_name
                elif 'controller' in comp_name:
                    result['Controller'] = lot_name
                elif 'battery' in comp_name:
                    result['Battery No'] = lot_name
                elif 'charger' in comp_name:
                    result['Charger No'] = lot_name
                elif 'converter' in comp_name:
                    result['Converter'] = lot_name
        return result
