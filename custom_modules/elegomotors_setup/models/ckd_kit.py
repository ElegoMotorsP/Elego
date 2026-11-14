# -*- coding: utf-8 -*-
"""CKD kit purchasing: one Kit BoM per model + colour, bought as a single PO
line, received as individual parts, priced by approved percentages.

What Odoo 18 already does (purchase_mrp) and we rely on:
  * a kit (phantom BoM) PO line explodes into its component moves on receipt;
  * the kit price is split across the components by each BoM line's
    "Cost Share (%)", which must total 100;
  * the PO line's received quantity counts whole kits.

What this file adds:
  * a CKD flag + an approval (who / when / version) on the kit BoM — any change
    to the components withdraws the approval;
  * a PO cannot be confirmed with a CKD kit whose allocation is not approved;
  * a FROZEN copy of the allocation per PO line, taken at confirmation, so a
    later BoM edit never changes the price of parts already on order;
  * that frozen share is what the exploded receipt moves are priced with.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero

APPROVER_GROUPS = ('purchase.group_purchase_manager', 'base.group_erp_manager')


class MrpBomCkd(models.Model):
    _inherit = 'mrp.bom'

    x_is_ckd_kit = fields.Boolean(
        string='CKD Kit', copy=False, tracking=True,
        help='A colour-wise CKD import kit. Bought as one PO line, received as '
             'individual parts. Needs an approved cost allocation before it can '
             'be put on a Purchase Order.',
    )
    x_ckd_bike_tmpl_id = fields.Many2one(
        'product.template', string='For Bike Model', copy=False,
        domain=[('x_is_ego_bike', '=', True)],
        help='The bike this kit is made for. "Update from Bike BoM" compares the kit '
             'with that bike\'s current Manufacturing BoM.')
    x_ckd_colour_id = fields.Many2one(
        'product.attribute.value', string='For Colour', copy=False)
    x_cost_share_total = fields.Float(
        string='Total Cost Share (%)', compute='_compute_x_cost_share_total',
        digits=(5, 2))
    x_cost_share_version = fields.Integer(
        string='Allocation Version', default=0, copy=False, readonly=True,
        help='Increases by one every time the allocation is approved.')
    x_cost_share_approved = fields.Boolean(
        string='Allocation Approved', copy=False, readonly=True, tracking=True)
    x_cost_share_approved_by = fields.Many2one(
        'res.users', string='Approved By', copy=False, readonly=True)
    x_cost_share_approved_on = fields.Datetime(
        string='Approved On', copy=False, readonly=True)

    @api.depends('bom_line_ids.cost_share')
    def _compute_x_cost_share_total(self):
        for bom in self:
            bom.x_cost_share_total = sum(bom.bom_line_ids.mapped('cost_share'))

    def _ckd_check_can_approve(self):
        self.ensure_one()
        if not self.x_is_ckd_kit or self.type != 'phantom':
            raise UserError(_('Only a CKD kit (BoM type "Kit") can have its cost allocation approved.'))
        if not self.bom_line_ids:
            raise UserError(_('Add the components of the kit first.'))
        zero = self.bom_line_ids.filtered(lambda l: float_is_zero(l.cost_share, precision_digits=2))
        if zero:
            raise UserError(_(
                'Every component needs a cost share above 0%%. Missing for: %s',
                ', '.join(zero.mapped('product_id.display_name'))))
        if float_compare(self.x_cost_share_total, 100.0, precision_digits=2) != 0:
            raise UserError(_(
                'The cost shares of "%(kit)s" total %(total).2f%% — they must total exactly 100%%.',
                kit=self.product_tmpl_id.display_name, total=self.x_cost_share_total))

    def _ckd_user_can_approve(self):
        user = self.env.user
        return self.env.su or any(user.has_group(g) for g in APPROVER_GROUPS)

    def action_approve_cost_share(self):
        if not self._ckd_user_can_approve():
            raise AccessError(_('Only a Purchase Manager or an Administrator can approve a cost allocation.'))
        for bom in self:
            bom._ckd_check_can_approve()
            version = bom.x_cost_share_version + 1
            bom.sudo().write({
                'x_cost_share_approved': True,
                'x_cost_share_version': version,
                'x_cost_share_approved_by': self.env.user.id,
                'x_cost_share_approved_on': fields.Datetime.now(),
            })
            bom.message_post(body=_(
                'Cost allocation version %(v)s approved by %(user)s: %(rows)s',
                v=version, user=self.env.user.name,
                rows=', '.join(
                    '%s %.2f%%' % (l.product_id.display_name, l.cost_share)
                    for l in bom.bom_line_ids)))
        return True

    def action_update_from_bike(self):
        """Open the New CKD Kit wizard in "update" mode for this kit: its parts
        are compared with the bike's current BoM so new / removed / changed
        parts can be reviewed before they are applied."""
        self.ensure_one()
        if not self._ckd_user_can_approve():
            raise AccessError(_('Only a Purchase Manager or an Administrator can update a CKD kit.'))
        wizard = self.env['elegomotors.ckd.kit.wizard'].create({
            'mode': 'update',
            'kit_bom_id': self.id,
            'bike_tmpl_id': self.x_ckd_bike_tmpl_id.id or False,
            'colour_value_id': self.x_ckd_colour_id.id or False,
        })
        wizard._reload_for_update()
        return wizard._reopen()

    def action_withdraw_cost_share_approval(self):
        if not self._ckd_user_can_approve():
            raise AccessError(_('Only a Purchase Manager or an Administrator can withdraw an approval.'))
        self._ckd_withdraw_approval(_('withdrawn by %s', self.env.user.name))
        return True

    def _ckd_withdraw_approval(self, reason):
        """Drop the approval of approved CKD kits (a component changed).
        Open POs are unaffected: they carry their own frozen copy."""
        for bom in self.filtered(lambda b: b.x_is_ckd_kit and b.x_cost_share_approved):
            bom.sudo().write({
                'x_cost_share_approved': False,
                'x_cost_share_approved_by': False,
                'x_cost_share_approved_on': False,
            })
            bom.message_post(body=_(
                'Cost allocation approval (version %(v)s) withdrawn — %(why)s. '
                'It must be approved again before the kit can go on a new PO. '
                'Purchase Orders already confirmed keep the allocation they were frozen with.',
                v=bom.x_cost_share_version, why=reason))


class MrpBomLineCkd(models.Model):
    _inherit = 'mrp.bom.line'

    _CKD_WATCHED = ('cost_share', 'product_qty', 'product_id', 'product_uom_id')

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.bom_id._ckd_withdraw_approval(_('a component was added'))
        return lines

    def write(self, vals):
        watched = any(f in vals for f in self._CKD_WATCHED)
        boms = self.bom_id if watched else self.env['mrp.bom']
        res = super().write(vals)
        if boms:
            boms._ckd_withdraw_approval(_('a component line was changed'))
        return res

    def unlink(self):
        boms = self.bom_id
        res = super().unlink()
        boms.exists()._ckd_withdraw_approval(_('a component was removed'))
        return res


class CkdKitAllocation(models.Model):
    """The cost allocation of a CKD kit as it was when the PO line was
    confirmed — frozen, so the price of parts already on order never moves."""
    _name = 'elegomotors.ckd.kit.allocation'
    _description = 'Frozen CKD Kit Cost Allocation'
    _order = 'id desc'

    purchase_line_id = fields.Many2one(
        'purchase.order.line', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one(
        'purchase.order', related='purchase_line_id.order_id', store=True, index=True)
    product_id = fields.Many2one('product.product', string='Kit', required=True)
    bom_id = fields.Many2one('mrp.bom', string='Kit BoM', ondelete='set null')
    version = fields.Integer(string='Allocation Version')
    frozen_on = fields.Datetime(default=fields.Datetime.now, readonly=True)
    frozen_by = fields.Many2one(
        'res.users', default=lambda self: self.env.user, readonly=True)
    line_ids = fields.One2many(
        'elegomotors.ckd.kit.allocation.line', 'allocation_id', string='Components')
    total_share = fields.Float(compute='_compute_total_share', digits=(5, 2))

    @api.depends('line_ids.cost_share')
    def _compute_total_share(self):
        for rec in self:
            rec.total_share = sum(rec.line_ids.mapped('cost_share'))

    def _shares_by_bom_line(self):
        self.ensure_one()
        return {l.bom_line_id.id: l.cost_share for l in self.line_ids if l.bom_line_id}

    def _shares_by_product(self):
        self.ensure_one()
        return {l.product_id.id: l.cost_share for l in self.line_ids}


class CkdKitAllocationLine(models.Model):
    _name = 'elegomotors.ckd.kit.allocation.line'
    _description = 'Frozen CKD Kit Cost Allocation Line'
    _order = 'id'

    allocation_id = fields.Many2one(
        'elegomotors.ckd.kit.allocation', required=True, ondelete='cascade', index=True)
    bom_line_id = fields.Many2one('mrp.bom.line', ondelete='set null')
    product_id = fields.Many2one('product.product', string='Component', required=True)
    qty_per_kit = fields.Float(string='Qty per Kit', digits='Product Unit of Measure')
    cost_share = fields.Float(string='Cost Share (%)', digits=(5, 2))


class PurchaseOrderLineCkd(models.Model):
    _inherit = 'purchase.order.line'

    x_ckd_allocation_ids = fields.One2many(
        'elegomotors.ckd.kit.allocation', 'purchase_line_id', string='Frozen Allocation')

    def _ckd_kit_bom(self):
        """The CKD kit BoM of this line's product, or an empty recordset."""
        self.ensure_one()
        if self.display_type or not self.product_id:
            return self.env['mrp.bom']
        bom = self.env['mrp.bom'].sudo()._bom_find(
            self.product_id, company_id=self.company_id.id, bom_type='phantom',
        )[self.product_id]
        return bom if bom and bom.x_is_ckd_kit else self.env['mrp.bom']

    def _ckd_allocation(self):
        self.ensure_one()
        return self.x_ckd_allocation_ids[:1]

    def _ckd_cost_share_for(self, bom_line, explode_share=None):
        """Cost share (%) for a component of this line: the frozen figure when
        the line has one, else the figure Odoo worked out from the live BoM."""
        self.ensure_one()
        alloc = self._ckd_allocation()
        if alloc:
            share = alloc._shares_by_bom_line().get(bom_line.id)
            if share is None:
                share = alloc._shares_by_product().get(bom_line.product_id.id)
            if share is not None:
                return share
        return explode_share


class PurchaseOrderCkd(models.Model):
    _inherit = 'purchase.order'

    x_has_ckd_kit = fields.Boolean(
        string='Has CKD Kit', compute='_compute_x_has_ckd_kit')

    @api.depends('order_line.product_id')
    def _compute_x_has_ckd_kit(self):
        for po in self:
            po.x_has_ckd_kit = bool(po._ckd_kit_lines())

    def _ckd_kit_lines(self):
        """PO lines whose product is a CKD kit. One BoM lookup per order, and
        none at all while no CKD kit exists."""
        lines = self.env['purchase.order.line']
        Bom = self.env['mrp.bom'].sudo()
        if not Bom.search_count([('x_is_ckd_kit', '=', True)], limit=1):
            return lines
        for po in self:
            order_lines = po.order_line.filtered(lambda l: not l.display_type and l.product_id)
            if not order_lines:
                continue
            boms = Bom._bom_find(order_lines.product_id, company_id=po.company_id.id, bom_type='phantom')
            for line in order_lines:
                bom = boms.get(line.product_id)
                if bom and bom.x_is_ckd_kit:
                    lines |= line
        return lines

    def button_confirm(self):
        for po in self:
            for line in po._ckd_kit_lines():
                bom = line._ckd_kit_bom()
                if not bom.x_cost_share_approved:
                    raise UserError(_(
                        '"%(kit)s" is a CKD kit whose cost allocation is not approved. '
                        'Open its Bill of Materials, check the cost shares total 100%% '
                        'and press "Approve Cost Allocation" before confirming this order.',
                        kit=line.product_id.display_name))
        res = super().button_confirm()
        self._ckd_freeze_allocations()
        return res

    def _ckd_freeze_allocations(self):
        """Keep a frozen copy of each CKD kit line's allocation. Taken at
        confirmation; retaken only if the BoM was re-approved since AND nothing
        of that line has been received yet."""
        Allocation = self.env['elegomotors.ckd.kit.allocation'].sudo()
        for po in self:
            if po.state not in ('purchase', 'done', 'to approve'):
                continue
            for line in po._ckd_kit_lines():
                bom = line._ckd_kit_bom()
                if not bom.x_cost_share_approved:
                    continue
                current = line._ckd_allocation()
                if current:
                    started = any(m.state == 'done' for m in line.move_ids)
                    if started or (current.bom_id == bom and current.version == bom.x_cost_share_version):
                        continue
                    current.sudo().unlink()
                Allocation.create({
                    'purchase_line_id': line.id,
                    'product_id': line.product_id.id,
                    'bom_id': bom.id,
                    'version': bom.x_cost_share_version,
                    'line_ids': [(0, 0, {
                        'bom_line_id': bl.id,
                        'product_id': bl.product_id.id,
                        'qty_per_kit': bl.product_qty,
                        'cost_share': bl.cost_share,
                    }) for bl in bom.bom_line_ids],
                })
                po.message_post(body=_(
                    'CKD kit %(kit)s: cost allocation version %(v)s frozen for this order '
                    '(later changes to the kit BoM will not affect it).',
                    kit=line.product_id.display_name, v=bom.x_cost_share_version))


class StockMoveCkd(models.Model):
    _inherit = 'stock.move'

    def _get_kit_ratio(self):
        """Value per received part of a CKD kit = kit price x its cost share /
        parts per kit — whatever has been received, cancelled or is still to come.

        Odoo divides by the demand of the moves that are not cancelled. Here a
        short delivery cancels its remainder (a new GRN is made for the rest), so
        for 90 of 100 chassis Odoo would spread the whole 100-kit share over the
        90 parts received and overvalue them by 11%. For a CKD kit the divisor
        is the full ordered demand instead, so every part carries exactly its
        own share and a short delivery is valued at what actually arrived."""
        line = self.purchase_line_id
        if line and self.bom_line_id and line.product_id != self.product_id and line._ckd_kit_bom():
            kits = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_id)
            bom = self.bom_line_id.bom_id
            per_kit = self.bom_line_id.product_uom_id._compute_quantity(
                self.bom_line_id.product_qty, self.product_id.uom_id) / (bom.product_qty or 1.0)
            demand = kits * per_kit
            if demand:
                return 1.0 / demand
        return super()._get_kit_ratio()

    def _generate_all_phantom_moves(self, exploded_lines_data):
        """Price the exploded kit parts with the allocation frozen on the PO
        line instead of the live BoM percentages."""
        vals_list = super()._generate_all_phantom_moves(exploded_lines_data)
        line = self.purchase_line_id
        if not line or not vals_list:
            return vals_list
        alloc = line._ckd_allocation()
        if not alloc:
            return vals_list
        by_line = alloc._shares_by_bom_line()
        by_product = alloc._shares_by_product()
        for vals in vals_list:
            share = by_line.get(vals.get('bom_line_id'))
            if share is None:
                share = by_product.get(vals.get('product_id'))
            if share is not None:
                vals['cost_share'] = share
        return vals_list
