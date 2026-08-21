"""Datazione per-colonna del Piano Finanziario multi-anno.

Il nuovo standard dei master (2026-08-18) estende l'orizzonte a giugno
dell'anno dopo: riga 2 porta 16 mesi (APR 2026 … GIU 2027), riga 1 i marker
d'anno. Il vecchio detector restituiva UN anno per l'intero foglio — l'ultimo
marker trovato — quindi ogni riga usciva stampata 2027: il fitto Hotel di
luglio 2026 (488.000) diventava luglio 2027.

Semantica canonica (stessa di pf_rotate/excel_model.find_month_periods):
anno base = ultimo marker in riga 1 fino alla prima colonna-mese inclusa;
+1 a ogni wrap del numero di mese (DIC→GEN). Senza anno dichiarato: esplode,
niente default silenziosi (CLAUDE.md §Chiave periodo).
"""

import openpyxl
import pytest

from ingest.flussi.ingest_piano_finanziario_xlsx import _detect_year_and_month_block


def _ws(year_cells: dict[int, int], month_cells: dict[int, str]):
    wb = openpyxl.Workbook()
    ws = wb.active
    for col, y in year_cells.items():
        ws.cell(1, col, y)
    for col, name in month_cells.items():
        ws.cell(2, col, name)
    return ws


def test_wrap_dic_gen_increments_the_year():
    """Layout ORTI nuovo standard: C1=2026, APR..DIC poi GEN..GIU."""
    names = [
        "APRILE",
        "MAGGIO",
        "GIUGNO",
        "LUGLIO",
        "AGOSTO",
        "SETTEMBRE",
        "OTTOBRE",
        "NOVEMBRE",
        "DICEMBRE",
        "GENNAIO",
        "FEBBRAIO",
        "MARZO",
        "APRILE",
        "MAGGIO",
        "GIUGNO",
    ]
    ws = _ws({3: 2026}, {c + 3: n for c, n in enumerate(names)})

    cols = _detect_year_and_month_block(ws)

    assert [(a, m) for _, a, m in cols] == (
        [(2026, m) for m in range(4, 13)] + [(2027, m) for m in range(1, 7)]
    )


def test_mid_row_year_marker_does_not_leak_backwards():
    """Il marker 2027 sopra GENNAIO non deve datare i mesi 2026 alla sua
    sinistra — il difetto originale ('ultimo marker vince su tutto')."""
    ws = _ws(
        {4: 2026, 10: 2027},
        {
            4: "LUGLIO",
            5: "AGOSTO",
            6: "SETTEMBRE",
            7: "OTTOBRE",
            8: "NOVEMBRE",
            9: "DICEMBRE",
            10: "GENNAIO",
            11: "FEBBRAIO",
        },
    )

    cols = _detect_year_and_month_block(ws)

    anni = {m: a for _, a, m in cols}
    assert anni[7] == 2026, "LUGLIO deve restare 2026"
    assert anni[1] == 2027


def test_single_year_sheet_unchanged():
    """Il vecchio standard (12 mesi, un anno) deve continuare a funzionare."""
    names = [
        "GENNAIO",
        "FEBBRAIO",
        "MARZO",
        "APRILE",
        "MAGGIO",
        "GIUGNO",
        "LUGLIO",
        "AGOSTO",
        "SETTEMBRE",
        "OTTOBRE",
        "NOVEMBRE",
        "DICEMBRE",
    ]
    ws = _ws({3: 2026}, {c + 3: n for c, n in enumerate(names)})

    cols = _detect_year_and_month_block(ws)

    assert [(a, m) for _, a, m in cols] == [(2026, m) for m in range(1, 13)]


def test_missing_year_explodes():
    """Niente default 2026 silenzioso: un foglio-mese senza anno esplode."""
    ws = _ws({}, {3: "GENNAIO", 4: "FEBBRAIO"})
    with pytest.raises(ValueError, match="[Aa]nno"):
        _detect_year_and_month_block(ws)


def test_intur_fallback_data_rilevazione_still_works():
    """Layout INTUR storico: nessun marker in riga 1, data in riga 2."""
    ws = _ws({}, {4: "LUGLIO", 5: "AGOSTO"})
    ws.cell(1, 3, "DATA RILEVAZ")
    ws.cell(2, 3, "30/06/2026")

    cols = _detect_year_and_month_block(ws)

    assert [(a, m) for _, a, m in cols] == [(2026, 7), (2026, 8)]
