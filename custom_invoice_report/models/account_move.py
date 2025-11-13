
from odoo import models,fields


class AccountMove(models.Model):
    _inherit = 'account.move'
    number_to_words = fields.Char(string="Amount in words",compute="_compute_number_to_words")

    def _compute_number_to_words(self):
         for order in self:
              order.number_to_words = order.currency_id.amount_to_text(order.amount_total)

    def _get_component_serials_by_line(self):
        """
        Traces the serials/lots of the invoiced vehicle back to its Manufacturing Order (MO)
        to find component serials (Chassis, Motor, Controller) by checking BOM/MO traces.
        FIXED: Uses the correct path for consumed move lines: mo.move_raw_ids.move_line_ids.
        """
        result = {}
        target_component_keywords = {
            'chassis': 'Chassis No',
            'motor': 'Motor No',
            'controller': 'Controller',
        }

        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
            product = line.product_id
            line_serials = []

            # --- 1. Find the Lots (Serial Numbers) sold for this invoice line ---
            lots = self.env['stock.lot']
            if line.sale_line_ids:
                move_lines = line.sale_line_ids.mapped(
                    'move_ids').mapped('move_line_ids')
                lots |= move_lines.mapped('lot_id')

            # --- 2. Check for BOM (Direct Search) ---
            bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('type', '!=', 'phantom'),
            ], limit=1)

            for lot_index, lot in enumerate(lots, 1):
                formatted_string = f"{lot_index}: "

                if bom:
                    # --- A. BOM/Assembly Product Logic (Tracing MO) ---
                    component_details = {}

                    # Find the MO that produced this final product lot
                    production_moves = self.env['stock.move'].search([
                        ('product_id', '=', product.id),
                        ('lot_ids', 'in', lot.ids),
                        ('state', '=', 'done'),
                        ('location_id.usage', '=', 'production')
                    ], limit=1)

                    mo = production_moves.mapped('production_id')

                    if mo:
                        # FIX: Correctly access the consumed move lines via the raw moves
                        consumed_move_lines = mo.move_raw_ids.move_line_ids.filtered(
                            lambda ml: ml.state == 'done' and ml.lot_id
                        )

                        for keyword, label in target_component_keywords.items():

                            # Find the lot consumed for the specific component product in the MO
                            component_move_line = consumed_move_lines.filtered(
                                lambda ml: keyword in ml.product_id.name.lower()
                            )

                            component_lot_name = component_move_line.mapped(
                                'lot_id.name')
                            component_details[label] = component_lot_name[0] if component_lot_name else 'N/A'

                        # Set final component values for the output string
                        chassis = component_details.get('Chassis No', 'N/A')
                        motor = component_details.get('Motor No', 'N/A')
                        controller = component_details.get('Controller', 'N/A')

                        # Fallback: If no 'chassis' component was explicitly found, use the final product lot name as the Chassis No.
                        if chassis == 'N/A' and lot.name:
                            chassis = lot.name

                        formatted_string += f"Chassis No: {chassis}, Motor No: {motor}, Controller: {controller}"

                    else:
                        formatted_string += f"Chassis No: {lot.name or 'N/A'}, Motor No: N/A, Controller: N/A (MO Not Linked)"

                else:
                    # --- B. Simple Serialized Product Logic (No BOM found) ---
                    formatted_string += f"{lot.name or 'N/A'}"

                line_serials.append(formatted_string)

            result[line.id] = line_serials

        return result
