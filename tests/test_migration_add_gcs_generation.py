"""Migration is idempotent and emits the right ALTER when column missing."""

import importlib
from unittest.mock import MagicMock

mig = importlib.import_module("core.bq.migrations.2026_05_05_add_gcs_generation")


def test_migration_skips_when_column_exists(monkeypatch) -> None:
    monkeypatch.setattr(mig, "column_exists", lambda: True)
    fake_client = MagicMock()
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    mig.run(dry_run=False)

    fake_client.query.assert_not_called()


def test_migration_runs_alter_when_column_missing(monkeypatch) -> None:
    monkeypatch.setattr(mig, "column_exists", lambda: False)
    fake_client = MagicMock()
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    mig.run(dry_run=False)

    fake_client.query.assert_called_once()
    sql_arg = fake_client.query.call_args[0][0]
    assert "ALTER TABLE" in sql_arg
    assert "gcs_generation INT64" in sql_arg
