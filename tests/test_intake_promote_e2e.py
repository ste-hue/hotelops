"""Reproduces the InvalidTransition bug found in Task 5 production smoke.

Intake with source_name → row at status RAW_ONLY (pre-Fix-B).
Then promote → state machine raises InvalidTransition because
PROMOTION_REQUESTED is not allowed from RAW_ONLY.

After Fix B: intake also emits SOURCE_RESOLVED → CLASSIFIED.
Promote then proceeds through (CLASSIFIED, PROMOTION_REQUESTED) without raising.

Subprocess is mocked: this test does NOT touch BQ, GCS, or the parser.
The full smoke (real BQ + GCS + parser) is Task 5.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Come test_intake: il mock non copre la factory del client GCP, senza ADC il
# costruttore esplode. Marcato bq finché il mock non copre anche il client.
pytestmark = pytest.mark.bq


@pytest.fixture
def fixture_file(tmp_path: Path) -> Path:
    f = tmp_path / "MPS_ORTI_HOMEBANKING_2026_05.csv"
    f.write_bytes(b"fake-mps-content-for-hash")
    return f


def test_intake_then_promote_does_not_raise_invalid_transition(
    monkeypatch, fixture_file: Path
) -> None:
    """The bug: pre-Fix-B, this test would raise InvalidTransition on promote."""
    # ── Stub intake side ────────────────────────────────────────────────────
    captured_events: list[dict] = []
    captured_register: dict = {}

    def fake_emit(**kw):
        captured_events.append(kw)
        return f"ev-{len(captured_events)}"

    def fake_register(**kw):
        captured_register.update(kw)
        return "raw-id-pilot-1"

    monkeypatch.setattr("ingest.intake._lookup_existing_by_hash", lambda h: None)
    monkeypatch.setattr("ingest.intake.register_raw_object", fake_register)
    monkeypatch.setattr("ingest.intake.emit_event", fake_emit)

    # Source registry stub: a real-looking MPS source.
    fake_source = MagicMock()
    fake_source.source_name = "MPS_BANCA_ORTI_APPEND"
    fake_source.societa = "ORTI"
    fake_source.business_unit = None
    fake_source.detector_category = "banca"
    fake_source.raw_storage = MagicMock(backend="local", bucket=None)
    fake_source.loop_targets = ["daily_reconciliation"]
    fake_source.promotion_policy = "AUTO"
    fake_source.parser_module = "ingest.banca.ingest"
    fake_source.canonical_table = "f_banche_movimenti"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.intake.load_registry", lambda: fake_reg)

    from ingest.intake import intake_file

    intake_result = intake_file(
        path=fixture_file,
        source_name="MPS_BANCA_ORTI_APPEND",
        actor="test",
    )

    # Post-Fix-B contract: intake emits 2 events when source is resolved.
    event_types = [e["event_type"] for e in captured_events]
    assert "RAW_INGESTED" in event_types
    assert "SOURCE_RESOLVED" in event_types, (
        f"Expected SOURCE_RESOLVED after RAW_INGESTED when source_name is set; "
        f"got {event_types!r}. Without it, promote would raise InvalidTransition."
    )

    # ── Stub promote side ──────────────────────────────────────────────────
    captured_events.clear()  # promote will append its own events

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stderr = ""
    monkeypatch.setattr("ingest.promotion.subprocess.run", lambda cmd, **kw: fake_proc)

    fake_raw = MagicMock()
    fake_raw.source_name = "MPS_BANCA_ORTI_APPEND"
    fake_raw.raw_uri = f"file://{fixture_file}"
    fake_raw.gcs_generation = None
    fake_raw.societa_id = "ORTI"
    monkeypatch.setattr("ingest.promotion._fetch_raw_object", lambda _id: fake_raw)
    monkeypatch.setattr("ingest.promotion.latest_status", lambda _id: "CLASSIFIED")
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)
    monkeypatch.setattr("ingest.promotion.emit_event", fake_emit)

    # Skip pipeline_run side effects.
    import contextlib
    monkeypatch.setattr(
        "ingest.promotion.PipelineRun",
        lambda *a, **kw: contextlib.nullcontext(),
    )

    from ingest.promotion import promote_raw_object

    # The crux: this MUST NOT raise InvalidTransition.
    result = promote_raw_object(intake_result.raw_object_id, actor="test")

    assert result.status == "PROMOTED", (
        f"Expected status=PROMOTED, got {result.status!r}. "
        f"Events emitted during promote: "
        f"{[e['event_type'] for e in captured_events]!r}"
    )


def test_intake_then_promote_with_real_state_machine(
    monkeypatch, fixture_file: Path
) -> None:
    """Regression: real emit_event + real state machine, no InvalidTransition.

    Pre-Task-4.6 this raises InvalidTransition at the VALIDATED_OK emit
    (no `(None, "VALIDATED_OK")` transition in the state machine table).

    Mocks BQ writes and BQ-side queries; lets emit_event + state_machine
    run with real implementations. The Task 4.5 sibling test mocks
    emit_event itself, so it doesn't catch this.
    """
    import contextlib
    from unittest.mock import MagicMock

    # ── Mock BQ writes inside the lineage layer ────────────────────────────
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated", lambda *a, **kw: None
    )

    # ── Mock BQ-side reads ─────────────────────────────────────────────────
    # _lookup_existing_by_hash is defined in raw_manifest and called there
    # directly; ingest.intake re-exports it but the call site is raw_manifest.
    monkeypatch.setattr(
        "core.lineage.raw_manifest._lookup_existing_by_hash", lambda h: None
    )
    # latest_status is the function promote uses to decide the current state.
    # Since we mocked bq_write_validated, the v_raw_objects_current view
    # wouldn't be updated by the SOURCE_RESOLVED emit. Simulate the post-
    # intake state directly: CLASSIFIED.
    monkeypatch.setattr(
        "ingest.promotion.latest_status", lambda _id: "CLASSIFIED"
    )

    # ── Mock the storage backend (avoid touching disk for upload) ──────────
    fake_upload_result = MagicMock(
        raw_uri=f"file://{fixture_file}", generation=None
    )
    fake_local = MagicMock(upload=lambda **kw: fake_upload_result)
    monkeypatch.setattr("ingest.intake.LocalBackend", lambda: fake_local)

    # ── Source registry (real-looking MPS source) ─────────────────────────
    fake_source = MagicMock()
    fake_source.source_name = "MPS_BANCA_ORTI_APPEND"
    fake_source.societa = "ORTI"
    fake_source.business_unit = None
    fake_source.detector_category = "banca"
    fake_source.raw_storage = MagicMock(backend="local", bucket=None)
    fake_source.loop_targets = ["daily_reconciliation"]
    fake_source.promotion_policy = "AUTO"
    fake_source.parser_module = "ingest.banca.ingest"
    fake_source.canonical_table = "f_banche_movimenti"

    fake_reg = MagicMock()
    fake_reg.get = (
        lambda name: fake_source if name == fake_source.source_name else None
    )
    monkeypatch.setattr("ingest.intake.load_registry", lambda: fake_reg)
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)

    # ── Mock _fetch_raw_object (would query BQ otherwise) ──────────────────
    fake_raw = MagicMock()
    fake_raw.source_name = "MPS_BANCA_ORTI_APPEND"
    fake_raw.raw_uri = f"file://{fixture_file}"
    fake_raw.gcs_generation = None
    fake_raw.societa_id = "ORTI"
    monkeypatch.setattr("ingest.promotion._fetch_raw_object", lambda _id: fake_raw)

    # ── Mock subprocess (parser run) ───────────────────────────────────────
    fake_proc = MagicMock(returncode=0, stderr="")
    monkeypatch.setattr(
        "ingest.promotion.subprocess.run", lambda cmd, **kw: fake_proc
    )

    # ── Skip PipelineRun side effects ──────────────────────────────────────
    monkeypatch.setattr(
        "ingest.intake.PipelineRun",
        lambda *a, **kw: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        "ingest.promotion.PipelineRun",
        lambda *a, **kw: contextlib.nullcontext(),
    )

    # ── Run the full chain with REAL emit_event + REAL state_machine ──────
    from ingest.intake import intake_file
    from ingest.promotion import promote_raw_object

    intake_result = intake_file(
        path=fixture_file,
        source_name="MPS_BANCA_ORTI_APPEND",
        actor="test",
    )
    # If intake or promote raised InvalidTransition, the test fails here.
    result = promote_raw_object(intake_result.raw_object_id, actor="test")

    assert result.status == "PROMOTED", (
        f"Expected PROMOTED via real state machine; got {result.status!r}"
    )
