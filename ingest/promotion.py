"""Promotion entrypoint — PROMOTABLE raw_object → parser run → canonical write → PROMOTED.

Spec: §3.1, §5.2 (PROMOTABLE → PROMOTED transition), §7.1 (hard gate)
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from core.lineage.policy_gate import (
    PolicyViolation,
    enforce_loop_target_gate_at_promotion,
)
from core.lineage.raw_manifest import (
    F_RAW_OBJECTS,
    emit_event,
    latest_status,
)
from core.lineage.raw_storage import GCSBackend
from core.lineage.source_resolver import load_registry
from core.pipeline_run import PipelineRun

log = logging.getLogger(__name__)


@dataclass
class PromotionResult:
    raw_object_id: str
    status: str  # PROMOTED | REJECTED | NOOP
    reason: Optional[str] = None
    rows_written: int = 0
    noop: bool = False


def _fetch_raw_object(raw_object_id: str):
    """Lookup raw_object row from BQ. Returns object with attribute access."""
    from core.bq.client import get_client
    from google.cloud import bigquery

    client = get_client()
    sql = f"SELECT * FROM `{F_RAW_OBJECTS}` WHERE raw_object_id = @id"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", raw_object_id)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    if not rows:
        raise KeyError(f"raw_object_id not found: {raw_object_id}")
    return rows[0]


def _invoke_parser(
    parser_module: str,
    raw_uri: str,
    source_def,
    gcs_generation: Optional[int] = None,
) -> dict:
    """Invoke the parser via subprocess.

    file:// → pass parsed path directly.
    gs://   → download to temp, pass temp path, cleanup on exit.
    """
    from urllib.parse import urlparse

    parsed = urlparse(raw_uri)
    backend = None
    cleanup_path: Optional[str] = None

    if parsed.scheme == "gs":
        bucket = parsed.netloc
        backend = GCSBackend(bucket=bucket)
        local_path = backend.download_to_temp(raw_uri, generation=gcs_generation)
        cleanup_path = local_path
    elif parsed.scheme in ("file", ""):
        local_path = parsed.path
    else:
        raise NotImplementedError(
            f"Unsupported raw_uri scheme {parsed.scheme!r}: {raw_uri}"
        )

    cmd = [sys.executable, "-m", parser_module, "--file", local_path]
    if source_def.societa in ("ORTI", "INTUR"):
        cmd += ["--societa", source_def.societa]

    log.info("Invoking parser: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Parser {parser_module} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
        return {"rows_written": -1}
    finally:
        if backend is not None and cleanup_path is not None:
            try:
                backend.cleanup(cleanup_path)
            except Exception as e:
                log.warning("Cleanup of temp %s failed: %s", cleanup_path, e)


def promote_raw_object(raw_object_id: str, actor: str = "cli") -> PromotionResult:
    """Promote a single raw_object to canonical.

    Sequence:
      1. Fetch raw_object + source_def
      2. Check current_status (idempotent if already PROMOTED)
      3. Hard gate (NO_LOOP_TARGET if RAW_ONLY)
      4. Emit PROMOTION_REQUESTED
      5. Invoke parser via subprocess
      6. On parser ok: emit VALIDATED_OK + PROMOTED
      7. On parser fail: emit VALIDATED_FAIL + REJECTED(VALIDATE_FAIL)
    """
    raw = _fetch_raw_object(raw_object_id)

    # Idempotency
    current = latest_status(raw_object_id)
    if current == "PROMOTED":
        log.info("raw_object_id=%s already PROMOTED, skipping", raw_object_id)
        return PromotionResult(raw_object_id, status="PROMOTED", noop=True)

    if not raw.source_name:
        raise ValueError(
            f"raw_object_id={raw_object_id} has no source_name; classify first"
        )

    reg = load_registry()
    source_def = reg.get(raw.source_name)
    if source_def is None:
        raise KeyError(f"source_name not in registry: {raw.source_name}")

    # Hard gate
    try:
        enforce_loop_target_gate_at_promotion(source_def)
    except PolicyViolation as e:
        emit_event(
            raw_object_id=raw_object_id,
            event_type="REJECTED",
            actor=actor,
            from_status=current or "CLASSIFIED",
            to_status="REJECTED",
            reason="NO_LOOP_TARGET",
            payload={"source_name": raw.source_name, "message": str(e)},
        )
        return PromotionResult(
            raw_object_id, status="REJECTED", reason="NO_LOOP_TARGET"
        )

    with PipelineRun(
        "promotion",
        societa_id=getattr(raw, "societa_id", None),
        file_sorgente=getattr(raw, "raw_uri", None),
    ):
        emit_event(
            raw_object_id=raw_object_id,
            event_type="PROMOTION_REQUESTED",
            actor=actor,
            from_status=current,
            to_status=None,
            payload={"parser_module": source_def.parser_module},
        )

        try:
            parser_result = _invoke_parser(
                source_def.parser_module,
                raw.raw_uri,
                source_def,
                gcs_generation=getattr(raw, "gcs_generation", None),
            )
        except Exception as e:
            emit_event(
                raw_object_id=raw_object_id,
                event_type="VALIDATED_FAIL",
                actor=actor,
                payload={"error": str(e)[:500]},
            )
            emit_event(
                raw_object_id=raw_object_id,
                event_type="REJECTED",
                actor=actor,
                from_status="PROMOTABLE",
                to_status="REJECTED",
                reason="VALIDATE_FAIL",
                payload={"error": str(e)[:500]},
            )
            return PromotionResult(
                raw_object_id, status="REJECTED", reason="VALIDATE_FAIL"
            )

        emit_event(
            raw_object_id=raw_object_id,
            event_type="VALIDATED_OK",
            actor=actor,
            payload=parser_result,
        )
        emit_event(
            raw_object_id=raw_object_id,
            event_type="PROMOTED",
            actor=actor,
            from_status="PROMOTABLE",
            to_status="PROMOTED",
            payload={
                "canonical_table": source_def.canonical_table,
                **parser_result,
            },
        )
        return PromotionResult(
            raw_object_id,
            status="PROMOTED",
            rows_written=parser_result.get("rows_written", 0),
        )


def main() -> None:
    p = argparse.ArgumentParser(prog="promotion")
    p.add_argument("--raw-object-id", required=True)
    p.add_argument("--actor", default="cli")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    r = promote_raw_object(args.raw_object_id, actor=args.actor)
    print(
        f"status={r.status} reason={r.reason or '-'} rows_written={r.rows_written} noop={r.noop}"
    )
    if r.status == "REJECTED":
        sys.exit(2)


if __name__ == "__main__":
    main()
