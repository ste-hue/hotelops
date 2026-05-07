"""Intake entrypoint: file → raw blob + RAW_INGESTED event."""

from pathlib import Path

import pytest

from ingest.intake import IntakeResult, intake_file


def _fixture_xlsx(tmp_path: Path) -> Path:
    f = tmp_path / "ESOLVER_BILANCINO_ORTI_apr.xls"
    f.write_bytes(b"FAKE_XLS_CONTENT_FOR_HASH")
    return f


def test_intake_basic(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_register(**kwargs):
        captured["register"] = kwargs
        return "raw-id-1"

    def fake_emit(**kwargs):
        captured.setdefault("events", []).append(kwargs)
        return f"ev-{len(captured['events'])}"

    monkeypatch.setattr("ingest.intake._lookup_existing_by_hash", lambda h: None)
    monkeypatch.setattr("ingest.intake.register_raw_object", fake_register)
    monkeypatch.setattr("ingest.intake.emit_event", fake_emit)

    f = _fixture_xlsx(tmp_path)
    result = intake_file(
        f,
        source_name="ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        actor="test",
    )
    assert isinstance(result, IntakeResult)
    assert result.raw_object_id == "raw-id-1"
    assert captured["register"]["content_hash"]
    assert captured["register"]["source_name"] == "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    # 2 events with source_name resolved: RAW_INGESTED + SOURCE_RESOLVED
    assert len(captured["events"]) == 2
    assert captured["events"][0]["event_type"] == "RAW_INGESTED"
    assert captured["events"][0]["to_status"] == "RAW_ONLY"
    assert captured["events"][1]["event_type"] == "SOURCE_RESOLVED"
    assert captured["events"][1]["to_status"] == "CLASSIFIED"


def test_intake_unknown_source_raises(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("ingest.intake._lookup_existing_by_hash", lambda h: None)
    monkeypatch.setattr("ingest.intake.register_raw_object", lambda **kw: "x")
    monkeypatch.setattr("ingest.intake.emit_event", lambda **kw: "x")
    f = _fixture_xlsx(tmp_path)
    with pytest.raises(Exception):  # source_name not in registry
        intake_file(f, source_name="FAKE_DATASET_ORTI_APPEND", actor="test")


def test_intake_no_source_skips_classification_event(monkeypatch, tmp_path) -> None:
    captured = {"events": []}
    monkeypatch.setattr("ingest.intake._lookup_existing_by_hash", lambda h: None)
    monkeypatch.setattr("ingest.intake.register_raw_object", lambda **kw: "raw-id")
    monkeypatch.setattr(
        "ingest.intake.emit_event",
        lambda **kw: captured["events"].append(kw) or "ev-1",
    )
    f = _fixture_xlsx(tmp_path)
    result = intake_file(f, source_name=None, actor="test")
    # Only RAW_INGESTED — no SOURCE_RESOLVED, no DETECTED
    types = [ev["event_type"] for ev in captured["events"]]
    assert types == ["RAW_INGESTED"]
