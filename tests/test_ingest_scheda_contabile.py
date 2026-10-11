"""Tests for scheda contabile Esolver parser (multi-bank XLSX support)."""

from datetime import date, datetime
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


def test_multibank_write_stampa_raw_object_id(tmp_path, monkeypatch):
    # I9: il path multibank deve stampare la FK lineage su ogni riga
    # (il writer mono la stampava già; il multibank la perdeva → FK-void).
    from ingest.flussi import ingest_scheda_contabile as mod

    captured = {}

    def fake_write(table, rows, mode, natural_key):
        captured["rows"] = rows

    import core.bq.write as bqw

    monkeypatch.setattr(bqw, "bq_write_validated", fake_write)
    path = _make_scheda_xlsx(tmp_path, ORTI_MULTIBANK_ROWS)
    n = mod.process_file(path, "ORTI", None, dry_run=False, raw_object_id="ro-lineage-1")
    assert n > 0
    assert all(r.raw_object_id == "ro-lineage-1" for r in captured["rows"])


# ── Mastrino incollato in Excel (Esolver che fa i capricci, 2026-09-24) ─────────
# Esolver scrive le date come testo "GG/MM/AAAA". Incollando in Excel, le date con
# giorno ≤ 12 vengono riconosciute come MM/GG e diventano datetime con giorno e
# mese scambiati; quelle con giorno ≥ 13 restano stringhe. Regola deterministica:
# colonna mista + tutte le stringhe con giorno ≥ 13 ⇒ ogni datetime va invertita.

PASTED_MIXED_DATE_ROWS = [
    [datetime(2026, 1, 1), "PNC n 1", "SMS BANKING", 0, 3, -3, "", 1, "BANCA SELLA"],
    [datetime(2026, 2, 1), "PNC n 3", "GC rata mutuo", 0, 6000, -6003, "", 1, "BANCA SELLA"],
    [datetime(2026, 5, 1), "PNC n 1", "bollo", 0, 25, -6028, "", 1, "BANCA SELLA"],
    ["13/01/2026", "PNC n 2", "incasso", 100, 0, -5928, "", 1, "BANCA SELLA"],
]


def test_multibank_pasted_xlsx_swaps_datetime_cells_when_strings_start_at_13(tmp_path):
    from ingest.flussi.ingest_scheda_contabile import parse_mastrino_multibank

    path = _make_scheda_xlsx(tmp_path, PASTED_MIXED_DATE_ROWS)
    rows = parse_mastrino_multibank(path, "INTUR")

    assert [r["data_registrazione"] for r in rows] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 13),
    ]


def test_multibank_native_xlsx_with_only_datetime_cells_is_not_swapped(tmp_path):
    from ingest.flussi.ingest_scheda_contabile import parse_mastrino_multibank

    rows_in = [
        [datetime(2026, 2, 1), "PNC n 1", "mov", 10, 0, 10, "", 1, "BANCA SELLA"],
        [datetime(2026, 3, 1), "PNC n 2", "mov", 10, 0, 20, "", 1, "BANCA SELLA"],
    ]
    path = _make_scheda_xlsx(tmp_path, rows_in)
    rows = parse_mastrino_multibank(path, "INTUR")

    assert [r["data_registrazione"] for r in rows] == [date(2026, 2, 1), date(2026, 3, 1)]


def test_multibank_row_with_dropped_dare_cell_is_recovered_from_valuta_columns(tmp_path):
    # Causale lunga incollata: la cella vuota "Dare in UdC" sparisce e tutto slitta
    # a sinistra di una colonna. L'importo si recupera da "Dare/Avere in valuta".
    from ingest.flussi.ingest_scheda_contabile import parse_mastrino_multibank

    normal = ["13/01/2026", "PNC n 1", "mov", None, "52,61", "100,00", None, 2,
              "MONTE DEI PASCHI", "EUR", None, "52,61", None, "0 Centro"]
    shifted_avere = ["14/01/2026", "PNC n 7", "Pagamento FT 1 FT 2 FT 3", "1103,51", "680,63",
                     None, 2, "MONTE DEI PASCHI", "EUR", None, "1103,51", None, "0 Centro", None]
    shifted_dare = ["15/01/2026", "PNC n 8", "Incasso FT 4 FT 5", "200,00", "880,63",
                    None, 2, "MONTE DEI PASCHI", "EUR", "200,00", None, None, "0 Centro", None]
    path = _make_scheda_xlsx(tmp_path, [normal, shifted_avere, shifted_dare])
    rows = parse_mastrino_multibank(path, "ORTI")

    assert [(r["banca_id"], r["dare"], r["avere"]) for r in rows] == [
        ("MPS", 0.0, 52.61),
        ("MPS", 0.0, 1103.51),
        ("MPS", 200.0, 0.0),
    ]
