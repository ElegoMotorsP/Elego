# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, content_disposition
import io, csv, xlsxwriter, json
from datetime import datetime
from odoo.tools.safe_eval import safe_eval as o_safe_eval

class VehicleStockReportController(http.Controller):
    def _build_domain_from_params(self, params):
        domain = []
        if params.get('domain'):
            try:
                domain = o_safe_eval(params.get('domain'))
            except Exception:
                domain = []
        else:
            if params.get('model_name'):
                domain.append(('model_name','ilike', params.get('model_name')))
            if params.get('chassis_no'):
                domain.append(('chassis_no','ilike', params.get('chassis_no')))
            if params.get('customer_name'):
                domain.append(('customer_name','ilike', params.get('customer_name')))
            if params.get('sales_from'):
                domain.append(('sales_invoice_date','>=', params.get('sales_from')))
            if params.get('sales_to'):
                domain.append(('sales_invoice_date','<=', params.get('sales_to')))
        return domain

    @http.route(['/vehicle_stock_dynamic/export_xlsx'], type='http', auth='user')
    def export_xlsx(self, **kwargs):
        params = kwargs
        domain = self._build_domain_from_params(params)
        records = request.env['vehicle.stock.report'].sudo().search(domain, limit=100000)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Vehicle Stock')
        headers = ['Item','Model Name','Part No','Color','Chassis No','Motor No','Battery','Controller','Charger','Convertor','QAFG Date','QAFG No','Picking Slip Date','Picking Slip No','Sales Invoice Date','Sales Invoice No','Customer Name','Customer Location']
        for c, h in enumerate(headers):
            sheet.write(0, c, h)
        row = 1
        for r in records:
            vals = [r.item, r.model_name, r.part_no, r.color, r.chassis_no, r.motor_no, r.battery, r.controller, r.charger, r.convertor, (r.qafg_date and r.qafg_date.isoformat() or ''), r.qafg_no, (r.picking_slip_date and r.picking_slip_date.isoformat() or ''), r.picking_slip_no, (r.sales_invoice_date and r.sales_invoice_date.isoformat() or ''), r.sales_invoice_no, r.customer_name, r.customer_location]
            for c, v in enumerate(vals):
                sheet.write(row, c, v if v is not None else '')
            row += 1
        workbook.close()
        output.seek(0)
        data = output.read()
        filename = 'vehicle_stock_report_%s.xlsx' % datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S')
        return request.make_response(data, headers=[('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),('Content-Disposition', content_disposition(filename))])

    @http.route(['/vehicle_stock_dynamic/export_csv'], type='http', auth='user')
    def export_csv(self, **kwargs):
        params = kwargs
        domain = self._build_domain_from_params(params)
        records = request.env['vehicle.stock.report'].sudo().search(domain, limit=100000)
        output = io.StringIO()
        writer = csv.writer(output)
        headers = ['Item','Model Name','Part No','Color','Chassis No','Motor No','Battery','Controller','Charger','Convertor','QAFG Date','QAFG No','Picking Slip Date','Picking Slip No','Sales Invoice Date','Sales Invoice No','Customer Name','Customer Location']
        writer.writerow(headers)
        for r in records:
            vals = [r.item, r.model_name, r.part_no, r.color, r.chassis_no, r.motor_no, r.battery, r.controller, r.charger, r.convertor, (r.qafg_date and r.qafg_date.isoformat() or ''), r.qafg_no, (r.picking_slip_date and r.picking_slip_date.isoformat() or ''), r.picking_slip_no, (r.sales_invoice_date and r.sales_invoice_date.isoformat() or ''), r.sales_invoice_no, r.customer_name, r.customer_location]
            writer.writerow(vals)
        data = output.getvalue().encode('utf-8')
        filename = 'vehicle_stock_report.csv'
        return request.make_response(data, headers=[('Content-Type','text/csv'),('Content-Disposition', content_disposition(filename))])
