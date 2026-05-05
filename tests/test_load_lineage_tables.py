"""DDL loader for f_raw_objects, f_lineage_events, v_raw_objects_current."""

from unittest.mock import MagicMock

from core.bq.load.load_lineage_tables import (
    DDL_FACT_LINEAGE_EVENTS,
    DDL_FACT_RAW_OBJECTS,
    SQL_VIEW_RAW_OBJECTS_CURRENT,
    create_lineage_tables,
)


def test_ddl_strings_are_valid() -> None:
    assert (
        "CREATE TABLE" in DDL_FACT_RAW_OBJECTS
        or "CREATE OR REPLACE TABLE" in DDL_FACT_RAW_OBJECTS
    )
    assert "f_raw_objects" in DDL_FACT_RAW_OBJECTS
    assert "PARTITION BY" in DDL_FACT_RAW_OBJECTS

    assert "f_lineage_events" in DDL_FACT_LINEAGE_EVENTS
    assert "PARTITION BY" in DDL_FACT_LINEAGE_EVENTS

    assert "CREATE OR REPLACE VIEW" in SQL_VIEW_RAW_OBJECTS_CURRENT
    assert "v_raw_objects_current" in SQL_VIEW_RAW_OBJECTS_CURRENT


def test_create_lineage_tables_executes_3_statements(monkeypatch) -> None:
    fake_client = MagicMock()
    fake_client.query.return_value.result.return_value = None
    monkeypatch.setattr(
        "core.bq.load.load_lineage_tables.get_client", lambda: fake_client
    )
    create_lineage_tables(dry_run=False)
    assert fake_client.query.call_count == 3


def test_create_lineage_tables_dry_run_does_not_call(monkeypatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr(
        "core.bq.load.load_lineage_tables.get_client", lambda: fake_client
    )
    create_lineage_tables(dry_run=True)
    assert fake_client.query.call_count == 0
