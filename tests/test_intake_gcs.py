"""intake_file dispatches to GCSBackend when source_def says backend=gcs."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fixture_file(tmp_path: Path) -> Path:
    f = tmp_path / "situazione_partite.xlsx"
    f.write_bytes(b"fake")
    return f


@pytest.fixture
def patch_intake_deps(monkeypatch):
    """Stub register_raw_object + emit_event + dedup probe; capture calls.

    Default _lookup_existing_by_hash returns None (no dedup hit). Tests that
    want to exercise the dedup path override this monkeypatch.
    """
    captured = {"register": [], "events": []}
    monkeypatch.setattr(
        "ingest.intake._lookup_existing_by_hash",
        lambda content_hash: None,
    )
    monkeypatch.setattr(
        "ingest.intake.register_raw_object",
        lambda **kw: captured["register"].append(kw) or "raw-id-123",
    )
    monkeypatch.setattr(
        "ingest.intake.emit_event",
        lambda **kw: captured["events"].append(kw) or "ev-1",
    )
    return captured


def test_intake_with_gcs_source_uploads_and_records_uri_generation(
    monkeypatch, fixture_file: Path, patch_intake_deps
) -> None:
    fake_source = MagicMock()
    fake_source.source_name = "ESOLVER_PARTITE_ORTI_SNAPSHOT"
    fake_source.societa = "ORTI"
    fake_source.business_unit = None
    fake_source.detector_category = "partite_fornitori"
    fake_source.raw_storage = MagicMock(backend="gcs", bucket="hotelops-raw")
    fake_source.loop_targets = ["cash_control"]
    fake_source.promotion_policy = "AUTO"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.intake.load_registry", lambda: fake_reg)

    upload_calls: list = []

    class FakeGCSBackend:
        def __init__(self, bucket):
            self.bucket = bucket

        def upload(self, local_path, source_name, intake_at):
            upload_calls.append((local_path, source_name, intake_at, self.bucket))
            from core.lineage.raw_storage import UploadResult

            return UploadResult(
                raw_uri=f"gs://{self.bucket}/{source_name}/2026/05/{local_path.name}",
                generation=1715000000123456,
            )

    monkeypatch.setattr("ingest.intake.GCSBackend", FakeGCSBackend)

    from ingest.intake import intake_file

    result = intake_file(
        path=fixture_file,
        source_name="ESOLVER_PARTITE_ORTI_SNAPSHOT",
        actor="test",
    )

    assert result.raw_object_id == "raw-id-123"
    assert len(upload_calls) == 1
    assert upload_calls[0][1] == "ESOLVER_PARTITE_ORTI_SNAPSHOT"
    assert upload_calls[0][3] == "hotelops-raw"
    assert isinstance(upload_calls[0][2], datetime)
    assert upload_calls[0][2].tzinfo == timezone.utc

    reg_call = patch_intake_deps["register"][0]
    assert reg_call["raw_backend"] == "gcs"
    assert reg_call["raw_uri"].startswith("gs://hotelops-raw/")
    assert reg_call["gcs_generation"] == 1715000000123456


def test_intake_with_drive_source_does_not_upload(
    monkeypatch, fixture_file: Path, patch_intake_deps
) -> None:
    fake_source = MagicMock()
    fake_source.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake_source.societa = "ORTI"
    fake_source.business_unit = None
    fake_source.detector_category = "bilancino"
    fake_source.raw_storage = MagicMock(backend="drive", bucket=None)
    fake_source.loop_targets = ["budget_canonical"]
    fake_source.promotion_policy = "AUTO"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.intake.load_registry", lambda: fake_reg)

    gcs_init_calls = []

    class FakeGCSBackend:
        def __init__(self, bucket):
            gcs_init_calls.append(bucket)

    monkeypatch.setattr("ingest.intake.GCSBackend", FakeGCSBackend)

    from ingest.intake import intake_file

    intake_file(
        path=fixture_file,
        source_name="ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        actor="test",
    )

    assert gcs_init_calls == [], "GCSBackend must not be instantiated for drive backend"
    reg_call = patch_intake_deps["register"][0]
    assert reg_call["raw_backend"] == "drive"
    assert reg_call["raw_uri"].startswith("file://")
    assert reg_call.get("gcs_generation") is None


def test_intake_without_source_name_stays_local(
    monkeypatch, fixture_file: Path, patch_intake_deps
) -> None:
    """No source → no GCS upload (Q4 decision: sourceless intake stays local)."""
    gcs_init_calls = []

    class FakeGCSBackend:
        def __init__(self, bucket):
            gcs_init_calls.append(bucket)

    monkeypatch.setattr("ingest.intake.GCSBackend", FakeGCSBackend)

    from ingest.intake import intake_file

    intake_file(path=fixture_file, source_name=None, actor="test")

    assert gcs_init_calls == []
    reg_call = patch_intake_deps["register"][0]
    assert reg_call["raw_backend"] == "local"
    assert reg_call["raw_uri"].startswith("file://")


def test_intake_dedup_hit_skips_upload_and_event(
    monkeypatch, fixture_file: Path, patch_intake_deps
) -> None:
    """Spec §3 D8 paragraph 1: re-intake of a known content_hash must NOT
    upload to GCS and must NOT emit a duplicate RAW_INGESTED event.

    Regression guard for the gap discovered in the Phase 4 smoke test
    (orphan GCS generation + duplicate lineage event).
    """
    # Override the default fixture stub: dedup hit returns existing id.
    monkeypatch.setattr(
        "ingest.intake._lookup_existing_by_hash",
        lambda content_hash: "raw-id-existing-7",
    )

    fake_source = MagicMock()
    fake_source.source_name = "MPS_BANCA_ORTI_APPEND"
    fake_source.societa = "ORTI"
    fake_source.business_unit = None
    fake_source.detector_category = "banca"
    fake_source.raw_storage = MagicMock(backend="gcs", bucket="hotelops-raw")
    fake_source.loop_targets = ["daily_reconciliation"]
    fake_source.promotion_policy = "AUTO"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.intake.load_registry", lambda: fake_reg)

    upload_calls: list = []

    class FakeGCSBackend:
        def __init__(self, bucket):
            self.bucket = bucket

        def upload(self, **kw):
            upload_calls.append(kw)
            raise AssertionError("upload must NOT be called on dedup hit")

    monkeypatch.setattr("ingest.intake.GCSBackend", FakeGCSBackend)

    from ingest.intake import intake_file

    result = intake_file(
        path=fixture_file,
        source_name="MPS_BANCA_ORTI_APPEND",
        actor="test",
    )

    # Behavioural contract on dedup hit:
    assert result.raw_object_id == "raw-id-existing-7"
    assert result.deduped is True
    assert upload_calls == [], "no GCS upload"
    assert patch_intake_deps["register"] == [], "no register_raw_object call"
    assert patch_intake_deps["events"] == [], "no RAW_INGESTED emit"
