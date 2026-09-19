# -*- coding: utf-8 -*-
"""Dealer-facing invoice PDF download — the same "ElegoMotors Tax Invoice"
QWeb report available from the Print menu in Odoo's own UI
(elegomotors_setup/views/report_invoice.xml, action
elegomotors_setup.action_elegomotors_tax_invoice), exposed here so a
dealer can download the real, accepted invoice once their PO's linked
Sales Order has one — same bearer-token contract and PDF-rendering
pattern as the existing warranty certificate endpoint
(elegomotors_setup/controllers/warranty_api.py's `certificate` route).
"""
from odoo import http
from odoo.http import request

from .connect_auth import _json_response, log_connect_call, require_connect_bearer_token

TAX_INVOICE_REPORT = 'elegomotors_setup.report_elegomotors_invoice'


class ConnectInvoicesApiController(http.Controller):

    @http.route(
        '/elegomotors/connect/invoices/<int:invoice_id>/pdf', type='http',
        auth='public', methods=['GET'], csrf=False,
    )
    def invoice_pdf(self, invoice_id, **kwargs):
        client, error_response = require_connect_bearer_token()
        if error_response:
            return error_response

        invoice = request.env['account.move'].sudo().browse(invoice_id)
        if not invoice.exists() or invoice.move_type != 'out_invoice':
            log_connect_call(client.client_id, 'invoices/pdf', str(invoice_id), 'invoice_not_found')
            return _json_response({'error': 'invoice_not_found'}, status=404)

        pdf_content, _ = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            TAX_INVOICE_REPORT, [invoice.id],
        )
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="{invoice.name or invoice.id}.pdf"'),
            ('Content-Length', str(len(pdf_content))),
        ]
        log_connect_call(client.client_id, 'invoices/pdf', invoice.name or str(invoice.id), 'pdf_rendered')
        return request.make_response(pdf_content, headers=headers)
