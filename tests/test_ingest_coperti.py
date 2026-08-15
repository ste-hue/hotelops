"""Test ingest_coperti: riconoscimento fogli, guard anti-shrink."""

from datetime import date, datetime, timezone

import openpyxl
import pytest

from ingest.flussi.ingest_coperti import (
    parse_xlsx_file,
    replace_guard,
)

TS = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _wb(tmp_path, sheets: dict[str, list[list]]):
    """Build a minimal xlsx with the given {sheet_name: rows}."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    path = tmp_path / "coperti_test.xlsx"
    wb.save(path)
    return path


BRK_HEADER = [
    "Informazioni cronologiche",
    "Breakfast Ospiti Hotel",
    "Breakfast Esterni",
]
MENSA_HEADER = ["Informazioni cronologiche", "TIPO DI PASTO", "PAX"]


def test_tab_mensa_semplice(tmp_path):
    path = _wb(
        tmp_path,
        {
            "Mensa Dipendenti": [
                MENSA_HEADER,
                [datetime(2026, 8, 10, 22, 0), "PRANZO", 30],
            ]
        },
    )
    rows = parse_xlsx_file(path, "ORTI", TS)
    assert len(rows) == 1
    assert rows[0]["tipo_ospite"] == "DIPENDENTI"
    assert rows[0]["tipo_pasto"] == "LUNCH"


def test_tab_scarico_mensa_non_viene_ignorato(tmp_path):
    """Bug: 'Scarico Mensa Dipendenti' cadeva nel ramo pasto_sheets (prefisso
    'scarico') e veniva scartato in silenzio perché senza tipo_pasto."""
    path = _wb(
        tmp_path,
        {
            "Scarico Mensa Dipendenti": [
                MENSA_HEADER,
                [datetime(2026, 8, 10, 22, 0), "CENA", 15],
            ]
        },
    )
    rows = parse_xlsx_file(path, "ORTI", TS)
    assert len(rows) == 1
    assert rows[0]["tipo_ospite"] == "DIPENDENTI"
    assert rows[0]["tipo_pasto"] == "DINNER"


def test_tab_breakfast_wide(tmp_path):
    path = _wb(
        tmp_path,
        {"Breakfast": [BRK_HEADER, [datetime(2026, 8, 10, 11, 0), 180, 3]]},
    )
    rows = parse_xlsx_file(path, "ORTI", TS)
    assert {(r["tipo_ospite"], r["n_coperti"]) for r in rows} == {
        ("HOTEL", 180),
        ("ESTERNI", 3),
    }
    assert all(r["data_servizio"] == date(2026, 8, 10).isoformat() for r in rows)


def test_replace_guard_blocca_shrink():
    with pytest.raises(SystemExit):
        replace_guard(n_new=100, n_existing=2274, allow_shrink=False)


def test_replace_guard_passa_se_cresce_o_pari():
    replace_guard(n_new=2274, n_existing=2274, allow_shrink=False)
    replace_guard(n_new=2300, n_existing=2274, allow_shrink=False)


def test_replace_guard_override():
    replace_guard(n_new=100, n_existing=2274, allow_shrink=True)
