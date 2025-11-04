from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    vehicle_details = fields.Text(
        string="Vehicle Details",
        compute="_compute_vehicle_details",
        store=False,
        readonly=True,
    )

    def _compute_vehicle_details(self):
        for line in self:
            details = line._get_vehicle_details()
            line.vehicle_details = "\n".join(details) if details else ""

    def _get_vehicle_details(self):
        """Return formatted list of vehicle details for this invoice line."""
        self.ensure_one()
        details = []
        product = self.product_id

        # Only applicable for serial-tracked products
        if not product or product.tracking != "serial":
            return details

        StockMoveLine = self.env["stock.move.line"]
        MrpProduction = self.env["mrp.production"]

        # 1️⃣ Find delivery move lines (linked to sales delivery)
        delivery_moves = StockMoveLine.search(
            [
                ("product_id", "=", product.id),
                ("lot_id", "!=", False),
                ("picking_id.origin", "ilike", self.move_id.invoice_origin or ""),
            ]
        )

        for idx, move_line in enumerate(delivery_moves, start=1):
            serial_lot = move_line.lot_id

            # 2️⃣ Try to find the Manufacturing Order that produced this lot
            mo = MrpProduction.search(
                [
                    ("product_id", "=", product.id),
                    ("finished_move_line_ids.lot_id", "=", serial_lot.id),
                ],
                limit=1,
            )

            if not mo:
                # fallback — no MO found, show serial only
                details.append(serial_lot.name)
                continue

            # 3️⃣ Fetch component move lines (raw material lots)
            comp_lines = StockMoveLine.search(
                [
                    ("move_id", "in", mo.move_raw_ids.ids),
                    ("lot_id", "!=", False),
                ]
            )

            chassis = motor = controller = ""
            for comp in comp_lines:
                name = (comp.product_id.name or "").lower()
                lot_name = comp.lot_id.name or ""
                if "chassis" in name and not chassis:
                    chassis = lot_name
                elif "motor" in name and not motor:
                    motor = lot_name
                elif "controller" in name and not controller:
                    controller = lot_name

            details.append(
                f"{idx}: Chassis No: {chassis or '-'}, Motor No: {motor or '-'}, Controller: {controller or '-'}"
            )

        # If no delivery or MO info, fallback to just serials
        if not details:
            fallback_serials = StockMoveLine.search(
                [("product_id", "=", product.id), ("lot_id", "!=", False)]
            ).mapped("lot_id.name")
            details = fallback_serials or []

        return details
