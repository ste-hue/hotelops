"""Regression: saldo snapshot upsert must not use streaming inserts.

Bug 2026-05-13/16: ingest/banca/ingest.py::upsert_saldo_snapshot wrote
f_saldi_banca_snapshot via insert_rows_json (streaming). Rows in the
streaming buffer can't be DELETEd by DML for ~90 min, so the best-effort
DELETE silently skipped and re-runs accumulated duplicates (3 copies each
for ORTI MPS/MPS_KROSS and INTUR MPS on 2026-04-20 / 2026-05-01).

Fix: route through bq_write_validated(mode="snapshot") — load job, no
streaming buffer, surgical DELETE-INSERT.
"""

import logging
from unittest.mock import MagicMock

from core.schemas import SaldoBancaSnapshotRow


def test_upsert_saldo_snapshot_uses_validated_gate_not_streaming(monkeypatch):
    """upsert_saldo_snapshot must write via bq_write_validated snapshot mode,
    never via the streaming insert_rows_json API (the duplicate-bug root cause)."""
    calls = []
    monkeypatch.setattr(
        "core.bq.write.bq_write_validated",
        lambda table, rows, **kw: calls.append((table, rows, kw)),
    )

    fake_bq = MagicMock()
    from ingest.banca.ingest import upsert_saldo_snapshot

    snapshot = {
        "societa_id": "ORTI",
        "banca_id": "MPS",
        "data_snapshot": "2026-05-01",
        "saldo_finale": 251897.54,
    }
    upsert_saldo_snapshot(
        fake_bq, snapshot, dry_run=False, logger=logging.getLogger("test")
    )

    fake_bq.insert_rows_json.assert_not_called()
    assert len(calls) == 1
    _table, rows, kw = calls[0]
    assert kw["mode"] == "snapshot"
    assert kw["natural_key"] == ["societa_id", "banca_id", "data_snapshot"]
    assert len(rows) == 1 and isinstance(rows[0], SaldoBancaSnapshotRow)
    assert rows[0].data_snapshot.isoformat() == "2026-05-01"
    assert rows[0].saldo_finale == 251897.54
