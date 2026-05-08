"""Regression tests for ingest.flussi.ingest_movimenti_contabili."""

import logging

import pytest


def _legacy_row(date_cell):
    """Build a minimal legacy XLS row with expected column positions."""
    row = [""] * 26
    row[0] = 1001.0  # id_documento
    row[1] = 1.0  # id_movimento
    row[2] = 1.0  # num_progr_riga
    row[3] = "PNC"
    row[4] = 2026.0
    row[5] = 2.0
    row[6] = date_cell
    row[7] = "PNC"
    row[8] = "RIF-1"
    row[9] = "DOC-1"
    row[10] = date_cell
    row[11] = "TIPO"
    row[12] = "330301"
    row[13] = "1152"
    row[15] = "ROVIELLO S.R.L."
    row[18] = "Pagamento con Bonifico SEPA FT 678"
    row[20] = 452.74
    row[21] = 0.0
    row[25] = "DIV-1"
    return row


def test_parse_file_skips_rows_with_missing_data_reg(monkeypatch, tmp_path):
    from ingest.flussi import ingest_movimenti_contabili as mod

    class _Sheet:
        def __init__(self):
            self._rows = [["header"] * 26, _legacy_row("BAD"), _legacy_row("GOOD")]
            self.nrows = len(self._rows)

        def row_values(self, idx):
            return self._rows[idx]

    class _Book:
        def sheets(self):
            return [_Sheet()]

    monkeypatch.setattr(mod, "HAS_XLRD", True)
    class _XlrdStub:
        @staticmethod
        def open_workbook(_):
            return _Book()

    monkeypatch.setattr(mod, "xlrd", _XlrdStub, raising=False)
    monkeypatch.setattr(
        mod, "xl_date", lambda v: None if v == "BAD" else "2026-02-26"
    )

    rows = mod.parse_file(tmp_path / "fake.xls", "ORTI", logging.getLogger("test"))
    assert len(rows) == 1
    assert rows[0]["data_registrazione"] == "2026-02-26"


def test_main_passes_raw_object_id_to_process_societa(monkeypatch):
    from ingest.flussi import ingest_movimenti_contabili as mod

    captured = {}

    def _fake_process_societa(
        societa_id,
        files,
        datahub,
        bq_client,
        dry_run,
        replace,
        raw_object_id,
        logger,
    ):
        captured["societa_id"] = societa_id
        captured["raw_object_id"] = raw_object_id
        captured["files"] = files

    monkeypatch.setattr(mod, "process_societa", _fake_process_societa)
    monkeypatch.setattr(
        mod,
        "setup_logger",
        lambda: logging.getLogger("test_ingest_movimenti_contabili_main"),
    )
    monkeypatch.setattr(
        mod.sys,
        "argv",
        [
            "prog",
            "--file",
            "/tmp/fake.xls",
            "--societa",
            "ORTI",
            "--dry-run",
            "--raw-object-id",
            "raw-pilot-1",
        ],
    )

    mod.main()
    assert captured["societa_id"] == "ORTI"
    assert captured["raw_object_id"] == "raw-pilot-1"


def test_make_hash_content_rejects_missing_data_reg():
    from ingest.flussi import ingest_movimenti_contabili as mod

    with pytest.raises(ValueError, match="data_reg_iso"):
        mod.make_hash_content("ORTI", None, "330301", 10.0, 0.0, "causale")


def test_process_societa_stamps_raw_object_id_on_written_rows(monkeypatch, tmp_path):
    from ingest.flussi import ingest_movimenti_contabili as mod

    file_path = tmp_path / "fake.xls"
    file_path.write_text("x")
    captured = {}

    def _fake_parse_file(filepath, societa_id, logger):
        return [
            {
                "hash_riga": "h1",
                "societa_id": societa_id,
                "id_documento": 1001,
                "num_progr_riga": 1,
                "gruppo_doc": "PNC",
                "anno": 2026,
                "mese": 2,
                "data_registrazione": "2026-02-26",
                "sigla_doc": "PNC",
                "rif_registrazione": "RIF-1",
                "num_doc_originale": "DOC-1",
                "data_originale": "2026-02-26",
                "tipo_documento": "TIPO",
                "cod_conto": "330301",
                "cod_partitario": "1152",
                "rag_sociale": "ROVIELLO S.R.L.",
                "causale_contabile": "Pagamento",
                "imp_dare": 452.74,
                "imp_avere": 0.0,
                "cod_divisione": "DIV-1",
                "file_sorgente": filepath.name,
                "data_ingresso": "2026-05-08",
            }
        ]

    def _fake_write_to_bq(rows, bq_client, logger):
        captured["rows"] = rows

    monkeypatch.setattr(mod, "parse_file", _fake_parse_file)
    monkeypatch.setattr(mod, "load_hashes_bq", lambda *_: set())
    monkeypatch.setattr(mod, "write_to_bq", _fake_write_to_bq)

    mod.process_societa(
        societa_id="ORTI",
        files=[file_path],
        datahub=None,
        bq_client=object(),
        dry_run=False,
        replace=False,
        raw_object_id="raw-pilot-1",
        logger=logging.getLogger("test"),
    )

    assert captured["rows"][0]["raw_object_id"] == "raw-pilot-1"
