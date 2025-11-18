# -*- coding: utf-8 -*-
from odoo import models, fields, tools, api


class VehicleStockReport(models.Model):
    _name = 'vehicle.stock.report'
    _description = 'Vehicle Stock Dynamic Report'
    _auto = False
    _order = 'sales_invoice_date desc NULLS LAST, picking_slip_date desc NULLS LAST'

    id = fields.Integer(string='ID', readonly=True)
    item = fields.Char(string='Item', readonly=True)
    model_name = fields.Char(string='Model Name', readonly=True)
    part_no = fields.Char(string='Part No', readonly=True)
    color = fields.Char(string='Color', readonly=True)
    chassis_no = fields.Char(string='Chassis No', readonly=True)
    motor_no = fields.Char(string='Motor No', readonly=True)
    battery = fields.Char(string='Battery', readonly=True)
    controller = fields.Char(string='Controller', readonly=True)
    charger = fields.Char(string='Charger', readonly=True)
    convertor = fields.Char(string='Convertor', readonly=True)
    qafg_date = fields.Date(string='QAFG Date', readonly=True)
    qafg_no = fields.Char(string='QAFG No', readonly=True)
    picking_slip_date = fields.Date(string='Picking Slip Date', readonly=True)
    picking_slip_no = fields.Char(string='Picking Slip No', readonly=True)
    sales_invoice_date = fields.Date(
        string='Sales Invoice Date', readonly=True)
    sales_invoice_no = fields.Char(string='Sales Invoice No', readonly=True)
    customer_name = fields.Char(string='Customer Name', readonly=True)
    customer_location = fields.Char(string='Customer Location', readonly=True)

    def _select(self):
        return """
            SELECT
                row_number() OVER () AS id,
                pt.name->>'en_US' AS item,
                pt.name->>'en_US' AS model_name,
                pp.default_code::text AS part_no,
                NULL::text AS color,
                lot.name::text AS chassis_no,
                -- motor serials: lots used in stock_move_lines for component products mapped as motor
                (SELECT string_agg(DISTINCT sml_m.lot_name, ', ')
                   FROM stock_move_line sml_m
                   JOIN product_product pp_m ON pp_m.id = sml_m.product_id
                   JOIN vehicle_component_role vcr ON vcr.product_tmpl_id = pp_m.product_tmpl_id AND vcr.role = 'motor' AND vcr.active = true
                   WHERE sml_m.production_id IS NOT NULL
                     AND sml_m.product_id IN (SELECT product_id FROM product_product WHERE product_tmpl_id = vcr.product_tmpl_id)
                ) AS motor_no,
                (SELECT string_agg(DISTINCT sml_b.lot_name, ', ')
                   FROM stock_move_line sml_b
                   JOIN product_product pp_b ON pp_b.id = sml_b.product_id
                   JOIN vehicle_component_role vcrb ON vcrb.product_tmpl_id = pp_b.product_tmpl_id AND vcrb.role = 'battery' AND vcrb.active = true
                   WHERE sml_b.production_id IS NOT NULL
                     AND sml_b.product_id IN (SELECT product_id FROM product_product WHERE product_tmpl_id = vcrb.product_tmpl_id)
                ) AS battery,
                (SELECT string_agg(DISTINCT sml_c.lot_name, ', ')
                   FROM stock_move_line sml_c
                   JOIN product_product pp_c ON pp_c.id = sml_c.product_id
                   JOIN vehicle_component_role vcrc ON vcrc.product_tmpl_id = pp_c.product_tmpl_id AND vcrc.role = 'controller' AND vcrc.active = true
                   WHERE sml_c.production_id IS NOT NULL
                     AND sml_c.product_id IN (SELECT product_id FROM product_product WHERE product_tmpl_id = vcrc.product_tmpl_id)
                ) AS controller,
                (SELECT string_agg(DISTINCT sml_ch.lot_name, ', ')
                   FROM stock_move_line sml_ch
                   JOIN product_product pp_ch ON pp_ch.id = sml_ch.product_id
                   JOIN vehicle_component_role vcrch ON vcrch.product_tmpl_id = pp_ch.product_tmpl_id AND vcrch.role = 'charger' AND vcrch.active = true
                   WHERE sml_ch.production_id IS NOT NULL
                     AND sml_ch.product_id IN (SELECT product_id FROM product_product WHERE product_tmpl_id = vcrch.product_tmpl_id)
                ) AS charger,
                (SELECT string_agg(DISTINCT sml_cv.lot_name, ', ')
                   FROM stock_move_line sml_cv
                   JOIN product_product pp_cv ON pp_cv.id = sml_cv.product_id
                   JOIN vehicle_component_role vcrcv ON vcrcv.product_tmpl_id = pp_cv.product_tmpl_id AND vcrcv.role = 'convertor' AND vcrcv.active = true
                   WHERE sml_cv.production_id IS NOT NULL
                     AND sml_cv.product_id IN (SELECT product_id FROM product_product WHERE product_tmpl_id = vcrcv.product_tmpl_id)
                ) AS convertor,
                sp.date_done::date AS qafg_date,
                sp.name::text AS qafg_no,
                sp.date_done::date AS picking_slip_date,
                sp.name::text AS picking_slip_no,
                am.invoice_date::date AS sales_invoice_date,
                am.name::text AS sales_invoice_no,
                rp.name::text AS customer_name,
                coalesce(rp.city, rp.street, rp.comment)::text AS customer_location
            FROM stock_move sm
            LEFT JOIN product_product pp ON pp.id = sm.product_id
            LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN stock_picking sp ON sp.id = sm.picking_id
            LEFT JOIN stock_move_line sml ON sml.move_id = sm.id
            LEFT JOIN stock_lot lot ON lot.id = sml.lot_id
            LEFT JOIN sale_order_line sol ON sol.id = sm.sale_line_id
            LEFT JOIN sale_order so ON so.id = sol.order_id
            LEFT JOIN account_move am ON am.invoice_origin = so.name
            LEFT JOIN res_partner rp ON rp.id = so.partner_id
            WHERE coalesce(sm.state,'') <> 'cancel'
        """

    # @api.model_cr
    def init(self):
        tools.drop_view_if_exists(self._cr, 'vehicle_stock_report')
        self.env.cr.execute(
            'CREATE OR REPLACE VIEW vehicle_stock_report AS ( %s )' % (self._select(),))
