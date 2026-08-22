# -*- coding: utf-8 -*-
"""Extends elegomotors_setup's elegomotors.warranty.claim with the fuller
status timeline and dispatch/failed-part-action data the Elego Connect app's
warranty screens need — see docs/09-module-warranty.md §9.2 in the app's own
design repo: "Odoo's current model only has 5 states (draft/submitted/
approved/rejected/completed); the requirement doc's status list has 11."

Deliberately done via _inherit here (Elego Connect module) rather than
editing elegomotors_setup/models/warranty.py directly — keeps that
already-shipped module's own file untouched; this module owns everything
Elego-Connect-specific, and depends on elegomotors_setup for the base model.

Odoo 18 requires `ondelete` behavior for every selection_add value — 'set
default' just means: if this module is ever uninstalled, any claim sitting
in one of these states falls back to the base module's default ('draft')
rather than leaving an invalid value in the column.
"""
from odoo import fields, models
from odoo.exceptions import UserError


class WarrantyClaimConnectExtension(models.Model):
    _inherit = 'elegomotors.warranty.claim'

    state = fields.Selection(selection_add=[
        ('more_info_required', 'More Information Required'),
        ('under_inspection', 'Under Inspection'),
        ('partially_approved', 'Partially Approved'),
        ('replacement_ready', 'Replacement Ready'),
        ('dispatched', 'Dispatched'),
        ('delivered_confirmed', 'Delivered / Dealer Confirmed'),
        ('failed_part_returned_scrapped', 'Failed Part Returned / Scrapped'),
        ('closed', 'Closed'),
    ], ondelete={
        'more_info_required': 'set default',
        'under_inspection': 'set default',
        'partially_approved': 'set default',
        'replacement_ready': 'set default',
        'dispatched': 'set default',
        'delivered_confirmed': 'set default',
        'failed_part_returned_scrapped': 'set default',
        'closed': 'set default',
    })

    # --- Replacement dispatch — POST /elegomotors/warranty/claims/<n>/dispatch
    dispatch_item = fields.Char(string='Dispatched Item')
    dispatch_serial = fields.Char(string='Dispatched Serial/Lot')
    dispatch_qty = fields.Integer(string='Dispatched Qty', default=1)
    dispatch_challan_number = fields.Char(string='Delivery Challan No.')
    dispatch_transporter = fields.Char(string='Transporter')
    dispatch_lr_awb_number = fields.Char(string='LR / AWB Number')
    dispatch_date = fields.Date()
    dispatch_expected_delivery_date = fields.Date(string='Expected Delivery')

    # --- Failed-part disposition — POST .../failed-part-action
    failed_part_action = fields.Selection([
        ('return', 'Returned to Elego'),
        ('scrap', 'Scrapped with company approval'),
        ('retain', 'Retained pending instruction'),
    ], copy=False)
    failed_part_action_evidence = fields.Image(max_width=1920, max_height=1920)
    failed_part_action_date = fields.Date()

    def action_mark_dispatched(self, vals):
        """vals: item, serial, qty, challan_number, transporter, lr_awb_number,
        dispatch_date, expected_delivery_date — see connect_warranty_api.py."""
        self.ensure_one()
        if self.state not in ('approved', 'partially_approved'):
            raise UserError('Only an approved claim can be marked as dispatched.')
        self.write({
            'dispatch_item': vals.get('item'),
            'dispatch_serial': vals.get('serial'),
            'dispatch_qty': vals.get('qty') or 1,
            'dispatch_challan_number': vals.get('challan_number'),
            'dispatch_transporter': vals.get('transporter'),
            'dispatch_lr_awb_number': vals.get('lr_awb_number'),
            'dispatch_date': vals.get('dispatch_date'),
            'dispatch_expected_delivery_date': vals.get('expected_delivery_date'),
            'state': 'dispatched',
        })
        self.message_post(
            body=f'Replacement dispatched via {vals.get("transporter") or "—"}, '
                 f'LR/AWB {vals.get("lr_awb_number") or "—"}.',
        )

    def action_record_failed_part_action(self, action, evidence_base64=None):
        self.ensure_one()
        if action not in ('return', 'scrap', 'retain'):
            raise UserError('failed_part_action must be one of: return, scrap, retain.')
        if self.state not in ('dispatched', 'delivered_confirmed'):
            raise UserError('The failed-part action can only be recorded after dispatch.')
        vals = {
            'failed_part_action': action,
            'failed_part_action_date': fields.Date.today(),
            'state': 'failed_part_returned_scrapped',
        }
        if evidence_base64:
            vals['failed_part_action_evidence'] = evidence_base64
        self.write(vals)
        self.message_post(body=f'Dealer recorded failed-part action: {action}.')
