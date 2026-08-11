import argparse
from datetime import date

import openpyxl

from verticals.condges.pf_rotate.cli_handler import (
    _parse_exclude,
    _resolve_data_saldo,
    add_subparser,
)
from verticals.condges.pf_rotate.excel_model import find_month_periods, periodo


def test_resolve_data_saldo_explicit_wins():
    """--data-saldo esplicito è override: vince sull'anno/mese derivato."""
    assert _resolve_data_saldo(date(2026, 4, 30), 2026, 5) == date(2026, 4, 30)


def test_resolve_data_saldo_derives_last_day_of_month():
    assert _resolve_data_saldo(None, 2026, 5) == date(2026, 5, 31)


def test_resolve_data_saldo_february_non_leap():
    assert _resolve_data_saldo(None, 2026, 2) == date(2026, 2, 28)


def test_resolve_data_saldo_february_leap():
    assert _resolve_data_saldo(None, 2024, 2) == date(2024, 2, 29)


def test_parse_exclude_comma_separated():
    assert _parse_exclude(["264,48"]) == {264, 48}


def test_parse_exclude_repeatable_and_empty():
    assert _parse_exclude(["264", "48"]) == {264, 48}
    assert _parse_exclude([]) == set()


def test_pf_extend_cli_scrive_file_esteso(tmp_path, minimal_pf_orti_bytes):
    pf_path = tmp_path / "ORTI_PF.xlsx"
    pf_path.write_bytes(minimal_pf_orti_bytes)
    out_dir = tmp_path / "out"

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    add_subparser(sub)
    args = parser.parse_args(
        ["pf-extend", "--pf", str(pf_path), "--to", "2027-06", "--out", str(out_dir)]
    )

    rc = args.func(args)
    assert rc == 0

    outputs = list(out_dir.glob("*_extended_2027-06_*.xlsx"))
    assert len(outputs) == 1
    wb = openpyxl.load_workbook(outputs[0])
    cols = find_month_periods(wb["Piano Finanziario"])
    assert max(cols) == periodo(2027, 6)

    # l'input su disco non è mai stato toccato
    wb_in = openpyxl.load_workbook(pf_path)
    cols_in = find_month_periods(wb_in["Piano Finanziario"])
    assert max(cols_in) == periodo(2026, 12)
