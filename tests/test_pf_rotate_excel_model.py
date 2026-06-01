from io import BytesIO
import openpyxl

from verticals.condges.pf_rotate.excel_model import (
    find_layout,
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


def test_find_layout_orti_fixture(minimal_pf_orti_bytes):
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    layout = find_layout(wb)
    assert layout.saldo_iniziale_row == 4
    assert layout.totale_entrate_row == 12
    assert layout.totale_uscite_row == 27
    assert layout.cashflow_row == 29
    assert layout.totale_banche_row == 35
    assert layout.saldo_proiettato_row == 37
    assert layout.saldi_banca_rows == [32, 33]
    assert layout.entrate_rows == [6, 7, 8, 9, 10, 11]


def test_find_layout_intur_style_fixture():
    """Build a minimal INTUR-style workbook (saldo at r3, etc.) e verifica layout detection."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    pf = wb.create_sheet("Piano Finanziario")
    pf["A1"] = "INTUR"
    # INTUR: saldo at r3 (NOT r4)
    pf["A3"] = "SALDO MESE PRECED."
    pf["A5"] = "Fitto Hotel"
    pf["A6"] = "Fitto AR"
    pf["A7"] = "Entrate Residence"
    pf["A12"] = "TOTALE ENTRATE"
    pf["A14"] = "Salari e Stipendi"
    pf["A15"] = "Utenze"
    pf["A27"] = "TOTALE USCITE"
    pf["A29"] = "CASH FLOW"
    pf["A31"] = "Saldo Banca Sella"
    pf["A32"] = "Saldo MPS"
    pf["A33"] = "Saldo Intesa"
    pf["A35"] = "TOTALE BANCHE"
    pf["A38"] = "Saldo di Periodo/Proiettato"

    layout = find_layout(wb)
    assert layout.saldo_iniziale_row == 3
    assert layout.totale_entrate_row == 12
    assert layout.totale_uscite_row == 27
    assert layout.cashflow_row == 29
    assert layout.totale_banche_row == 35
    assert layout.saldo_proiettato_row == 38
    assert layout.saldi_banca_rows == [31, 32, 33]
    assert layout.entrate_rows == [5, 6, 7]
