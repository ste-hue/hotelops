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
    # importo = col 26 "Saldo scadenza in UDC" (residuo per-scadenza, signed)
    buf = _wb_bytes(
        [
            {11: 42, 12: "FORNITORE SINT", 26: -100.0, 23: FUTURE},
            {11: 42, 12: "FORNITORE SINT", 26: -50.0, 23: PAST},
        ]
    )
    df, buckets = parse_scadenze(buf)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["codice_fornitore"] == 42
    assert row["totale"] == -150.0
    assert row["scaduto"] == -50.0
    assert buckets == [FUTURE.month]


def test_sintetica_usa_saldo_scadenza_non_apertura():
    """issue #47: usa col 26 (saldo scadenza) NON col 20 (importo apertura).

    col 20 = fattura intera ripetuta su ogni rata → da ignorare;
    col 26 = residuo della singola scadenza → quello da bucketare.
    """
    buf = _wb_bytes(
        [
            {11: 99, 12: "MIELE", 20: -10857.37, 26: -3619.13, 23: FUTURE},
        ]
    )
    df, _ = parse_scadenze(buf)
    row = df.iloc[0]
    assert row[f"mese_{FUTURE.month}"] == -3619.13  # col 26, non -10857.37
    assert row["totale"] == -3619.13


def test_due_rate_stesso_mese_sommate():
    """Due scadenze della stessa voce nello stesso mese → sommate (caso Miele lug)."""
    m = FUTURE.month
    buf = _wb_bytes(
        [
            {11: 1008, 12: "MIELE", 26: -3619.12, 23: FUTURE},
            {11: 1008, 12: "MIELE", 26: -439.74, 23: FUTURE},
        ]
    )
    df, _ = parse_scadenze(buf)
    assert round(df.iloc[0][f"mese_{m}"], 2) == -4058.86


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


def test_cutoff_esplicito_decide_scaduto():
    """primo_mese_aperto ancora lo scaduto alla rotation, non a date.today().

    Cutoff (2026, 5): scadenze < maggio 2026 -> scaduto; maggio resta mese_5
    anche se oggi e' giugno o oltre.
    """
    buf = _wb_bytes(
        [
            {11: 92, 12: "AMALFI SEI ESSE", 26: -100.0, 23: date(2026, 4, 30)},
            {11: 92, 12: "AMALFI SEI ESSE", 26: -200.0, 23: date(2026, 5, 31)},
            {11: 92, 12: "AMALFI SEI ESSE", 26: -300.0, 23: date(2026, 6, 30)},
        ]
    )
    df, buckets = parse_scadenze(buf, primo_mese_aperto=(2026, 5))
    row = df.iloc[0]
    assert row["scaduto"] == -100.0
    assert row["mese_5"] == -200.0
    assert row["mese_6"] == -300.0
    assert buckets == [5, 6]


def test_nome_completo_da_due_colonne():
    """Ragione sociale 1 (col 12) + Ragione sociale 2 (col 13) concatenate."""
    buf = _wb_bytes(
        [
            {11: 417, 12: "CIMINI", 13: "FILOMENA", 26: -51.48, 23: FUTURE},
        ]
    )
    df, _ = parse_scadenze(buf)
    assert df.iloc[0]["nome"] == "CIMINI FILOMENA"
