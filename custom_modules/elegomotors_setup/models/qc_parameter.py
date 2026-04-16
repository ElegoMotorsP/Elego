# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ElegoQcParameter(models.Model):
    """
    QC inspection parameter definition — linked to a product template.
    Manohar sets these up once per QC-required product (e.g. Battery,
    Charger). They describe what Pratik must inspect and what the
    expected value is.
    """
    _name = 'elegomotors.qc.parameter'
    _description = 'QC Inspection Parameter'
    _order = 'product_tmpl_id, sequence, id'

    name = fields.Char(string='Parameter', required=True)
    expected_value = fields.Char(
        string='Expected Value',
        help='e.g. "74 V", "24 Kg", "OK"',
    )
    check_description = fields.Text(
        string='How to Check',
        help='Instructions for Pratik — e.g. "Measure with multimeter, record actual value."',
    )
    result_type = fields.Selection([
        ('ok_not_ok', 'OK / NOT OK'),
        ('measurement', 'Measured Value'),
    ], string='Result Type', default='ok_not_ok', required=True,
        help='OK/NOT OK — binary pass/fail (Physical Condition, Test Report, etc.).\n'
             'Measured Value — Pratik enters an actual reading (Voltage, Weight, etc.).')
    sequence = fields.Integer(default=10)
    product_tmpl_id = fields.Many2one(
        'product.template', string='Product', ondelete='cascade', required=True, index=True,
    )


class ElegoQcCheckResult(models.Model):
    """
    Actual QC inspection result filled by Pratik for one parameter
    on one Gate Entry picking. Auto-created when the picking transitions
    to 'in_qc'. Persisted as an audit trail after QC is approved.
    """
    _name = 'elegomotors.qc.check.result'
    _description = 'QC Inspection Result'
    _order = 'picking_id, sequence, parameter_id'

    picking_id = fields.Many2one(
        'stock.picking', string='Gate Entry', ondelete='cascade', required=True, index=True,
    )
    move_id = fields.Many2one(
        'stock.move', string='Product Move', ondelete='cascade', required=True, index=True,
    )
    parameter_id = fields.Many2one(
        'elegomotors.qc.parameter', string='Parameter', ondelete='restrict', required=True,
    )

    # Display fields pulled from the parameter definition (read-only context)
    name = fields.Char(related='parameter_id.name', string='Parameter', store=True)
    sequence = fields.Integer(related='parameter_id.sequence', store=True)
    expected_value = fields.Char(related='parameter_id.expected_value', string='Expected Value')
    check_description = fields.Text(related='parameter_id.check_description', string='How to Check')
    result_type = fields.Selection(related='parameter_id.result_type', string='Type')

    # Results filled by Pratik during inspection
    actual_value = fields.Char(
        string='Actual Value / Observation',
        help='Enter the measured or observed value (e.g. "73.8 V", "24.1 Kg", "Seal intact").',
    )
    result = fields.Selection([
        ('pass', 'OK'),
        ('fail', 'NOT OK'),
    ], string='Pass/Fail')
    notes = fields.Char(
        string='Failure Reason',
        help='Required when result is NOT OK — describe the defect or discrepancy.',
    )
