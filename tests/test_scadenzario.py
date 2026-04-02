"""Tests for scadenzario Excel bridge."""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import date


def _make_sintetica_workbook(rows, header_dates=None):
    """Create a minimal sintetica-style workbook in memory."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="Fornitore/Tipo pagamento/Conto")
    ws.cell(row=1, column=2, value="Scadenze - Totale")
    ws.cell(row=1, column=3, value="Scadenze - Scaduto fino al 02/04/2026")
    defaults = header_dates or [
        "Scadenze - In scadenza al 02/05/2026",
        "Scadenze - In scadenza al 02/06/2026",
        "Scadenze - In scadenza al 02/07/2026",
    ]
    for i, h in enumerate(defaults):
        ws.cell(row=1, column=4 + i, value=h)
    for r_idx, row_data in enumerate(rows, start=2):
        ws.cell(row=r_idx, column=1, value=row_data[0])
        if len(row_data) > 1 and row_data[1] is not None:
            ws.cell(row=r_idx, column=2, value=row_data[1])
        if len(row_data) > 2 and row_data[2] is not None:
            ws.cell(row=r_idx, column=3, value=row_data[2])
        for i, val in enumerate(row_data[3:]):
            if val is not None:
                ws.cell(row=r_idx, column=4 + i, value=val)
    return wb


class TestParseSinteticaScadenze:
    def test_parses_codice_and_nome(self, tmp_path):
        from condges.scadenzario_excel import parse_sintetica_scadenze
        wb = _make_sintetica_workbook([
            ("264 PANORAMA COMPANY S.R.L.", -1000, -500, -500),
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)
        result = parse_sintetica_scadenze(f)
        assert len(result) == 1
        assert result[0]["codice_fornitore"] == 264
        assert result[0]["nome"] == "PANORAMA COMPANY S.R.L."

    def test_parses_buckets_from_headers(self, tmp_path):
        from condges.scadenzario_excel import parse_sintetica_scadenze
        wb = _make_sintetica_workbook([
            ("1 FORNITORE TEST", -1500, -500, -600, -400),
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)
        result = parse_sintetica_scadenze(f)
        r = result[0]
        assert r["totale"] == -1500
        assert r["scaduto"] == -500
        assert r["buckets"] == {5: -600, 6: -400}

    def test_skips_rows_without_numeric_prefix(self, tmp_path):
        from condges.scadenzario_excel import parse_sintetica_scadenze
        wb = _make_sintetica_workbook([
            ("264 PANORAMA S.R.L.", -1000, -1000),
            ("Totale", -1000, -1000),
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)
        result = parse_sintetica_scadenze(f)
        assert len(result) == 1

    def test_handles_positive_amounts(self, tmp_path):
        from condges.scadenzario_excel import parse_sintetica_scadenze
        wb = _make_sintetica_workbook([
            ("1008 MIELE SPA", 2294.28, 2294.28),
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)
        result = parse_sintetica_scadenze(f)
        assert result[0]["totale"] == 2294.28
