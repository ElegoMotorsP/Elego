# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ElegoPdiParameter(models.Model):
    """
    PDI (Pre-Delivery Inspection) checklist item definition — global list,
    not tied to a product template, since PDI applies to the finished bike
    itself rather than a specific component. Manohar (Admin) maintains this
    list; Pratik/Amit fill the results per bike serial before dispatch.
    """
    _name = 'elegomotors.pdi.parameter'
    _description = 'PDI Checklist Item'
    _order = 'sequence, id'

    name = fields.Char(string='Checklist Item', required=True)
    category = fields.Selection([
        ('document', 'Document'),
        ('physical', 'Physical Check'),
    ], string='Category', default='physical', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class ElegoPdiCheckResult(models.Model):
    """
    Actual PDI result filled by Pratik/Amit for one checklist item on one
    bike serial (stock.lot). Auto-created when the bike is scanned onto an
    outgoing delivery (see delivery_bike_scan_wizard.py). Persisted as an
    audit trail after PDI is approved.
    """
    _name = 'elegomotors.pdi.check.result'
    _description = 'PDI Inspection Result'
    _order = 'lot_id, sequence, parameter_id'

    lot_id = fields.Many2one(
        'stock.lot', string='Bike Serial', ondelete='cascade', required=True, index=True,
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Outgoing Delivery', ondelete='set null', index=True,
        help='The delivery this bike was scanned onto when the PDI checklist was created.',
    )
    parameter_id = fields.Many2one(
        'elegomotors.pdi.parameter', string='Checklist Item', ondelete='restrict', required=True,
    )

    # Display fields pulled from the parameter definition (read-only context)
    name = fields.Char(related='parameter_id.name', string='Checklist Item', store=True)
    category = fields.Selection(related='parameter_id.category', string='Category', store=True)
    sequence = fields.Integer(related='parameter_id.sequence', store=True)

    # Results filled by Pratik/Amit during PDI inspection
    result = fields.Selection([
        ('pass', 'OK'),
        ('fail', 'NOT OK'),
    ], string='Pass/Fail')
    notes = fields.Char(
        string='Notes / Failure Reason',
        help='Required when result is NOT OK — describe the issue or missing document.',
    )
