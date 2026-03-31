"""Tests for condges/parse_pf.py -- Rosa's Piano Finanziario Excel parser.

Uses in-memory openpyxl Workbooks so no real files are needed.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook


# ---------------------------------------------------------------------------
# Helpers to build minimal ORTI / INTUR fixtures in memory
# ---------------------------------------------------------------------------

MESI_IT = [
    "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
    "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE",
]


def _wb_to_bytes(wb: Workbook) -> BytesIO:
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _make_orti_wb() -> Workbook:
    """Build a minimal ORTI PF workbook that mirrors Rosa's real format.

    Layout:
      A2="ORTI"  B2=date(2026,2,28)  C1=2026
      Row 2 cols C-N: GENNAIO..DICEMBRE (month headers)
      Entrate rows (5-10):
        Row 5:  A="Entrate Hotel",       C..N = 700000 each (Jul value must be recognizable)
        Row 6:  A="Entrate Residence",   C..N = 50000
        Row 7:  A="Entrate CVM",         C..N = 10000
        Row 8:  A="Entrate Supermercato",C..N = 5000
        Row 9:  A="Rientro Sospesi",     C..N = 0
        Row 10: A="Caparre Intur",       C..N = 3000
      Row 11: A="Totale Entrate" (skip label)
      Uscite rows (14-24):
        Row 14: A="Salari e Stipendi",   C=18142.04, rest=15000
        Row 15: A="Utenze",              C..N = 8000
        Row 16: A="Materie Prime/Consumo",C..N=4000
        Row 17: A="Tasse e Imposte",     C..N=2000
        Row 18: A="Commissioni Portali", C..N=1500
        Row 19: A="Mutui e Finaziamenti",C..N=9000   # Rosa's typo
        Row 20: A="Consulenze",          C..N=3000
        Row 21: A="Godimento Beni di Terzi", C..N=5500
        Row 22: A="Varie ed Eventuali",  C..N=800
        Row 23: A="Canoni e Servizi",    C..N=600
        Row 24: A="Deposito Fitto",      C..N=0
      Row 32: A="Saldo MPS",    B=67724.67
      Row 33: A="Saldo Intesa", B=66922.12
      Row 35: A="TOTALE BANCHE ",        B=134646.79
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Piano Finanziario"

    # Header identifiers
    ws["A2"] = "ORTI"
    ws["B2"] = date(2026, 2, 28)
    ws["C1"] = 2026

    # Month headers in row 2, cols C(3)..N(14)
    for i, mese in enumerate(MESI_IT):
        ws.cell(row=2, column=3 + i, value=mese)

    # Entrate
    entrate = [
        ("Entrate Hotel",        [700000] * 12),
        ("Entrate Residence",    [50000] * 12),
        ("Entrate CVM",          [10000] * 12),
        ("Entrate Supermercato", [5000] * 12),
        ("Rientro Sospesi",      [0] * 12),
        ("Caparre Intur",        [3000] * 12),
    ]
    for row_idx, (label, vals) in enumerate(entrate, start=5):
        ws.cell(row=row_idx, column=1, value=label)
        for col_idx, v in enumerate(vals):
            ws.cell(row=row_idx, column=3 + col_idx, value=v)

    ws["A11"] = "Totale Entrate"

    # Uscite  (Salari March = col 5 = index 2 in vals = 18142.04)
    salari_vals = [15000] * 12
    salari_vals[2] = 18142.04  # March

    uscite = [
        ("Salari e Stipendi",        salari_vals),
        ("Utenze",                   [8000] * 12),
        ("Materie Prime/Consumo",    [4000] * 12),
        ("Tasse e Imposte",          [2000] * 12),
        ("Commissioni Portali",      [1500] * 12),
        ("Mutui e Finaziamenti",     [9000] * 12),  # Rosa typo
        ("Consulenze",               [3000] * 12),
        ("Godimento Beni di Terzi",  [5500] * 12),
        ("Varie ed Eventuali",       [800] * 12),
        ("Canoni e Servizi",         [600] * 12),
        ("Deposito Fitto",           [0] * 12),
    ]
    for row_idx, (label, vals) in enumerate(uscite, start=14):
        ws.cell(row=row_idx, column=1, value=label)
        for col_idx, v in enumerate(vals):
            ws.cell(row=row_idx, column=3 + col_idx, value=v)

    # Saldi banca
    ws["A32"] = "Saldo MPS"
    ws["B32"] = 67724.67
    ws["A33"] = "Saldo Intesa"
    ws["B33"] = 66922.12
    ws["A35"] = "TOTALE BANCHE "
    ws["B35"] = 134646.79

    return wb


def _make_intur_wb() -> Workbook:
    """Build a minimal INTUR PF workbook.

    Layout (from task spec):
      A1="INTUR"  C3=date(2025,10,31)
      Row 1 cols 4-5: year 2025 months (Nov, Dec)
      Row 1 cols 6+:  year 2026 months (Jan-Dec) — so 14 month columns total
      But we simplify: row 3 cols C(3)..N(14) = GENNAIO..DICEMBRE (2026 months).
      Saldi in col C (not B):
        Row 33: A="Saldo Banca Sella", C=17317.96
        Row 34: A="Saldo MPS",         C=37075.87
        Row 35: A="Saldo Intesa",      C=3000
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Piano Finanziario"

    ws["A1"] = "INTUR"
    ws["C3"] = date(2025, 10, 31)
    ws["C1"] = 2026  # anno header

    # Month headers in row 3, cols D(4)..O(15) — C3 is the data_saldo date
    for i, mese in enumerate(MESI_IT):
        ws.cell(row=3, column=4 + i, value=mese)

    entrate_intur = [
        ("Fitto Hotel",                [80000] * 12),
        ("Fitto AR",                   [20000] * 12),
        ("Ribaltamento Costi a Orti",  [5000] * 12),
        ("Entrate Farmacia",           [3000] * 12),
        ("Entrate Spiaggia",           [12000] * 12),
    ]
    for row_idx, (label, vals) in enumerate(entrate_intur, start=5):
        ws.cell(row=row_idx, column=1, value=label)
        for col_idx, v in enumerate(vals):
            ws.cell(row=row_idx, column=4 + col_idx, value=v)

    uscite_intur = [
        ("Salari e Stipendi",         [15000] * 12),
        ("Utenze",                    [8000] * 12),
        ("Mutui e Finanziamenti",     [9000] * 12),
        ("Godimento Benidi Terzi",    [5500] * 12),  # INTUR typo
        ("Caparre da Girocantare aOrti", [2000] * 12),
    ]
    for row_idx, (label, vals) in enumerate(uscite_intur, start=14):
        ws.cell(row=row_idx, column=1, value=label)
        for col_idx, v in enumerate(vals):
            ws.cell(row=row_idx, column=4 + col_idx, value=v)

    # Saldi in col C
    ws["A33"] = "Saldo Banca Sella"
    ws["C33"] = 17317.96
    ws["A34"] = "Saldo MPS"
    ws["C34"] = 37075.87
    ws["A35"] = "Saldo Intesa"
    ws["C35"] = 3000.0

    return wb


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def orti_bytes() -> BytesIO:
    return _wb_to_bytes(_make_orti_wb())


@pytest.fixture()
def intur_bytes() -> BytesIO:
    return _wb_to_bytes(_make_intur_wb())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseORTI:
    def test_parse_orti_detects_societa(self, orti_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert result.societa == "ORTI"

    def test_parse_orti_anno(self, orti_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert result.anno == 2026

    def test_parse_orti_reads_data_saldo(self, orti_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert result.data_saldo == date(2026, 2, 28)

    def test_parse_orti_reads_voci_hotel_luglio(self, orti_bytes):
        """Entrate Hotel Luglio (month 7) = 700000."""
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert "ENTRATE_HOTEL" in result.voci
        assert result.voci["ENTRATE_HOTEL"].importi[7] == 700000

    def test_parse_orti_reads_voci_salari_marzo(self, orti_bytes):
        """Salari Marzo (month 3) = 18142.04."""
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert "USCITE_SALARI" in result.voci
        assert result.voci["USCITE_SALARI"].importi[3] == pytest.approx(18142.04)

    def test_parse_orti_reads_saldi_banca(self, orti_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert result.saldi_banca["Saldo MPS"] == pytest.approx(67724.67)
        assert result.saldi_banca["Saldo Intesa"] == pytest.approx(66922.12)

    def test_parse_orti_saldo_totale(self, orti_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert result.saldo_totale == pytest.approx(134646.79)

    def test_parse_orti_all_12_months_present(self, orti_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        hotel = result.voci["ENTRATE_HOTEL"]
        assert set(hotel.importi.keys()) == set(range(1, 13))

    def test_parse_orti_no_skip_labels_as_voci(self, orti_bytes):
        """'Totale Entrate' must not appear as a voce."""
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        voce_ids = set(result.voci.keys())
        assert not any("TOTALE" in v for v in voce_ids)

    def test_parse_mutui_typo_matches(self, orti_bytes):
        """Rosa's typo 'Mutui e Finaziamenti' (missing 'n') must map to USCITE_MUTUI."""
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert "USCITE_MUTUI" in result.voci

    def test_parse_orti_excel_label_preserved(self, orti_bytes):
        """excel_label on VoceRow must match the original cell text."""
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert result.voci["ENTRATE_HOTEL"].excel_label == "Entrate Hotel"

    def test_parse_orti_voce_id_on_row(self, orti_bytes):
        """VoceRow.voce_id must equal the key in voci dict."""
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        for voce_id, row in result.voci.items():
            assert row.voce_id == voce_id


class TestParseINTUR:
    def test_parse_intur_detects_societa(self, intur_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(intur_bytes)
        assert result.societa == "INTUR"

    def test_parse_intur_anno(self, intur_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(intur_bytes)
        assert result.anno == 2026

    def test_parse_intur_reads_data_saldo(self, intur_bytes):
        from condges.parse_pf import parse_pf
        result = parse_pf(intur_bytes)
        assert result.data_saldo == date(2025, 10, 31)

    def test_parse_intur_fitto_hotel_and_ar_summed(self, intur_bytes):
        """'Fitto Hotel' + 'Fitto AR' both map to ENTRATE_AFFITTI_INTUR; amounts summed."""
        from condges.parse_pf import parse_pf
        result = parse_pf(intur_bytes)
        assert "ENTRATE_AFFITTI_INTUR" in result.voci
        # 80000 + 20000 = 100000 for every month
        assert result.voci["ENTRATE_AFFITTI_INTUR"].importi[1] == pytest.approx(100000)

    def test_parse_intur_godimento_beni_typo(self, intur_bytes):
        """'Godimento Benidi Terzi' (INTUR typo) maps to USCITE_GODIMENTO_BENI."""
        from condges.parse_pf import parse_pf
        result = parse_pf(intur_bytes)
        assert "USCITE_GODIMENTO_BENI" in result.voci

    def test_parse_intur_caparre_girocantare(self, intur_bytes):
        """'Caparre da Girocantare aOrti' maps to ENTRATE_CAPARRE_INTUR."""
        from condges.parse_pf import parse_pf
        result = parse_pf(intur_bytes)
        assert "ENTRATE_CAPARRE_INTUR" in result.voci

    def test_parse_intur_saldi_banca_col_c(self, intur_bytes):
        """INTUR saldi are in col C, not B."""
        from condges.parse_pf import parse_pf
        result = parse_pf(intur_bytes)
        assert result.saldi_banca["Saldo Banca Sella"] == pytest.approx(17317.96)
        assert result.saldi_banca["Saldo MPS"] == pytest.approx(37075.87)
        assert result.saldi_banca["Saldo Intesa"] == pytest.approx(3000.0)


class TestWarnings:
    def test_unknown_voce_logged_as_warning(self):
        """A label not in the mapping must appear in warnings, not crash."""
        from condges.parse_pf import parse_pf

        wb = Workbook()
        ws = wb.active
        ws.title = "Piano Finanziario"
        ws["A2"] = "ORTI"
        ws["C1"] = 2026
        for i, mese in enumerate(MESI_IT):
            ws.cell(row=2, column=3 + i, value=mese)
        # Unknown voce
        ws["A5"] = "Voce Sconosciuta XYZ"
        for col in range(3, 15):
            ws.cell(row=5, column=col, value=9999)

        buf = _wb_to_bytes(wb)
        result = parse_pf(buf)
        assert any("Voce Sconosciuta XYZ" in w for w in result.warnings)
        assert "Voce Sconosciuta XYZ" not in result.voci

    def test_no_warnings_on_clean_orti(self, orti_bytes):
        """A well-formed ORTI file must produce no warnings."""
        from condges.parse_pf import parse_pf
        result = parse_pf(orti_bytes)
        assert result.warnings == []
