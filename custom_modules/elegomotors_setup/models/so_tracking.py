# -*- coding: utf-8 -*-
"""All Sales Order Tracking Report.

One row per Sales Order LINE, not per order — the client's own "Sales Master"
Excel is explicit about this: "If one order contains 10 products, the report
must show 10 rows under the same SO number." Mirrors the shape of PO Tracking
(see po_tracking.py) on the sales side: Quotation -> Approval -> Dispatch ->
Invoice.

Wherever Odoo already computes a figure the client's report wants (delivered/
invoiced quantities, invoice status, the line's own price/tax amounts), this
reuses that field directly rather than recomputing it, so the report can never
disagree with the Sales Order itself. Only what Odoo does not already track
— the quotation/approval timeline, dispatch references, and the combined
"Current Stage" — is added here, as small stored fields so the list's own
filters, grouping and native Export work on it.
"""
from odoo import api, fields, models
from odoo.tools import float_compare, float_is_zero

SO_TRACKING_STAGES = [
    ('quotation', 'Quotation Pending'),
    ('rejected', 'Rejected'),
    ('approval', 'Approval Pending'),
    ('dispatch_pending', 'Approved - Dispatch Pending'),
    ('partial_dispatch', 'Partially Dispatched'),
    ('invoice_pending', 'Fully Dispatched - Invoice Pending'),
    ('partial_invoice', 'Partially Invoiced'),
    ('completed', 'Fully Invoiced'),
    ('cancelled', 'Cancelled'),
]


class SaleOrderTracking(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # Dates the base model does not keep: when the order was actually
    # confirmed, and when it was first approved.
    # ------------------------------------------------------------------

    x_trk_so_date = fields.Datetime(
        string='SO Date', copy=False, readonly=True,
        help='When this order was first confirmed into a Sales Order '
             '(state became "sale") — separate from the Quotation Date.')
    x_trk_approval_date = fields.Datetime(
        string='Approval Date', copy=False, readonly=True,
        help='When Accounts or MD first approved this order.')

    def write(self, vals):
        result = super().write(vals)
        if vals.get('state') == 'sale':
            for order in self:
                if not order.x_trk_so_date:
                    order.x_trk_so_date = fields.Datetime.now()
        return result

    def _on_approval_recorded(self):
        for order in self:
            if (order.approval_accounts or order.approval_manohar) and not order.x_trk_approval_date:
                order.x_trk_approval_date = fields.Datetime.now()
        return super()._on_approval_recorded()

    # ------------------------------------------------------------------
    # Labels derived from the order's own state/approval fields
    # ------------------------------------------------------------------

    x_trk_quotation_no = fields.Char(
        string='Quotation No.', compute='_compute_x_trk_quotation_no', store=True,
        help='The quotation-era number (EGO-QUO-...), kept even after the '
             'order is renamed to its SO number.')
    x_trk_quotation_status = fields.Char(
        string='Quotation Status', compute='_compute_x_trk_quotation_status', store=True)
    x_trk_approval_status = fields.Char(
        string='Approval Status', compute='_compute_x_trk_approval_status', store=True)
    x_trk_approved_by = fields.Char(
        string='Approved By', compute='_compute_x_trk_approved_by', store=True)

    @api.depends('x_quotation_number', 'name')
    def _compute_x_trk_quotation_no(self):
        for order in self:
            # x_quotation_number is only set once the order is renamed to its SO
            # number (_assign_sale_order_number); until then order.name IS still
            # the quotation number. Falling back to name rather than blanking it
            # also covers orders confirmed before x_quotation_number existed.
            order.x_trk_quotation_no = order.x_quotation_number or order.name

    @api.depends('state')
    def _compute_x_trk_quotation_status(self):
        labels = {
            'draft': 'Quotation', 'sent': 'Quotation Sent', 'accepted': 'Quotation Accepted',
            'sale': 'Converted to SO', 'done': 'Converted to SO', 'cancel': 'Cancelled',
        }
        for order in self:
            order.x_trk_quotation_status = labels.get(order.state, order.state or '')

    @api.depends('state', 'pending_approval', 'approval_accounts', 'approval_manohar', 'rejection_reason')
    def _compute_x_trk_approval_status(self):
        for order in self:
            if order.state == 'cancel':
                order.x_trk_approval_status = 'Cancelled'
            elif order.state == 'draft' and order.rejection_reason:
                order.x_trk_approval_status = 'Rejected'
            elif order.pending_approval:
                order.x_trk_approval_status = 'Pending'
            elif order.approval_accounts or order.approval_manohar:
                order.x_trk_approval_status = 'Approved'
            else:
                order.x_trk_approval_status = 'Not Submitted'

    @api.depends('approval_accounts', 'approval_manohar')
    def _compute_x_trk_approved_by(self):
        for order in self:
            names = []
            if order.approval_accounts:
                names.append('Accounts (Rajshri)')
            if order.approval_manohar:
                names.append('MD (Manohar)')
            order.x_trk_approved_by = ' and '.join(names)


class SaleOrderLineTracking(models.Model):
    _inherit = 'sale.order.line'

    # ------------------------------------------------------------------
    # Order-level columns, carried onto the line so the list/search/Excel
    # (all keyed on sale.order.line, one row per item) can show and group
    # on them without a dotted path.
    # ------------------------------------------------------------------

    x_trk_quotation_no = fields.Char(
        related='order_id.x_trk_quotation_no', store=True, string='Quotation No.')
    x_trk_quotation_date = fields.Datetime(
        related='order_id.create_date', store=True, string='Quotation Date')
    x_trk_quotation_status = fields.Char(
        related='order_id.x_trk_quotation_status', store=True, string='Quotation Status')
    x_trk_approval_status = fields.Char(
        related='order_id.x_trk_approval_status', store=True, string='Approval Status')
    x_trk_so_no = fields.Char(
        related='order_id.sale_order_number', store=True, string='SO No.')
    x_trk_so_date = fields.Datetime(
        related='order_id.x_trk_so_date', store=True, string='SO Date')
    x_trk_approved_by = fields.Char(
        related='order_id.x_trk_approved_by', store=True, string='Approved By')
    x_trk_approval_date = fields.Datetime(
        related='order_id.x_trk_approval_date', store=True, string='Approval Date')
    x_trk_customer_po_ref = fields.Char(
        related='order_id.client_order_ref', store=True, string='Customer PO Ref.')
    x_trk_product_code = fields.Char(
        related='product_id.default_code', store=True, string='Product Code')

    x_trk_colour = fields.Char(string='Colour', compute='_compute_x_trk_colour', store=True)

    @api.depends('product_id')
    def _compute_x_trk_colour(self):
        for line in self:
            values = line.product_id.product_template_attribute_value_ids.filtered(
                lambda v: 'colour' in v.attribute_id.name.lower() or 'color' in v.attribute_id.name.lower())
            line.x_trk_colour = ', '.join(values.mapped('name'))

    # ------------------------------------------------------------------
    # Dispatch: gross delivered / returned, split out of the standard
    # qty_delivered (which already nets the two against each other), plus
    # the DO reference(s) and dispatch date.
    # ------------------------------------------------------------------

    x_trk_gross_delivered_qty = fields.Float(
        string='Delivered Qty', compute='_compute_x_trk_dispatch', store=True,
        digits='Product Unit of Measure')
    x_trk_return_qty = fields.Float(
        string='Return Qty', compute='_compute_x_trk_dispatch', store=True,
        digits='Product Unit of Measure')
    x_trk_do_refs = fields.Char(
        string='DO / Out Order No.', compute='_compute_x_trk_dispatch', store=True)
    x_trk_dispatch_date = fields.Datetime(
        string='Dispatch Date', compute='_compute_x_trk_dispatch', store=True)
    x_trk_pending_dispatch_qty = fields.Float(
        string='Pending Dispatch Qty', compute='_compute_x_trk_pending_dispatch', store=True,
        digits='Product Unit of Measure',
        help='MAX(0, Ordered Qty - Net Delivered Qty); 0 on a cancelled order.')
    x_trk_delivery_status = fields.Char(
        string='Delivery Status', compute='_compute_x_trk_delivery_status', store=True)

    @api.depends('move_ids.state', 'move_ids.quantity', 'move_ids.location_dest_id', 'move_ids.location_id')
    def _compute_x_trk_dispatch(self):
        for line in self:
            delivered = returned = 0.0
            do_names, dispatch_dates = [], []
            for move in line.move_ids.filtered(lambda m: m.state == 'done'):
                qty = move.product_uom._compute_quantity(move.quantity, line.product_uom)
                if move.location_dest_id.usage == 'customer':
                    delivered += qty
                    if move.picking_id:
                        do_names.append(move.picking_id.name)
                    if move.date:
                        dispatch_dates.append(move.date)
                elif move.location_id.usage == 'customer':
                    returned += qty
            line.x_trk_gross_delivered_qty = delivered
            line.x_trk_return_qty = returned
            line.x_trk_do_refs = ', '.join(dict.fromkeys(do_names))
            line.x_trk_dispatch_date = max(dispatch_dates) if dispatch_dates else False

    @api.depends('product_uom_qty', 'qty_delivered', 'order_id.state')
    def _compute_x_trk_pending_dispatch(self):
        for line in self:
            if line.order_id.state == 'cancel':
                line.x_trk_pending_dispatch_qty = 0.0
            else:
                line.x_trk_pending_dispatch_qty = max(line.product_uom_qty - line.qty_delivered, 0.0)

    @api.depends('qty_delivered', 'product_uom_qty', 'order_id.state', 'order_id.picking_ids.state')
    def _compute_x_trk_delivery_status(self):
        for line in self:
            order = line.order_id
            if order.state == 'cancel':
                line.x_trk_delivery_status = 'Cancelled'
                continue
            rounding = line.product_uom.rounding or 0.01
            has_outgoing = bool(order.picking_ids.filtered(
                lambda p: p.picking_type_code == 'outgoing' and p.state != 'cancel'))
            if float_is_zero(line.qty_delivered, precision_rounding=rounding):
                line.x_trk_delivery_status = 'Pending' if has_outgoing else 'Not Created'
            elif float_compare(line.qty_delivered, line.product_uom_qty, precision_rounding=rounding) >= 0:
                line.x_trk_delivery_status = 'Delivered'
            else:
                line.x_trk_delivery_status = 'Partial'

    # ------------------------------------------------------------------
    # Invoice reference string (qty_invoiced / qty_to_invoice / invoice_status
    # are already standard fields on this model — reused as-is in the view).
    # ------------------------------------------------------------------

    x_trk_invoice_refs = fields.Char(
        string='Invoice No. / Date', compute='_compute_x_trk_invoice_refs', store=True)

    @api.depends('invoice_lines.move_id.state', 'invoice_lines.move_id.name',
                 'invoice_lines.move_id.invoice_date', 'invoice_lines.move_id.move_type')
    def _compute_x_trk_invoice_refs(self):
        for line in self:
            moves = line.invoice_lines.move_id.filtered(
                lambda m: m.move_type in ('out_invoice', 'out_refund') and m.state == 'posted')
            refs = []
            for move in moves.sorted('invoice_date'):
                label = move.name if move.name and move.name != '/' else 'Draft'
                if move.invoice_date:
                    label = '%s (%s)' % (label, move.invoice_date.strftime('%d/%m/%Y'))
                refs.append(label)
            line.x_trk_invoice_refs = ', '.join(refs)

    # ------------------------------------------------------------------
    # Current Stage: the single column that tells where this item sits in
    # Quotation -> Approval -> Dispatch -> Invoice.
    # ------------------------------------------------------------------

    x_trk_stage = fields.Selection(
        SO_TRACKING_STAGES, string='Current Stage', compute='_compute_x_trk_stage', store=True)

    @api.depends(
        'order_id.state', 'order_id.pending_approval', 'order_id.rejection_reason',
        'product_uom_qty', 'qty_delivered', 'qty_invoiced', 'display_type',
    )
    def _compute_x_trk_stage(self):
        for line in self:
            order = line.order_id
            if order.state == 'cancel':
                line.x_trk_stage = 'cancelled'
                continue
            if order.state == 'draft' and order.rejection_reason:
                line.x_trk_stage = 'rejected'
                continue
            if order.state in ('draft', 'sent'):
                line.x_trk_stage = 'quotation'
                continue
            if order.state == 'accepted' or order.pending_approval:
                line.x_trk_stage = 'approval'
                continue
            # order.state in ('sale', 'done'), approved
            rounding = line.product_uom.rounding or 0.01
            if float_is_zero(line.qty_delivered, precision_rounding=rounding):
                line.x_trk_stage = 'dispatch_pending'
            elif float_compare(line.qty_delivered, line.product_uom_qty, precision_rounding=rounding) < 0:
                line.x_trk_stage = 'partial_dispatch'
            elif float_is_zero(line.qty_invoiced, precision_rounding=rounding):
                line.x_trk_stage = 'invoice_pending'
            elif float_compare(line.qty_invoiced, line.qty_delivered, precision_rounding=rounding) < 0:
                line.x_trk_stage = 'partial_invoice'
            else:
                line.x_trk_stage = 'completed'

    def _trk_reportable(self):
        """Real product lines only — no section/note headers, no the
        down-payment pseudo-line sale_management adds on invoicing."""
        return self.filtered(lambda l: not l.display_type and not l.is_downpayment and l.product_id)

    def action_open_so_tracking_export(self):
        """The "Download Excel" button of the report: opens the download window,
        for the lines ticked in the list (or, with none ticked, for the
        filters of the window it opens)."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Download SO Tracking (Excel)',
            'res_model': 'elegomotors.so.tracking.export',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_line_ids': [(6, 0, self.ids)]},
        }
