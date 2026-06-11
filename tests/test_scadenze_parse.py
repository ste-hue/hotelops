"""Tests per parse_scadenze — layout sintetica e dettagliata."""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import openpyxl

from verticals.condges.scadenze_parse import parse_scadenze

FUTURE = date.today() + timedelta(days=40)
PAST = date.today() - timedelta(days=40)


def _wb_bytes(rows: list[dict]) -> BytesIO:
    """rows: dict {col_1based: value}."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for r_idx, r in enumerate(rows, 1):
        for col, v in r.items():
            ws.cell(row=r_idx, column=col).value = v
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_sintetica_layout():
    buf = _wb_bytes(
        [
            {11: 42, 12: "FORNITORE SINT", 20: -100.0, 23: FUTURE},
            {11: 42, 12: "FORNITORE SINT", 20: -50.0, 23: PAST},
        ]
    )
    df, buckets = parse_scadenze(buf)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["codice_fornitore"] == 42
    assert row["totale"] == -150.0
    assert row["scaduto"] == -50.0
    assert buckets == [FUTURE.month]


def test_dettagliata_layout():
    """Dettagliata: col 23 non-data, scadenza in col 34, residuo in col 37."""
    buf = _wb_bytes(
        [
            {11: 42, 12: "FORNITORE DETT", 23: "Q", 30: -999.0, 34: FUTURE, 37: -200.0},
            {11: 42, 12: "FORNITORE DETT", 23: "Q", 30: -999.0, 34: PAST, 37: -80.0},
        ]
    )
    df, buckets = parse_scadenze(buf)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["totale"] == -280.0  # usa col 37 (residuo), non col 30/20
    assert row["scaduto"] == -80.0
    assert buckets == [FUTURE.month]


def test_dettagliata_riga_senza_scadenza_skippata():
    buf = _wb_bytes(
        [
            {11: 42, 12: "X", 23: "Q", 34: FUTURE, 37: -10.0},
            {11: 43, 12: "Y", 23: "Q"},  # nessuna data in 23 né 34
        ]
    )
    df, _ = parse_scadenze(buf)
    assert list(df["codice_fornitore"]) == [42]
