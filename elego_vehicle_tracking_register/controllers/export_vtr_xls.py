import json
from odoo import http
from odoo.http import content_disposition, request, serialize_exception as _serialize_exception
from odoo.tools import html_escape


class XLSXReportController(http.Controller):
    """Controller to generate and print XLS reports."""

    @http.route('/xlsx_reports', type='http', auth='user', methods=['POST'], csrf=False)
    def get_report_xlsx(self, model, options, output_format, report_name):
        """Retrieve and generate XLSX report."""
        try:
            options = json.loads(options)
            wizard_id = options.get('wizard_id')  # ✅ Get wizard ID
            token = 'dummy-because-api-expects-one'

            # ✅ Browse the wizard record
            report_obj = request.env[model].browse(wizard_id).sudo()
            if not report_obj.exists():
                return request.not_found()

            if output_format == 'xlsx':
                response = request.make_response(
                    None,
                    headers=[
                        ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                        ('Content-Disposition',
                         content_disposition(f"{report_name}.xlsx")),
                    ],
                )

                # ✅ Call with wizard record
                report_obj.get_xlsx_report(options, response)
                response.set_cookie('fileToken', token)
                return response

        except Exception as e:
            se = _serialize_exception(e)
            error = {'code': 200, 'message': 'Odoo Server Error', 'data': se}
            return request.make_response(html_escape(json.dumps(error)))
