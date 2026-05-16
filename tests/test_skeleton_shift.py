"""Tests for the monthly skeleton shift used in the cashflow rollover.

The shift moves VALUE cells left by 1 column inside the PF "forward months"
range, preserving FORMULA cells (they reference fixed cells like =C37 and
remain correct in place). The new last column starts empty for the wraparound
month. Headers (row 2 month names + row 1 year markers) are updated.
"""

from __future__ import annotations

import openpyxl

MASTER_MONTHS_SEED = ["APRILE", "MAGGIO", "GIUGNO", "LUGLIO", "AGOSTO",
                      "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE"]
DETAIL_MONTHS_SEED = MASTER_MONTHS_SEED


def _make_master(months: list[str] = None, year: int = 2026) -> openpyxl.Workbook:
    """Minimal master 'Piano Finanziario' sheet mirroring the real file."""
    months = months or MASTER_MONTHS_SEED
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Piano Finanziario"

    ws.cell(row=1, column=1, value="ORTI S.R.L.")
    ws.cell(row=1, column=3, value=float(year))
    for i, m in enumerate(months):
        ws.cell(row=2, column=3 + i, value=m)

    # row 4: SALDO MESE PRECED — col 3 VALUE, col 4..11 FORMULA =C37, =D37 ...
    ws.cell(row=4, column=1, value="SALDO MESE PRECED")
    ws.cell(row=4, column=3, value=115860.87)
    for i in range(1, len(months)):
        col = 3 + i
        col_letter = openpyxl.utils.get_column_letter(col - 1)
        ws.cell(row=4, column=col, value=f"={col_letter}37")

    # row 6: Entrate Hotel — manual VALUES across months
    ws.cell(row=6, column=1, value="Entrate Hotel ")
    apr_vals = [123000, 450000, 600000, 750000, 830000, 580000, 270000, None, None]
    for i, v in enumerate(apr_vals):
        if v is not None:
            ws.cell(row=6, column=3 + i, value=v)

    # row 12: TOTALE ENTRATE — FORMULA =SUM(C6:C11)
    ws.cell(row=12, column=1, value="TOTALE ENTRATE")
    for i in range(len(months)):
        col_letter = openpyxl.utils.get_column_letter(3 + i)
        ws.cell(row=12, column=3 + i, value=f"=SUM({col_letter}6:{col_letter}11)")

    # row 14: Salari — VALUES
    ws.cell(row=14, column=1, value="Salari e Stipendi")
    sal_vals = [27780, 77000, 102000, 112000, 137000, 117000, 108682, 175000, 58000]
    for i, v in enumerate(sal_vals):
        ws.cell(row=14, column=3 + i, value=v)

    # row 27: TOTALE USCITE — FORMULA
    ws.cell(row=27, column=1, value="TOTALE USCITE ")
    for i in range(len(months)):
        col_letter = openpyxl.utils.get_column_letter(3 + i)
        ws.cell(row=27, column=3 + i, value=f"=SUM({col_letter}14:{col_letter}26)")

    # row 31: date reference
    ws.cell(row=31, column=1, value="31/03/2026")
    # row 32: Saldo MPS — VALUE in col 3 only
    ws.cell(row=32, column=1, value="Saldo MPS")
    ws.cell(row=32, column=3, value=52799.65)
    ws.cell(row=33, column=1, value="Saldo Intesa")
    ws.cell(row=33, column=3, value=63061.22)
    ws.cell(row=35, column=1, value="TOTALE BANCHE ")
    ws.cell(row=35, column=3, value="=SUM(C32:C34)")

    # row 37: Saldo di Periodo — FORMULA across all months
    ws.cell(row=37, column=1, value="Saldo di Periodo/Proiett")
    for i in range(len(months)):
        col_letter = openpyxl.utils.get_column_letter(3 + i)
        ws.cell(row=37, column=3 + i, value=f"={col_letter}4+{col_letter}29")

    return wb


def _make_detail(sheet_name: str = "Materie Prime-Consumo ",
                 months: list[str] = None,
                 year: int = 2026) -> openpyxl.Workbook:
    """Minimal per-voce detail sheet."""
    months = months or DETAIL_MONTHS_SEED
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    ws.cell(row=1, column=4, value=float(year))
    ws.cell(row=2, column=1, value="CODICE")
    for i, m in enumerate(months):
        ws.cell(row=2, column=4 + i, value=m)

    # row 3 PREVISIONALE — col 3 FORMULA aggregate, col 4..12 VALUES
    ws.cell(row=3, column=2, value="PREVISIONALE")
    ws.cell(row=3, column=3, value="=SUM(D3:L3)")
    prev = [60000, 40000, 95000, 120000, 145000, 140000, 135000, 75000, 60000]
    for i, v in enumerate(prev):
        ws.cell(row=3, column=4 + i, value=v)

    # row 4 totale voce — col 3 FORMULA aggregate, col 4..12 FORMULAS sum suppliers
    ws.cell(row=4, column=2, value="Materie Prime e Consumo ")
    ws.cell(row=4, column=3, value="=SUM(D4:L4)")
    for i in range(len(months)):
        col_letter = openpyxl.utils.get_column_letter(4 + i)
        ws.cell(row=4, column=4 + i, value=f"=SUM({col_letter}5:{col_letter}178)")

    # row 5: empty supplier (all None except row aggregate)
    ws.cell(row=5, column=1, value=801)
    ws.cell(row=5, column=2, value="A. Migliore srl")
    ws.cell(row=5, column=3, value="=SUM(D5:L5)")

    # row 8: supplier with value in APRILE only
    ws.cell(row=8, column=1, value=412)
    ws.cell(row=8, column=2, value="Alberto D'Urso")
    ws.cell(row=8, column=3, value="=SUM(D8:L8)")
    ws.cell(row=8, column=4, value=819.45)  # APRILE

    # row 10: supplier with APRILE + MAGGIO
    ws.cell(row=10, column=1, value=92)
    ws.cell(row=10, column=2, value="Amalfi sei esse")
    ws.cell(row=10, column=3, value="=SUM(D10:L10)")
    ws.cell(row=10, column=4, value=111.97)
    ws.cell(row=10, column=5, value=247.71)

    return wb


# ── Master shift ────────────────────────────────────────────────────────────


class TestShiftMaster:
    def test_month_headers_shift_left_with_wraparound(self):
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]

        shift_master_sheet(ws, current_year=2026)

        expected = ["MAGGIO", "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE",
                    "OTTOBRE", "NOVEMBRE", "DICEMBRE", "GENNAIO"]
        actual = [ws.cell(row=2, column=3 + i).value for i in range(9)]
        assert actual == expected

    def test_year_marker_added_for_wraparound(self):
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]

        shift_master_sheet(ws, current_year=2026)

        # col 3 still 2026 (now MAGGIO 2026), col 11 should be 2027 (GENNAIO 2027)
        assert ws.cell(row=1, column=3).value == 2026.0
        assert ws.cell(row=1, column=11).value == 2027.0

    def test_value_rows_shift_left(self):
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]

        shift_master_sheet(ws, current_year=2026)

        # row 6 Entrate Hotel: original 123000 (APR) | 450000 (MAG) | 600000 (GIU)...
        # after shift: col 3 (MAGGIO) = 450000, col 4 (GIUGNO) = 600000 ...
        assert ws.cell(row=6, column=3).value == 450000
        assert ws.cell(row=6, column=4).value == 600000
        assert ws.cell(row=6, column=5).value == 750000

        # row 14 Salari: APR=27780, MAG=77000 ...
        # after: col 3 = 77000, col 4 = 102000 ...
        assert ws.cell(row=14, column=3).value == 77000
        assert ws.cell(row=14, column=4).value == 102000

    def test_last_column_value_cleared_for_wraparound(self):
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]

        shift_master_sheet(ws, current_year=2026)

        # row 14 Salari last column (GENNAIO 2027) should be empty (None)
        assert ws.cell(row=14, column=11).value is None
        # row 6 Entrate Hotel last column also empty
        assert ws.cell(row=6, column=11).value is None

    def test_formula_cells_unchanged(self):
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]

        shift_master_sheet(ws, current_year=2026)

        # row 12 TOTALE ENTRATE formulas =SUM(C6:C11) etc. stay in place
        assert ws.cell(row=12, column=3).value == "=SUM(C6:C11)"
        assert ws.cell(row=12, column=4).value == "=SUM(D6:D11)"
        # row 27 TOTALE USCITE
        assert ws.cell(row=27, column=3).value == "=SUM(C14:C26)"
        # row 37 Saldo di Periodo
        assert ws.cell(row=37, column=3).value == "=C4+C29"
        # row 4 col 4 was =C37 — stays
        assert ws.cell(row=4, column=4).value == "=C37"

    def test_saldo_mese_preced_value_untouched(self):
        """Row 4 col 3 (SALDO MESE PRECED current month VALUE) is NOT shifted;
        bank-balance update step owns it."""
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]
        original = ws.cell(row=4, column=3).value

        shift_master_sheet(ws, current_year=2026)

        assert ws.cell(row=4, column=3).value == original

    def test_bank_balance_rows_untouched(self):
        """Rows 32-33 (Saldo MPS, Saldo Intesa) and row 31 (date) are NOT
        touched here; bank-balance update step owns them."""
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]

        shift_master_sheet(ws, current_year=2026)

        assert ws.cell(row=31, column=1).value == "31/03/2026"
        assert ws.cell(row=32, column=3).value == 52799.65
        assert ws.cell(row=33, column=3).value == 63061.22


# ── Detail shift ────────────────────────────────────────────────────────────


class TestShiftDetail:
    def test_month_headers_shift_left(self):
        from verticals.condges.skeleton_shift import shift_detail_sheet
        wb = _make_detail()
        ws = wb["Materie Prime-Consumo "]

        shift_detail_sheet(ws, current_year=2026)

        expected = ["MAGGIO", "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE",
                    "OTTOBRE", "NOVEMBRE", "DICEMBRE", "GENNAIO"]
        actual = [ws.cell(row=2, column=4 + i).value for i in range(9)]
        assert actual == expected

    def test_year_marker_wraparound(self):
        from verticals.condges.skeleton_shift import shift_detail_sheet
        wb = _make_detail()
        ws = wb["Materie Prime-Consumo "]

        shift_detail_sheet(ws, current_year=2026)

        assert ws.cell(row=1, column=4).value == 2026.0
        assert ws.cell(row=1, column=12).value == 2027.0

    def test_previsionale_row_shifts(self):
        from verticals.condges.skeleton_shift import shift_detail_sheet
        wb = _make_detail()
        ws = wb["Materie Prime-Consumo "]

        shift_detail_sheet(ws, current_year=2026)

        # row 3 PREVISIONALE: was [60000, 40000, 95000, 120000, ...]
        # after shift: col 4 (MAGGIO) = 40000, col 5 (GIUGNO) = 95000, ...
        assert ws.cell(row=3, column=4).value == 40000
        assert ws.cell(row=3, column=5).value == 95000
        # last col cleared
        assert ws.cell(row=3, column=12).value is None

    def test_supplier_values_shift(self):
        from verticals.condges.skeleton_shift import shift_detail_sheet
        wb = _make_detail()
        ws = wb["Materie Prime-Consumo "]

        shift_detail_sheet(ws, current_year=2026)

        # row 8 Alberto D'Urso: had 819.45 in APRILE (col 4). After shift,
        # col 4 (MAGGIO) should be None (because old MAGGIO was empty)
        assert ws.cell(row=8, column=4).value is None

        # row 10 Amalfi sei esse: had 111.97 in APR (col 4), 247.71 in MAG (col 5)
        # after shift: col 4 (MAGGIO) = 247.71, col 5 (GIUGNO) = None
        assert ws.cell(row=10, column=4).value == 247.71
        assert ws.cell(row=10, column=5).value is None

    def test_formula_cells_unchanged(self):
        from verticals.condges.skeleton_shift import shift_detail_sheet
        wb = _make_detail()
        ws = wb["Materie Prime-Consumo "]

        shift_detail_sheet(ws, current_year=2026)

        # row 4 totale voce formulas stay
        assert ws.cell(row=4, column=4).value == "=SUM(D5:D178)"
        assert ws.cell(row=4, column=12).value == "=SUM(L5:L178)"
        # row 3 col 3 aggregate formula stays
        assert ws.cell(row=3, column=3).value == "=SUM(D3:L3)"
        # supplier row aggregate formulas stay
        assert ws.cell(row=5, column=3).value == "=SUM(D5:L5)"
        assert ws.cell(row=10, column=3).value == "=SUM(D10:L10)"


# ── Month name utilities ────────────────────────────────────────────────────


class TestMergedHeaders:
    def test_master_row1_merged_year_is_split_on_wraparound(self):
        """Real PF has C1:K1 merged with single year value. After rollover with
        wraparound, year should split into two merged ranges (2026 + 2027)."""
        from verticals.condges.skeleton_shift import shift_master_sheet
        wb = _make_master()
        ws = wb["Piano Finanziario"]
        ws.merge_cells("C1:K1")  # simulate real-file merge

        shift_master_sheet(ws, current_year=2026)

        assert ws.cell(row=1, column=3).value == 2026.0
        assert ws.cell(row=1, column=11).value == 2027.0
        # 2026 should span C1:J1 (8 cols, MAY-DEC), 2027 just K1 (1 col, JAN)
        ranges = {str(r) for r in ws.merged_cells.ranges}
        assert "C1:J1" in ranges
        assert "K1:K1" not in ranges  # single cell is not merged
        # Original C1:K1 must be gone
        assert "C1:K1" not in ranges

    def test_detail_row1_merged_year_is_split_on_wraparound(self):
        from verticals.condges.skeleton_shift import shift_detail_sheet
        wb = _make_detail()
        ws = wb["Materie Prime-Consumo "]
        ws.merge_cells("D1:L1")

        shift_detail_sheet(ws, current_year=2026)

        assert ws.cell(row=1, column=4).value == 2026.0
        assert ws.cell(row=1, column=12).value == 2027.0
        ranges = {str(r) for r in ws.merged_cells.ranges}
        assert "D1:K1" in ranges
        assert "D1:L1" not in ranges


class TestRolloverMonths:
    def test_simple_shift_no_wraparound(self):
        from verticals.condges.skeleton_shift import rollover_month_labels
        labels, year_changes = rollover_month_labels(
            current_month=4, current_year=2026, n_forward=9
        )
        assert labels == [
            "MAGGIO", "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE",
            "OTTOBRE", "NOVEMBRE", "DICEMBRE", "GENNAIO",
        ]
        # year_changes: list of (slot_index, new_year) for the wraparound
        assert year_changes == [(8, 2027)]

    def test_multi_year_wraparound(self):
        """Rolling from Nov: labels span 2 year transitions."""
        from verticals.condges.skeleton_shift import rollover_month_labels
        labels, year_changes = rollover_month_labels(
            current_month=11, current_year=2026, n_forward=9
        )
        # current_month=11 means we're AT November. Rollover to month 12.
        # n_forward=9 produces months 12, 1, 2, 3, 4, 5, 6, 7, 8 with years
        # 2026, 2027, 2027, 2027, 2027, 2027, 2027, 2027, 2027
        assert labels[0] == "DICEMBRE"
        assert labels[1] == "GENNAIO"
        assert year_changes == [(1, 2027)]
