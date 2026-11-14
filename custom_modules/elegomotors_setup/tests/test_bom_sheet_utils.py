# -*- coding: utf-8 -*-
"""Plain-Python tests (no database) for the New Bike Model wizard's sheet
reader and name matcher."""
import io

import xlsxwriter

from odoo.tests.common import BaseCase, tagged

from ..models.bom_sheet_utils import (
    SheetError, clean_name, find_candidates, name_key, parse_bom_table, read_table,
)


def _xlsx(rows, sheet='BOM'):
    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {'in_memory': True})
    ws = wb.add_worksheet(sheet)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is not None:
                ws.write(r, c, value)
    wb.close()
    return out.getvalue()


@tagged('post_install', '-at_install')
class TestBomSheetUtils(BaseCase):

    def test_names_ignore_spaces_and_case(self):
        self.assertEqual(clean_name('  1.1/1.2  FRONT\xa0FENDER RED '), '1.1/1.2 FRONT FENDER RED')
        self.assertEqual(name_key(' Mirror  Set'), name_key('MIRROR SET'))
        self.assertEqual(clean_name(5.0), '5')

    def test_xlsx_and_csv_give_same_rows(self):
        rows = [
            ['Component Name', 'Quantity', 'Colour'],
            ['MIRROR SET ', 2, None],
            ['1.2 FRONT PANEL RED', 1, 'Red'],
            [None, None, None],
        ]
        csv_bytes = ('\ufeffComponent Name,Quantity,Colour\n'
                     'MIRROR SET ,2,\n1.2 FRONT PANEL RED,1,Red\n,,\n').encode('utf-8')
        want = [('MIRROR SET', 2.0, ''), ('1.2 FRONT PANEL RED', 1.0, 'Red')]
        for data, fname in ((_xlsx(rows), 'a.xlsx'), (csv_bytes, 'a.csv')):
            parsed, errors = parse_bom_table(read_table(data, fname))
            self.assertEqual(errors, [])
            self.assertEqual([(r['name'], r['qty'], r['colour']) for r in parsed], want)

    def test_bom_sheet_preferred_over_first_sheet(self):
        out = io.BytesIO()
        wb = xlsxwriter.Workbook(out, {'in_memory': True})
        wb.add_worksheet('Instructions').write(0, 0, 'read me')
        bom = wb.add_worksheet('BOM')
        for c, h in enumerate(('Component Name', 'Quantity', 'Colour')):
            bom.write(0, c, h)
        bom.write(1, 0, 'TYRE 3-00-10')
        bom.write(1, 1, 2)
        wb.close()
        parsed, errors = parse_bom_table(read_table(out.getvalue(), 'x.xlsx'))
        self.assertEqual((errors, [r['name'] for r in parsed]), ([], ['TYRE 3-00-10']))

    def test_bad_rows_are_all_reported(self):
        table = [['Component Name', 'Quantity', 'Colour'],
                 ['A', 0, ''], ['B', 'x', ''], ['', 1, ''], ['OK', 3, '']]
        parsed, errors = parse_bom_table(table)
        self.assertEqual([r['name'] for r in parsed], ['OK'])
        self.assertEqual(len(errors), 3)

    def test_missing_header_and_bad_files(self):
        with self.assertRaises(SheetError):
            parse_bom_table([['#', 'Component (as the wizard will read it)', 'Qty per bike']])
        with self.assertRaises(SheetError):
            read_table(b'PK\x03\x04 not really a zip', 'x.xlsx')
        with self.assertRaises(SheetError):
            read_table(b'', 'x.csv')
        with self.assertRaises(SheetError):
            read_table(b'abc', 'old.xls')

    def test_candidates(self):
        names = ['1.2 MAIN WIRE HARNESS', 'MIRROR SET', '1.1/1.2 MCB', 'CONE SET 7 PARTS',
                 '1.1/1.2 FLASHER', 'MAIN STAND SPRING', '1.1/1.2 CONTROLLER CAP BIG']
        pool = [(i, name_key(n), n) for i, n in enumerate(names)]

        def near(sheet_name):
            return [n for _i, n, _s in find_candidates(name_key(sheet_name), pool)]

        self.assertEqual(near('2W LOADER MAIN WIRE HARNESS'), ['1.2 MAIN WIRE HARNESS'])
        self.assertEqual(near('2W LOADER MIRROR SET'), ['MIRROR SET'])
        self.assertEqual(near('MCB'), ['1.1/1.2 MCB'])
        self.assertEqual(near('2W LOADER CONE SET'), ['CONE SET 7 PARTS'])
        self.assertEqual(near('2W/3W FLASHER'), ['1.1/1.2 FLASHER'])
        # a different part that merely shares words is NOT suggested
        self.assertEqual(near('2W LOADER MAIN STAND'), [])
        self.assertEqual(near('2W LOADER CONTROLLER'), [])
        self.assertEqual(near('2W LOADER MOTOR'), [])
