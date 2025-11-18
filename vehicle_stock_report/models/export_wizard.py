# -*- coding: utf-8 -*-
from odoo import models, fields, api
import urllib.parse

class VehicleStockExportWizard(models.TransientModel):
    _name = 'vehicle.stock.export.wizard'
    _description = 'Export Vehicle Stock Report'

    model_name = fields.Char(string='Model Filter')
    chassis_no = fields.Char(string='Chassis No Filter')
    customer_name = fields.Char(string='Customer Name Filter')
    sales_from = fields.Date(string='Sales From')
    sales_to = fields.Date(string='Sales To')

    def _build_params(self):
        params = {
            'model_name': self.model_name or '',
            'chassis_no': self.chassis_no or '',
            'customer_name': self.customer_name or '',
            'sales_from': self.sales_from and self.sales_from.isoformat() or '',
            'sales_to': self.sales_to and self.sales_to.isoformat() or '',
        }
        return urllib.parse.urlencode(params)

    def action_export_xlsx(self):
        self.ensure_one()
        url = '/vehicle_stock_dynamic/export_xlsx?' + self._build_params()
        return {'type':'ir.actions.act_url','url': url, 'target': 'self'}

    def action_export_csv(self):
        self.ensure_one()
        url = '/vehicle_stock_dynamic/export_csv?' + self._build_params()
        return {'type':'ir.actions.act_url','url': url, 'target': 'self'}
