# -*- coding: utf-8 -*-
"""Client Excel of the SO Tracking report.

Same idea as PO Tracking's export (po_tracking_export.py): the sheet is built
straight from the report's own stored x_trk_* fields (plus the standard
qty_delivered / qty_invoiced / qty_to_invoice / invoice_status / price_* Odoo
already computes), so the Excel can never disagree with the screen. Unlike PO
Tracking, there is no separate "part rows" pass — the report's own grain is
already one row per Sales Order line.
"""
import base64
import io
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .so_tracking import SO_TRACKING_STAGES

try:
    import xlsxwriter
except ImportError:  # pragma: no cover - xlsxwriter ships with Odoo
    xlsxwriter = None

# (heading, width) in the client's column order
COLUMNS = [
    ('Sr. No.', 7), ('Quotation No.', 16), ('Quotation Date', 16), ('Quotation Status', 16),
    ('Customer', 24), ('Salesperson', 16), ('Approval Status', 14), ('SO No.', 16), ('SO Date', 16),
    ('Approved By', 20), ('Approval Date', 16), ('Customer PO Ref.', 18), ('Product Code', 14),
    ('Product Name', 28), ('Model', 16), ('Colour', 12), ('UoM', 8), ('Ordered Qty', 11),
    ('Delivered Qty', 11), ('Return Qty', 10), ('Net Delivered Qty', 14), ('Pending Dispatch Qty', 14),
    ('DO / Out Order No.', 22), ('Dispatch Date', 16), ('Delivery Status', 12), ('Invoice No. / Date', 26),
    ('Invoiced Qty', 11), ('Pending Invoice Qty', 14), ('Unit Price', 11), ('Taxable Amount', 13),
    ('GST Amount', 11), ('Invoice Total', 13), ('Invoice Status', 12), ('Current Stage', 24),
]
NUM = '#,##0.00'
DATE = 'dd/mm/yyyy'


class SoTrackingExport(models.TransientModel):
    _name = 'elegomotors.so.tracking.export'
    _description = 'SO Tracking: download the client Excel'

    line_ids = fields.Many2many(
        'sale.order.line', string='Sales Order Lines',
        help='The lines ticked in the report. Leave empty to use the filters below.')
    line_count = fields.Integer(compute='_compute_line_count')
    date_from = fields.Date(string='Order Date from')
    date_to = fields.Date(string='Order Date to')
    partner_id = fields.Many2one('res.partner', string='Customer')
    x_salesperson = fields.Selection([
        ('priyanka_kul', 'Priyanka Kul'),
        ('priyanka_sutar', 'Priyanka Sutar'),
        ('srushti_gund', 'Srushti Gund'),
    ], string='Salesperson')
    stage = fields.Selection(SO_TRACKING_STAGES, string='Stage')
    include_cancelled = fields.Boolean(string='Include cancelled orders', default=True)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for wiz in self:
            wiz.line_count = len(wiz.line_ids)

    def _lines(self):
        self.ensure_one()
        if self.line_ids:
            lines = self.line_ids
        else:
            domain = []
            if self.date_from:
                domain.append(('order_id.date_order', '>=', fields.Datetime.to_datetime(self.date_from)))
            if self.date_to:
                domain.append(
                    ('order_id.date_order', '<', fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)))
            if self.partner_id:
                domain.append(('order_id.partner_id', '=', self.partner_id.id))
            if self.x_salesperson:
                domain.append(('order_id.x_actual_salesperson', '=', self.x_salesperson))
            if self.stage:
                domain.append(('x_trk_stage', '=', self.stage))
            lines = self.env['sale.order.line'].search(domain)
        lines = lines._trk_reportable()
        if not self.include_cancelled:
            lines = lines.filtered(lambda l: l.order_id.state != 'cancel')
        return lines.sorted(lambda l: (l.order_id.name, l.id))

    def _build_xlsx(self, lines):
        if xlsxwriter is None:
            raise UserError('The Excel library (xlsxwriter) is not installed on this server.')
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = book.add_worksheet('SO Tracking')
        head = book.add_format({
            'bold': True, 'bg_color': '#714B67', 'font_color': '#FFFFFF', 'border': 1,
            'text_wrap': True, 'valign': 'vcenter'})
        cell_text = book.add_format({'border': 1})
        cell_num = book.add_format({'border': 1, 'num_format': NUM})
        cell_date = book.add_format({'border': 1, 'num_format': DATE})

        for col, (title, width) in enumerate(COLUMNS):
            sheet.write(0, col, title, head)
            sheet.set_column(col, col, width)
        sheet.set_row(0, 30)
        sheet.freeze_panes(1, 1)

        salesperson_labels = dict(lines._fields['x_report_salesperson']._description_selection(self.env))
        stage_labels = dict(lines._fields['x_trk_stage']._description_selection(self.env))

        def write_date(row, col, value):
            if value:
                sheet.write_datetime(row, col, fields.Datetime.context_timestamp(
                    self, value).replace(tzinfo=None), cell_date)
            else:
                sheet.write(row, col, '', cell_text)

        for row, line in enumerate(lines, start=1):
            order = line.order_id
            sheet.write(row, 0, row, cell_text)
            sheet.write(row, 1, line.x_trk_quotation_no or '', cell_text)
            write_date(row, 2, line.x_trk_quotation_date)
            sheet.write(row, 3, line.x_trk_quotation_status or '', cell_text)
            sheet.write(row, 4, order.partner_id.name or '', cell_text)
            sheet.write(row, 5, salesperson_labels.get(line.x_report_salesperson, ''), cell_text)
            sheet.write(row, 6, line.x_trk_approval_status or '', cell_text)
            sheet.write(row, 7, line.x_trk_so_no or '', cell_text)
            write_date(row, 8, line.x_trk_so_date)
            sheet.write(row, 9, line.x_trk_approved_by or '', cell_text)
            write_date(row, 10, line.x_trk_approval_date)
            sheet.write(row, 11, line.x_trk_customer_po_ref or '', cell_text)
            sheet.write(row, 12, line.x_trk_product_code or '', cell_text)
            sheet.write(row, 13, line.product_id.name or '', cell_text)
            sheet.write(row, 14, line.x_report_bike_tmpl_id.name or '', cell_text)
            sheet.write(row, 15, line.x_trk_colour or '', cell_text)
            sheet.write(row, 16, line.product_uom.name or '', cell_text)
            sheet.write_number(row, 17, line.product_uom_qty, cell_num)
            sheet.write_number(row, 18, line.x_trk_gross_delivered_qty, cell_num)
            sheet.write_number(row, 19, line.x_trk_return_qty, cell_num)
            sheet.write_number(row, 20, line.qty_delivered, cell_num)
            sheet.write_number(row, 21, line.x_trk_pending_dispatch_qty, cell_num)
            sheet.write(row, 22, line.x_trk_do_refs or '', cell_text)
            write_date(row, 23, line.x_trk_dispatch_date)
            sheet.write(row, 24, line.x_trk_delivery_status or '', cell_text)
            sheet.write(row, 25, line.x_trk_invoice_refs or '', cell_text)
            sheet.write_number(row, 26, line.qty_invoiced, cell_num)
            sheet.write_number(row, 27, line.qty_to_invoice, cell_num)
            sheet.write_number(row, 28, line.price_unit, cell_num)
            sheet.write_number(row, 29, line.price_subtotal, cell_num)
            sheet.write_number(row, 30, line.price_tax, cell_num)
            sheet.write_number(row, 31, line.price_total, cell_num)
            sheet.write(row, 32, dict(line._fields['invoice_status'].selection).get(line.invoice_status, ''),
                        cell_text)
            sheet.write(row, 33, stage_labels.get(line.x_trk_stage, ''), cell_text)
        book.close()
        return output.getvalue()

    def action_download(self):
        self.ensure_one()
        lines = self._lines()
        if not lines:
            raise UserError('No Sales Order lines match: change the filters, or untick fewer of them.')
        content = self._build_xlsx(lines)
        attachment = self.env['ir.attachment'].create({
            'name': 'SO_Tracking_%s.xlsx' % fields.Date.context_today(self),
            'type': 'binary',
            'datas': base64.b64encode(content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
