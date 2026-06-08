"""Tests for scheda contabile Esolver parser (multi-bank XLSX support)."""

from datetime import date
from pathlib import Path

import openpyxl


SCHEDA_HEADER = [
    "Data registrazione",
    "Rif. registrazione",
    "Causale contabile",
    "Dare in UdC",
    "Avere in UdC",
    "Saldo in UdC",
    "Documento",
    "Partitario",
    "Descrizione partitario",
]

# ORTI multi-bank mastrino: partitario 2=MPS, 3=MPS_KROSS.
# The "Saldo in UdC" column (idx 5) is a cumulative cross-bank total and MUST be
# ignored: the parser recomputes a per-bank running balance from dare/avere.
ORTI_MULTIBANK_ROWS = [
    [date(2026, 1, 2), "PNC n 1", "mov MPS", 100, 0, 100, "", 2, "MONTE DEI PASCHI"],
    [date(2026, 1, 2), "PNC n 2", "mov KROSS", 50, 0, 150, "", 3, "MPS CC 1205058"],
    [date(2026, 1, 3), "PNC n 3", "mov MPS", 0, 30, 120, "", 2, "MONTE DEI PASCHI"],
    [date(2026, 1, 3), "PNC n 4", "mov KROSS", 20, 0, 140, "", 3, "MPS CC 1205058"],
]


def _make_scheda_xlsx(tmp_path: Path, rows: list[list]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Foglio1"
    ws.append(SCHEDA_HEADER)
    for row in rows:
        ws.append(row)
    path = tmp_path / "AEGRIOR20260601184600.XLSX"
    wb.save(path)
    return path


def test_is_multibank_detects_xlsx_with_partitario(tmp_path):
    from ingest.flussi.ingest_scheda_contabile import is_multibank

    path = _make_scheda_xlsx(tmp_path, ORTI_MULTIBANK_ROWS)
    assert is_multibank(path) is True


def test_parse_multibank_xlsx_maps_banca_via_partitario(tmp_path):
    from ingest.flussi.ingest_scheda_contabile import parse_mastrino_multibank

    path = _make_scheda_xlsx(tmp_path, ORTI_MULTIBANK_ROWS)
    rows = parse_mastrino_multibank(path, "ORTI")

    assert len(rows) == 4
    bancas = {(r["data_registrazione"], r["banca_id"]) for r in rows}
    assert (date(2026, 1, 2), "MPS") in bancas
    assert (date(2026, 1, 2), "MPS_KROSS") in bancas


def test_multibank_xlsx_running_balance_ignores_cumulative_saldo(tmp_path):
    from ingest.flussi.ingest_scheda_contabile import (
        extract_daily_saldi_per_banca,
        parse_mastrino_multibank,
    )

    path = _make_scheda_xlsx(tmp_path, ORTI_MULTIBANK_ROWS)
    rows = parse_mastrino_multibank(path, "ORTI")
    saldi = extract_daily_saldi_per_banca(rows)

    assert saldi[("MPS", date(2026, 1, 2))] == 100
    assert saldi[("MPS_KROSS", date(2026, 1, 2))] == 50
    assert saldi[("MPS", date(2026, 1, 3))] == 70  # 100 - 30
    assert saldi[("MPS_KROSS", date(2026, 1, 3))] == 70  # 50 + 20
