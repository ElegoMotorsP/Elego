# -*- coding: utf-8 -*-
from odoo import api, fields, models, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError


class MrpUnbuild(models.Model):
    """Serial-Number-Wise Bike Unbuild.

    Extends Odoo's native Unbuild Order to reverse a specific bike serial
    back into its components, snapshot the component serials that were on
    that bike at the time (immune to the lot's own fields being overwritten
    later), and free those serials for the next bike. No MO is created by
    the unbuild: the user raises a new MO when they want one. Unbuilds done
    before that change may still carry the auto-created Rebuild MO
    (x_rebuild_mo_id), which stays visible for traceability.
    """
    _inherit = 'mrp.unbuild'

    x_original_mo_id = fields.Many2one(
        'mrp.production', string='Original Manufacturing Order',
        compute='_compute_original_mo_id', store=True,
        help='The MO that originally produced the bike serial being unbuilt.',
    )
    x_rebuild_mo_id = fields.Many2one(
        'mrp.production', string='Rebuild Manufacturing Order',
        readonly=True, copy=False,
        help='Older unbuilds only: the MO that used to be auto-created to rebuild '
             'this bike. Unbuilds no longer create an MO.',
    )

    # Snapshot of the bike's component serials at the moment of unbuild — kept
    # immutable here even if the same stock.lot's own fields are later
    # overwritten (e.g. reused with different components on rebuild).
    x_chassis_serial    = fields.Char(string='Chassis No. (Frame Plate)',   readonly=True, copy=False)
    x_motor_serial      = fields.Char(string='Hub Motor Serial No.',        readonly=True, copy=False)
    x_battery_serial    = fields.Char(string='Battery Pack Serial No.',     readonly=True, copy=False)
    x_controller_serial = fields.Char(string='Motor Controller Serial No.', readonly=True, copy=False)
    x_charger_serial    = fields.Char(string='Charger Serial No.',          readonly=True, copy=False)
    x_color             = fields.Char(string='Colour',                      readonly=True, copy=False)

    @api.depends('lot_id')
    def _compute_original_mo_id(self):
        for unbuild in self:
            mo = self.env['mrp.production']
            if unbuild.lot_id:
                mo = self.env['mrp.production'].search(
                    [('lot_producing_id', '=', unbuild.lot_id.id)], limit=1
                )
            unbuild.x_original_mo_id = mo.id if mo else False

    @api.model
    def _find_bom_for_product(self, product):
        """Resolve the BOM for a specific product variant, falling back to the
        template-generic BOM — same variant-first priority Odoo itself uses,
        without depending on a private core helper whose signature has moved
        across versions."""
        Bom = self.env['mrp.bom']
        return Bom.search([
            ('product_id', '=', product.id), ('type', '=', 'normal'),
        ], limit=1) or Bom.search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False), ('type', '=', 'normal'),
        ], limit=1)

    def _check_unbuild_rebuild_access(self):
        if (
            not self.env.su
            and self.env.uid != SUPERUSER_ID
            and not self.env.user.has_group('elegomotors_setup.group_unbuild_rebuild_operator')
        ):
            raise AccessError(
                'Only users with Unbuild / Rebuild access can create or validate '
                'Unbuild Orders. Ask Manohar (Admin) to grant this from Settings > Users.'
            )

    @api.model_create_multi
    def create(self, vals_list):
        self._check_unbuild_rebuild_access()
        records = super().create(vals_list)
        for unbuild in records:
            if not unbuild.lot_id:
                continue
            vals = {
                'x_chassis_serial':    unbuild.lot_id.x_chassis_serial,
                'x_motor_serial':      unbuild.lot_id.x_motor_serial,
                'x_battery_serial':    unbuild.lot_id.x_battery_serial,
                'x_controller_serial': unbuild.lot_id.x_controller_serial,
                'x_charger_serial':    unbuild.lot_id.x_charger_serial,
                'x_color':             unbuild.lot_id.x_color,
            }
            if not unbuild.location_dest_id:
                wip = self.env.ref(
                    'elegomotors_setup.location_ego_production_wip', raise_if_not_found=False
                )
                if wip:
                    vals['location_dest_id'] = wip.id
            unbuild.write(vals)
        return records

    def action_validate(self):
        self._check_unbuild_rebuild_access()
        result = super().action_validate()
        for unbuild in self:
            if unbuild.state == 'done' and unbuild.lot_id:
                # The bike no longer exists: free its component serials now
                # (the snapshot above keeps them for the next bike's MO).
                unbuild.lot_id._release_component_serials()
            # No Manufacturing Order is created here. An unbuild only takes the
            # bike apart and puts the parts back where the user chose; a new
            # MO is raised by the user when a bike is actually wanted. (It used
            # to be auto-created and confirmed on every unbuild, which left an
            # extra open MO holding a claim on the recovered parts.)
        return result
