"""High-level API for raw object lifecycle persistence."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.lineage.raw_manifest import (
    emit_event,
    register_raw_object,
)
from core.lineage.schemas import RawObject


def _fake_run(monkeypatch) -> None:
    fake_run = MagicMock()
    fake_run.run_id = "run-test"
    fake_run.pipeline_name = "test_pipeline"
    fake_run.file_sorgente = None
    monkeypatch.setattr(
        "core.bq.write.PipelineRun.get_current",
        lambda: fake_run,
        raising=False,
    )


def test_register_writes_via_gate(monkeypatch, tmp_path) -> None:
    written = {}

    def fake_write(table, rows, mode="append", natural_key=None):
        written.setdefault("calls", []).append((table, rows, mode))

    monkeypatch.setattr("core.lineage.raw_manifest.bq_write_validated", fake_write)
    monkeypatch.setattr(
        "core.lineage.raw_manifest._lookup_existing_by_hash", lambda h: None
    )

    raw_id = register_raw_object(
        content_hash="abc",
        raw_uri="file:///tmp/x.xlsx",
        raw_backend="local",
        file_name_original="x.xlsx",
        bytes_size=10,
        intake_actor="cli",
    )
    assert raw_id
    assert "calls" in written
    table, rows, mode = written["calls"][0]
    assert table.endswith("f_raw_objects")
    assert mode == "append"
    assert isinstance(rows[0], RawObject)


def test_register_dedup_returns_existing_on_same_hash(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "core.lineage.raw_manifest._lookup_existing_by_hash",
        lambda h: "existing-id" if h == "dedup-hash" else None,
    )
    raw_id = register_raw_object(
        content_hash="dedup-hash",
        raw_uri="file:///tmp/y.xlsx",
        raw_backend="local",
        file_name_original="y.xlsx",
        bytes_size=20,
        intake_actor="cli",
    )
    assert raw_id == "existing-id"


def test_emit_event_writes_to_lineage_events(monkeypatch) -> None:
    written = []
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated",
        lambda table, rows, mode="append", natural_key=None: written.append(
            (table, rows)
        ),
    )
    emit_event(
        raw_object_id="abc-123",
        event_type="RAW_INGESTED",
        actor="cli",
        from_status=None,
        to_status="RAW_ONLY",
    )
    assert len(written) == 1
    table, rows = written[0]
    assert table.endswith("f_lineage_events")
    assert rows[0].event_type == "RAW_INGESTED"


def test_emit_event_validates_transition(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated", lambda *a, **kw: None
    )
    with pytest.raises(Exception):  # InvalidTransition raised by state_machine
        emit_event(
            raw_object_id="abc-123",
            event_type="PROMOTED",
            actor="cli",
            from_status="RAW_ONLY",  # forbidden: must be PROMOTABLE
            to_status="PROMOTED",
        )


def test_register_raw_object_persists_gcs_generation(monkeypatch) -> None:
    from core.lineage import raw_manifest

    captured: list = []
    monkeypatch.setattr(raw_manifest, "_lookup_existing_by_hash", lambda h: None)
    monkeypatch.setattr(
        raw_manifest,
        "bq_write_validated",
        lambda table, rows, mode: captured.append((table, rows, mode)),
    )

    rid = raw_manifest.register_raw_object(
        content_hash="h",
        raw_uri="gs://hotelops-raw/k/v.xlsx",
        raw_backend="gcs",
        file_name_original="v.xlsx",
        bytes_size=1,
        intake_actor="cli",
        gcs_generation=1715000000123456,
    )

    assert rid
    table, rows, mode = captured[0]
    assert mode == "append"
    row = rows[0]
    assert row.raw_backend == "gcs"
    assert row.raw_uri == "gs://hotelops-raw/k/v.xlsx"
    assert row.gcs_generation == 1715000000123456


def test_register_raw_object_default_gcs_generation_none(monkeypatch) -> None:
    from core.lineage import raw_manifest

    captured: list = []
    monkeypatch.setattr(raw_manifest, "_lookup_existing_by_hash", lambda h: None)
    monkeypatch.setattr(
        raw_manifest,
        "bq_write_validated",
        lambda table, rows, mode: captured.append((table, rows, mode)),
    )

    raw_manifest.register_raw_object(
        content_hash="h2",
        raw_uri="file:///tmp/x.xlsx",
        raw_backend="local",
        file_name_original="x.xlsx",
        bytes_size=1,
        intake_actor="cli",
    )

    row = captured[0][1][0]
    assert row.gcs_generation is None
