"""MPS Web Banking 2026 export format.

Repro of pilot bug 2026-05-12: file `ORTI_conto_ultimi12mesi_11maggio.xlsx`
(no banca keyword in filename) failed to be identified as MPS because:
  1. infer_meta keyword lookup misses (no "MPS" in name)
  2. _detect_banca_from_content reads only nrows=5 → header data is at row 19
     (preceded by 18 rows of preamble: Conto / Di / IBAN / Saldo metadata)
  3. dispatch in process_file falls through to read_mps_excel (classic
     Data/Valuta/Dare/Avere schema) → SchemaViolationError → 0 rows written.

Fix: _detect_banca_from_content must scan deeper rows for IBAN regex,
extract ABI → banca via deterministic map; conto suffix distinguishes
MPS principale vs MPS_KROSS for ORTI.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from openpyxl import Workbook


# ── Fixtures ─────────────────────────────────────────────────────────────

def _build_mps_web2026_xlsx(
    tmp_path: Path,
    filename: str = "ORTI_estratto_test.xlsx",
    iban: str = "IT18X0103076230000001194052",  # MPS conto principale ORTI
    intestatario: str = "ORTI SRL",
    rows: list[tuple] | None = None,
) -> Path:
    """Build a minimal MPS Web Banking 2026 XLSX with preamble + header at R19.

    Layout mirrors real pilot file:
      R 1-3: empty
      R 4:   "Lista movimenti" (label in col F)
      R 5:   "Dati al ..."
      R 6-9: empty
      R10:   Conto | <numero>
      R11:   Di    | <ORTI SRL>
      R12:   IBAN  | <IBAN>
      R13:   Saldo disponibile C/C (€) | <num>
      R14:   Non contabilizzati (€)    | <num>
      R15:   Saldo contabile (€)       | <num>
      R16:   Saldo Iniziale (€) | <num>
      R17:   Saldo Finale (€)   | <num>
      R18:   empty
      R19:   DATA CONT. | DATA VAL. | CAUSALE | DESCRIZIONE | (empty) | IMPORTO(€)
      R20+:  data rows
    """
    if rows is None:
        rows = [
            ("2026-05-11", "2026-05-11", "Incasso POS", "Incasso tramite p.o.s.", "", 1888.00),
            ("2026-05-10", "2026-05-10", "Bonifico a tuo favore", "Bonifico per ordine", "", 914.95),
            ("2026-05-09", "2026-05-09", "Addebito Direct Debit", "Addebito diretto.", "", -287.23),
        ]

    f = tmp_path / filename
    wb = Workbook()
    ws = wb.active
    ws.title = "Movimenti"

    # Preamble (col 1 = empty everywhere; data in col 2/3 and label in col 7 in real file)
    ws.cell(row=4, column=7, value="Lista movimenti")
    ws.cell(row=5, column=7, value="Dati al 11/05/26 alle 12:26")

    conto_num = iban[-12:].lstrip("0") or iban[-12:]
    ws.cell(row=10, column=2, value="Conto")
    ws.cell(row=10, column=4, value=f"9330 {conto_num[:5]}")
    ws.cell(row=11, column=2, value="Di")
    ws.cell(row=11, column=4, value=intestatario)
    ws.cell(row=12, column=2, value="IBAN")
    ws.cell(row=12, column=4, value=iban)
    ws.cell(row=13, column=2, value="Saldo disponibile C/C (€)")
    ws.cell(row=13, column=4, value=307880.08)
    ws.cell(row=14, column=2, value="Non contabilizzati (€)")
    ws.cell(row=14, column=4, value=-341.02)
    ws.cell(row=15, column=2, value="Saldo contabile (€)")
    ws.cell(row=15, column=4, value=308221.10)
    ws.cell(row=16, column=2, value="Saldo Iniziale (€)")
    ws.cell(row=16, column=4, value=207207.37)
    ws.cell(row=17, column=2, value="Saldo Finale (€)")
    ws.cell(row=17, column=4, value=308221.10)

    # Header row 19
    headers = ["", "DATA CONT.", "DATA VAL.", "CAUSALE", "DESCRIZIONE", "", "IMPORTO(€)"]
    for ci, h in enumerate(headers, start=1):
        ws.cell(row=19, column=ci, value=h)

    # Data rows
    for ri, row in enumerate(rows, start=20):
        ws.cell(row=ri, column=2, value=row[0])  # DATA CONT.
        ws.cell(row=ri, column=3, value=row[1])  # DATA VAL.
        ws.cell(row=ri, column=4, value=row[2])  # CAUSALE
        ws.cell(row=ri, column=5, value=row[3])  # DESCRIZIONE
        ws.cell(row=ri, column=7, value=row[5])  # IMPORTO

    wb.save(f)
    return f


# ── Tests: _detect_banca_from_content (unit) ─────────────────────────────

def test_detect_mps_from_iban_in_preamble(tmp_path):
    """ABI 01030 in IBAN at R12 → 'MPS' (even though first 5 rows are blank)."""
    f = _build_mps_web2026_xlsx(tmp_path, iban="IT18X0103076230000001194052")

    from ingest.banca.ingest import _detect_banca_from_content
    assert _detect_banca_from_content(f) == "MPS"


def test_detect_mps_kross_from_conto_suffix(tmp_path):
    """ORTI conto 1205058 = MPS_KROSS, distinct from MPS principale 1194052."""
    f = _build_mps_web2026_xlsx(
        tmp_path,
        filename="ORTI_kross_test.xlsx",
        iban="IT99X0103076230000001205058",
    )

    from ingest.banca.ingest import _detect_banca_from_content
    assert _detect_banca_from_content(f) == "MPS_KROSS"


def test_detect_intesa_from_abi(tmp_path):
    """ABI 03069 → INTESA."""
    f = _build_mps_web2026_xlsx(
        tmp_path,
        filename="ORTI_intesa_test.xlsx",
        iban="IT00X0306915216100000010919",
    )

    from ingest.banca.ingest import _detect_banca_from_content
    assert _detect_banca_from_content(f) == "INTESA"


def test_detect_unknown_when_no_iban(tmp_path):
    """No IBAN anywhere → returns None (caller decides fallback)."""
    f = tmp_path / "garbage.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="hello world")
    wb.save(f)

    from ingest.banca.ingest import _detect_banca_from_content
    assert _detect_banca_from_content(f) is None


# ── Tests: backward compat ───────────────────────────────────────────────

def test_classic_mps_columns_still_detected(tmp_path):
    """Old MPS format (Data/Valuta/Dare/Avere header at R1) must still work."""
    f = tmp_path / "MPS_ORTI_classic.xlsx"
    wb = Workbook()
    ws = wb.active
    for ci, h in enumerate(["Data", "Valuta", "Dare", "Avere", "Descrizione operazioni"], 1):
        ws.cell(row=1, column=ci, value=h)
    ws.cell(row=2, column=1, value="2025-01-01")
    ws.cell(row=2, column=2, value="2025-01-01")
    ws.cell(row=2, column=3, value=None)
    ws.cell(row=2, column=4, value=100.0)
    ws.cell(row=2, column=5, value="Bonifico")
    wb.save(f)

    from ingest.banca.ingest import _detect_banca_from_content
    assert _detect_banca_from_content(f) == "MPS"


# ── Test: integration through ingest_single_file ─────────────────────────

def test_orti_no_banca_keyword_writes_rows_via_iban(tmp_path, monkeypatch):
    """End-to-end: filename has no 'MPS' keyword → IBAN preamble must drive
    detection → read_mps2026_excel runs → rows are written with banca_id='MPS'."""
    f = _build_mps_web2026_xlsx(
        tmp_path,
        filename="ORTI_conto_ultimi12mesi_TEST.xlsx",
        iban="IT18X0103076230000001194052",
    )

    captured_dfs: list[pd.DataFrame] = []
    fake_bq = MagicMock()
    fake_load_job = MagicMock()
    fake_load_job.result.return_value = None

    def capture_load(df, table, job_config=None):
        captured_dfs.append(df.copy())
        return fake_load_job

    fake_bq.load_table_from_dataframe.side_effect = capture_load

    monkeypatch.setattr("ingest.banca.ingest.get_client", lambda: fake_bq)
    monkeypatch.setattr("ingest.banca.ingest.load_hashes", lambda _c: set())
    monkeypatch.setattr("ingest.banca.ingest.load_mappings", lambda _p, _l: {})
    # Stub the saldo snapshot upsert (uses a separate BQ flow we don't care about here)
    monkeypatch.setattr(
        "ingest.banca.ingest.upsert_saldo_snapshot", lambda *a, **kw: None
    )

    from ingest.banca.ingest import ingest_single_file

    stats = ingest_single_file(
        file_path=f,
        raw_object_id="raw-pilot-test",
        societa="ORTI",
        dry_run=False,
    )

    assert stats["written"] >= 1, (
        f"expected ≥1 row from 3 fixture rows, got stats={stats}. "
        f"IBAN-based bank detection probably did not fire."
    )
    assert len(captured_dfs) == 1
    df = captured_dfs[0]
    assert (df["banca_id"] == "MPS").all(), (
        f"banca_id should be 'MPS' (ABI 01030), got {df['banca_id'].unique()}"
    )
    assert (df["raw_object_id"] == "raw-pilot-test").all()
