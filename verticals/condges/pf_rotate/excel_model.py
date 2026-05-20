"""Excel model primitives for PF rotation.

Pure functions on openpyxl Workbook/Worksheet. No I/O, no BQ.
"""

from __future__ import annotations

import re
from typing import Iterable

from openpyxl.worksheet.worksheet import Worksheet

MESI_IT = {
    "GENNAIO": 1,
    "FEBBRAIO": 2,
    "MARZO": 3,
    "APRILE": 4,
    "MAGGIO": 5,
    "GIUGNO": 6,
    "LUGLIO": 7,
    "AGOSTO": 8,
    "SETTEMBRE": 9,
    "OTTOBRE": 10,
    "NOVEMBRE": 11,
    "DICEMBRE": 12,
}


def find_month_columns(ws: Worksheet, header_row: int = 2) -> dict[int, int]:
    """Scan header_row for month names ITA. Return {mese_num: col_idx}.

    Latest col wins if a month appears twice (e.g. multi-year files).
    """
    result: dict[int, int] = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if not isinstance(v, str):
            continue
        key = v.strip().upper()
        if key in MESI_IT:
            result[MESI_IT[key]] = c
    return result


# Matches an A1-style reference (e.g. A1, $B$5, 'Sheet Name'!D3, Utenze!D3).
# Avoid matching function names by requiring a digit somewhere in the token.
_A1_REF_RE = re.compile(
    r"(?:'[^']+'|[A-Z][A-Za-z0-9_ ]*)?!?\$?[A-Z]{1,3}\$?\d+",
)


def is_formula_with_refs(cell) -> bool:
    """True if cell value is a formula string containing A1-style references."""
    v = cell.value
    if not isinstance(v, str) or not v.startswith("="):
        return False
    # Strip the leading '='
    body = v[1:]
    return _A1_REF_RE.search(body) is not None


def is_value_cell(cell) -> bool:
    """True if cell holds a value (number, string, formula-of-constants).

    False for None and formulas that reference other cells.
    """
    v = cell.value
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        if not v.startswith("="):
            return True
        # Formula: only-constants → value-equivalent; with refs → not value.
        return not is_formula_with_refs(cell)
    return False


def resolve_sheet_name(wb, candidates: Iterable[str]) -> str | None:
    """Return the first candidate that exists in wb.sheetnames, else None."""
    names = set(wb.sheetnames)
    for c in candidates:
        if c in names:
            return c
    return None


_SUM_RANGE_RE = re.compile(r"SUM\(\$?[A-Z]+\$?(\d+):\$?[A-Z]+\$?(\d+)\)")


def find_total_row_and_sum_range(
    ws: Worksheet,
    scan_max_row: int = 10,
) -> tuple[int | None, int, int]:
    """Locate the total row + vertical SUM range in a PF detail sheet.

    Strategy: scan first `scan_max_row` rows for a vertical SUM formula in any
    column. Return (total_row, sum_start, sum_end). If none found, (None, 0, 0).
    """
    for r in range(1, scan_max_row + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if not isinstance(v, str):
                continue
            m = _SUM_RANGE_RE.search(v)
            if not m:
                continue
            start, end = int(m.group(1)), int(m.group(2))
            if end - start >= 5:  # vertical = many rows
                return r, start, end
    return None, 0, 0
