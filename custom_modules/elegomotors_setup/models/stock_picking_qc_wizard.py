# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models


class StockPickingQcWizard(models.TransientModel):
    _name = 'stock.picking.qc.wizard'
    _description = 'QC Routing: Choose how to handle QC vs Non-QC products'

    picking_id = fields.Many2one('stock.picking', string='Gate Entry', readonly=True)

    # Computed display-only fields shown in the wizard body
    qc_product_names = fields.Char(
        string='Products Requiring QC',
        compute='_compute_product_lists',
    )
    non_qc_product_names = fields.Char(
        string='Products Going Directly to Store',
        compute='_compute_product_lists',
    )
    has_non_qc_products = fields.Boolean(compute='_compute_product_lists')

    @api.depends('picking_id')
    def _compute_product_lists(self):
        for wiz in self:
            qc_moves = wiz.picking_id.move_ids.filtered(
                lambda m: m.product_id.x_qc_required
            )
            non_qc_moves = wiz.picking_id.move_ids.filtered(
                lambda m: not m.product_id.x_qc_required
            )
            wiz.qc_product_names = ', '.join(qc_moves.mapped('product_id.name'))
            wiz.non_qc_product_names = ', '.join(non_qc_moves.mapped('product_id.name'))
            wiz.has_non_qc_products = bool(non_qc_moves)

    # ------------------------------------------------------------------
    # Option 1: Send QC products to Pratik for inspection,
    #           validate non-QC products directly to Store now.
    # ------------------------------------------------------------------
    def action_send_qc_and_validate_others(self):
        picking = self.picking_id
        store_loc = self.env.ref('elegomotors_setup.location_ego_store')

        for move in picking.move_ids:
            if not move.product_id.x_qc_required:
                # Non-QC product → destination changes to Store, qty_done = received
                move.location_dest_id = store_loc.id
                for ml in move.move_line_ids:
                    ml.location_dest_id = store_loc.id
                    ml.qty_done = move.x_qty_received or move.product_uom_qty
            else:
                # QC product → qty_done = 0 so Odoo creates a backorder
                for ml in move.move_line_ids:
                    ml.qty_done = 0.0

        # Bypass our own QC guard (we are about to call button_validate ourselves)
        picking.x_gate_entry_state = 'ready'
        result = picking.with_context(skip_qc_wizard=True).button_validate()

        # If Odoo returned a backorder confirmation wizard, auto-confirm it
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            backorder_wiz = self.env['stock.backorder.confirmation'].with_context(
                button_validate_picking_ids=picking.ids
            ).create({'pick_ids': [(4, picking.id)]})
            backorder_wiz.process()

        # Find the newly-created backorder (QC products) and kick off QC flow
        backorder = picking.backorder_ids[:1]
        if backorder:
            backorder.x_gate_entry_state = 'in_qc'
            pratik = self.env.ref(
                'elegomotors_setup.user_ego_pratik', raise_if_not_found=False
            )
            partner_ids = [pratik.partner_id.id] if pratik and pratik.partner_id else []
            backorder.message_post(
                body=Markup(
                    f"QC routing by <b>{self.env.user.name}</b>: "
                    f"The following products require QC inspection: "
                    f"<b>{self.qc_product_names}</b>.<br/>"
                    f"<b>Quality (Pratik):</b> Please inspect each unit, enter QC Passed qty, "
                    f"then click <b>Approve QC</b>."
                ),
                partner_ids=partner_ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    # ------------------------------------------------------------------
    # Option 2: Validate only non-QC products to Store now.
    #           QC products remain in a backorder (pending_qc) for later.
    # ------------------------------------------------------------------
    def action_validate_non_qc_only(self):
        picking = self.picking_id
        store_loc = self.env.ref('elegomotors_setup.location_ego_store')

        for move in picking.move_ids:
            if not move.product_id.x_qc_required:
                move.location_dest_id = store_loc.id
                for ml in move.move_line_ids:
                    ml.location_dest_id = store_loc.id
                    ml.qty_done = move.x_qty_received or move.product_uom_qty
            else:
                for ml in move.move_line_ids:
                    ml.qty_done = 0.0

        picking.x_gate_entry_state = 'ready'
        result = picking.with_context(skip_qc_wizard=True).button_validate()

        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            backorder_wiz = self.env['stock.backorder.confirmation'].with_context(
                button_validate_picking_ids=picking.ids
            ).create({'pick_ids': [(4, picking.id)]})
            backorder_wiz.process()
        # Backorder stays in 'pending_qc' — Amit manually sends QC products later
