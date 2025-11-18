# -*- coding: utf-8 -*-
from odoo import models, fields


class VehicleComponentRole(models.Model):
    _name = 'vehicle.component.role'
    _description = 'Map component product templates to roles (motor, battery, controller, charger, convertor)'

    product_tmpl_id = fields.Many2one(
        'product.template', string='Component Product Template', required=True, ondelete='cascade')
    role = fields.Selection([('motor', 'Motor'), ('battery', 'Battery'), ('controller', 'Controller'), (
        'charger', 'Charger'), ('convertor', 'Convertor')], string='Role', required=True)
    active = fields.Boolean(default=True)
