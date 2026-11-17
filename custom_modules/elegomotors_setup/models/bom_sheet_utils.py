# -*- coding: utf-8 -*-
"""Pure-Python helpers for the New Bike Model wizard's BOM import.

Deliberately has no `odoo` import so it can be unit-tested outside Odoo.

  * read_table()      — bytes of an .xlsx or .csv file -> list of rows
  * parse_bom_table() — rows -> (clean BOM rows, per-row error messages)
  * clean_name() / name_key() — the one normalisation used everywhere a
    sheet name is compared with a system name (trailing / double / non-breaking
    spaces and letter case never cause a mismatch)
  * find_candidates() — "very similar" existing names for a sheet name

The .xlsx reader uses only the standard library (zipfile + ElementTree):
Odoo.sh's bundled xlrd (2.x) cannot read .xlsx and openpyxl is not
guaranteed to be installed, so nothing here depends on either.
"""
import csv
import difflib
import io
import math
import re
import zipfile
import xml.etree.ElementTree as ET

_MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_PKG_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'

MAX_UNZIPPED_BYTES = 30 * 1024 * 1024

HEADER_ALIASES = {
    'name': {'component name', 'component', 'part name', 'part'},
    'qty': {'quantity', 'qty', 'bom qty', 'qty per bike'},
    'colour': {'colour', 'color'},
}


class SheetError(Exception):
    """A file-level problem; the message is safe to show to the user."""


# ----------------------------------------------------------------------
# Names
# ----------------------------------------------------------------------

def clean_name(value):
    """Trim, turn non-breaking spaces into spaces and collapse runs of
    whitespace. The result is what a NEW part is created with."""
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r'\s+', ' ', str(value).replace('\xa0', ' ')).strip()


def name_key(value):
    """Comparison key: cleaned and case-folded."""
    return clean_name(value).casefold()


# ----------------------------------------------------------------------
# Reading files
# ----------------------------------------------------------------------

def _col_index(cell_ref):
    letters = re.match(r'[A-Za-z]+', cell_ref or '')
    if not letters:
        return None
    idx = 0
    for ch in letters.group(0).upper():
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _shared_strings(zf):
    try:
        root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
    except KeyError:
        return []
    out = []
    for si in root.findall(_MAIN + 'si'):
        parts = []
        for child in si:
            if child.tag == _MAIN + 't':
                parts.append(child.text or '')
            elif child.tag == _MAIN + 'r':  # rich-text run
                parts.extend(t.text or '' for t in child.findall(_MAIN + 't'))
        out.append(''.join(parts))
    return out


def _pick_sheet_path(zf):
    """Path of the worksheet to read: the one named 'BOM' if there is one,
    otherwise the first visible sheet."""
    wb = ET.fromstring(zf.read('xl/workbook.xml'))
    rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
    targets = {r.get('Id'): r.get('Target') for r in rels.findall(_PKG_REL + 'Relationship')}
    sheets = []
    for sh in wb.find(_MAIN + 'sheets'):
        target = targets.get(sh.get(_REL + 'id'))
        if not target:
            continue
        target = target.lstrip('/')
        path = target if target.startswith('xl/') else 'xl/' + target
        sheets.append((sh.get('name') or '', sh.get('state') or 'visible', path))
    if not sheets:
        raise SheetError('The Excel file has no sheets.')
    for name, _state, path in sheets:
        if name.strip().casefold() == 'bom':
            return path
    for _name, state, path in sheets:
        if state == 'visible':
            return path
    return sheets[0][2]


def _read_xlsx(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SheetError('This is not a valid .xlsx file. Use the BOM template, '
                         'or save the sheet as .xlsx / .csv again.')
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
        raise SheetError('The Excel file is too large to be a BOM sheet.')
    try:
        strings = _shared_strings(zf)
        root = ET.fromstring(zf.read(_pick_sheet_path(zf)))
    except (KeyError, ET.ParseError):
        raise SheetError('Could not read the Excel file. Use the BOM template.')

    rows = []
    for row in root.iter(_MAIN + 'row'):
        cells = {}
        for c in row.findall(_MAIN + 'c'):
            idx = _col_index(c.get('r'))
            if idx is None:
                continue
            ctype = c.get('t')
            v = c.find(_MAIN + 'v')
            if ctype == 'inlineStr':
                is_el = c.find(_MAIN + 'is')
                value = ''.join(t.text or '' for t in is_el.iter(_MAIN + 't')) if is_el is not None else ''
            elif v is None or v.text is None:
                continue
            elif ctype == 's':
                try:
                    value = strings[int(v.text)]
                except (ValueError, IndexError):
                    continue
            elif ctype in ('str', 'e'):
                value = v.text
            elif ctype == 'b':
                value = v.text == '1'
            else:
                try:
                    value = float(v.text)
                except ValueError:
                    value = v.text
            cells[idx] = value
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i) for i in range(width)])
        else:
            rows.append([])
    return rows


def _read_csv(data):
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SheetError('Could not read the file as text. Save it as .xlsx or UTF-8 .csv.')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def read_table(data, filename=''):
    """List of rows (each a list of cell values) from an .xlsx or .csv."""
    if not data:
        raise SheetError('The BOM file is empty.')
    if data[:4] == b'PK\x03\x04':
        return _read_xlsx(data)
    if (filename or '').lower().endswith('.xls'):
        raise SheetError('Old .xls files are not supported. Save the sheet as '
                         '.xlsx (or use the BOM template) and upload that.')
    return _read_csv(data)


# ----------------------------------------------------------------------
# BOM rows
# ----------------------------------------------------------------------

def parse_bom_table(table):
    """Turn a table into BOM rows.

    Returns (rows, errors). rows: list of dicts
        {row, name, key, qty, colour}   (colour is '' for "all colours")
    errors: list of human-readable strings, one per bad row. Raises
    SheetError if the header row is missing or incomplete.
    """
    header_idx, cols = None, {}
    for i, row in enumerate(table):
        found = {}
        for j, cell in enumerate(row):
            label = clean_name(cell).casefold()
            for field, aliases in HEADER_ALIASES.items():
                if label in aliases and field not in found:
                    found[field] = j
        if len(found) == 3:
            header_idx, cols = i, found
            break
        if i >= 10:
            break
    if header_idx is None:
        raise SheetError(
            'Could not find the header row. The first row must have the columns '
            'Component Name, Quantity, Colour (download the BOM template).'
        )

    rows, errors = [], []
    for i, row in enumerate(table[header_idx + 1:], start=header_idx + 2):
        def cell(field):
            j = cols[field]
            return row[j] if j < len(row) else None
        name, qty_raw, colour = clean_name(cell('name')), cell('qty'), clean_name(cell('colour'))
        if not name and clean_name(qty_raw) == '' and not colour:
            continue  # blank row
        if not name:
            errors.append(f'Row {i}: Component Name is empty.')
            continue
        try:
            qty = float(clean_name(qty_raw).replace(',', '.')) if isinstance(qty_raw, str) \
                else float(qty_raw)
            if not math.isfinite(qty) or qty <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f'Row {i} ({name}): Quantity "{clean_name(qty_raw)}" is not a positive number.')
            continue
        rows.append({'row': i, 'name': name, 'key': name.casefold(), 'qty': qty, 'colour': colour})
    return rows, errors


# ----------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------

_TOKEN = re.compile(r'[a-z0-9]+')
# Series / model prefixes that differ between bikes but say nothing about the
# part itself: "1.1/1.2 MCB", "2W LOADER MCB" and "MCB" share the core "mcb".
_PREFIX_NOISE = {'2w', '3w', 'loader', 'elego', 'ego'}
_FILLER = {'dc', 'ac', 'set', 'kit', 'part', 'parts', 'pcs', 'assy', 'assembly'}


def _core_tokens(key):
    """Words of a name with its leading series/model prefix removed."""
    tokens = _TOKEN.findall(key)
    while tokens and (tokens[0].isdigit() or tokens[0] in _PREFIX_NOISE):
        tokens = tokens[1:]
    return tokens


def _score(key, key_core, cand_key, cand_core, matcher):
    """0.0 (not similar) .. 1.0 (identical but for the series prefix)."""
    score = 0.0
    if matcher.real_quick_ratio() >= 0.8 and matcher.quick_ratio() >= 0.8:
        score = max(score, matcher.ratio() if matcher.ratio() >= 0.8 else 0.0)
    if key_core and cand_core:
        a, b = set(key_core), set(cand_core)
        if key_core == cand_core:
            score = max(score, 0.95)
        else:
            small, large = (a, b) if len(a) <= len(b) else (b, a)
            extras = large - small
            # One name's words fully inside the other's, and the extra words
            # are only filler ("SET", "7 PARTS", "DC", ...) — NOT a different
            # part such as SPRING, CAP, HOLDER.
            if (len(small) >= 2 and small <= large
                    and all(w.isdigit() or w in _FILLER for w in extras)):
                score = max(score, 0.85)
            core_ratio = difflib.SequenceMatcher(
                None, ' '.join(key_core), ' '.join(cand_core), autojunk=False).ratio()
            if core_ratio >= 0.8:
                score = max(score, core_ratio)
    return score


def find_candidates(key, pool, limit=3):
    """Existing names that look like `key` without being identical.

    pool: iterable of (ident, candidate_key, display_name), keys already
    passed through name_key(). Returns up to `limit` of
    (ident, display_name, score), best first. A candidate qualifies if the
    names are >= 80% alike character by character, or if their words match
    once the series prefix ("1.1/1.2", "2W LOADER", ...) is ignored — see
    _score().
    """
    key_core = _core_tokens(key)
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(key)
    scored = []
    for ident, cand_key, display in pool:
        if cand_key == key:
            continue
        matcher.set_seq1(cand_key)
        score = _score(key, key_core, cand_key, _core_tokens(cand_key), matcher)
        if score:
            scored.append((ident, display, score))
    scored.sort(key=lambda t: (-t[2], t[1]))
    return scored[:limit]
