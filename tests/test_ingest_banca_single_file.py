"""Single-file invocation mode for ingest.banca.ingest.

Required by promote_raw_object subprocess contract:
  python -m ingest.banca.ingest --file <path> --raw-object-id <id> --societa <code>
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _fake_csv_sella(tmp_path: Path) -> Path:
    """Minimal Sella CSV that infer_meta + process_file can swallow.

    Uses Sella format because process_file routes all .csv files through
    read_sella_csv (CSV router is format-agnostic by extension, not by banca).
    Columns must satisfy SELLA_REQUIRED_COLUMNS exactly.
    """
    f = tmp_path / "SELLA_ORTI_2026_05.csv"
    f.write_text(
        "Codice identificativo,Data operazione,Data valuta,Descrizione,Divisa,Debito,Credito,Categoria,Sottocategoria,Etichette,Note\n"
        "TXN001,01/05/2026,01/05/2026,BONIFICO TEST,EUR,,100.00,ENTRATE,,,\n",
        encoding="utf-8",
    )
    return f


def test_single_file_mode_stamps_raw_object_id(tmp_path, monkeypatch):
    """When invoked with --file + --raw-object-id, every written row carries the FK."""
    f = _fake_csv_sella(tmp_path)

    captured_dfs: list[pd.DataFrame] = []

    fake_bq = MagicMock()
    fake_load_job = MagicMock()
    fake_load_job.result.return_value = None

    def capture_load(df, table, job_config=None):
        captured_dfs.append(df.copy())
        return fake_load_job

    fake_bq.load_table_from_dataframe.side_effect = capture_load

    # Patch the BQ client used by ingest_banca and disable hash dedup.
    monkeypatch.setattr("ingest.banca.ingest.get_client", lambda: fake_bq)
    monkeypatch.setattr("ingest.banca.ingest.load_hashes", lambda _client: set())
    # Mappings: empty dict path — parser must tolerate.
    monkeypatch.setattr("ingest.banca.ingest.load_mappings", lambda _path, _logger: {})

    from ingest.banca.ingest import ingest_single_file

    stats = ingest_single_file(
        file_path=f,
        raw_object_id="raw-pilot-1",
        societa="ORTI",
        dry_run=False,
    )

    assert stats["written"] >= 1, f"expected ≥1 row, got stats={stats}"
    assert len(captured_dfs) == 1
    df = captured_dfs[0]
    assert "raw_object_id" in df.columns
    assert (df["raw_object_id"] == "raw-pilot-1").all()


def test_single_file_mode_dry_run_no_write(tmp_path, monkeypatch):
    f = _fake_csv_sella(tmp_path)

    fake_bq = MagicMock()
    monkeypatch.setattr("ingest.banca.ingest.get_client", lambda: fake_bq)
    monkeypatch.setattr("ingest.banca.ingest.load_hashes", lambda _c: set())
    monkeypatch.setattr("ingest.banca.ingest.load_mappings", lambda _p, _l: {})

    from ingest.banca.ingest import ingest_single_file

    stats = ingest_single_file(
        file_path=f,
        raw_object_id="raw-pilot-1",
        societa="ORTI",
        dry_run=True,
    )

    assert stats["written"] == 0
    fake_bq.load_table_from_dataframe.assert_not_called()
