"""Tests per il layout 'saldi Dare/Avere' di ingest_bilancino (terzo layout Esolver)
e per la scrittura SNAPSHOT via bq_write_validated (I1, #152)."""

import logging
import sys
from unittest.mock import MagicMock

import openpyxl
import pytest
from pydantic import ValidationError

from core.schemas import BilancinoRow
from ingest.flussi.ingest_bilancino import main, parse_bilancino

logger = logging.getLogger("test_ingest_bilancino")

HDR_5COL = ["Conto", "Partitari", "Descrizione", "Saldo finale\nDare", "Saldo finale\nAvere"]
HDR_11COL = HDR_5COL + [
    "Progressivi annui\nSaldo iniziale", "Progressivi annui\nDare", "Progressivi annui\nAvere",
    "Progressivi periodici\nDare", "Progressivi periodici\nAvere", "Progressivi periodici\nSaldo periodo",
]


def _make_xlsx(tmp_path, header, rows, name="saldi.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    p = tmp_path / name
    wb.save(p)
    return p


def test_saldi_5col_leaves_and_signs(tmp_path):
    p = _make_xlsx(tmp_path, HDR_5COL, [
        ["05", None, "IMMOBILIZZAZIONI MATERIALI", 100.0, None],       # gruppo: escluso
        ["    05.01", None, "TERRENI E FABBRICATI", 100.0, None],       # gruppo: escluso
        ["        05.01.07", "S", "Fabbricati strumentali", 100.0, None],
        ["47", None, "RICAVI", None, 200.0],
        ["    47.91", None, "Ricavi Hotel", None, 200.0],
        ["        47.91.01", None, "Ricavi per alloggi", None, 200.0],  # leaf CE senza marker
    ])
    rows = parse_bilancino(p, "ORTI", "2026-06", logger)
    by_code = {r["codice_conto"]: r for r in rows}
    assert set(by_code) == {"05.01.07", "47.91.01"}
    sp = by_code["05.01.07"]
    assert sp["tipo_conto"] == "SP" and sp["sezione"] == ""
    assert sp["saldo"] == 100.0 and sp["dare"] == 100.0 and sp["avere"] == 0.0
    ce = by_code["47.91.01"]
    assert ce["tipo_conto"] == "CE" and ce["sezione"] == "Ricavi"
    assert ce["saldo"] == -200.0  # saldo = dare − avere: ricavi negativi
    assert ce["categoria"] == "RICAVI" and ce["business_unit_id"] == "HOTEL"


def test_saldi_11col_reads_saldo_finale_not_progressivi(tmp_path):
    p = _make_xlsx(tmp_path, HDR_11COL, [
        ["57", None, "SERVIZI", None, None, 0, 0, 0, 0, 0, 0],
        ["    57.01", None, "Costi tel", 300.0, None, 9, 9, 9, 9, 9, 9],  # leaf: Progressivi ≠ Saldo finale
    ])
    rows = parse_bilancino(p, "ORTI", "2026-04", logger)
    assert len(rows) == 1
    r = rows[0]
    assert r["codice_conto"] == "57.01" and r["saldo"] == 300.0
    assert r["tipo_conto"] == "CE" and r["sezione"] == "Costi" and r["categoria"] == "COSTI"


def test_saldi_zero_rows_skipped_and_89_is_sp(tmp_path):
    p = _make_xlsx(tmp_path, HDR_5COL, [
        ["61.01", None, "Conto a zero", None, None],       # entrambi vuoti: escluso
        ["89.01", None, "Conti transitori", 50.0, None],   # 89 = SP (come storico BQ)
    ])
    rows = parse_bilancino(p, "INTUR", "2026-03", logger)
    assert len(rows) == 1
    assert rows[0]["codice_conto"] == "89.01" and rows[0]["tipo_conto"] == "SP"


def test_saldi_53_is_ricavi(tmp_path):
    p = _make_xlsx(tmp_path, HDR_5COL, [
        ["53", None, "ALTRI RICAVI E PROVENTI", None, 500.0],
        ["    53.01.51", None, "Altri ricavi e proventi", None, 500.0],
    ])
    rows = parse_bilancino(p, "INTUR", "2026-06", logger)
    assert len(rows) == 1
    r = rows[0]
    assert r["codice_conto"] == "53.01.51"
    assert r["tipo_conto"] == "CE" and r["sezione"] == "Ricavi"
    assert r["saldo"] == -500.0  # saldo negativo, mostrabile positivo lato renderer


def test_grid_layout_still_dispatched(tmp_path):
    # guardia di regressione: il branch griglia resta attivo
    p = _make_xlsx(tmp_path, ["Codice conto", "Descrizione conto", "Livello di imputazione bilancio", "Importo colonna 1"], [
        ["05.01.07", "Fabbricati", "Si", 100.0],
        ["05.01", "Terreni", "No", 100.0],
    ])
    rows = parse_bilancino(p, "ORTI", "2026-01", logger)
    assert [r["codice_conto"] for r in rows] == ["05.01.07"]


# ── Scrittura: SNAPSHOT via bq_write_validated (I1, #152) ─────────────────────
# Prima: append + dedup per hash → ri-promuovere un mese pieno sopra un parziale
# lasciava le righe stale (due DELETE manuali, 25/09 e 16/10). Ora il gate
# cancella l'intero scope (societa_id, mese) e ricarica tutte le righe del file.


@pytest.fixture
def bq_client(monkeypatch):
    """Client BQ mock dietro il gate; PipelineRun senza scrittura su f_pipeline_runs."""
    monkeypatch.setattr(
        "core.pipeline_run.PipelineRun._insert_final", lambda self: None
    )
    client = MagicMock()
    client.load_table_from_json.return_value.result.return_value = None
    monkeypatch.setattr("core.bq.write.get_client", lambda: client)
    return client


def _run_main(monkeypatch, path, *extra):
    argv = [
        "ingest_bilancino",
        "--file",
        str(path),
        "--societa",
        "ORTI",
        "--raw-object-id",
        "raw-42",
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    main()


def test_write_replaces_whole_societa_mese_scope(tmp_path, monkeypatch, bq_client):
    p = _make_xlsx(
        tmp_path,
        HDR_5COL,
        [
            ["        05.01.07", "S", "Fabbricati strumentali", 100.0, None],
            ["        47.91.01", None, "Ricavi per alloggi", None, 200.0],
        ],
        name="SETTEMBRE2026ESOLVER.xlsx",
    )  # mese inferito dal filename
    _run_main(monkeypatch, p)

    delete_sql = bq_client.query.call_args.args[0]
    assert delete_sql.startswith("DELETE FROM `hotelops-suite.hotelops.f_bilancino`")
    assert "(societa_id, mese) IN" in delete_sql and "('ORTI', '2026-09')" in delete_sql
    assert (
        "codice_conto" not in delete_sql
    )  # scope = il mese intero, non le sole righe del file

    loaded = bq_client.load_table_from_json.call_args.args[0]
    assert {r["codice_conto"] for r in loaded} == {"05.01.07", "47.91.01"}
    assert all(
        r["raw_object_id"] == "raw-42" and r["mese"] == "2026-09" for r in loaded
    )


def test_dry_run_does_not_touch_bq(tmp_path, monkeypatch, bq_client):
    p = _make_xlsx(tmp_path, HDR_5COL, [["05.01.07", "S", "Fabbricati", 100.0, None]])
    _run_main(monkeypatch, p, "--mese", "2026-09", "--dry-run")
    bq_client.query.assert_not_called()
    bq_client.load_table_from_json.assert_not_called()


def test_empty_parse_does_not_delete_existing_month(tmp_path, monkeypatch, bq_client):
    # Nessuna riga foglia con movimenti → nessuna DELETE: il mese già in BQ resta intatto.
    p = _make_xlsx(tmp_path, HDR_5COL, [["61.01", None, "Conto a zero", None, None]])
    _run_main(monkeypatch, p, "--mese", "2026-09")
    bq_client.query.assert_not_called()
    bq_client.load_table_from_json.assert_not_called()


def test_bilancino_row_rejects_mese_non_yyyy_mm():
    with pytest.raises(ValidationError):
        BilancinoRow(hash_riga="h", societa_id="ORTI", mese="2026-9", codice_conto="05.01")
