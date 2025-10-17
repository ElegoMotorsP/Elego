from odoo import models, api

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # def get_vehicle_details(self):
    #     """
    #     Retrieves a list of dictionaries, where each dictionary contains
    #     the Chassis SN and its linked component SNs for the units sold on this line.
    #     """
    #     self.ensure_one()
    #     vehicle_details_list = []

    #     # Only proceed if the product is serial tracked and linked to a sale order
    #     if self.product_id.tracking != 'serial' or not self.sale_line_ids:
    #         return []

    #     # 1. Find the specific serial numbers (chassis) delivered for this invoice line
    #     chassis_lots = self.env['stock.lot']
        
    #     # Go through the related stock moves that are 'done' (delivered)
    #     done_moves = self.sale_line_ids.move_ids.filtered(lambda m: m.state == 'done' and m.product_uom_qty > 0)
    #     for move in done_moves:
    #         chassis_lots |= move.move_line_ids.lot_id
        
    #     # 2. For each sold chassis, fetch its manufactured component serials
    #     for chassis_lot in chassis_lots:
    #         # Fetch component serials using the helper method
    #         component_serials = self._get_components_from_chassis_lot(chassis_lot.id)
            
    #         # Add the chassis number itself (Req. 8)
    #         component_serials['Chassis No'] = chassis_lot.name
            
    #         # Append the full set of details for this one sold unit
    #         vehicle_details_list.append(component_serials)

    #     return vehicle_details_list
    def get_vehicle_details(self):
        """
        Retrieves a list of dictionaries, where each dictionary contains
        the Chassis SN and its linked component SNs for the units sold on this line.
        """
        self.ensure_one()
        vehicle_details_list = []

        # Only proceed if the product is serial tracked and linked to a sale order
        if self.product_id.tracking != 'serial' or not self.sale_line_ids:
            return []

        # 1. Find the specific serial numbers (chassis) delivered for this invoice line
        chassis_lots = self.env['stock.lot']

        # Go through the related stock moves that are 'done' (delivered)
        done_moves = self.sale_line_ids.move_ids.filtered(
            lambda m: m.state == 'done' and m.product_uom_qty > 0
        )
        for move in done_moves:
            chassis_lots |= move.move_line_ids.lot_id

        # 2. For each sold chassis, fetch its manufactured component serials
        for chassis_lot in chassis_lots:
            # Fetch component serials using the helper method
            component_serials = self._get_components_from_chassis_lot(chassis_lot.id)

            # Rebuild the dictionary with 'Chassis No' first
            ordered_details = {'Chassis No': chassis_lot.name}
            ordered_details.update(component_serials)

            # Append the full set of details for this one sold unit
            vehicle_details_list.append(ordered_details)

        return vehicle_details_list

    @api.model
    def _get_components_from_chassis_lot(self, chassis_lot_id):
        """Helper method to look up consumed parts during manufacturing."""
        if not chassis_lot_id:
            return {}

        # FIX: Replaced 'stock.production.lot' with 'stock.lot'
        chassis_lot = self.env['stock.lot'].browse(chassis_lot_id)
        component_serials = {}

        # Find the stock move that created this finished good (chassis) via an MO
        mo_finished_move = self.env['stock.move'].search([
            ('lot_ids', 'in', chassis_lot.id),
            ('product_id', '=', chassis_lot.product_id.id),
            ('state', '=', 'done'),
            ('production_id', '!=', False) 
        ], limit=1, order='date desc')

        if mo_finished_move and mo_finished_move.production_id:
            mo = mo_finished_move.production_id
            consumed_moves = mo.move_raw_ids.filtered(lambda m: m.state == 'done')

            for move in consumed_moves:
                if move.lot_ids:
                    for lot in move.lot_ids:
                        product_name = lot.product_id.name.lower()
                        
                        # Map product names to the required output keys (Motor No, Controller, etc.)
                        if 'motor' in product_name:
                            component_serials['Motor No'] = lot.name
                        elif 'controller' in product_name:
                            component_serials['Controller'] = lot.name
                        elif 'battery' in product_name:
                            component_serials['Battery No'] = lot.name
                        elif 'charger' in product_name:
                            component_serials['Charger No'] = lot.name
        return component_serials