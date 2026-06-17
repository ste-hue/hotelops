"""Tests for the Drive auto-sync module (no live Drive API calls)."""

from core.lineage.schemas import RawStorage, SourceDefinition
from core.lineage.source_resolver import load_registry

TARGET_SOURCE = "RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"
EXPECTED_FILE_ID = "1RwaXbXtRL3XQ9iq0nIpj7qG9ixUHn-Wt"


# ── SourceDefinition schema tests ─────────────────────────────────────────────


def _minimal_source_def(**overrides) -> SourceDefinition:
    """Build a minimal valid SourceDefinition for schema round-trip tests."""
    base = dict(
        source_name="RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT",
        system="RT",
        dataset="CORRISPETTIVISPIAGGIA",
        societa="INTUR",
        lifecycle="SNAPSHOT",
        canonical_table="f_spiaggia_corrispettivi",
        parser_module="ingest.flussi.ingest_spiaggia_corrispettivi",
        promotion_policy="MANUAL",
        detector_category="corrispettivi_spiaggia",
        loop_targets=["cash_control"],
        raw_storage=RawStorage(
            backend="gcs",
            bucket="hotelops-raw",
            path_template="intur/corrispettivi_spiaggia/INTUR",
        ),
    )
    base.update(overrides)
    return SourceDefinition(**base)


def test_source_definition_accepts_drive_file_id() -> None:
    sd = _minimal_source_def(drive_file_id="abc123")
    assert sd.drive_file_id == "abc123"


def test_source_definition_drive_file_id_defaults_to_none() -> None:
    sd = _minimal_source_def()
    assert sd.drive_file_id is None


def test_source_definition_drive_file_id_round_trips() -> None:
    sd = _minimal_source_def(drive_file_id=EXPECTED_FILE_ID)
    dumped = sd.model_dump(mode="json")
    revived = SourceDefinition(**dumped)
    assert revived.drive_file_id == EXPECTED_FILE_ID


# ── Registry tests ────────────────────────────────────────────────────────────


def test_registry_source_has_drive_file_id() -> None:
    reg = load_registry()
    src = reg.get(TARGET_SOURCE)
    assert src is not None, f"{TARGET_SOURCE} missing from registry"
    assert src.drive_file_id == EXPECTED_FILE_ID
