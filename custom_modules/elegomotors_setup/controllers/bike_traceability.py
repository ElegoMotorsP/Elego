# -*- coding: utf-8 -*-
import datetime
import io
import json

import xlsxwriter

from odoo import http
from odoo.http import request

REPORT_COLUMNS = [
    ('MO Date',                     lambda lot: lot.x_mo_date),
    ('MO No.',                      lambda lot: lot.x_mo_id.name),
    ('Picking Slip No.',            lambda lot: lot.x_delivery_id.name),
    ('Picking Slip Date',           lambda lot: lot.x_delivery_id.scheduled_date),
    ('Lot/Serial Number',           lambda lot: lot.name),
    ('Created On',                  lambda lot: lot.create_date),
    ('Product',                     lambda lot: lot.product_id.display_name),
    ('Colour',                      lambda lot: lot.x_color),
    ('Chassis No. (Frame Plate)',   lambda lot: lot.x_chassis_serial),
    ('Hub Motor Serial No.',        lambda lot: lot.x_motor_serial),
    ('Motor Controller Serial No.', lambda lot: lot.x_controller_serial),
    ('Battery Pack Serial No.',     lambda lot: lot.x_battery_serial),
    ('Charger Serial No.',          lambda lot: lot.x_charger_serial),
    ('Battery Type',                lambda lot: lot.x_battery_type),
    ('QC Status',                   lambda lot: lot.x_qc_status),
    ('QC No.',                      lambda lot: lot.x_qc_no),
    ('SO No.',                      lambda lot: lot.x_so_id.name),
    ('Delivery Out No.',            lambda lot: lot.x_delivery_id.name),
    ('Delivery Out Date',           lambda lot: lot.x_delivery_date),
    ('Invoice No.',                 lambda lot: lot.x_invoice_id.name),
    ('Invoice Date',                lambda lot: lot.x_invoice_date),
    ('Dealer Name',                 lambda lot: lot.x_dealer_id.name),
    ('Dealer Delivery Address',     lambda lot: lot.x_dealer_address),
]


class BikeTraceabilityController(http.Controller):

    @http.route('/elegomotors/bike_traceability/xlsx', type='http', auth='user')
    def export_master_report(self, domain='[]', **kwargs):
        try:
            parsed_domain = json.loads(domain)
        except (TypeError, ValueError):
            parsed_domain = []

        # request.env (not sudo) so the exported rows respect the
        # requesting user's own record rules/access groups.
        lots = request.env['stock.lot'].search(
            parsed_domain, order='create_date asc, name asc'
        )

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Master Report')

        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})
        date_fmt = workbook.add_format({'num_format': 'dd-mm-yyyy', 'border': 1})
        text_fmt = workbook.add_format({'border': 1})

        for col, (title, _getter) in enumerate(REPORT_COLUMNS):
            sheet.write(0, col, title, header_fmt)
            sheet.set_column(col, col, 20)

        for row, lot in enumerate(lots, start=1):
            for col, (_title, getter) in enumerate(REPORT_COLUMNS):
                value = getter(lot)
                if isinstance(value, datetime.datetime):
                    sheet.write_datetime(row, col, value, date_fmt)
                elif isinstance(value, datetime.date):
                    sheet.write_datetime(
                        row, col, datetime.datetime.combine(value, datetime.time.min), date_fmt
                    )
                else:
                    sheet.write(row, col, value or '', text_fmt)

        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, max(len(lots), 1), len(REPORT_COLUMNS) - 1)

        workbook.close()
        output.seek(0)

        filename = 'Bike_Master_Traceability_Report_%s.xlsx' % (
            datetime.date.today().isoformat()
        )
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="%s"' % filename),
            ('Content-Length', str(len(output.getvalue()))),
        ]
        return request.make_response(output.getvalue(), headers=headers)
