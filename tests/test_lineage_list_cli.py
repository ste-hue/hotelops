"""hotelops lineage --list filters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_lineage_list_filters_status_and_source(monkeypatch, capsys):
    """list mode: --status PROMOTABLE --source MPS_BANCA_ORTI_APPEND --limit 5."""
    fake_rows = [
        MagicMock(
            raw_object_id="r1",
            source_name="MPS_BANCA_ORTI_APPEND",
            current_status="PROMOTABLE",
            intake_at="2026-05-05T10:00:00",
            file_name_original="MPS_ORTI_2026_05.csv",
        ),
        MagicMock(
            raw_object_id="r2",
            source_name="MPS_BANCA_ORTI_APPEND",
            current_status="PROMOTABLE",
            intake_at="2026-05-04T09:00:00",
            file_name_original="MPS_ORTI_2026_04.csv",
        ),
    ]

    fake_client = MagicMock()
    fake_query_job = MagicMock()
    fake_query_job.result.return_value = fake_rows
    fake_client.query.return_value = fake_query_job

    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    import cli as cli_module

    args = SimpleNamespace(
        status="PROMOTABLE",
        source="MPS_BANCA_ORTI_APPEND",
        limit=5,
        days=None,
    )
    cli_module.cmd_lineage_list(args)

    out = capsys.readouterr().out
    assert "r1" in out
    assert "r2" in out
    assert "MPS_BANCA_ORTI_APPEND" in out
    sent_sql = fake_client.query.call_args[0][0]
    assert "COALESCE(c.current_status" in sent_sql
    assert "source_name" in sent_sql
    assert "LIMIT 5" in sent_sql


def test_lineage_dispatch_errors_without_id_or_list(capsys):
    import cli as cli_module

    args = SimpleNamespace(lineage_list=False, raw_object_id=None)
    with pytest.raises(SystemExit) as ei:
        cli_module.cmd_lineage_dispatch(args)
    assert ei.value.code == 2
    assert "ERROR" in capsys.readouterr().err

