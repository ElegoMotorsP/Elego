# -*- coding: utf-8 -*-
"""Excel download of the CKD reconciliation screen."""
import io

import xlsxwriter
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class CkdReconciliationController(http.Controller):

    @http.route('/elegomotors/ckd_reconciliation/<int:wizard_id>.xlsx', type='http', auth='user')
    def ckd_reconciliation_xlsx(self, wizard_id, **kwargs):
        # request.env (not sudo): a user only reaches their own transient record.
        wizard = request.env['elegomotors.ckd.reconciliation'].browse(wizard_id).exists()
        if not wizard:
            raise NotFound()

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('CKD Reconciliation')
        head = wb.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1, 'text_wrap': True})
        text = wb.add_format({'border': 1})
        num = wb.add_format({'border': 1, 'num_format': '#,##0.00'})
        bold = wb.add_format({'bold': True})
        bold_num = wb.add_format({'bold': True, 'num_format': '#,##0.00', 'top': 1})

        ws.write(0, 0, 'CKD cost and quantity reconciliation', bold)
        ws.write(1, 0, 'Purchase Order')
        ws.write(1, 1, wizard.order_id.name)
        ws.write(2, 0, 'Vendor')
        ws.write(2, 1, wizard.order_id.partner_id.name or '')
        ws.write(3, 0, 'Result')
        ws.write(3, 1, wizard.status or '')

        columns = [
            ('Kit', 28), ('Part', 40), ('Per Kit', 9), ('Cost Share %', 11), ('Frozen', 8),
            ('Ordered', 10), ('Received', 10), ('Kit Value in Stock', 16),
            ('Expected Value', 16), ('Duty / Landed Cost', 16), ('Final Value', 16), ('Note', 40),
        ]
        top = 5
        for col, (title, width) in enumerate(columns):
            ws.write(top, col, title, head)
            ws.set_column(col, col, width)
        for row, line in enumerate(wizard.line_ids, start=top + 1):
            ws.write(row, 0, line.kit_id.display_name or '', text)
            ws.write(row, 1, line.product_id.display_name or '', text)
            ws.write(row, 2, line.qty_per_kit, num)
            ws.write(row, 3, line.cost_share, num)
            ws.write(row, 4, 'Yes' if line.frozen else 'No', text)
            ws.write(row, 5, line.ordered_qty, num)
            ws.write(row, 6, line.received_qty, num)
            ws.write(row, 7, line.allocated_value, num)
            ws.write(row, 8, line.expected_value, num)
            ws.write(row, 9, line.landed_value, num)
            ws.write(row, 10, line.final_value, num)
            ws.write(row, 11, line.note or '', text)
        end = top + 1 + len(wizard.line_ids)
        ws.write(end, 6, 'Total', bold)
        for col, value in ((7, wizard.allocated_value), (8, wizard.expected_value),
                           (9, wizard.landed_value), (10, wizard.inventory_value)):
            ws.write(end, col, value, bold_num)
        ws.write(end + 2, 0, 'Bill of Entry amounts capitalised')
        ws.write(end + 2, 9, wizard.boe_capitalised, num)
        ws.write(end + 3, 0, 'Landed cost in stock less Bill of Entry capitalised')
        ws.write(end + 3, 9, wizard.landed_difference, num)
        ws.freeze_panes(top + 1, 2)
        wb.close()

        data = output.getvalue()
        filename = 'CKD_Reconciliation_%s.xlsx' % (wizard.order_id.name or wizard_id)
        return request.make_response(data, headers=[
            ('Content-Type', XLSX_MIME),
            ('Content-Disposition', 'attachment; filename="%s"' % filename),
            ('Content-Length', str(len(data))),
        ])
