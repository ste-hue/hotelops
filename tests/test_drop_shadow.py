"""Phase 2 shadow mode tests for `hotelops drop --lineage`.

Verifies:
- without --lineage: zero call to intake, audit shape unchanged
- with --lineage + intake ok: intake called once, audit carries lineage fields
- with --lineage + intake raises: drop continues, error captured in audit
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import cli
from ingest.classify import LIFECYCLE_SNAPSHOT, ClassificationResult


@pytest.fixture
def fixture_file(tmp_path: Path) -> Path:
    f = tmp_path / "INTUR_PARTITE_FORNITORI_test.xlsx"
    f.write_bytes(b"fake-xlsx-bytes")
    return f


@pytest.fixture
def fake_classification(fixture_file: Path) -> ClassificationResult:
    return ClassificationResult(
        file_path=fixture_file,
        file_type="partite_fornitori",
        category="partite_fornitori",
        lifecycle=LIFECYCLE_SNAPSHOT,
        societa="INTUR",
        canonical_name="INTUR_PARTITE_FORNITORI_20260505.xlsx",
        dest_folder="partite_fornitori/INTUR",
        pipeline_cmd="python -m ingest.flussi.ingest_partite_aperte --file {dest_file}",
        confidence=0.9,
    )


@pytest.fixture
def patch_classify_route_ingest(monkeypatch, fake_classification, tmp_path: Path):
    """Stub out classify_batch / route_file / run_ingest / file_md5_hex.

    Returns the captured-audit list reference for the test body.
    """
    dest = tmp_path / "ORTI" / "INTUR_PARTITE_FORNITORI_20260505.xlsx"
    audit_records: list[dict] = []

    monkeypatch.setattr(
        "ingest.classify.classify_batch", lambda paths: [fake_classification]
    )
    monkeypatch.setattr(
        "ingest.classify.route_file",
        lambda r, d, dry_run, use_rclone: dest,
    )
    monkeypatch.setattr(
        "ingest.classify.run_ingest",
        lambda r, d, dh, dry_run=False: True,
    )
    monkeypatch.setattr("ingest.classify.file_md5_hex", lambda p: "fakehash")
    monkeypatch.setattr(
        "ingest.classify.append_drop_audit",
        lambda dh, rec: audit_records.append(rec),
    )
    return audit_records


def _make_args(
    files: list[str], lineage: bool = False, dry_run: bool = False
) -> Namespace:
    return Namespace(
        files=files,
        lineage=lineage,
        dry_run=dry_run,
        locale=True,
        datahub=None,
    )


def test_drop_without_lineage_does_not_invoke_intake(
    monkeypatch, fixture_file, patch_classify_route_ingest
) -> None:
    intake_calls: list[tuple] = []
    monkeypatch.setattr(
        "ingest.intake.intake_file",
        lambda *a, **kw: (
            intake_calls.append((a, kw))
            or MagicMock(raw_object_id="should-not-be-used")
        ),
    )

    args = _make_args(files=[str(fixture_file)], lineage=False)
    cli.cmd_drop(args)

    assert intake_calls == [], "intake must not be called without --lineage"
    assert len(patch_classify_route_ingest) == 1
    rec = patch_classify_route_ingest[0]
    assert rec["status"] == "OK"
    # Lineage fields ABSENT when flag off (additive contract)
    assert "lineage_enabled" not in rec
    assert "lineage_raw_object_id" not in rec
    assert "lineage_error" not in rec


def test_drop_with_lineage_ok_records_raw_object_id(
    monkeypatch, fixture_file, patch_classify_route_ingest
) -> None:
    intake_calls: list[tuple] = []

    def fake_intake(path, source_name=None, actor="cli", **kw):
        intake_calls.append({"path": path, "source_name": source_name, "actor": actor})
        return MagicMock(
            raw_object_id="raw-abc-123", content_hash="h", source_name=source_name
        )

    monkeypatch.setattr("ingest.intake.intake_file", fake_intake)
    # Stub the registry resolver to return a fake source_def for partite/INTUR.
    fake_source = MagicMock(source_name="ESOLVER_PARTITE_INTUR_SNAPSHOT")
    fake_reg = MagicMock()
    fake_reg.resolve = lambda cat, societa: (
        fake_source if (cat == "partite_fornitori" and societa == "INTUR") else None
    )
    monkeypatch.setattr("core.lineage.source_resolver.load_registry", lambda: fake_reg)

    args = _make_args(files=[str(fixture_file)], lineage=True)
    cli.cmd_drop(args)

    assert len(intake_calls) == 1, "intake must be called exactly once"
    assert intake_calls[0]["actor"] == "drop_shadow"
    assert intake_calls[0]["source_name"] == "ESOLVER_PARTITE_INTUR_SNAPSHOT"

    assert len(patch_classify_route_ingest) == 1
    rec = patch_classify_route_ingest[0]
    assert rec["status"] == "OK"
    assert rec["lineage_enabled"] is True
    assert rec["lineage_raw_object_id"] == "raw-abc-123"
    assert rec["lineage_error"] is None


def test_drop_with_lineage_failure_continues_and_records_error(
    monkeypatch, fixture_file, patch_classify_route_ingest
) -> None:
    def boom(*a, **kw):
        raise RuntimeError("BQ unreachable")

    monkeypatch.setattr("ingest.intake.intake_file", boom)
    # Resolver also fine — failure happens inside intake, not resolver.
    fake_reg = MagicMock()
    fake_reg.resolve = lambda cat, societa: None
    monkeypatch.setattr("core.lineage.source_resolver.load_registry", lambda: fake_reg)

    args = _make_args(files=[str(fixture_file)], lineage=True)
    # Must NOT raise — drop is best-effort about lineage.
    cli.cmd_drop(args)

    assert len(patch_classify_route_ingest) == 1
    rec = patch_classify_route_ingest[0]
    # Drop itself succeeded (run_ingest stub returned True).
    assert rec["status"] == "OK"
    assert rec["ingest_ok"] is True
    assert rec["lineage_enabled"] is True
    assert rec["lineage_raw_object_id"] is None
    assert rec["lineage_error"] is not None
    assert "BQ unreachable" in rec["lineage_error"]


def test_drop_lineage_skipped_in_dry_run(
    monkeypatch, fixture_file, patch_classify_route_ingest
) -> None:
    """Even with --lineage, dry-run must not invoke intake (no BQ side-effects)."""
    intake_calls: list[tuple] = []
    monkeypatch.setattr(
        "ingest.intake.intake_file",
        lambda *a, **kw: intake_calls.append((a, kw)) or MagicMock(raw_object_id="x"),
    )

    args = _make_args(files=[str(fixture_file)], lineage=True, dry_run=True)
    cli.cmd_drop(args)

    assert intake_calls == [], "intake must not be called in --dry-run"
    rec = patch_classify_route_ingest[0]
    # Audit still carries the flag (operator wanted shadow), but no id and no error.
    assert rec["lineage_enabled"] is True
    assert rec["lineage_raw_object_id"] is None
    assert rec["lineage_error"] is None
