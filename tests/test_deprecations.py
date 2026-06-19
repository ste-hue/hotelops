from pathlib import Path


def test_tesoreria_deprecated():
    src = Path("verticals/condges/tesoreria.py").read_text()
    assert "DEPRECATO" in src and "app_cashflow" in src
