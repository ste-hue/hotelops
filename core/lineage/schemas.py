"""Pydantic schemas + naming grammar for the lineage layer.

Spec: docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md §4

Era semantics
─────────────
PHASE4_GCS_CUTOFF is the wall-clock boundary between two archaeological layers:

  pre_phase4  (raw_backend in 'drive'|'local', intake_at < cutoff)
    Immutable history.  f_raw_objects rows created during Phase 1-4 smoke
    tests.  raw_uri points to file:// or drive:// paths that may no longer
    exist.  Provenance is partial — canonical rows downstream may have
    raw_object_id IS NULL.  Trust the canonical data; treat the raw provenance
    as archaeological context only.

  live        (raw_backend = 'gcs', intake_at >= cutoff)
    Operational memory.  Every raw file is in GCS with a stable gs:// URI,
    a content_hash, and an FK chain to canonical rows.  This is the layer
    where provenance is trustworthy and replayable.

Lineage confidence vocabulary (informational — not enforced at write time):
  NONE         pre-lineage canonical rows: raw_object_id IS NULL
  PARTIAL      lineage_era='pre_phase4': raw row exists, FK may be absent
  VERIFIED     lineage_era='live', FK present, hash matches promotion record
  RECONSTRUCTED retroactively backfilled (see docs/architecture/AI_INSTRUCTIONS.md)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Era boundary ──────────────────────────────────────────────────────────────

# Phase 4 cutover: GCS becomes default raw backend for all new sources.
# Files registered BEFORE this date (lineage_era='pre_phase4') are considered
# archaeological; files AFTER (lineage_era='live') are the operational memory.
PHASE4_GCS_CUTOFF = datetime(2026, 5, 5, tzinfo=timezone.utc)

LineageEra = Literal["pre_phase4", "live"]

# ── Closed enums ──────────────────────────────────────────────────────────────

SOCIETA_VALUES = ("ORTI", "INTUR", "GROUP", "VIGNA", "STEFANO_PERSONALE", "PERSONALE")
LIFECYCLE_VALUES = ("APPEND", "SNAPSHOT")
TOKEN_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*$")

RawObjectStatus = Literal[
    "RAW_ONLY", "CLASSIFIED", "PROMOTABLE", "PROMOTED", "REJECTED"
]

LineageEventType = Literal[
    "RAW_INGESTED",
    "DETECTED",
    "SOURCE_RESOLVED",
    "VALIDATED_OK",
    "VALIDATED_FAIL",
    "PROMOTION_REQUESTED",
    "PROMOTED",
    "REJECTED",
    "RECLASSIFIED",
]

RejectionReason = Literal[
    "NO_LOOP_TARGET", "DETECT_FAIL", "VALIDATE_FAIL", "WRITE_FAIL"
]
PromotionPolicy = Literal["AUTO", "MANUAL", "RAW_ONLY"]
RawBackend = Literal["drive", "gcs", "local"]


# ── Naming grammar ────────────────────────────────────────────────────────────


class InvalidSourceName(ValueError):
    """source_name does not match <SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>."""


def validate_source_name(name: str) -> tuple[str, str, str, str]:
    """Parse + validate a source_name. Returns (system, dataset, societa, lifecycle).

    Strict 4-token grammar — see spec §4.1.1.
    """
    parts = name.split("_")
    if len(parts) != 4:
        raise InvalidSourceName(
            f"{name!r}: expected 4 underscore-separated tokens, got {len(parts)}"
        )
    system, dataset, societa, lifecycle = parts
    for token, label in ((system, "system"), (dataset, "dataset")):
        if not TOKEN_PATTERN.match(token):
            raise InvalidSourceName(
                f"{name!r}: {label} token {token!r} must match [A-Z][A-Z0-9]*"
            )
    if societa not in SOCIETA_VALUES:
        raise InvalidSourceName(
            f"{name!r}: societa {societa!r} must be one of {list(SOCIETA_VALUES)}"
        )
    if lifecycle not in LIFECYCLE_VALUES:
        raise InvalidSourceName(
            f"{name!r}: lifecycle {lifecycle!r} must be one of {list(LIFECYCLE_VALUES)}"
        )
    return (system, dataset, societa, lifecycle)


# ── Source definition (yaml row) ──────────────────────────────────────────────


class RawStorage(BaseModel):
    backend: RawBackend
    path_template: Optional[str] = None
    bucket: Optional[str] = None


class SourceDefinition(BaseModel):
    source_name: str
    system: str
    dataset: str
    dataset_label: Optional[str] = None
    societa: Literal["ORTI", "INTUR", "GROUP", "VIGNA", "STEFANO_PERSONALE"]
    business_unit: Optional[str] = None
    lifecycle: Literal["APPEND", "SNAPSHOT"]
    canonical_table: str
    parser_module: str
    parser_entrypoint: str = "main"
    natural_key: Optional[list[str]] = None
    hash_basis: Optional[str] = None
    loop_targets: list[str] = Field(default_factory=list)
    promotion_policy: PromotionPolicy
    detector_category: str
    raw_storage: RawStorage
    # Sorgenti PEC (system == "PEC"): identità della casella. La policy di
    # visibilità sul pannello NON sta qui: vive in PANEL_ENTITIES (whitelist).
    casella: Optional[str] = None
    entity_id: Optional[
        Literal["INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"]
    ] = None
    input_formats: list[Literal["mbox", "eml"]] = Field(
        default_factory=lambda: ["mbox"]
    )
    drive_file_id: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("source_name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        validate_source_name(v)
        return v

    @model_validator(mode="after")
    def _pec_richiede_identita_casella(self):
        if self.system == "PEC" and (not self.casella or not self.entity_id):
            raise ValueError(
                f"{self.source_name}: sorgente PEC richiede casella ed entity_id"
            )
        return self


# ── Raw object (identity row) ─────────────────────────────────────────────────


class RawObject(BaseModel):
    raw_object_id: str
    content_hash: str
    raw_uri: str
    raw_backend: RawBackend
    gcs_generation: Optional[int] = None
    file_name_original: str
    file_name_canonical: Optional[str] = None
    bytes_size: int
    source_name: Optional[str] = None
    detector_category: Optional[str] = None
    societa_id: Optional[str] = None
    business_unit_id: Optional[str] = None
    banca_id: Optional[str] = None
    intake_at: datetime
    intake_actor: str
    pipeline_run_id: str
    pipeline_name: str
    file_sorgente: Optional[str] = None
    ingestion_ts: datetime
    lineage_era: LineageEra = "live"


# ── Lineage event (state transition log row) ──────────────────────────────────


class LineageEvent(BaseModel):
    event_id: str
    raw_object_id: str
    event_type: LineageEventType
    event_at: datetime
    actor: str
    pipeline_run_id: Optional[str] = None
    pipeline_name: Optional[str] = None
    from_status: Optional[RawObjectStatus] = None
    to_status: Optional[RawObjectStatus] = None
    payload_json: Optional[str] = None
    reason: Optional[RejectionReason] = None
