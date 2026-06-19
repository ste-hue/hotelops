from pathlib import Path


def test_app_scadenzario_deprecated():
    src = Path("verticals/condges/app_scadenzario.py").read_text()
    assert "DEPRECATO" in src and "app_cashflow" in src


def test_tesoreria_deprecated():
    src = Path("verticals/condges/tesoreria.py").read_text()
    assert "DEPRECATO" in src and "app_cashflow" in src
