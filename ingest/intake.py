"""Intake entrypoint — file + source metadata → raw blob + RAW_INGESTED event.

Spec: §3.1, §5.2 (∅ → RAW_ONLY transition)
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.lineage.policy_gate import enforce_loop_target_gate_consistency
from core.lineage.raw_manifest import emit_event, register_raw_object
from core.lineage.source_resolver import load_registry
from core.pipeline_run import PipelineRun

log = logging.getLogger(__name__)


@dataclass
class IntakeResult:
    raw_object_id: str
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
    raw_backend: str = "local",
    raw_uri: Optional[str] = None,
) -> IntakeResult:
    """Register a file in the lineage layer.

    If source_name is provided, it must exist in the registry; the source_def
    is propagated to the RawObject row (societa, detector_category, etc.).
    If source_name is None, the row is registered as RAW_ONLY without source binding.

    Phase 1: blob storage is the file's existing path (raw_backend='local' or 'drive').
    Phase 4: blob is written to GCS first, then registered.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    content_hash = _file_md5(path)
    bytes_size = path.stat().st_size
    raw_uri_final = raw_uri or path.resolve().as_uri()

    # Resolve source if provided
    source_def = None
    if source_name is not None:
        reg = load_registry()
        source_def = reg.get(source_name)
        if source_def is None:
            raise KeyError(f"source_name not in registry: {source_name}")
        # Boot-time check for the resolved source
        enforce_loop_target_gate_consistency(source_def)

    with PipelineRun(
        "ingest_intake",
        societa_id=source_def.societa if source_def else None,
        file_sorgente=str(path),
    ):
        raw_object_id = register_raw_object(
            content_hash=content_hash,
            raw_uri=raw_uri_final,
            raw_backend=raw_backend,
            file_name_original=path.name,
            bytes_size=bytes_size,
            intake_actor=actor,
            source_name=source_name,
            detector_category=source_def.detector_category if source_def else None,
            societa_id=source_def.societa if source_def else None,
            business_unit_id=source_def.business_unit if source_def else None,
            file_sorgente=str(path),
        )

        # Always emit RAW_INGESTED for new objects. (register_raw_object dedups
        # internally; if dedup hit, we skip the event to keep log idempotent.)
        # Heuristic: dedup ⇒ raw_object_id was already in BQ ⇒ check via lookup.
        # Phase 1 simplification: emit always; phase 2 add dedup check before emit.
        emit_event(
            raw_object_id=raw_object_id,
            event_type="RAW_INGESTED",
            actor=actor,
            from_status=None,
            to_status="RAW_ONLY",
            payload={
                "file_name": path.name,
                "bytes_size": bytes_size,
                "raw_backend": raw_backend,
            },
        )

    return IntakeResult(
        raw_object_id=raw_object_id,
        content_hash=content_hash,
        source_name=source_name,
        deduped=False,  # Phase 1 placeholder
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
