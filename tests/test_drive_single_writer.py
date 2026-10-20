"""Un solo scrittore sugli intake Drive + schema delle sorgenti Drive
(spec 2026-10-17 drive-agent-friendly, D6)."""

from pathlib import Path

import pytest

from core.lineage.schemas import RawStorage, SourceDefinition
from ingest.intake import DriveSingleWriterError, intake_file


def _sd(**over) -> SourceDefinition:
    base = {
        "source_name": "ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        "system": "ESOLVER",
        "dataset": "BILANCINO",
        "societa": "ORTI",
        "lifecycle": "SNAPSHOT",
        "canonical_table": "f_bilancino",
        "parser_module": "ingest.flussi.ingest_bilancino",
        "promotion_policy": "AUTO",
        "detector_category": "bilancino",
        "loop_targets": ["monthly_close"],
        "raw_storage": RawStorage(
            backend="gcs", bucket="hotelops-raw", path_template="x"
        ),
    }
    base.update(over)
    return SourceDefinition(**base)


# ── schema ───────────────────────────────────────────────────────────────────


def test_drive_folder_id_round_trips():
    sd = _sd(drive_folder_id="folder123")
    assert sd.is_drive_source
    assert SourceDefinition(**sd.model_dump(mode="json")).drive_folder_id == "folder123"


def test_file_id_e_folder_id_sono_alternativi():
    with pytest.raises(ValueError, match="alternativi"):
        _sd(drive_file_id="f", drive_folder_id="d")


def test_sorgente_drive_richiede_raw_su_gcs():
    with pytest.raises(ValueError, match="gcs"):
        _sd(drive_folder_id="d", raw_storage=RawStorage(backend="local"))


def test_senza_id_drive_non_e_sorgente_drive():
    assert not _sd().is_drive_source


# ── la porta: intake fuori dal job ───────────────────────────────────────────


def _fake_registry(sd):
    class R:
        def get(self, name):
            return sd if name == sd.source_name else None

    return R()


def test_intake_interattivo_di_sorgente_drive_viene_rifiutato(monkeypatch, tmp_path):
    sd = _sd(drive_folder_id="folder123")
    monkeypatch.setattr("ingest.intake.load_registry", lambda: _fake_registry(sd))
    monkeypatch.setattr("ingest.intake._lookup_existing_by_hash", lambda h: None)
    f = tmp_path / "ORTI_BILANCINO_2026-10.xls"
    f.write_bytes(b"x")
    with pytest.raises(DriveSingleWriterError, match="riservato al job drive_fetch"):
        intake_file(f, source_name=sd.source_name, actor="cli")


def test_intake_del_job_passa_la_porta(monkeypatch, tmp_path):
    """Con actor drive_sync la porta non scatta: il flusso prosegue fino al
    dedup (qui simulato come hit, così non serve GCS né BigQuery)."""
    sd = _sd(drive_folder_id="folder123")
    monkeypatch.setattr("ingest.intake.load_registry", lambda: _fake_registry(sd))
    monkeypatch.setattr(
        "ingest.intake._lookup_existing_by_hash", lambda h: "raw-esistente"
    )
    f = tmp_path / "ORTI_BILANCINO_2026-10.xls"
    f.write_bytes(b"x")
    r = intake_file(Path(f), source_name=sd.source_name, actor="drive_sync")
    assert r.deduped and r.raw_object_id == "raw-esistente"


def test_sorgenti_non_drive_non_sono_toccate(monkeypatch, tmp_path):
    sd = _sd()
    monkeypatch.setattr("ingest.intake.load_registry", lambda: _fake_registry(sd))
    monkeypatch.setattr(
        "ingest.intake._lookup_existing_by_hash", lambda h: "raw-esistente"
    )
    f = tmp_path / "a.xls"
    f.write_bytes(b"x")
    assert intake_file(f, source_name=sd.source_name, actor="cli").deduped
