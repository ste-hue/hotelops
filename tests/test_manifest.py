"""Tests for manifest generation helpers."""

from core.bq.manifest import _column_stats


def test_column_stats_few_values():
    """When distinct <= 30, list all values."""
    stats = _column_stats(
        col_name="societa_id",
        col_type="STRING",
        distinct=2,
        values=["ORTI", "INTUR"],
        sample=None,
        min_val=None,
        max_val=None,
    )
    assert stats["type"] == "STRING"
    assert stats["distinct"] == 2
    assert stats["values"] == ["ORTI", "INTUR"]
    assert "sample" not in stats


def test_column_stats_many_values():
    """When distinct > 100, show count + sample."""
    stats = _column_stats(
        col_name="descrizione",
        col_type="STRING",
        distinct=891,
        values=None,
        sample=["Prosecco", "Farina", "Olio"],
        min_val=None,
        max_val=None,
    )
    assert stats["distinct"] == 891
    assert stats["sample"] == ["Prosecco", "Farina", "Olio"]
    assert "values" not in stats


def test_column_stats_numeric():
    """Numeric columns get min/max."""
    stats = _column_stats(
        col_name="importo",
        col_type="FLOAT",
        distinct=500,
        values=None,
        sample=None,
        min_val=-234.5,
        max_val=1890.0,
    )
    assert stats["min"] == -234.5
    assert stats["max"] == 1890.0


def test_column_stats_date():
    """Date columns get min/max as strings."""
    stats = _column_stats(
        col_name="data_op",
        col_type="DATE",
        distinct=365,
        values=None,
        sample=None,
        min_val="2025-01-01",
        max_val="2026-03-27",
    )
    assert stats["min"] == "2025-01-01"
    assert stats["max"] == "2026-03-27"
