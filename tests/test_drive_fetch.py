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


def test_main_apre_un_pipeline_run_col_nome_del_job(monkeypatch, tmp_path):
    """Il job registra `drive_fetch:<SOURCE>` in f_pipeline_runs (spec 2026-09-09 §8)."""
    import sys
    from types import SimpleNamespace

    import ingest.drive_fetch as df

    runs = []

    class FakeRun:
        def __init__(self, pipeline_name, societa_id=None, file_sorgente=None):
            self.pipeline_name = pipeline_name
            self.societa_id = societa_id
            self.rows_new = None

        def __enter__(self):
            runs.append(self)
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("core.pipeline_run.PipelineRun", FakeRun)
    f = tmp_path / "x.xlsx"
    f.write_bytes(b"x")
    monkeypatch.setattr(df, "fetch_drive_file", lambda *a, **k: f)
    monkeypatch.setattr(
        "ingest.intake.intake_file",
        lambda *a, **k: SimpleNamespace(
            raw_object_id="r1", content_hash="h", deduped=False
        ),
    )
    monkeypatch.setattr(
        "ingest.promotion.promote_raw_object",
        lambda *a, **k: SimpleNamespace(status="PROMOTED", reason=None, noop=False),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["drive_fetch", "--source-name", "RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"],
    )
    df.main()
    assert [r.pipeline_name for r in runs] == [
        "drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"
    ]
    assert runs[0].societa_id == "INTUR"
    assert runs[0].rows_new == 1
