"""Pydantic schemas + naming grammar for the lineage layer."""

from datetime import datetime, timezone

import pytest

from core.lineage.schemas import (
    InvalidSourceName,
    LineageEvent,
    RawObject,
    SourceDefinition,
    validate_source_name,
)


# ── Naming grammar ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        "MPS_BANCA_INTUR_APPEND",
        "POWERBI_CRUSCOTTO_ORTI_APPEND",
        "ESOLVER_BUDGET_GROUP_SNAPSHOT",
    ],
)
def test_valid_source_names(name: str) -> None:
    system, dataset, societa, lifecycle = validate_source_name(name)
    assert "_" not in system
    assert societa in {"ORTI", "INTUR", "GROUP"}
    assert lifecycle in {"APPEND", "SNAPSHOT"}


@pytest.mark.parametrize(
    "name, fragment",
    [
        ("ESOLVER_BILANCINO_ORTI", "expected 4"),
        ("ESOLVER_MOVIMENTI_CONTABILI_ORTI_APPEND", "expected 4"),
        ("esolver_BILANCINO_ORTI_SNAPSHOT", "[A-Z]"),
        ("ESOLVER_BILANCINO_HOTEL_SNAPSHOT", "societa"),
        ("ESOLVER_BILANCINO_ORTI_DELTA", "lifecycle"),
        ("1ESOLVER_BILANCINO_ORTI_SNAPSHOT", "[A-Z]"),
    ],
)
def test_invalid_source_names_raise(name: str, fragment: str) -> None:
    with pytest.raises(InvalidSourceName) as exc:
        validate_source_name(name)
    assert fragment in str(exc.value)


# ── Pydantic round-trip ──────────────────────────────────────────────────────


def test_RawObject_round_trip() -> None:
    now = datetime(2026, 5, 5, 10, 0, tzinfo=timezone.utc)
    obj = RawObject(
        raw_object_id="abc-123",
        content_hash="d41d8cd98f00b204e9800998ecf8427e",
        raw_uri="file:///tmp/test.xlsx",
        raw_backend="local",
        file_name_original="Master_Completo_ORTI_20260430.xlsx",
        bytes_size=12345,
        source_name="ESOLVER_BUDGET_ORTI_SNAPSHOT",
        detector_category="gasparotto",
        societa_id="ORTI",
        intake_at=now,
        intake_actor="cli",
        pipeline_run_id="run-1",
        pipeline_name="ingest_intake",
        ingestion_ts=now,
    )
    dumped = obj.model_dump(mode="json")
    revived = RawObject(**dumped)
    assert revived.raw_object_id == "abc-123"
    assert revived.intake_at == now


def test_LineageEvent_minimal() -> None:
    ev = LineageEvent(
        event_id="ev-1",
        raw_object_id="abc-123",
        event_type="RAW_INGESTED",
        event_at=datetime.now(timezone.utc),
        actor="cli",
        from_status=None,
        to_status="RAW_ONLY",
    )
    assert ev.to_status == "RAW_ONLY"


def test_LineageEvent_with_reason() -> None:
    ev = LineageEvent(
        event_id="ev-2",
        raw_object_id="abc-123",
        event_type="REJECTED",
        event_at=datetime.now(timezone.utc),
        actor="gate",
        from_status="CLASSIFIED",
        to_status="REJECTED",
        reason="NO_LOOP_TARGET",
        payload_json='{"source_name": "POWERBI_CRUSCOTTO_ORTI_APPEND"}',
    )
    assert ev.reason == "NO_LOOP_TARGET"


def test_SourceDefinition_invalid_name_rejected() -> None:
    import pytest as _pytest

    with _pytest.raises(Exception):  # Pydantic ValidationError wraps InvalidSourceName
        SourceDefinition(
            source_name="bad_name",
            system="ESOLVER",
            dataset="X",
            societa="ORTI",
            lifecycle="APPEND",
            canonical_table="f_x",
            parser_module="ingest.flussi.x",
            promotion_policy="AUTO",
            detector_category="x",
            raw_storage={},
        )
