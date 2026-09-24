"""Tests per ingest_occupazione_pms — BU dal footer Power BI (positivo o in negazione)."""

from pathlib import Path

import openpyxl
import pytest

HEADER = ["Data", "Cam. Totali", "OOO", "Cam. Vendibili", "Cam. Occupate", "Cam. Day Use",
          "Adulti", "Ragazzi", "Bambini", "ARB", "Infant", "Pax Day Use", "Importo"]


def _make_xlsx(tmp_path: Path, footer: str) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(HEADER)
    ws.append(["01/05/2026", 86, 11, 75, 75, 0, 163, 0, 7, 170, 6, 0, 17168.07])
    ws.append([footer])
    path = tmp_path / "Daily Production Report (6).xlsx"
    wb.save(path)
    return path


def test_footer_positivo_da_bu(tmp_path):
    from ingest.flussi.ingest_occupazione_pms import detect_bu_from_footer

    path = _make_xlsx(tmp_path, "Applied filters:\nCodiceHotel is PANORAMAHT\nAnno is 2026")
    assert detect_bu_from_footer(path) == "HOTEL"


def test_footer_in_negazione_da_bu_per_complemento(tmp_path):
    # Export Power BI 2026-09-24: "CodiceHotel is not HOMEHOLIDAY or ANGELINARES" → HOTEL
    from ingest.flussi.ingest_occupazione_pms import detect_bu_from_footer

    path = _make_xlsx(
        tmp_path,
        "Applied filters:\nMis_PB_ShowRow is greater than 0\n"
        "CodiceHotel is not HOMEHOLIDAY or ANGELINARES\nAnno is 2026\nDescrizione is Imponibile",
    )
    assert detect_bu_from_footer(path) == "HOTEL"


def test_footer_in_negazione_ambiguo_esplode(tmp_path):
    # Esclusa una sola struttura su tre: il complemento non è univoco → mai default silenzioso.
    from ingest.flussi.ingest_occupazione_pms import detect_bu_from_footer

    path = _make_xlsx(tmp_path, "Applied filters:\nCodiceHotel is not PANORAMAHT\nAnno is 2026")
    with pytest.raises(ValueError, match="ambigu"):
        detect_bu_from_footer(path)
