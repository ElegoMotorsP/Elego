# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import date
from dateutil.relativedelta import relativedelta


class ProductWarranty(models.Model):
    _name = "product.warranty"
    _description = "Product Warranty"
    _order = "id desc"

    name = fields.Char(
        string="Warranty Reference",
        required=True,
        copy=False,
        default="New",
    )

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
    )

    serial_number = fields.Char( 
        string="Serial/Lot",
        help="Auto-filled from Delivery Order (lot/serial number).",
    )

    start_date = fields.Date(
        string="Start Date",
        help="Auto-set from delivery date.",
    )

    end_date = fields.Date(
        string="End Date",
        help="Auto-set from product warranty months.",
    )

    warranty_terms = fields.Text(
        string="Warranty Terms"
    )

    partner_id = fields.Many2one(
        "res.partner",
        string="Owner/Customer",
    )

    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sale Order",
        copy=False,
    )

    picking_id = fields.Many2one(
        "stock.picking",
        string="Delivery Order",
        copy=False,
    )

    # -----------------------------------------------------------
    # CREATE WITH AUTO-POPULATE LOGIC
    # -----------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:

            # 1) Sequence
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "product.warranty") or "/"

            # 2) Copy partner/picking from sale order
            if vals.get("sale_order_id"):
                so = self.env["sale.order"].browse(vals["sale_order_id"])

                if so.partner_id and not vals.get("partner_id"):
                    vals["partner_id"] = so.partner_id.id

                # Auto-detect delivery
                if not vals.get("picking_id"):
                    picking = self._get_latest_done_delivery(so)
                    if picking:
                        vals["picking_id"] = picking.id

            # 3) Picking-based fields
            if vals.get("picking_id"):
                picking = self.env["stock.picking"].browse(vals["picking_id"])

                # Serial auto-fill
                if not vals.get("serial_number"):
                    lots = picking.move_line_ids.mapped("lot_id.name")
                    lots = [l for l in lots if l]
                    if lots:
                        vals["serial_number"] = ", ".join(lots)

                # Start date auto-fill
                if not vals.get("start_date"):
                    dt = picking.date_done or picking.scheduled_date or fields.Date.today()
                    vals["start_date"] = dt.date() if hasattr(
                        dt, "date") else dt

            # 4) Warranty template logic
            if vals.get("product_id"):
                product = self.env["product.product"].browse(
                    vals["product_id"])
                tmpl = product.product_tmpl_id

                # Warranty terms
                if tmpl.warranty_terms and not vals.get("warranty_terms"):
                    vals["warranty_terms"] = tmpl.warranty_terms

                # Warranty duration → end date
                months = tmpl.warranty_duration_months or 0
                if months and vals.get("start_date") and not vals.get("end_date"):
                    start_dt = fields.Date.from_string(vals["start_date"])
                    vals["end_date"] = start_dt + relativedelta(months=months)

        return super().create(vals_list)

    # -----------------------------------------------------------
    # Get latest delivery for sale order
    # -----------------------------------------------------------
    def _get_latest_done_delivery(self, so):
        pickings = so.picking_ids.filtered(
            lambda p: p.picking_type_code == "outgoing" and p.state == "done"
        )
        if pickings:
            return pickings.sorted(
                key=lambda p: p.date_done or p.scheduled_date
            )[-1]
        return None

    # -----------------------------------------------------------
    # Warranty valid?
    # -----------------------------------------------------------
    def is_active(self):
        today = date.today()
        return any([(not w.end_date) or (w.end_date >= today) for w in self])
