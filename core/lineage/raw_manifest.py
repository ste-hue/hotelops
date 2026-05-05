"""High-level API for raw object lifecycle persistence.

Confined: ALL writes to f_raw_objects and f_lineage_events go through this module.
ALL writes use bq_write_validated(append) — never raw client. I1 strict.

Spec: §3.3, §5.3
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.bq.write import bq_write_validated
from core.lineage.schemas import (
    LineageEvent,
    LineageEventType,
    RawBackend,
    RawObject,
    RawObjectStatus,
    RejectionReason,
)
from core.lineage.state_machine import next_status_after_event

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
F_RAW_OBJECTS = f"{PROJECT}.{DATASET}.f_raw_objects"
F_LINEAGE_EVENTS = f"{PROJECT}.{DATASET}.f_lineage_events"
V_RAW_OBJECTS_CURRENT = f"{PROJECT}.{DATASET}.v_raw_objects_current"


def _lookup_existing_by_hash(content_hash: str) -> Optional[str]:
    """Return raw_object_id of an existing row with this hash, or None."""
    from core.bq.client import get_client
    from google.cloud import bigquery

    client = get_client()
    sql = f"""
    SELECT raw_object_id
    FROM `{F_RAW_OBJECTS}`
    WHERE content_hash = @hash
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("hash", "STRING", content_hash)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return rows[0].raw_object_id if rows else None


def register_raw_object(
    content_hash: str,
    raw_uri: str,
    raw_backend: RawBackend,
    file_name_original: str,
    bytes_size: int,
    intake_actor: str,
    file_name_canonical: Optional[str] = None,
    source_name: Optional[str] = None,
    detector_category: Optional[str] = None,
    societa_id: Optional[str] = None,
    business_unit_id: Optional[str] = None,
    banca_id: Optional[str] = None,
    file_sorgente: Optional[str] = None,
) -> str:
    """Write a new row to f_raw_objects (or return existing id on dedup).

    Generates raw_object_id (UUID4). Lineage fields (pipeline_run_id, pipeline_name)
    are populated via PipelineRun.get_current() inside bq_write_validated.
    """
    existing = _lookup_existing_by_hash(content_hash)
    if existing:
        log.info(
            "register_raw_object: dedup hit on %s, returning existing %s",
            content_hash[:12],
            existing,
        )
        return existing

    now = datetime.now(timezone.utc)
    raw_object_id = str(uuid.uuid4())

    # PipelineRun ContextVar is read by bq_write_validated for lineage fields;
    # we still need to pass them on the Pydantic row (REQUIRED). Read here.
    from core.pipeline_run import PipelineRun

    run = PipelineRun.get_current()
    pipeline_run_id = run.run_id if run else str(uuid.uuid4())
    pipeline_name = run.pipeline_name if run else "intake_standalone"

    row = RawObject(
        raw_object_id=raw_object_id,
        content_hash=content_hash,
        raw_uri=raw_uri,
        raw_backend=raw_backend,
        file_name_original=file_name_original,
        file_name_canonical=file_name_canonical,
        bytes_size=bytes_size,
        source_name=source_name,
        detector_category=detector_category,
        societa_id=societa_id,
        business_unit_id=business_unit_id,
        banca_id=banca_id,
        intake_at=now,
        intake_actor=intake_actor,
        pipeline_run_id=pipeline_run_id,
        pipeline_name=pipeline_name,
        file_sorgente=file_sorgente,
        ingestion_ts=now,
    )
    bq_write_validated(F_RAW_OBJECTS, [row], mode="append")
    return raw_object_id


def emit_event(
    raw_object_id: str,
    event_type: LineageEventType,
    actor: str,
    from_status: Optional[RawObjectStatus] = None,
    to_status: Optional[RawObjectStatus] = None,
    reason: Optional[RejectionReason] = None,
    payload: Optional[dict] = None,
) -> str:
    """Append a LineageEvent. Validates transition before writing.

    For non-transitional events (DETECTED, VALIDATED_*, PROMOTION_REQUESTED),
    pass to_status=None.
    """
    # Validate transition (raises InvalidTransition if forbidden)
    expected_to = next_status_after_event(from_status, event_type)
    if to_status is not None and expected_to is not None and to_status != expected_to:
        raise ValueError(
            f"Inconsistent transition: event {event_type} from {from_status} "
            f"yields {expected_to}, caller passed to_status={to_status}"
        )

    from core.pipeline_run import PipelineRun

    run = PipelineRun.get_current()
    event = LineageEvent(
        event_id=str(uuid.uuid4()),
        raw_object_id=raw_object_id,
        event_type=event_type,
        event_at=datetime.now(timezone.utc),
        actor=actor,
        pipeline_run_id=run.run_id if run else None,
        pipeline_name=run.pipeline_name if run else None,
        from_status=from_status,
        to_status=to_status if to_status is not None else expected_to,
        payload_json=json.dumps(payload, default=str) if payload else None,
        reason=reason,
    )
    bq_write_validated(F_LINEAGE_EVENTS, [event], mode="append")
    return event.event_id


def latest_status(raw_object_id: str) -> Optional[RawObjectStatus]:
    """Read current status from v_raw_objects_current."""
    from core.bq.client import get_client
    from google.cloud import bigquery

    client = get_client()
    sql = f"""
    SELECT current_status
    FROM `{V_RAW_OBJECTS_CURRENT}`
    WHERE raw_object_id = @id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", raw_object_id)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return rows[0].current_status if rows else None
