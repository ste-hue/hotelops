from io import BytesIO

import openpyxl

from verticals.condges.pf_rotate.diff import semantic_diff


def _wb_with(cells: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    for ref, val in cells.items():
        ws[ref] = val
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_semantic_diff_equal_within_tolerance():
    a = _wb_with({"A1": 1.0, "B2": "=SUM(A1:A2)"})
    b = _wb_with({"A1": 1.0 + 1e-9, "B2": "=SUM(A1:A2)"})
    diff = semantic_diff(a, b, target_cells={"S": ["A1", "B2"]})
    assert diff == []


def test_semantic_diff_detects_value_change():
    a = _wb_with({"A1": 1.0})
    b = _wb_with({"A1": 2.0})
    diff = semantic_diff(a, b, target_cells={"S": ["A1"]})
    assert len(diff) == 1
    assert "A1" in diff[0]


def test_semantic_diff_ignores_non_target_cells():
    a = _wb_with({"A1": 1.0, "Z99": "noise"})
    b = _wb_with({"A1": 1.0, "Z99": "different noise"})
    diff = semantic_diff(a, b, target_cells={"S": ["A1"]})
    assert diff == []
