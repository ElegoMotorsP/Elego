# -*- coding: utf-8 -*-
"""Client Excel of the PO Tracking report.

The client asked for the report as one sheet: every PO as a row, with its parts on
the rows underneath. This builds that sheet from the report's own figures (the
stored x_trk_* fields for the PO row, PurchaseOrder._trk_part_rows for the part
rows), so the Excel can never disagree with the screen.
"""
import base64
import io
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:  # pragma: no cover - xlsxwriter ships with Odoo
    xlsxwriter = None

# (heading, width) in the client's column order
COLUMNS = [
    ('Order Reference', 16), ('Domestic / Import', 12), ('Vendor', 28), ('Order Deadline', 17),
    ('Part Name', 34), ('PO Qty', 11), ('GRN No.', 24), ('Supplier Invoice No. / Date', 26),
    ('Elego Purchase Invoice', 24), ('Received', 11), ('Pending', 11), ('QC No.', 24),
    ('PO Value', 14), ('Currency', 9), ('QC Pass', 10), ('QC Reject', 10),
    ('QC Pending', 11), ('Stock', 11), ('Current Stage', 20),
]
NUM = '#,##0.00'


class PoTrackingExport(models.TransientModel):
    _name = 'elegomotors.po.tracking.export'
    _description = 'PO Tracking: download the client Excel'

    order_ids = fields.Many2many(
        'purchase.order', string='Purchase Orders',
        help='The POs ticked in the report. Leave empty to use the filters below.')
    order_count = fields.Integer(compute='_compute_order_count')
    date_from = fields.Date(string='PO Date from')
    date_to = fields.Date(string='PO Date to')
    po_type = fields.Selection(
        [('all', 'Domestic and Import'), ('domestic', 'Domestic'), ('import', 'Import')],
        string='Type', default='all', required=True)
    partner_id = fields.Many2one('res.partner', string='Supplier / Vendor')
    include_cancelled = fields.Boolean(string='Include cancelled POs', default=True)
    include_parts = fields.Boolean(
        string='Show the parts under each PO', default=True,
        help='One row per part under each PO row. Untick for one row per PO only.')

    @api.depends('order_ids')
    def _compute_order_count(self):
        for wiz in self:
            wiz.order_count = len(wiz.order_ids)

    def _orders(self):
        self.ensure_one()
        if self.order_ids:
            orders = self.order_ids
        else:
            domain = []
            if self.date_from:
                domain.append(('date_order', '>=', fields.Datetime.to_datetime(self.date_from)))
            if self.date_to:
                domain.append(('date_order', '<', fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)))
            if self.po_type != 'all':
                domain.append(('x_po_type', '=', self.po_type))
            if self.partner_id:
                domain.append(('partner_id', '=', self.partner_id.id))
            orders = self.env['purchase.order'].search(domain)
        if not self.include_cancelled:
            orders = orders.filtered(lambda po: po.state != 'cancel')
        return orders.sorted('name', reverse=True)

    def _build_xlsx(self, orders):
        if xlsxwriter is None:
            raise UserError('The Excel library (xlsxwriter) is not installed on this server.')
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = book.add_worksheet('PO Tracking')
        head = book.add_format({
            'bold': True, 'bg_color': '#714B67', 'font_color': '#FFFFFF', 'border': 1,
            'text_wrap': True, 'valign': 'vcenter'})
        po_text = book.add_format({'bold': True, 'bg_color': '#F3E8F0', 'border': 1})
        po_num = book.add_format({'bold': True, 'bg_color': '#F3E8F0', 'border': 1, 'num_format': NUM})
        po_date = book.add_format({
            'bold': True, 'bg_color': '#F3E8F0', 'border': 1, 'num_format': 'dd/mm/yyyy hh:mm',
            'align': 'left'})
        part_text = book.add_format({'border': 1, 'indent': 1, 'font_color': '#374151'})
        part_num = book.add_format({'border': 1, 'num_format': NUM, 'font_color': '#374151'})
        blank_part = book.add_format({'border': 1})

        for col, (title, width) in enumerate(COLUMNS):
            sheet.write(0, col, title, head)
            sheet.set_column(col, col, width)
        sheet.set_row(0, 30)
        sheet.freeze_panes(1, 1)

        type_labels = dict(orders._fields['x_po_type']._description_selection(self.env))
        stage_labels = dict(orders._fields['x_trk_stage']._description_selection(self.env))
        row = 1
        for po in orders:
            ordered = fields.Datetime.context_timestamp(po, po.date_order).replace(tzinfo=None) \
                if po.date_order else None
            sheet.write(row, 0, po.name, po_text)
            sheet.write(row, 1, type_labels.get(po.x_po_type, ''), po_text)
            sheet.write(row, 2, po.partner_id.name or '', po_text)
            if ordered:
                sheet.write_datetime(row, 3, ordered, po_date)
            else:
                sheet.write(row, 3, '', po_text)
            sheet.write(row, 4, '', po_text)
            sheet.write_number(row, 5, po.x_trk_po_qty, po_num)
            sheet.write(row, 6, po.x_trk_grn_refs or '', po_text)
            sheet.write(row, 7, po.x_trk_invoice_refs or '', po_text)
            sheet.write(row, 8, po.x_trk_bill_refs or '', po_text)
            sheet.write_number(row, 9, po.x_trk_received_qty, po_num)
            sheet.write_number(row, 10, po.x_trk_pending_qty, po_num)
            sheet.write(row, 11, po.x_trk_qc_refs or '', po_text)
            sheet.write_number(row, 12, po.amount_total, po_num)
            sheet.write(row, 13, po.currency_id.name or '', po_text)
            sheet.write_number(row, 14, po.x_trk_qc_passed_qty, po_num)
            sheet.write_number(row, 15, po.x_trk_qc_rejected_qty, po_num)
            sheet.write_number(row, 16, po.x_trk_qc_pending_qty, po_num)
            sheet.write_number(row, 17, po.x_trk_stock_qty, po_num)
            sheet.write(row, 18, stage_labels.get(po.x_trk_stage, ''), po_text)
            row += 1
            if not self.include_parts:
                continue
            for part in po._trk_part_rows():
                for col in range(len(COLUMNS)):
                    sheet.write_blank(row, col, None, blank_part)
                sheet.write(row, 4, part['name'], part_text)
                sheet.write_number(row, 5, part['ordered'], part_num)
                sheet.write_number(row, 9, part['received'], part_num)
                sheet.write_number(row, 10, part['pending'], part_num)
                sheet.write_number(row, 14, part['qc_passed'], part_num)
                sheet.write_number(row, 15, part['qc_rejected'], part_num)
                sheet.write_number(row, 16, part['qc_pending'], part_num)
                sheet.write_number(row, 17, part['stock'], part_num)
                row += 1
        book.close()
        return output.getvalue()

    def action_download(self):
        self.ensure_one()
        orders = self._orders()
        if not orders:
            raise UserError('No purchase orders match: change the filters, or untick fewer of them.')
        content = self._build_xlsx(orders)
        attachment = self.env['ir.attachment'].create({
            'name': 'PO_Tracking_%s.xlsx' % fields.Date.context_today(self),
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
