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


class TestMapToVoci:
    def test_maps_supplier_to_voce(self):
        from condges.scadenzario_excel import map_to_voci
        partite = [
            {"codice_fornitore": 1, "nome": "LE CROISSANT", "totale": -1000,
             "scaduto": -500, "buckets": {5: -500}},
        ]
        fornitori_map = {1: "USCITE_MATERIE_PRIME"}
        mapped, unmapped = map_to_voci(partite, fornitori_map)
        assert "USCITE_MATERIE_PRIME" in mapped
        assert len(mapped["USCITE_MATERIE_PRIME"]) == 1
        assert unmapped == []

    def test_unmapped_supplier_goes_to_unmapped_list(self):
        from condges.scadenzario_excel import map_to_voci
        partite = [
            {"codice_fornitore": 9999, "nome": "UNKNOWN", "totale": -100,
             "scaduto": -100, "buckets": {}},
        ]
        fornitori_map = {1: "USCITE_MATERIE_PRIME"}
        mapped, unmapped = map_to_voci(partite, fornitori_map)
        assert len(unmapped) == 1
        assert unmapped[0]["codice_fornitore"] == 9999

    def test_multiple_suppliers_same_voce(self):
        from condges.scadenzario_excel import map_to_voci
        partite = [
            {"codice_fornitore": 1, "nome": "A", "totale": -500,
             "scaduto": -500, "buckets": {}},
            {"codice_fornitore": 4, "nome": "B", "totale": -300,
             "scaduto": -300, "buckets": {}},
        ]
        fornitori_map = {1: "USCITE_MATERIE_PRIME", 4: "USCITE_MATERIE_PRIME"}
        mapped, unmapped = map_to_voci(partite, fornitori_map)
        assert len(mapped["USCITE_MATERIE_PRIME"]) == 2


class TestLoadFornitoriMap:
    def test_loads_csv(self, tmp_path):
        from condges.scadenzario_excel import load_fornitori_map
        csv_path = tmp_path / "d_fornitori.csv"
        csv_path.write_text(
            "codice_fornitore,nome_esolver,nome_pf,voce_id,is_intercompany\n"
            "1,LE CROISSANT SRL,Le Croissant,USCITE_MATERIE_PRIME,False\n"
            "264,PANORAMA COMPANY S.R.L.,Fitto,USCITE_CANONE_PASSIVO,True\n"
        )
        result = load_fornitori_map(csv_path=csv_path)
        assert result[1] == "USCITE_MATERIE_PRIME"
        assert result[264] == "USCITE_CANONE_PASSIVO"
