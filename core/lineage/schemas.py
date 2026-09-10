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
    "NO_LOOP_TARGET",
    "DETECT_FAIL",
    "VALIDATE_FAIL",
    "WRITE_FAIL",
    "EMPTY_PARSE",  # issue #125: parser exit 0 ma 0 righe atterrate in canonical
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


class ImapMailbox(BaseModel):
    """Config IMAP in sola lettura di una casella PEC.

    L'utente NON sta qui: è il campo `casella` della sorgente.
    La password NON sta qui: `password_env` nomina la variabile d'ambiente.
    """

    host: str
    port: int = 993
    password_env: str
    folders: list[str] = Field(default_factory=lambda: ["INBOX"])


class FreshnessContract(BaseModel):
    """Come si misura la freschezza di una sorgente (spec 2026-09-09 §3-4).

    `basis: canonical` legge MAX(coverage_column) dalla canonical_table, per
    combinazione di `dims` (societa_id è sempre implicito). `basis: raw` legge
    l'ultimo intake in f_raw_objects: serve alle sorgenti che condividono la
    tabella senza una colonna che le distingua, e alle RAW_ONLY.
    """

    tier: Literal["R", "E", "M"]
    cadence: Literal["daily", "weekly", "monthly", "quarterly", "adhoc"]
    grace_day: int = 10
    grain: Literal["daily", "monthly", "snapshot"]
    basis: Literal["canonical", "raw"] = "canonical"
    coverage_column: Optional[str] = None
    dims: list[str] = Field(default_factory=list)
    dim_filter: dict[str, list[str]] = Field(default_factory=dict)
    dormant: Optional[str] = None

    @model_validator(mode="after")
    def _coerenza(self):
        if not 1 <= self.grace_day <= 28:
            raise ValueError("grace_day deve stare tra 1 e 28")
        if self.basis == "canonical" and not self.coverage_column:
            raise ValueError("basis canonical richiede coverage_column")
        if self.basis == "raw" and (
            self.coverage_column or self.dims or self.dim_filter
        ):
            raise ValueError("basis raw non ammette coverage_column, dims o dim_filter")
        for dim in self.dim_filter:
            if dim not in self.dims:
                raise ValueError(f"dim_filter su {dim!r} che non è in dims")
        return self


class AcquisitionContract(BaseModel):
    """Chi esporta cosa, da dove (spec 2026-09-09 §3, §5)."""

    mode: Literal["AUTO", "SEMI", "MANUAL"]
    owner: Literal["Stefano", "Rosa", "Antonio", "job"]
    location: str
    report: str
    filters: Optional[str] = None
    format: Optional[str] = None
    job: Optional[str] = None

    @model_validator(mode="after")
    def _coerenza(self):
        if self.mode == "AUTO":
            if not self.job:
                raise ValueError(
                    "mode AUTO richiede job (pipeline_name in f_pipeline_runs)"
                )
            if self.owner != "job":
                raise ValueError("mode AUTO richiede owner 'job'")
        elif self.job:
            raise ValueError("job è ammesso solo con mode AUTO")
        return self


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
    entity_id: Optional[Literal["INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"]] = None
    input_formats: list[Literal["mbox", "eml"]] = Field(
        default_factory=lambda: ["mbox"]
    )
    drive_file_id: Optional[str] = None
    imap: Optional[ImapMailbox] = None
    notes: Optional[str] = None
    freshness: Optional[FreshnessContract] = None
    acquisition: Optional[AcquisitionContract] = None

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

    @model_validator(mode="after")
    def _raw_only_usa_basis_raw(self):
        if (
            self.promotion_policy == "RAW_ONLY"
            and self.freshness is not None
            and self.freshness.basis != "raw"
        ):
            raise ValueError(
                f"{self.source_name}: sorgente RAW_ONLY con freshness deve avere basis raw"
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
