# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models


class StockPickingQcWizard(models.TransientModel):
    _name = 'stock.picking.qc.wizard'
    _description = 'QC Routing: Choose how to handle QC vs Non-QC products'

    picking_id = fields.Many2one('stock.picking', string='Gate Entry', readonly=True)

    # Stored display-only fields — populated via default_get (not @api.depends)
    # because computed fields on transient models are unreliable before the record
    # is saved in Odoo 18 wizard dialogs.
    qc_product_names = fields.Char(string='Products Requiring QC', readonly=True)
    non_qc_product_names = fields.Char(
        string='Products Going Directly to Store', readonly=True
    )
    has_non_qc_products = fields.Boolean(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        picking_id = res.get('picking_id') or self.env.context.get('default_picking_id')
        if picking_id:
            picking = self.env['stock.picking'].browse(picking_id)
            qc_moves = picking.move_ids.filtered(lambda m: m.product_id.x_qc_required)
            non_qc_moves = picking.move_ids.filtered(
                lambda m: not m.product_id.x_qc_required
            )
            res['qc_product_names'] = ', '.join(qc_moves.mapped('product_id.name'))
            res['non_qc_product_names'] = ', '.join(
                non_qc_moves.mapped('product_id.name')
            )
            res['has_non_qc_products'] = bool(non_qc_moves)
        return res

    def _create_move_lines(self, picking, store_loc):
        """
        Create explicit stock.move.line records for every move so Odoo
        does NOT auto-fill quantities in immediate-transfer mode (which
        happens when no move_line_ids exist on a Draft receipt).

        Non-QC → qty_done = received, dest = Store
        QC     → qty_done = 0  (triggers backorder on button_validate)
        """
        MoveL = self.env['stock.move.line']
        for move in picking.move_ids:
            # Remove any existing lines (shouldn't exist on Draft, but be safe)
            move.move_line_ids.unlink()

            qty = move.x_qty_received or move.product_uom_qty

            if not move.product_id.x_qc_required:
                # Non-QC: mark as fully passed, route to Store
                move.x_qty_qc_passed = qty
                move.location_dest_id = store_loc.id
                MoveL.create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'qty_done': qty,
                    'location_id': move.location_id.id,
                    'location_dest_id': store_loc.id,
                })
            else:
                # QC: done = 0 → Odoo will create a backorder for these
                MoveL.create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'qty_done': 0,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                })

    def _handle_backorder_and_notify(self, picking, result):
        """Process backorder confirmation if Odoo returned one, then
        set the backorder to in_qc and notify Pratik."""
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            backorder_wiz = self.env['stock.backorder.confirmation'].with_context(
                button_validate_picking_ids=picking.ids
            ).create({'pick_ids': [(4, picking.id)]})
            backorder_wiz.process()

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
    # Option 1: Send QC products to Pratik for inspection,
    #           validate non-QC products directly to Store now.
    # ------------------------------------------------------------------
    def action_send_qc_and_validate_others(self):
        """Option 1: Validate non-QC products to Store now; send QC products to Pratik."""
        picking = self.picking_id
        store_loc = self.env.ref('elegomotors_setup.location_ego_store')

        self._create_move_lines(picking, store_loc)
        # NOTE: do NOT set x_gate_entry_state = 'ready' here — that would trigger
        # _compute_qc_failed to show QC failures for products not yet inspected.
        # skip_qc_wizard=True context bypasses the gate check instead.
        result = picking.with_context(skip_qc_wizard=True).button_validate()
        self._handle_backorder_and_notify(picking, result)

    # ------------------------------------------------------------------
    # Option 2: Validate only non-QC products to Store now.
    #           QC products remain in a backorder (pending_qc) for later.
    # ------------------------------------------------------------------
    def action_validate_non_qc_only(self):
        """Option 2: Validate only non-QC products now; QC backorder stays pending_qc."""
        picking = self.picking_id
        store_loc = self.env.ref('elegomotors_setup.location_ego_store')

        self._create_move_lines(picking, store_loc)
        result = picking.with_context(skip_qc_wizard=True).button_validate()

        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            backorder_wiz = self.env['stock.backorder.confirmation'].with_context(
                button_validate_picking_ids=picking.ids
            ).create({'pick_ids': [(4, picking.id)]})
            backorder_wiz.process()
        # Backorder stays in 'pending_qc' — Amit manually sends QC products later
