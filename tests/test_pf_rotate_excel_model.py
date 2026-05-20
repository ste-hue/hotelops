from io import BytesIO
import openpyxl
import pytest

from verticals.condges.pf_rotate.excel_model import (
    find_month_columns,
    is_value_cell,
    is_formula_with_refs,
    resolve_sheet_name,
    find_total_row_and_sum_range,
)


def test_find_month_columns_returns_mese_to_col_map(minimal_pf_orti_bytes):
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    ws = wb["Utenze"]
    cols = find_month_columns(ws, header_row=2)
    assert cols == {
        4: 4,  # APRILE -> col D (4)
        5: 5,
        6: 6,
        7: 7,
        8: 8,
        9: 9,
        10: 10,
        11: 11,
        12: 12,
    }


def test_is_value_cell_pure_number():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = 123.45
    assert is_value_cell(ws["A1"]) is True
    assert is_formula_with_refs(ws["A1"]) is False


def test_is_value_cell_formula_only_constants():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "=110000+160000"
    assert is_value_cell(ws["A1"]) is True
    assert is_formula_with_refs(ws["A1"]) is False


def test_is_formula_with_refs_a1_reference():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "=B5"
    assert is_value_cell(ws["A1"]) is False
    assert is_formula_with_refs(ws["A1"]) is True


def test_is_formula_with_refs_cross_sheet():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "=Utenze!D3"
    assert is_value_cell(ws["A1"]) is False
    assert is_formula_with_refs(ws["A1"]) is True


def test_is_formula_with_refs_sum():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "=SUM(C6:C11)"
    assert is_formula_with_refs(ws["A1"]) is True


def test_is_value_cell_empty_is_false():
    wb = openpyxl.Workbook()
    ws = wb.active
    assert is_value_cell(ws["A1"]) is False  # None


def test_resolve_sheet_name_exact():
    wb = openpyxl.Workbook()
    wb.active.title = "Materie Prime-Consumo "
    wb.create_sheet("Utenze")
    assert (
        resolve_sheet_name(wb, ["Materie Prime-Consumo ", "Materie Prime-Conumo "])
        == "Materie Prime-Consumo "
    )


def test_resolve_sheet_name_typo_fallback():
    wb = openpyxl.Workbook()
    wb.active.title = "Materie Prime-Conumo "  # typo variant
    assert (
        resolve_sheet_name(wb, ["Materie Prime-Consumo ", "Materie Prime-Conumo "])
        == "Materie Prime-Conumo "
    )


def test_resolve_sheet_name_none_when_absent():
    wb = openpyxl.Workbook()
    wb.active.title = "Foo"
    assert resolve_sheet_name(wb, ["Bar", "Baz"]) is None


def test_find_total_row_and_sum_range_utenze(minimal_pf_orti_bytes):
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    ws = wb["Utenze"]
    # In fixture: r3 has =SUM(D4:D50), =SUM(E4:E50), ...
    total_row, sum_start, sum_end = find_total_row_and_sum_range(ws)
    assert total_row == 3
    assert sum_start == 4
    assert sum_end == 50
