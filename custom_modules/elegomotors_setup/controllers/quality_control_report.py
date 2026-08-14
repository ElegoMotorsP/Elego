# -*- coding: utf-8 -*-
import datetime
import io
import json

import xlsxwriter

from odoo import http
from odoo.http import request

INWARD_REPORT_COLUMNS = [
    ('Gate Entry No.',     lambda p: p.name),
    ('Date',               lambda p: p.scheduled_date),
    ('Vendor',             lambda p: p.partner_id.name),
    ('PO No.',             lambda p: p.x_source_po_id.name),
    ('Vendor Invoice No.', lambda p: p.x_vendor_invoice_number),
    ('QC Products',        lambda p: p.x_qc_required_product_names),
    ('Serial No(s).',      lambda p: p.x_qc_serial_nos),
    ('QC Status',          lambda p: dict(p._fields['x_gate_entry_state'].selection).get(p.x_gate_entry_state, '')),
]

BIKE_QC_REPORT_COLUMNS = [
    ('Serial No.',     lambda lot: lot.name),
    ('Bike Model',     lambda lot: lot.product_id.display_name),
    ('MO No.',         lambda lot: lot.x_mo_id.name),
    ('Produced On',    lambda lot: lot.create_date),
    ('FG QC Status',   lambda lot: lot.x_qc_status),
    ('PDI QC Status',  lambda lot: dict(lot._fields['x_pdi_state'].selection).get(lot.x_pdi_state, '')),
    ('PDI Checked On', lambda lot: lot.x_pdi_checked_date),
    ('Blacklisted',    lambda lot: 'Yes' if lot.x_blacklisted else 'No'),
]


def _write_xlsx(sheet_name, columns, records):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    sheet = workbook.add_worksheet(sheet_name)

    header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})
    date_fmt = workbook.add_format({'num_format': 'dd-mm-yyyy', 'border': 1})
    text_fmt = workbook.add_format({'border': 1})

    for col, (title, _getter) in enumerate(columns):
        sheet.write(0, col, title, header_fmt)
        sheet.set_column(col, col, 20)

    for row, rec in enumerate(records, start=1):
        for col, (_title, getter) in enumerate(columns):
            value = getter(rec)
            if isinstance(value, datetime.datetime):
                sheet.write_datetime(row, col, value, date_fmt)
            elif isinstance(value, datetime.date):
                sheet.write_datetime(
                    row, col, datetime.datetime.combine(value, datetime.time.min), date_fmt
                )
            else:
                sheet.write(row, col, value or '', text_fmt)

    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, max(len(records), 1), len(columns) - 1)
    workbook.close()
    output.seek(0)
    return output.getvalue()


class QualityControlReportController(http.Controller):

    @http.route('/elegomotors/qc_report/inward/xlsx', type='http', auth='user')
    def export_inward_qc_report(self, domain='[]', **kwargs):
        try:
            parsed_domain = json.loads(domain)
        except (TypeError, ValueError):
            parsed_domain = []

        pickings = request.env['stock.picking'].search(
            parsed_domain, order='scheduled_date asc, name asc'
        )
        content = _write_xlsx('Inward QC Report', INWARD_REPORT_COLUMNS, pickings)

        filename = 'Inward_Material_QC_Report_%s.xlsx' % datetime.date.today().isoformat()
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="%s"' % filename),
            ('Content-Length', str(len(content))),
        ]
        return request.make_response(content, headers=headers)

    @http.route('/elegomotors/qc_report/bikes/xlsx', type='http', auth='user')
    def export_bike_qc_report(self, domain='[]', **kwargs):
        try:
            parsed_domain = json.loads(domain)
        except (TypeError, ValueError):
            parsed_domain = []

        lots = request.env['stock.lot'].search(
            parsed_domain, order='create_date asc, name asc'
        )
        content = _write_xlsx('QC Report', BIKE_QC_REPORT_COLUMNS, lots)

        filename = 'Bike_QC_Report_%s.xlsx' % datetime.date.today().isoformat()
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="%s"' % filename),
            ('Content-Length', str(len(content))),
        ]
        return request.make_response(content, headers=headers)
