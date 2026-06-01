from datetime import date

from verticals.condges.pf_rotate.cli_handler import _parse_exclude, _resolve_data_saldo


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
