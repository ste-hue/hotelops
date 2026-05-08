"""Intake entrypoint — file + source metadata → raw blob + RAW_INGESTED event.

Spec: §3.1, §5.2 (∅ → RAW_ONLY transition)

Lineage gate
────────────
Set the HOTELOPS_LINEAGE_GATE environment variable to control lineage behaviour:

  required  (default) — intake must succeed before promotion is allowed.
                        GCS upload failures raise, halting the pipeline.
  optional  — intake is attempted; failures are logged as warnings and
              skipped gracefully (raw_object_id = None on the canonical rows).
  disabled  — lineage layer is bypassed entirely. No GCS upload, no row in
              f_raw_objects, no event. raw_object_id = None everywhere.
              USE ONLY for emergency rollback or local dev without GCS.

Track D guidance (see docs/architecture/AI_INSTRUCTIONS.md §Lineage eras):
  Start with 'optional' on first production rollout; move to 'required' once
  GCS + promotion has been verified on all 11 registered sources.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.lineage.policy_gate import enforce_loop_target_gate_consistency
from core.lineage.raw_manifest import (
    _lookup_existing_by_hash,
    emit_event,
    register_raw_object,
)
from core.lineage.raw_storage import GCSBackend, LocalBackend
from core.lineage.source_resolver import load_registry
from core.pipeline_run import PipelineRun

log = logging.getLogger(__name__)

# HOTELOPS_LINEAGE_GATE controls how lineage failures are handled.
_GATE_MODES = {"required", "optional", "disabled"}


def _lineage_gate() -> str:
    """Return the current lineage gate mode."""
    mode = os.environ.get("HOTELOPS_LINEAGE_GATE", "required").lower()
    if mode not in _GATE_MODES:
        log.warning(
            "HOTELOPS_LINEAGE_GATE=%r is not a valid mode (%s) — using 'required'",
            mode,
            ", ".join(sorted(_GATE_MODES)),
        )
        return "required"
    return mode


@dataclass
class IntakeResult:
    raw_object_id: Optional[str]
    content_hash: str
    source_name: Optional[str]
    deduped: bool


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            block = f.read(1 << 20)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def intake_file(
    path: Path,
    source_name: Optional[str] = None,
    actor: str = "cli",
) -> IntakeResult:
    """Register a file in the lineage layer.

    Backend is selected from source_def.raw_storage.backend:
      - drive | local → file kept on local disk, raw_uri = file://...
      - gcs → file uploaded to gs://<bucket>/<source>/<YYYY>/<MM>/<filename>,
              raw_uri = gs://..., gcs_generation populated
    Sourceless intake (source_name=None) is always treated as local.

    Respects HOTELOPS_LINEAGE_GATE:
      disabled → returns a null IntakeResult (no upload, no row, no event)
      optional → wraps execution; logs failures and returns null on error
      required → raises on any failure (default)
    """
    gate = _lineage_gate()

    if gate == "disabled":
        log.debug("intake_file: lineage gate=disabled — skipping for %s", path.name)
        return IntakeResult(
            raw_object_id=None,
            content_hash="",
            source_name=source_name,
            deduped=False,
        )

    try:
        return _intake_file_core(path, source_name=source_name, actor=actor)
    except Exception:
        if gate == "optional":
            log.warning(
                "intake_file: lineage gate=optional — error suppressed for %s",
                path.name,
                exc_info=True,
            )
            return IntakeResult(
                raw_object_id=None,
                content_hash="",
                source_name=source_name,
                deduped=False,
            )
        raise


def _intake_file_core(
    path: Path,
    source_name: Optional[str] = None,
    actor: str = "cli",
) -> IntakeResult:
    if not path.exists():
        raise FileNotFoundError(path)

    content_hash = _file_md5(path)
    bytes_size = path.stat().st_size

    source_def = None
    if source_name is not None:
        reg = load_registry()
        source_def = reg.get(source_name)
        if source_def is None:
            raise KeyError(f"source_name not in registry: {source_name}")
        enforce_loop_target_gate_consistency(source_def)

    # Dedup-before-upload (spec §3 D8 paragraph 1).
    # Probe content_hash on f_raw_objects BEFORE invoking the storage backend:
    # a hit means we'd otherwise (a) waste a GCS upload that creates an orphan
    # generation under Object Versioning, and (b) emit a duplicate RAW_INGESTED
    # into f_lineage_events. Both were observed in the Phase 4 smoke test.
    existing_id = _lookup_existing_by_hash(content_hash)
    if existing_id is not None:
        log.info(
            "intake_file: dedup hit on %s — returning existing raw_object_id %s "
            "(no upload, no event)",
            content_hash[:12],
            existing_id,
        )
        return IntakeResult(
            raw_object_id=existing_id,
            content_hash=content_hash,
            source_name=source_name,
            deduped=True,
        )

    backend_kind = (
        source_def.raw_storage.backend
        if source_def and source_def.raw_storage
        else "local"
    )
    intake_at = datetime.now(timezone.utc)

    if backend_kind == "gcs":
        bucket = source_def.raw_storage.bucket or "hotelops-raw"
        backend = GCSBackend(bucket=bucket)
        upload_result = backend.upload(
            local_path=path, source_name=source_name, intake_at=intake_at
        )
    else:
        # drive | local: passthrough
        backend = LocalBackend()
        upload_result = backend.upload(
            local_path=path,
            source_name=source_name or "_unclassified",
            intake_at=intake_at,
        )

    with PipelineRun(
        "ingest_intake",
        societa_id=source_def.societa if source_def else None,
        file_sorgente=str(path),
    ):
        raw_object_id = register_raw_object(
            content_hash=content_hash,
            raw_uri=upload_result.raw_uri,
            raw_backend=backend_kind,
            file_name_original=path.name,
            bytes_size=bytes_size,
            intake_actor=actor,
            source_name=source_name,
            detector_category=source_def.detector_category if source_def else None,
            societa_id=source_def.societa if source_def else None,
            business_unit_id=source_def.business_unit if source_def else None,
            file_sorgente=str(path),
            gcs_generation=upload_result.generation,
        )

        emit_event(
            raw_object_id=raw_object_id,
            event_type="RAW_INGESTED",
            actor=actor,
            from_status=None,
            to_status="RAW_ONLY",
            payload={
                "file_name": path.name,
                "bytes_size": bytes_size,
                "raw_backend": backend_kind,
                "gcs_generation": upload_result.generation,
            },
        )

        # Fix B (Task 4.5): when source is resolved, immediately advance
        # RAW_ONLY → CLASSIFIED so promote_raw_object can start from a valid
        # state. Sourceless intake stays at RAW_ONLY (must be classified later).
        if source_def is not None:
            emit_event(
                raw_object_id=raw_object_id,
                event_type="SOURCE_RESOLVED",
                actor=actor,
                from_status="RAW_ONLY",
                to_status="CLASSIFIED",
                payload={"source_name": source_name},
            )

    return IntakeResult(
        raw_object_id=raw_object_id,
        content_hash=content_hash,
        source_name=source_name,
        deduped=False,
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="intake")
    p.add_argument("file", type=Path)
    p.add_argument("--source-name", default=None)
    p.add_argument("--actor", default="cli")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    result = intake_file(args.file, source_name=args.source_name, actor=args.actor)
    print(f"raw_object_id={result.raw_object_id}")
    print(f"content_hash={result.content_hash}")
    print(f"source_name={result.source_name}")


if __name__ == "__main__":
    main()
