# -*- coding: utf-8 -*-
"""Excel template for the New Bike Model wizard's BOM import.

Built fresh on every download so its drop-downs always list the parts that
exist in Odoo *right now*: picking a name from the list guarantees an exact
match, which is what prevents mismatch / duplicate-part problems at import.
"""
import io

import xlsxwriter
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request

FILL_ROWS = 1500  # rows of the BOM sheet that get drop-downs / validation
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class BomTemplateController(http.Controller):

    @http.route('/elegomotors/bom_template.xlsx', type='http', auth='user')
    def bom_template(self, **kwargs):
        user = request.env.user
        if not (user.has_group('mrp.group_mrp_routings') or user.has_group('base.group_system')):
            raise Forbidden()

        components = request.env['product.template'].search_read(
            [('x_is_ego_bike', '=', False)], ['name'], order='name')
        names = [c['name'] for c in components if c['name']]
        color_attr = request.env.ref('elegomotors_setup.attr_ego_color', raise_if_not_found=False)
        colours = color_attr.sudo().value_ids.mapped('name') if color_attr else []

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        head = wb.add_format({'bold': True, 'bg_color': '#714B67', 'font_color': '#FFFFFF', 'border': 1})
        note = wb.add_format({'text_wrap': True, 'valign': 'top'})
        bold = wb.add_format({'bold': True})
        grey = wb.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})

        # --- BOM (the sheet the wizard reads) -------------------------------
        bom = wb.add_worksheet('BOM')
        for col, title in enumerate(('Component Name', 'Quantity', 'Colour')):
            bom.write(0, col, title, head)
        bom.set_column(0, 0, 60)
        bom.set_column(1, 1, 12)
        bom.set_column(2, 2, 16)
        bom.freeze_panes(1, 0)
        if names:
            bom.data_validation(1, 0, FILL_ROWS, 0, {
                'validate': 'list',
                'source': f'=Components!$A$2:$A${len(names) + 1}',
                'ignore_blank': True,
                'input_title': 'Component Name',
                'input_message': 'Pick the part from the list. Type a new name only if the part really is new.',
                'error_type': 'warning',
                'error_title': 'Not in Odoo yet',
                'error_message': 'This name is not an existing part. It will be created as a NEW part '
                                 '(or flagged for you to review). Continue?',
            })
        bom.data_validation(1, 1, FILL_ROWS, 1, {
            'validate': 'decimal', 'criteria': '>', 'value': 0, 'ignore_blank': True,
            'error_title': 'Quantity', 'error_message': 'Enter a number greater than 0.',
        })
        if colours:
            bom.data_validation(1, 2, FILL_ROWS, 2, {
                'validate': 'list',
                'source': f'=Colours!$A$2:$A${len(colours) + 1}',
                'ignore_blank': True,
                'input_title': 'Colour',
                'input_message': 'Leave BLANK for a part used in every colour.',
                'error_type': 'warning',
                'error_title': 'Unknown colour',
                'error_message': 'This colour is not an existing colour. It must match a colour '
                                 'you enter in the wizard. Continue?',
            })

        # --- Instructions ----------------------------------------------------
        ins = wb.add_worksheet('Instructions')
        ins.set_column(0, 0, 110)
        lines = [
            ('How to fill the BOM sheet', bold),
            ('1. One row per component on the "BOM" sheet. Do not change the header row.', note),
            ('2. Component Name: pick it from the drop-down. That is an exact match with Odoo, '
             'so nothing can be mismatched. Type a name only for a part that does not exist yet.', note),
            ('3. Quantity: parts needed for ONE bike (number greater than 0).', note),
            ('4. Colour: leave BLANK if the part is used in every colour. Pick a colour only if '
             'the part belongs to that colour\'s BOM (e.g. a red panel -> Red).', note),
            ('5. Upload the file in Manufacturing > New Bike Model > Bill of Materials, then press '
             '"Check Components". Odoo shows what matched, what looks similar to an existing part '
             '(you choose) and what will be created new.', note),
            ('', note),
            ('Tips', bold),
            ('- Do not leave example rows in the BOM sheet - every row is imported.', note),
            ('- Extra / double spaces and upper/lower case are ignored when matching names.', note),
            ('- A part listed twice in the same colour is added as two BOM lines.', note),
            ('- The "Components" and "Colours" sheets are only the lists for the drop-downs; '
             'they are not imported.', note),
        ]
        for i, (text, fmt) in enumerate(lines):
            ins.write(i, 0, text, fmt)

        # --- Lists for the drop-downs ---------------------------------------
        comp = wb.add_worksheet('Components')
        comp.write(0, 0, 'Existing parts in Odoo', grey)
        comp.set_column(0, 0, 70)
        for i, name in enumerate(names, start=1):
            comp.write_string(i, 0, name)
        col = wb.add_worksheet('Colours')
        col.write(0, 0, 'Existing colours', grey)
        col.set_column(0, 0, 25)
        for i, name in enumerate(colours, start=1):
            col.write_string(i, 0, name)
        bom.activate()
        wb.close()

        data = output.getvalue()
        return request.make_response(data, headers=[
            ('Content-Type', XLSX_MIME),
            ('Content-Disposition', 'attachment; filename="Elego BOM Import Template.xlsx"'),
            ('Content-Length', str(len(data))),
        ])
