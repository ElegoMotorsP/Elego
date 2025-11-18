from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WarrantyClaim(models.Model):
    _name = "warranty.claim"
    _description = "Warranty Claim"

    # =========================================================================
    # CORE FIELDS
    # =========================================================================
    name = fields.Char(string="Claim Number", readonly=True, default="/")

    partner_id = fields.Many2one(
        "res.partner", string="Customer", required=True
    )

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        domain="[('id', 'in', product_ids_available)]",
    )

    product_ids_available = fields.Many2many(
        "product.product", compute="_compute_products_for_customer"
    )

    serial_number = fields.Char(string="Serial Number")

    serial_id = fields.Many2one(
        "stock.lot",
        string="Serial",
        domain="[('id', 'in', serials_available)]",
    )

    serials_available = fields.Many2many(
        "stock.lot", compute="_compute_serials_for_product"
    )

    warranty_id = fields.Many2one("product.warranty", string="Warranty")

    claim_reason = fields.Text(string="Claim Reason")

    quantity = fields.Float(default=1)
    warehouse_id = fields.Many2one("stock.warehouse", required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_warranty', 'In Warranty'),
        ('out_of_warranty', 'Out of Warranty'),
        ('repair_in_progress', 'Repair In Progress'),
        ('replaced', 'Replaced'),
        ('closed', 'Closed'),
    ], default='draft')

    # =========================================================================
    # CREATE SEQUENCE
    # =========================================================================
    @api.model
    def create(self, vals):
        if vals.get("name", "/") == "/":
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "warranty.claim"
            ) or "/"
        return super().create(vals)

    # =========================================================================
    # STEP 1 → When customer selected → Load products delivered to customer
    # =========================================================================
    @api.depends("partner_id")
    def _compute_products_for_customer(self):
        for rec in self:
            if not rec.partner_id:
                rec.product_ids_available = [(5, 0, 0)]
                continue

            pickings = self.env["stock.picking"].search([
                ("partner_id", "=", rec.partner_id.id),
                ("picking_type_code", "=", "outgoing"),
                ("state", "=", "done"),
            ])

            product_ids = pickings.move_line_ids.mapped("product_id").ids
            rec.product_ids_available = [(6, 0, product_ids)]

    # =========================================================================
    # STEP 2 → When product selected → Load serials delivered to customer
    # =========================================================================
    @api.depends("product_id", "partner_id")
    def _compute_serials_for_product(self):
        for rec in self:

            if not rec.partner_id or not rec.product_id:
                print("DEBUG → Missing customer or product")
                rec.serials_available = [(5, 0, 0)]
                continue

            pickings = self.env["stock.picking"].search([
                ("partner_id", "=", rec.partner_id.id),
                ("picking_type_code", "=", "outgoing"),
                ("state", "=", "done"),
            ])


            lot_ids = pickings.move_line_ids.filtered(
                lambda l: l.product_id.id == rec.product_id.id
            ).mapped("lot_id").ids


            rec.serials_available = [(6, 0, lot_ids)]

    # =========================================================================
    # STEP 3 → When serial selected → Load warranty record & auto-fill fields
    # =========================================================================
    @api.onchange("serial_id")
    def _onchange_serial(self):
        if not self.serial_id or not self.product_id or not self.partner_id:
            return

        warranty = self.env["product.warranty"].search([
            ("partner_id", "=", self.partner_id.id),
            ("product_id", "=", self.product_id.id),
            ("serial_number", "=", self.serial_id.name),
        ], limit=1)

        if warranty:
            self.warranty_id = warranty.id
            self.serial_number = warranty.serial_number
            self.claim_reason = warranty.warranty_terms or ""

            # Compute warranty validity
            today = fields.Date.today()
            self.state = (
                "in_warranty"
                if (not warranty.end_date or warranty.end_date >= today)
                else "out_of_warranty"
            )

    # =========================================================================
    # REPLACEMENT WORKFLOW (RETURN → SCRAP → ISSUE NEW PRODUCT)
    # =========================================================================
    def action_replace(self):
        for rec in self:

            # ============================================================
            # Get universal system locations (safe for Odoo 18+)
            # ============================================================

            # Internal Stock
            stock_loc = self.env["stock.location"].search([
                ("usage", "=", "internal")
            ], limit=1)
            if not stock_loc:
                raise UserError("No internal stock location found.")

            # Customer Location
            customer_loc = self.env["stock.location"].search([
                ("usage", "=", "customer")
            ], limit=1)
            if not customer_loc:
                raise UserError("No customer stock location found.")

            # Scrap / Inventory Adjustment Location
            scrap_loc = self.env["stock.location"].search([
                ("usage", "=", "inventory")
            ], limit=1)
            if not scrap_loc:
                raise UserError("No scrap/inventory location found.")

            # Get default picking types
            picking_in = self.env["stock.picking.type"].search([
                ("code", "=", "incoming")
            ], limit=1)

            picking_out = self.env["stock.picking.type"].search([
                ("code", "=", "outgoing")
            ], limit=1)

            if not picking_in or not picking_out:
                raise UserError("Picking types are not configured properly.")

            # ============================================================
            # 1️⃣ RETURN PICKING (Customer → Stock)
            # ============================================================
            incoming = self.env["stock.picking"].create({
                "picking_type_id": picking_in.id,
                "partner_id": rec.partner_id.id,
                "origin": f"Warranty Return {rec.name}",
                "location_id": customer_loc.id,
                "location_dest_id": stock_loc.id,
            })

            self.env["stock.move"].create({
                "name": rec.product_id.name,
                "product_id": rec.product_id.id,
                "product_uom_qty": rec.quantity,
                "product_uom": rec.product_id.uom_id.id,
                "picking_id": incoming.id,
                "location_id": customer_loc.id,
                "location_dest_id": stock_loc.id,
            })

            # ============================================================
            # 2️⃣ SCRAP RETURNED PRODUCT
            # ============================================================
            self.env["stock.scrap"].create({
                "product_id": rec.product_id.id,
                "scrap_qty": rec.quantity,
                "product_uom_id": rec.product_id.uom_id.id,
                "location_id": stock_loc.id,
                "scrap_location_id": scrap_loc.id,
            })

            # ============================================================
            # 3️⃣ NEW DELIVERY (Stock → Customer)
            # ============================================================
            outgoing = self.env["stock.picking"].create({
                "picking_type_id": picking_out.id,
                "partner_id": rec.partner_id.id,
                "origin": f"Warranty Replacement {rec.name}",
                "location_id": stock_loc.id,
                "location_dest_id": customer_loc.id,
            })

            self.env["stock.move"].create({
                "name": rec.product_id.name,
                "product_id": rec.product_id.id,
                "product_uom_qty": rec.quantity,
                "product_uom": rec.product_id.uom_id.id,
                "picking_id": outgoing.id,
                "location_id": stock_loc.id,
                "location_dest_id": customer_loc.id,
            })

            rec.state = "replaced"

    # =========================================================================
    # REPAIR WORKFLOW (INWARD ONLY)
    # =========================================================================
    def action_repair(self):
        for rec in self:
            wh = rec.warehouse_id

            incoming = self.env["stock.picking"].create({
                "picking_type_id": wh.in_type_id.id,
                "partner_id": rec.partner_id.id,
                "origin": f"Repair Inward {rec.name}",
                "location_id": rec.partner_id.property_stock_customer.id,
                "location_dest_id": wh.wh_input_stock_loc_id.id,
            })

            self.env["stock.move"].create({
                "name": rec.product_id.name,
                "product_id": rec.product_id.id,
                "product_uom_qty": rec.quantity,
                "product_uom": rec.product_id.uom_id.id,
                "picking_id": incoming.id,
                "location_id": rec.partner_id.property_stock_customer.id,
                "location_dest_id": wh.wh_input_stock_loc_id.id,
            })

            rec.state = "repair_in_progress"

    # =========================================================================
    # CLOSE CLAIM
    # =========================================================================
    def action_close(self):
        self.state = "closed"

    # =========================================================================
    # CHECK WARRANTY BUTTON (OPTIONAL)
    # =========================================================================
    def action_check_warranty(self):
        for rec in self:
            if not rec.warranty_id:
                rec.state = "out_of_warranty"
                continue

            today = fields.Date.today()
            rec.state = "in_warranty" if (
                not rec.warranty_id.end_date or rec.warranty_id.end_date >= today) else "out_of_warranty"
