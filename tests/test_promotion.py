"""Promotion entrypoint: PROMOTABLE raw_object → parser → bq_write_validated → PROMOTED."""

from unittest.mock import MagicMock

import pytest

from core.lineage.policy_gate import PolicyViolation
from ingest.promotion import PromotionResult, promote_raw_object


@pytest.fixture
def fake_registry(monkeypatch):
    """Patch source_resolver to return a fake source_def."""
    fake_source = MagicMock()
    fake_source.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake_source.promotion_policy = "AUTO"
    fake_source.parser_module = "ingest.flussi.ingest_bilancino"
    fake_source.parser_entrypoint = "main"
    fake_source.canonical_table = "f_bilancino"
    fake_source.lifecycle = "SNAPSHOT"
    fake_source.natural_key = ["data_snapshot", "societa_id"]
    fake_source.loop_targets = ["monthly_close"]
    fake_source.societa = "ORTI"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)
    return fake_source


@pytest.fixture
def captured_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        "ingest.promotion.emit_event",
        lambda **kw: events.append(kw) or f"ev-{len(events)}",
    )
    return events


@pytest.fixture
def fake_raw_object(monkeypatch):
    """Patch the raw_object lookup to return a fake row."""
    fake = MagicMock()
    fake.raw_object_id = "raw-1"
    fake.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake.raw_uri = "file:///tmp/x.xlsx"
    monkeypatch.setattr("ingest.promotion._fetch_raw_object", lambda rid: fake)
    return fake


def test_promote_happy_path(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    fake_parser_invoke = MagicMock(return_value={"rows_written": 42})
    monkeypatch.setattr("ingest.promotion._invoke_parser", fake_parser_invoke)

    result = promote_raw_object("raw-1", actor="test")

    assert result.status == "PROMOTED"
    types = [ev["event_type"] for ev in captured_events]
    assert "PROMOTION_REQUESTED" in types
    assert "VALIDATED_OK" in types
    assert "PROMOTED" in types
    fake_parser_invoke.assert_called_once()


def test_promote_raw_only_source_rejected(
    monkeypatch, captured_events, fake_raw_object
) -> None:
    fake_raw_object.source_name = "POWERBI_CRUSCOTTO_ORTI_APPEND"
    fake_source = MagicMock()
    fake_source.source_name = "POWERBI_CRUSCOTTO_ORTI_APPEND"
    fake_source.promotion_policy = "RAW_ONLY"
    fake_source.loop_targets = []
    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")

    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "REJECTED"
    assert result.reason == "NO_LOOP_TARGET"
    types = [ev["event_type"] for ev in captured_events]
    assert "REJECTED" in types


def test_promote_parser_failure_emits_validate_fail(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    monkeypatch.setattr(
        "ingest.promotion._invoke_parser",
        MagicMock(side_effect=ValueError("parser broke")),
    )
    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "REJECTED"
    assert result.reason == "VALIDATE_FAIL"
    types = [ev["event_type"] for ev in captured_events]
    assert "VALIDATED_FAIL" in types
    assert "REJECTED" in types


def test_promote_already_promoted_is_noop(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTED")
    fake_parser = MagicMock()
    monkeypatch.setattr("ingest.promotion._invoke_parser", fake_parser)
    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "PROMOTED"
    assert result.noop is True
    fake_parser.assert_not_called()
    assert captured_events == []
