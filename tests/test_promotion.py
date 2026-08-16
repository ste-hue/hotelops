"""Promotion entrypoint: PROMOTABLE raw_object → parser → bq_write_validated → PROMOTED."""

from unittest.mock import MagicMock

import pytest

from ingest.promotion import promote_raw_object


@pytest.fixture
def fake_registry(monkeypatch):
    """Patch source_resolver to return a fake source_def."""
    fake_source = MagicMock()
    fake_source.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake_source.promotion_policy = "AUTO"
    fake_source.parser_module = "ingest.flussi.ingest_bilancino"
    fake_source.parser_entrypoint = "main"
    fake_source.canonical_table = "f_bilancino"
    fake_source.lifecycle = "SNAPSHOT"
    fake_source.natural_key = ["data_snapshot", "societa_id"]
    fake_source.loop_targets = ["monthly_close"]
    fake_source.societa = "ORTI"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)
    return fake_source


@pytest.fixture
def captured_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        "ingest.promotion.emit_event",
        lambda **kw: events.append(kw) or f"ev-{len(events)}",
    )
    return events


@pytest.fixture
def fake_raw_object(monkeypatch):
    """Patch the raw_object lookup to return a fake row."""
    fake = MagicMock()
    fake.raw_object_id = "raw-1"
    fake.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake.raw_uri = "file:///tmp/x.xlsx"
    monkeypatch.setattr("ingest.promotion._fetch_raw_object", lambda rid: fake)
    return fake


def test_promote_happy_path(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    fake_parser_invoke = MagicMock(return_value={"rows_written": 42})
    monkeypatch.setattr("ingest.promotion._invoke_parser", fake_parser_invoke)
    # gate #125 neutralizzato: qui si testa il flusso, non il contatore FK
    monkeypatch.setattr("ingest.promotion._count_canonical_rows", lambda t, r: None)

    result = promote_raw_object("raw-1", actor="test")

    assert result.status == "PROMOTED"
    types = [ev["event_type"] for ev in captured_events]
    assert "PROMOTION_REQUESTED" in types
    assert "VALIDATED_OK" in types
    assert "PROMOTED" in types
    fake_parser_invoke.assert_called_once()


def test_promote_raw_only_source_rejected(
    monkeypatch, captured_events, fake_raw_object
) -> None:
    fake_raw_object.source_name = "POWERBI_CRUSCOTTO_ORTI_APPEND"
    fake_source = MagicMock()
    fake_source.source_name = "POWERBI_CRUSCOTTO_ORTI_APPEND"
    fake_source.promotion_policy = "RAW_ONLY"
    fake_source.loop_targets = []
    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")

    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "REJECTED"
    assert result.reason == "NO_LOOP_TARGET"
    types = [ev["event_type"] for ev in captured_events]
    assert "REJECTED" in types


def test_promote_parser_failure_emits_validate_fail(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    monkeypatch.setattr(
        "ingest.promotion._invoke_parser",
        MagicMock(side_effect=ValueError("parser broke")),
    )
    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "REJECTED"
    assert result.reason == "VALIDATE_FAIL"
    types = [ev["event_type"] for ev in captured_events]
    assert "VALIDATED_FAIL" in types
    assert "REJECTED" in types


def test_promote_already_promoted_is_noop(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTED")
    fake_parser = MagicMock()
    monkeypatch.setattr("ingest.promotion._invoke_parser", fake_parser)
    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "PROMOTED"
    assert result.noop is True
    fake_parser.assert_not_called()
    assert captured_events == []


def test_invoke_parser_downloads_gs_uri_to_temp(monkeypatch, tmp_path) -> None:
    """gs:// raw_uri → download to temp → subprocess gets a local path."""
    from unittest.mock import MagicMock
    from ingest import promotion

    # Stub backend
    download_calls = []
    cleanup_calls = []
    fake_local = str(tmp_path / "downloaded.xlsx")
    (tmp_path / "downloaded.xlsx").write_bytes(b"x")

    class FakeGCSBackend:
        def __init__(self, bucket):
            self.bucket = bucket

        def download_to_temp(self, raw_uri, generation):
            download_calls.append((raw_uri, generation))
            return fake_local

        def cleanup(self, p):
            cleanup_calls.append(p)
            return True

    monkeypatch.setattr(promotion, "GCSBackend", FakeGCSBackend)

    # Stub subprocess
    captured = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    monkeypatch.setattr("ingest.promotion.subprocess.run", fake_run)

    fake_source = MagicMock(societa="ORTI")
    promotion._invoke_parser(
        parser_module="ingest.flussi.ingest_partite_aperte",
        raw_uri="gs://hotelops-raw/X_Y_ORTI_SNAPSHOT/2026/05/file.xlsx",
        source_def=fake_source,
        gcs_generation=1715000000123456,
    )

    assert download_calls == [
        ("gs://hotelops-raw/X_Y_ORTI_SNAPSHOT/2026/05/file.xlsx", 1715000000123456)
    ]
    assert len(captured) == 1
    assert captured[0][1:5] == [
        "-m",
        "ingest.flussi.ingest_partite_aperte",
        "--file",
        fake_local,
    ]
    assert cleanup_calls == [fake_local]


def test_invoke_parser_file_uri_unchanged(monkeypatch, tmp_path) -> None:
    """file:// path: no download, no cleanup, parser receives the path directly."""
    from unittest.mock import MagicMock
    from ingest import promotion

    captured = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    monkeypatch.setattr("ingest.promotion.subprocess.run", fake_run)

    fake_source = MagicMock(societa="ORTI")
    promotion._invoke_parser(
        parser_module="ingest.flussi.ingest_x",
        raw_uri="file:///tmp/x.xlsx",
        source_def=fake_source,
        gcs_generation=None,
    )

    assert captured[0][1:5] == ["-m", "ingest.flussi.ingest_x", "--file", "/tmp/x.xlsx"]


# ── Gate anti verde-fabbricato (issue #125): PROMOTED solo se le righe sono atterrate ──


def test_promote_zero_righe_canonical_rejected(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    """Parser exit 0 ma nessuna riga in canonical → REJECTED EMPTY_PARSE, non PROMOTED."""
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    monkeypatch.setattr(
        "ingest.promotion._invoke_parser", MagicMock(return_value={"rows_written": -1})
    )
    monkeypatch.setattr("ingest.promotion._count_canonical_rows", lambda t, r: 0)

    result = promote_raw_object("raw-1", actor="test")

    assert result.status == "REJECTED"
    assert result.reason == "EMPTY_PARSE"
    types = [ev["event_type"] for ev in captured_events]
    assert "REJECTED" in types
    assert "PROMOTED" not in types


def test_promote_rows_written_dal_conteggio_fk(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    """Il conteggio FK sostituisce il -1 del parser: rows_written onesto."""
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    monkeypatch.setattr(
        "ingest.promotion._invoke_parser", MagicMock(return_value={"rows_written": -1})
    )
    monkeypatch.setattr("ingest.promotion._count_canonical_rows", lambda t, r: 17)

    result = promote_raw_object("raw-1", actor="test")

    assert result.status == "PROMOTED"
    assert result.rows_written == 17


def test_promote_conteggio_non_disponibile_non_blocca(
    monkeypatch, fake_registry, captured_events, fake_raw_object
) -> None:
    """Contatore FK non disponibile (None) → comportamento pre-gate, mai bloccare."""
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    monkeypatch.setattr(
        "ingest.promotion._invoke_parser", MagicMock(return_value={"rows_written": -1})
    )
    monkeypatch.setattr("ingest.promotion._count_canonical_rows", lambda t, r: None)

    result = promote_raw_object("raw-1", actor="test")

    assert result.status == "PROMOTED"
    assert result.rows_written == -1
