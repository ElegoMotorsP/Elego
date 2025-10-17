import io
import json
from datetime import datetime
from odoo import fields, models
from odoo.tools import json_default
import logging
_logger = logging.getLogger(__name__)

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class VehicleTrackingXlsReport(models.TransientModel):
    _name = "vtr.xls.report"
    _description = "Vehicle Tracking Register Report"

    sales_invoice_date_start = fields.Date(string="Sales Date From")
    sales_invoice_date_end = fields.Date(string="Sales Date To")
    company_ids = fields.Many2many('res.company', string="Company")
    invoice_ids = fields.Many2many('account.move', string="Invoices", domain=[
        ('move_type', '=', 'out_invoice')])

    def export_xls(self):
        """Action that returns the report data to the controller."""
        self.ensure_one()
        data = {'wizard_id': self.id}
        # data = {
        #     'wizard_id': self.id,
        #     'sales_invoice_date_start': str(self.sales_invoice_date_start) if self.sales_invoice_date_start else False,
        #     'sales_invoice_date_end': str(self.sales_invoice_date_end) if self.sales_invoice_date_end else False,
        #     'invoice_ids': self.invoice_ids,
        # }
        return {
            'type': 'ir.actions.report',
            'data': {
                'model': 'vtr.xls.report',
                # 'options': json.dumps(data, default=json_default),
                'options': json.dumps(data, default=lambda x: x.id if hasattr(x, 'id') else x),
                'output_format': 'xlsx',
                'report_name': 'Vehicle Tracking Register',
            },
            'report_type': 'veh_tracking_xlsx',
        }

    def get_xlsx_report(self, data, response):
        try:
            _logger.info("XLSX wizard filters: start=%s end=%s companies=%s invoices=%s",
                         self.sales_invoice_date_start, self.sales_invoice_date_end,
                         self.company_ids.ids, self.invoice_ids.ids)
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

            # --- Filter summary ---
            filters = []
            if self.sales_invoice_date_start and self.sales_invoice_date_end:
                filters.append(
                    f"Invoice Date: {self.sales_invoice_date_start} → {self.sales_invoice_date_end}")
            if self.invoice_ids:
                filters.append(
                    "Invoices: " + ', '.join(self.invoice_ids.mapped('name')))
            filter_str = '; '.join(
                filters) if filters else 'No Filters (All Data)'
            sheet.merge_range('A2:R2', filter_str, fmt_text)

            # --- Headers ---
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

            # --- Lot Filtering ---
            lot_domain = [('product_id.tracking', '=', 'serial')]
            if self.company_ids:
                lot_domain.append(('company_id', 'in', self.company_ids.ids))
            chassis_lots = self.env['stock.lot'].search(lot_domain)

            # --- Iterate ---
            for chassis in chassis_lots:
                mo_move = self.env['stock.move'].search([
                    ('lot_ids', 'in', chassis.id),
                    ('product_id', '=', chassis.product_id.id),
                    ('state', '=', 'done'),
                    ('production_id', '!=', False)
                ], limit=1, order='date desc')
                mo = mo_move.production_id

                delivery_move_line = self.env['stock.move.line'].search([
                    ('lot_id', '=', chassis.id),
                    ('state', '=', 'done'),
                    ('move_id.picking_code', '=', 'outgoing'),
                ], limit=1, order='date desc')

                sale_order = delivery_move_line.move_id.sale_line_id.order_id if delivery_move_line.move_id.sale_line_id else None
                invoices = sale_order.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'out_invoice' and inv.state in (
                        'posted', 'paid')
                ) if sale_order else self.env['account.move']

                invoices_filtered = invoices

                # --- Apply Filters ---
                if self.sales_invoice_date_start and self.sales_invoice_date_end:
                    invoices_filtered = invoices_filtered.filtered(
                        lambda inv: inv.invoice_date and self.sales_invoice_date_start <= inv.invoice_date <= self.sales_invoice_date_end
                    )
                if self.invoice_ids:
                    invoices_filtered = invoices_filtered.filtered(
                        lambda inv: inv.id in self.invoice_ids.ids)
                if self.company_ids:
                    invoices_filtered = invoices_filtered.filtered(
                        lambda inv: inv.company_id.id in self.company_ids.ids)

                filters_applied = any([
                    self.sales_invoice_date_start, self.sales_invoice_date_end, self.invoice_ids, self.company_ids
                ])
                if filters_applied and not invoices_filtered:
                    continue

                inv = invoices_filtered[:1] if invoices_filtered else None

                # --- QAFG (Quality Check for Finished Goods) ---
                # qafg_check = self.env['quality.check'].search([
                #     ('production_id', '=', mo.id),
                #     ('lot_id', '=', chassis.id),
                #     ('quality_state', '=', 'pass'),
                # ], limit=1, order='write_date desc')
               
                qafg_domain = [
                    ('quality_state', '=', 'pass'),
                    ('product_id', '=', chassis.product_id.id),
                ]
                qafg_check = self.env['quality.check'].search(qafg_domain, limit=1, order='write_date desc')


               # qafg_date = qafg_check.write_date if qafg_check else False
                # qafg_no = qafg_check.name if qafg_check else ''

                # --- Picking Slip (Delivery) ---
                picking_slip = delivery_move_line.move_id.picking_id if delivery_move_line else False

                color_attr = chassis.product_id.product_template_attribute_value_ids.filtered(
                    lambda a: a.attribute_id.name.lower() == 'color')
                color = color_attr.name if color_attr else ''
                components = self._get_components_from_mo(mo)

                # --- Write Data ---
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

                # --- QAFG info ---
                if qafg_check:
                    sheet.write_datetime(
                        row, 10, qafg_check.write_date, fmt_date)
                    sheet.write(row, 11, qafg_check.name, fmt_text)
                else:
                    sheet.write(row, 10, '', fmt_text)
                    sheet.write(row, 11, '', fmt_text)

                # --- Picking Slip info ---
                if picking_slip:
                    sheet.write_datetime(
                        row, 12, picking_slip.date_done, fmt_date)
                    sheet.write(row, 13, picking_slip.name or '', fmt_text)
                else:
                    sheet.write(row, 12, '', fmt_text)
                    sheet.write(row, 13, '', fmt_text)

                # --- Invoice info ---
                if inv and inv.invoice_date:
                    sheet.write_datetime(row, 14, inv.invoice_date, fmt_date)
                else:
                    sheet.write(row, 14, '', fmt_text)

                sheet.write(row, 15, inv.name if inv else '', fmt_text)
                sheet.write(
                    row, 16, inv.partner_id.name if inv and inv.partner_id else '', fmt_text)
                sheet.write(
                    row, 17, inv.partner_id.city if inv and inv.partner_id.city else '', fmt_text)

                row += 1

            _logger.info("Total rows written: %s", row - 5)
            workbook.close()
            output.seek(0)
            response.stream.write(output.read())
            output.close()

        except Exception as e:
            _logger.error(
                "Error generating Vehicle Tracking XLSX report: %s", str(e))
            raise e

    def _get_components_from_mo(self, mo):
        result = {}
        if not mo:
            return result
        for move_line in mo.move_raw_ids:
            comp_name = move_line.product_id.name
            lot = move_line.move_line_ids.lot_id
            if not lot:
                continue
            lname = comp_name.lower()
            if 'motor' in lname:
                result['Motor No'] = lot.name
            elif 'battery' in lname:
                result['Battery No'] = lot.name
            elif 'controller' in lname:
                result['Controller'] = lot.name
            elif 'charger' in lname:
                result['Charger No'] = lot.name
            elif 'converter' in lname:
                result['Converter'] = lot.name
        return result
