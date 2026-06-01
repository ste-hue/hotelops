from pathlib import Path

from core.bq.load.load_mapping_piano_finanziario import DEFAULT_SOURCE


def test_default_source_resolves_to_existing_csv():
    """Regression: il default puntava a core/core/bq/... (duplicato) → file inesistente."""
    p = Path(DEFAULT_SOURCE)
    assert p.name == "d_mapping_piano_finanziario.csv"
    assert "core/core" not in p.as_posix()
    assert p.exists(), f"DEFAULT_SOURCE non esiste: {p}"
