# Raw Object FK + Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the lineage chain by stamping `raw_object_id` on every promoted row of `f_banche_movimenti`, make the MPS parser actually invokable as a single-file (debt nascosto scoperto durante design), and ship universal observability tools (`hotelops lineage list` CLI + `v_raw_promotion_status` view) that work for all sources, not just the pilot.

**Architecture:**

- **Pilot scope (B1)**: only `f_banche_movimenti` gets the new FK column; only `ingest.banca.ingest` gets the single-file mode. Other 11+ fact tables stay untouched (Karpathy "surgical changes" — flip on-demand quando il loop le chiama).
- **Universal scope**: CLI `lineage list` and view `v_raw_promotion_status` query `v_raw_objects_current` directly, so they cover every source without further changes.
- **Migration pattern**: copy the idempotent INFORMATION_SCHEMA-probe pattern from `core/bq/migrations/2026_05_05_add_gcs_generation.py`.
- **Subprocess contract**: `promote_raw_object` already passes `--file <local_path>` and optionally `--societa <code>`. We extend it with `--raw-object-id <id>`. Parser receives the ID, stamps it on every row before write.

**Tech Stack:** Python 3.11+, Pydantic v2, BigQuery (`bq_write_validated` gate), pandas (existing parser uses `load_table_from_dataframe`), pytest, click-style argparse (existing convention).

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `core/bq/migrations/2026_05_06_add_raw_object_id_f_banche_movimenti.py` | create | Idempotent ALTER TABLE add column NULLABLE |
| `core/schemas.py` (lines 135-166) | modify | `BancaMovimentoRow.raw_object_id: Optional[str] = None` |
| `ingest/banca/ingest.py` (lines 79-106 FACT_HEADER, 800-880 process_file, 890-955 main) | modify | Add `raw_object_id` to FACT_HEADER + plumb through `process_file` + add single-file mode (`--file`, `--raw-object-id`, `--societa`) |
| `ingest/promotion.py` (lines 85-88) | modify | Pass `--raw-object-id <id>` in subprocess cmd |
| `core/bq/views/v_raw_promotion_status.sql` | create | Per source × status count |
| `core/bq/load/load_v_raw_promotion_status.py` | create | Materialize the view (follows existing view-loader pattern) |
| `cli.py` (lines 508-560 cmd_lineage area) | modify | Extend `hotelops lineage` with `list` subcommand: `--status`, `--source`, `--limit`, `--days` |
| `tests/test_ingest_banca_single_file.py` | create | Single-file mode parses one file + stamps raw_object_id |
| `tests/test_promote_raw_object_id_handoff.py` | create | Promotion subprocess receives raw_object_id and parser writes it |
| `tests/test_lineage_list_cli.py` | create | CLI list filters work correctly |
| `tests/test_v_raw_promotion_status.py` | create | View returns expected schema (smoke) |

---

## Task 1: BQ migration — add `raw_object_id` to `f_banche_movimenti`

**Files:**
- Create: `core/bq/migrations/2026_05_06_add_raw_object_id_f_banche_movimenti.py`

- [ ] **Step 1: Write the migration script (no test — mirrors existing migration; verify with INFORMATION_SCHEMA after run)**

```python
"""One-shot migration: ALTER TABLE f_banche_movimenti ADD COLUMN raw_object_id STRING.

Idempotent: probes column existence via INFORMATION_SCHEMA before altering.
NULLABLE so historical rows (pre-Phase-4-FK) stay valid.
Run: python -m core.bq.migrations.2026_05_06_add_raw_object_id_f_banche_movimenti
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = "f_banche_movimenti"
COLUMN = "raw_object_id"


def column_exists() -> bool:
    from core.bq.client import get_client

    client = get_client()
    sql = f"""
    SELECT 1
    FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}'
    """
    return any(client.query(sql).result())


def run(dry_run: bool = False) -> None:
    if column_exists():
        log.info("Column %s.%s.%s already exists — no-op.", DATASET, TABLE, COLUMN)
        return

    sql = (
        f"ALTER TABLE `{PROJECT}.{DATASET}.{TABLE}` "
        f"ADD COLUMN {COLUMN} STRING "
        f'OPTIONS(description="FK to f_raw_objects.raw_object_id; NULL for pre-Phase-4-FK historical rows")'
    )
    if dry_run:
        log.info("[DRY RUN] would execute: %s", sql)
        return

    from core.bq.client import get_client

    client = get_client()
    client.query(sql).result()
    log.info("ALTER TABLE complete: added %s.%s.%s", DATASET, TABLE, COLUMN)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run to verify SQL**

Run: `python -m core.bq.migrations.2026_05_06_add_raw_object_id_f_banche_movimenti --dry-run`
Expected: `INFO: [DRY RUN] would execute: ALTER TABLE ... ADD COLUMN raw_object_id STRING ...`

- [ ] **Step 3: Apply to BQ production**

Run: `python -m core.bq.migrations.2026_05_06_add_raw_object_id_f_banche_movimenti`
Expected: `INFO: ALTER TABLE complete: added hotelops.f_banche_movimenti.raw_object_id`

- [ ] **Step 4: Verify column exists**

Run:
```bash
bq query --use_legacy_sql=false --format=pretty \
  'SELECT column_name, data_type, is_nullable FROM `hotelops-suite.hotelops.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = "f_banche_movimenti" AND column_name = "raw_object_id"'
```
Expected: 1 row, `raw_object_id | STRING | YES`

- [ ] **Step 5: Re-run migration to verify idempotency**

Run: `python -m core.bq.migrations.2026_05_06_add_raw_object_id_f_banche_movimenti`
Expected: `INFO: Column hotelops.f_banche_movimenti.raw_object_id already exists — no-op.`

- [ ] **Step 6: Commit**

```bash
git add core/bq/migrations/2026_05_06_add_raw_object_id_f_banche_movimenti.py
git commit -m "$(cat <<'EOF'
feat(lineage): migration — f_banche_movimenti.raw_object_id STRING NULLABLE

Additive FK column to close the lineage chain (canonical row → raw blob).
Idempotent INFORMATION_SCHEMA probe. Applied to BQ production.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pydantic schema — `BancaMovimentoRow.raw_object_id`

**Files:**
- Modify: `core/schemas.py:135-166`
- Test: `tests/test_schemas.py` (add a test if not present, otherwise extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_schemas.py` (create if missing — minimal stub):

```python
def test_banca_movimento_row_accepts_raw_object_id():
    from core.schemas import BancaMovimentoRow
    from datetime import date

    row = BancaMovimentoRow(
        hash_riga="abc",
        societa_id="ORTI",
        banca_id="MPS",
        data_operazione=date(2026, 5, 1),
        importo_netto=100.0,
        file_sorgente="test.csv",
        raw_object_id="raw-uuid-1",
    )
    assert row.raw_object_id == "raw-uuid-1"


def test_banca_movimento_row_raw_object_id_optional():
    from core.schemas import BancaMovimentoRow
    from datetime import date

    row = BancaMovimentoRow(
        hash_riga="abc",
        societa_id="ORTI",
        banca_id="MPS",
        data_operazione=date(2026, 5, 1),
        importo_netto=100.0,
        file_sorgente="test.csv",
    )
    assert row.raw_object_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py::test_banca_movimento_row_accepts_raw_object_id -v`
Expected: FAIL — `TypeError` or `ValidationError` on unexpected keyword `raw_object_id`.

- [ ] **Step 3: Add the field to BancaMovimentoRow**

Edit `core/schemas.py` — find the `BancaMovimentoRow` class (around line 135) and add at the end of the field list (after `riga_sorgente`):

```python
    riga_sorgente: Optional[int] = None
    # FK to f_raw_objects.raw_object_id (Phase 4 FK — pilot on banca).
    raw_object_id: Optional[str] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schemas.py -v -k raw_object_id`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/schemas.py tests/test_schemas.py
git commit -m "$(cat <<'EOF'
feat(lineage): BancaMovimentoRow.raw_object_id Optional[str]

Pydantic side of the FK. NULLABLE: pre-FK historical rows stay valid.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `ingest_banca` single-file mode — `--file` + `--raw-object-id` + `--societa`

**Context:** Today `ingest.banca.ingest` only runs in batch mode (`--datahub <root> --source <folder>`). Promotion subprocess invokes it with `--file <local>` + `--societa <code>`, which today **fails argparse** — meaning no MPS file has ever actually been promoted end-to-end. This task adds the single-file invocation mode that promotion needs and stamps `raw_object_id` on each written row.

**Files:**
- Modify: `ingest/banca/ingest.py` (FACT_HEADER, transform, process_file, main)
- Test: `tests/test_ingest_banca_single_file.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_banca_single_file.py`:

```python
"""Single-file invocation mode for ingest.banca.ingest.

Required by promote_raw_object subprocess contract:
  python -m ingest.banca.ingest --file <path> --raw-object-id <id> --societa <code>
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _fake_csv_mps(tmp_path: Path) -> Path:
    """Minimal MPS CSV that infer_meta + process_file can swallow."""
    f = tmp_path / "MPS_ORTI_HOMEBANKING_2026_05.csv"
    # Schema kept minimal — see ingest_banca for full expected columns;
    # if your MPS parser needs more, extend this fixture.
    f.write_text(
        "Data;Valuta;Descrizione;Importo;Divisa\n"
        "01/05/2026;01/05/2026;BONIFICO TEST;100,00;EUR\n",
        encoding="utf-8",
    )
    return f


def test_single_file_mode_stamps_raw_object_id(tmp_path, monkeypatch):
    """When invoked with --file + --raw-object-id, every written row carries the FK."""
    f = _fake_csv_mps(tmp_path)

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
    f = _fake_csv_mps(tmp_path)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_banca_single_file.py -v`
Expected: FAIL with `ImportError: cannot import name 'ingest_single_file'`.

- [ ] **Step 3: Add `raw_object_id` to FACT_HEADER**

Edit `ingest/banca/ingest.py` — find FACT_HEADER (around line 79) and append at the end:

```python
FACT_HEADER = [
    "id_movimento",
    "societa_id",
    "business_unit_id",
    "funzione_id",
    "location_id",
    "oggetto_id",
    "banca_id",
    "data_operazione",
    "data_valuta",
    "descrizione",
    "divisa",
    "importo_debito",
    "importo_credito",
    "importo_netto",
    "categoria_raw",
    "sottocategoria_raw",
    "categoria_normalizzata",
    "sottocategoria_normalizzata",
    "tipo_movimento",
    "codice_identificativo_banca",
    "etichette",
    "note",
    "data_ingresso",
    "file_sorgente",
    "riga_sorgente",
    "hash_riga",
    "raw_object_id",
]
```

- [ ] **Step 4: Plumb `raw_object_id` into `process_file`**

Edit `ingest/banca/ingest.py:799-807` — extend the `process_file` signature with a final keyword-only parameter:

```python
def process_file(
    filepath: Path,
    bq_client: bigquery.Client,
    mappings: dict,
    hashes: set,
    logger: logging.Logger,
    dry_run: bool = False,
    meta: dict = None,
    raw_object_id: Optional[str] = None,
) -> dict:
```

Inside the row-construction loop (around line 849-858), `transform` (defined at line 726, returns a `dict`) builds `fact`. After the existing `fact = transform(raw, meta, i)` line, add:

```python
        fact["raw_object_id"] = raw_object_id
```

This stamps the FK on every row dict appended to `new_rows`. When called from batch mode (`main()`) without the kwarg, it defaults to `None` — historical batch ingestion paths stay backward-compatible.

- [ ] **Step 5: Add the single-file entrypoint**

Edit `ingest/banca/ingest.py` — add a new function above `def main()`:

```python
def ingest_single_file(
    file_path: Path,
    raw_object_id: str,
    societa: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Single-file ingestion path used by promote_raw_object.

    Differs from main() batch mode: caller already resolved the file (downloaded
    from GCS to temp by promotion), no datahub folder needed for mappings (we
    use an empty mapping dict — promote contract assumes the parser tolerates
    no-mapping for unmapped descriptors). Caller passes raw_object_id which is
    stamped on every row.
    """
    from core.bq.client import get_client

    bq_client = get_client()
    mappings: dict = {}  # promote contract: no datahub access
    hashes = load_hashes(bq_client)

    meta = infer_meta(file_path)
    if "UNKNOWN" in meta["societa_banca"] and societa:
        # Override inferred societa from CLI flag when fname doesn't carry it.
        meta["societa_banca"] = meta["societa_banca"].replace("UNKNOWN", societa)

    logger = logging.getLogger("ingest.banca.single_file")
    return process_file(
        file_path,
        bq_client,
        mappings,
        hashes,
        logger,
        dry_run,
        meta=meta,
        raw_object_id=raw_object_id,
    )
```

(Adapt `Optional` import from typing if not already present; check existing imports.)

- [ ] **Step 6: Add CLI args for single-file mode in `main()`**

Edit `ingest/banca/ingest.py` — extend the argparse in `main()` (around line 891):

```python
def main():
    parser = argparse.ArgumentParser(description="Bank transaction ingestion")
    # Batch mode (existing):
    parser.add_argument(
        "--datahub", help="Path to datahub root (batch mode — for mappings and logs)"
    )
    parser.add_argument(
        "--source", "-s", help="Staging folder from rclone sync (batch mode default)"
    )
    # Single-file mode (new — used by promote subprocess):
    parser.add_argument(
        "--file", help="Single file to ingest (used by promotion path)"
    )
    parser.add_argument(
        "--raw-object-id", help="Raw object ID to stamp on rows (single-file mode)"
    )
    parser.add_argument(
        "--societa", choices=["ORTI", "INTUR"],
        help="Societa override for single-file mode when filename doesn't carry it",
    )
    parser.add_argument("--project", default=PROJECT, help="GCP project")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Single-file mode (promotion path)
    if args.file:
        if not args.raw_object_id:
            print("ERROR: --file requires --raw-object-id", file=sys.stderr)
            sys.exit(2)
        stats = ingest_single_file(
            file_path=Path(args.file),
            raw_object_id=args.raw_object_id,
            societa=args.societa,
            dry_run=args.dry_run,
        )
        print(
            f"single-file: {stats.get('total', 0)} total, "
            f"{stats.get('written', 0)} written, {stats.get('dupes', 0)} dupes"
        )
        return

    # Batch mode (existing — keep behavior unchanged)
    if not args.datahub:
        print("ERROR: batch mode requires --datahub", file=sys.stderr)
        sys.exit(2)

    # ... rest of existing main() body unchanged below this line ...
```

(Move the existing `main()` body that follows under `# Batch mode` — the `datahub = Path(args.datahub) ...` block and downstream. Don't duplicate logic.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_ingest_banca_single_file.py -v`
Expected: 2 passed.

- [ ] **Step 8: Re-run the existing banca test suite to verify no regression**

Run: `pytest tests/ -v -k 'banca or ingest'` (or whatever scope covers the existing parser tests)
Expected: previous green count maintained (no failures introduced by FACT_HEADER change).

If a test fails because it constructs rows without `raw_object_id`: add the column with default `None` in the test fixture or update FACT_HEADER consumers to tolerate missing key. Fix until green before commit.

- [ ] **Step 9: Commit**

```bash
git add ingest/banca/ingest.py tests/test_ingest_banca_single_file.py
git commit -m "$(cat <<'EOF'
feat(banca): single-file mode + raw_object_id stamping

Adds ingest_single_file() entrypoint required by promote_raw_object subprocess
contract (--file + --raw-object-id + --societa). Every written row carries
raw_object_id FK to f_raw_objects.

Closes hidden debt: ingest.banca.ingest only ran in batch mode (--datahub
+ --source folder), so the promotion path never actually worked end-to-end
for MPS even after Phase 4 GCS staging.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `promote_raw_object` passes `--raw-object-id` to subprocess

**Files:**
- Modify: `ingest/promotion.py:85-88` (the `_invoke_parser` cmd builder)
- Test: `tests/test_promote_raw_object_id_handoff.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_promote_raw_object_id_handoff.py`:

```python
"""Promote subprocess receives --raw-object-id and parser stamps it.

Verifies the subprocess command line includes --raw-object-id <id>.
End-to-end stamping into f_banche_movimenti is covered separately via
production smoke (Task 5 verify step), not here (avoids BQ dependency).
"""

from unittest.mock import MagicMock, patch


def test_invoke_parser_passes_raw_object_id_in_cmd(monkeypatch):
    """_invoke_parser must include --raw-object-id <id> in the subprocess cmd."""
    captured_cmds: list[list[str]] = []

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stderr = ""

    def capture_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        return fake_proc

    monkeypatch.setattr("ingest.promotion.subprocess.run", capture_run)

    from ingest.promotion import _invoke_parser

    fake_source = MagicMock()
    fake_source.societa = "ORTI"

    _invoke_parser(
        parser_module="ingest.banca.ingest",
        raw_uri="file:///tmp/fake.csv",
        source_def=fake_source,
        gcs_generation=None,
        raw_object_id="raw-pilot-1",
    )

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert "--raw-object-id" in cmd
    idx = cmd.index("--raw-object-id")
    assert cmd[idx + 1] == "raw-pilot-1"
    assert "--file" in cmd
    assert "--societa" in cmd and cmd[cmd.index("--societa") + 1] == "ORTI"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_promote_raw_object_id_handoff.py -v`
Expected: FAIL — `_invoke_parser` doesn't accept `raw_object_id` kwarg.

- [ ] **Step 3: Update `_invoke_parser` signature + cmd builder**

Edit `ingest/promotion.py` — modify `_invoke_parser` signature and cmd construction:

```python
def _invoke_parser(
    parser_module: str,
    raw_uri: str,
    source_def,
    gcs_generation: Optional[int] = None,
    raw_object_id: Optional[str] = None,
) -> dict:
    """Invoke the parser via subprocess.

    file:// → pass parsed path directly.
    gs://   → download to temp, pass temp path, cleanup on exit.
    raw_object_id (when provided) → stamped on canonical rows for FK lineage.
    """
    from urllib.parse import urlparse

    parsed = urlparse(raw_uri)
    backend = None
    cleanup_path: Optional[str] = None

    if parsed.scheme == "gs":
        bucket = parsed.netloc
        backend = GCSBackend(bucket=bucket)
        local_path = backend.download_to_temp(raw_uri, generation=gcs_generation)
        cleanup_path = local_path
    elif parsed.scheme in ("file", ""):
        local_path = parsed.path
    else:
        raise NotImplementedError(
            f"Unsupported raw_uri scheme {parsed.scheme!r}: {raw_uri}"
        )

    cmd = [sys.executable, "-m", parser_module, "--file", local_path]
    if source_def.societa in ("ORTI", "INTUR"):
        cmd += ["--societa", source_def.societa]
    if raw_object_id:
        cmd += ["--raw-object-id", raw_object_id]

    log.info("Invoking parser: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Parser {parser_module} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
        return {"rows_written": -1}
    finally:
        if backend is not None and cleanup_path is not None:
            try:
                backend.cleanup(cleanup_path)
            except Exception as e:
                log.warning("Cleanup of temp %s failed: %s", cleanup_path, e)
```

- [ ] **Step 4: Update the call site in `promote_raw_object`**

Edit `ingest/promotion.py` — at the `_invoke_parser` call (around line 168):

```python
            parser_result = _invoke_parser(
                source_def.parser_module,
                raw.raw_uri,
                source_def,
                gcs_generation=getattr(raw, "gcs_generation", None),
                raw_object_id=raw_object_id,
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_promote_raw_object_id_handoff.py -v`
Expected: PASS.

- [ ] **Step 6: Run full promotion test suite to verify no regression**

Run: `pytest tests/ -v -k 'promot or lineage'`
Expected: previous green count maintained.

- [ ] **Step 7: Commit**

```bash
git add ingest/promotion.py tests/test_promote_raw_object_id_handoff.py
git commit -m "$(cat <<'EOF'
feat(promote): pass --raw-object-id to parser subprocess

Closes the FK loop: promote_raw_object now hands the raw_object_id to the
parser via CLI flag, parser stamps it on every canonical row written.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4.5: Fix B — intake emits `SOURCE_RESOLVED`, advance to `CLASSIFIED`

**Context:** Task 5 (production smoke, first attempt) revealed a real bug. `promote_raw_object` emits `PROMOTION_REQUESTED` with `from_status="RAW_ONLY"`, but the state machine transition table has no such pair — it only allows `PROMOTION_REQUESTED` from `CLASSIFIED` or `PROMOTABLE`. Root cause: `intake_file` only emits `RAW_INGESTED → RAW_ONLY`; it never emits the `SOURCE_RESOLVED` event that would advance to `CLASSIFIED`. So after intake, the row stays at `RAW_ONLY` forever, and any promote raises `InvalidTransition`.

This task implements **Fix B (faithful to design)**: intake emits `SOURCE_RESOLVED → CLASSIFIED` when `source_name` is resolved. Promote then starts from `CLASSIFIED` and the rest of the existing flow continues.

**Stefano's explicit rules (respect strictly):**
1. **Do NOT add** a `(RAW_ONLY, "PROMOTION_REQUESTED")` transition. (Shortcut prohibited.)
2. Intake **MUST** emit `SOURCE_RESOLVED → CLASSIFIED` when `source_name` is resolved.
3. Promote starts from `CLASSIFIED` and **continues the existing flow** (no new event types unless absolutely necessary).
4. Add a targeted test that **reproduces the real bug** (intake → promote with mocked subprocess) and verifies no `InvalidTransition` is raised.
5. **Escalate if downstream state machine gaps** prevent the existing promote flow from completing (e.g., `VALIDATED_OK` only valid from `PROMOTABLE` would block the path post-`CLASSIFIED`). Do NOT improvise new event types or add transitions Stefano hasn't authorized.

**Files:**
- Modify: `ingest/intake.py` — after the existing `emit_event(RAW_INGESTED)`, conditionally emit `SOURCE_RESOLVED`
- Modify: `tests/test_intake.py` — `test_intake_basic` currently asserts `len(events) == 1` with source_name set; update to expect 2 events (RAW_INGESTED + SOURCE_RESOLVED)
- Test: `tests/test_intake_promote_e2e.py` (new) — reproduces the bug end-to-end with mocked subprocess

- [ ] **Step 1: Write the failing E2E test (the bug reproducer)**

Create `tests/test_intake_promote_e2e.py` with a single test that:
1. Stubs `_lookup_existing_by_hash`, `register_raw_object`, `emit_event`, `load_registry` for intake
2. Calls `intake_file(path, source_name="MPS_BANCA_ORTI_APPEND", actor="test")`
3. Asserts that `SOURCE_RESOLVED` is in the captured events (post-Fix-B contract)
4. Stubs `subprocess.run`, `_fetch_raw_object`, `latest_status`, `load_registry`, `emit_event`, `PipelineRun` for promote
5. Calls `promote_raw_object(intake_result.raw_object_id, actor="test")`
6. Asserts `result.status == "PROMOTED"` (the crux: must NOT raise `InvalidTransition`)

The test isolates the state-machine flow without touching BQ, GCS, or the parser. Detailed test code in implementer prompt — keep all stubs scoped to the two functions they cover.

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/test_intake_promote_e2e.py -v`
Expected: FAIL on `"SOURCE_RESOLVED" in event_types` (pre-Fix-B intake emits only RAW_INGESTED).

If the test fails at a DIFFERENT assertion (downstream state machine gap), **STOP and report — that's the new bug Stefano needs to know about.**

- [ ] **Step 3: Apply Fix B in `ingest/intake.py`**

Edit `ingest/intake.py` — after the existing `emit_event(RAW_INGESTED)` call (around line 137), add a conditional second emit when `source_def` is resolved:

```python
        # Fix B (Task 4.5): when source is resolved, immediately advance
        # RAW_ONLY → CLASSIFIED so promote_raw_object can start from a valid
        # state. Sourceless intake stays at RAW_ONLY (must be classified later).
        if source_def is not None:
            emit_event(
                raw_object_id=raw_object_id,
                event_type="SOURCE_RESOLVED",
                actor=actor,
                from_status="RAW_ONLY",
                to_status="CLASSIFIED",
                payload={"source_name": source_name},
            )
```

Place inside the existing `with PipelineRun(...)` context, immediately after the RAW_INGESTED emit_event call.

- [ ] **Step 4: Update existing intake tests that asserted single RAW_INGESTED**

Read `tests/test_intake.py:test_intake_basic` (lines 16-44). It currently asserts `len(captured["events"]) == 1` and checks event_type. With Fix B, when `source_name` is provided, there are 2 events. Update assertions to expect both `RAW_INGESTED → RAW_ONLY` and `SOURCE_RESOLVED → CLASSIFIED`.

`test_intake_no_source_skips_classification_event` stays unchanged (no source_name → only RAW_INGESTED).

- [ ] **Step 5: Run the new E2E test + the touched intake tests**

Run: `pytest tests/test_intake.py tests/test_intake_promote_e2e.py -v`
Expected: all pass.

**If the new E2E test fails at `result.status == "PROMOTED"` because of a downstream state machine gap** (e.g., `(CLASSIFIED, "VALIDATED_OK")` not in transitions, or PROMOTED hardcoded `from_status="PROMOTABLE"` no longer matches the actual current state in a way that breaks), **STOP and report BLOCKED with the exact error and which transition is missing**. Do NOT add transitions Stefano hasn't authorized.

- [ ] **Step 6: Run full test suite to verify no regression**

Run: `pytest --tb=line -q`
Expected: all green (was 464 baseline + new tests added).

If existing tests in `test_intake_gcs.py` or elsewhere fail because they implicitly counted events: investigate. If the new event genuinely breaks an assertion, update that assertion (don't weaken — make it accurate).

- [ ] **Step 7: Commit**

```bash
git add ingest/intake.py tests/test_intake.py tests/test_intake_promote_e2e.py
git commit -m "$(cat <<'EOF'
fix(lineage): intake emits SOURCE_RESOLVED — promote can start from CLASSIFIED

Closes the InvalidTransition bug found in Task 5 production smoke:
intake_file only emitted RAW_INGESTED, leaving the row at RAW_ONLY.
promote_raw_object then tried to emit PROMOTION_REQUESTED from RAW_ONLY,
which is not a valid transition in the state machine.

Fix B (faithful to design): when source_name is resolved at intake,
also emit SOURCE_RESOLVED to advance RAW_ONLY → CLASSIFIED. Promote then
starts from CLASSIFIED, which is a valid PROMOTION_REQUESTED source.

Sourceless intake unchanged: stays at RAW_ONLY (must be classified later).

E2E regression test reproduces the original bug and verifies the fix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: End-to-end production smoke — promote a real MPS file, verify FK in BQ

**Context:** No new code. Operational verification on production with a real bank file. Mirrors the Phase 4 smoke test pattern.

**Files:**
- None modified. Output: a paragraph for STATUS.md plus the verification queries.

- [ ] **Step 1: Pick a fresh MPS file from datahub (or use one already intaken)**

If there's a recent MPS file pending promotion, find it:

```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT raw_object_id, file_name_original, intake_at
FROM `hotelops-suite.hotelops.v_raw_objects_current`
WHERE source_name = "MPS_BANCA_ORTI_APPEND"
  AND current_status IN ("RAW_ONLY", "PROMOTABLE")
ORDER BY intake_at DESC
LIMIT 5'
```

If none pending: take any MPS_ORTI homebanking export file and run intake first:

```bash
hotelops intake /path/to/MPS_ORTI_homebanking_2026_*.csv \
  --source-name MPS_BANCA_ORTI_APPEND
```

Note the `raw_object_id` printed.

- [ ] **Step 2: Promote it**

Run: `hotelops promote --raw-object-id <id>`
Expected: `status=PROMOTED reason=- rows=N noop=False` (N > 0).

If REJECTED: read stderr and stdout, file an issue, do not proceed to next step until promote succeeds on at least one file.

- [ ] **Step 3: Verify FK is stamped in BQ**

Run:
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  m.data_operazione,
  m.banca_id,
  m.importo_netto,
  m.raw_object_id,
  r.file_name_original,
  r.raw_uri
FROM `hotelops-suite.hotelops.f_banche_movimenti` m
JOIN `hotelops-suite.hotelops.f_raw_objects` r USING (raw_object_id)
WHERE m.raw_object_id = "<id from step 1>"
ORDER BY m.data_operazione
LIMIT 10'
```
Expected: rows returned, every row's `raw_object_id` matches the promoted id, JOIN to `f_raw_objects` resolves cleanly.

- [ ] **Step 4: Verify lineage event chain**

Run: `hotelops lineage <id>`
Expected: identity row + chronological events ending with PROMOTED.

- [ ] **Step 5: Idempotency check — re-promote same id**

Run: `hotelops promote --raw-object-id <id>`
Expected: `status=PROMOTED reason=- rows=0 noop=True` (already-promoted short-circuit).

No new rows in `f_banche_movimenti`, no new events in `f_lineage_events`.

Verify:
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT COUNT(*) AS row_count FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE raw_object_id = "<id>"'
```
Row count must be unchanged from step 3.

- [ ] **Step 6: No commit — operational verification only. Document in PR description / STATUS.**

---

## Task 6: View `v_raw_promotion_status` — per-source × status backlog

**Files:**
- Create: `core/bq/views/v_raw_promotion_status.sql`
- Create: `core/bq/load/load_v_raw_promotion_status.py`
- Test: `tests/test_v_raw_promotion_status.py`

- [ ] **Step 1: Write the failing test (smoke contract)**

Create `tests/test_v_raw_promotion_status.py`:

```python
"""v_raw_promotion_status — smoke test on schema + non-empty when sources exist."""

import pytest


@pytest.mark.integration
def test_view_returns_expected_columns():
    """Smoke: view exists and exposes the contract columns."""
    from core.bq.client import get_client

    client = get_client()
    rows = list(
        client.query(
            "SELECT * FROM `hotelops-suite.hotelops.v_raw_promotion_status` LIMIT 1"
        ).result()
    )
    if not rows:
        pytest.skip("view exists but no data — skip column check")

    expected_cols = {
        "source_name",
        "status",
        "n_objects",
        "oldest_intake_at",
        "latest_intake_at",
    }
    actual_cols = set(rows[0].keys())
    missing = expected_cols - actual_cols
    assert not missing, f"v_raw_promotion_status missing columns: {missing}"
```

(Mark `integration` because it hits BQ. Skipped automatically by `pytest -m "not integration"` in CI if you set up a marker.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_v_raw_promotion_status.py -v`
Expected: FAIL — view doesn't exist yet (BQ NotFound).

- [ ] **Step 3: Write the view SQL**

Create `core/bq/views/v_raw_promotion_status.sql`:

```sql
-- v_raw_promotion_status: per-source × status counts for operational visibility.
-- Used by `hotelops lineage list` and ad-hoc queries on the raw → canonical funnel.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_raw_promotion_status` AS
SELECT
  COALESCE(r.source_name, '(unclassified)') AS source_name,
  c.current_status AS status,
  COUNT(*) AS n_objects,
  MIN(r.intake_at) AS oldest_intake_at,
  MAX(r.intake_at) AS latest_intake_at
FROM `hotelops-suite.hotelops.f_raw_objects` r
LEFT JOIN `hotelops-suite.hotelops.v_raw_objects_current` c
  USING (raw_object_id)
GROUP BY source_name, status
ORDER BY source_name, status;
```

- [ ] **Step 4: Write the loader**

Create `core/bq/load/load_v_raw_promotion_status.py`:

```python
"""Materialize v_raw_promotion_status from SQL definition."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

SQL_PATH = (
    Path(__file__).parent.parent / "views" / "v_raw_promotion_status.sql"
)


def run() -> None:
    from core.bq.client import get_client

    sql = SQL_PATH.read_text(encoding="utf-8")
    client = get_client()
    client.query(sql).result()
    log.info("v_raw_promotion_status materialized.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Materialize on BQ**

Run: `python -m core.bq.load.load_v_raw_promotion_status`
Expected: `INFO: v_raw_promotion_status materialized.`

- [ ] **Step 6: Eyeball the view**

Run:
```bash
bq query --use_legacy_sql=false --format=pretty \
  'SELECT * FROM `hotelops-suite.hotelops.v_raw_promotion_status` ORDER BY source_name, status'
```
Expected: rows showing your sources × status with counts. At minimum `MPS_BANCA_ORTI_APPEND | PROMOTED | N` after Task 5.

- [ ] **Step 7: Run the integration test**

Run: `pytest tests/test_v_raw_promotion_status.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add core/bq/views/v_raw_promotion_status.sql \
        core/bq/load/load_v_raw_promotion_status.py \
        tests/test_v_raw_promotion_status.py
git commit -m "$(cat <<'EOF'
feat(lineage): v_raw_promotion_status — per-source × status backlog view

Universal observability over the raw → canonical funnel. Works for every
source, not just the GCS pilot. Joins f_raw_objects to v_raw_objects_current
and aggregates by (source_name, status) with min/max intake_at.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: CLI — `hotelops lineage list` with filters

**Files:**
- Modify: `cli.py` (around the existing cmd_lineage at line 508 + the argparse subcommand wiring)
- Test: `tests/test_lineage_list_cli.py`

**Design note:** `hotelops lineage <id>` already exists for inspection. This task adds `hotelops lineage list` (no positional id) with filters. Implement as a flag-based mode within the existing `cmd_lineage` to avoid restructuring the subcommand tree, OR as a new sub-subcommand if the existing argparse supports it cleanly. The simplest approach is the first.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lineage_list_cli.py`:

```python
"""hotelops lineage list — filter by status, source, days; prints raw_object_ids."""

from unittest.mock import MagicMock, patch


def test_lineage_list_filters_status_and_source(monkeypatch, capsys):
    """list mode: --status PROMOTABLE --source MPS_BANCA_ORTI_APPEND --limit 5."""
    fake_rows = [
        MagicMock(
            raw_object_id="r1",
            source_name="MPS_BANCA_ORTI_APPEND",
            current_status="PROMOTABLE",
            intake_at="2026-05-05T10:00:00",
            file_name_original="MPS_ORTI_2026_05.csv",
        ),
        MagicMock(
            raw_object_id="r2",
            source_name="MPS_BANCA_ORTI_APPEND",
            current_status="PROMOTABLE",
            intake_at="2026-05-04T09:00:00",
            file_name_original="MPS_ORTI_2026_04.csv",
        ),
    ]

    fake_client = MagicMock()
    fake_query_job = MagicMock()
    fake_query_job.result.return_value = fake_rows
    fake_client.query.return_value = fake_query_job

    monkeypatch.setattr("cli.get_client", lambda: fake_client, raising=False)
    # Some installs import get_client lazily inside cmd_lineage; if so, also patch:
    monkeypatch.setattr(
        "core.bq.client.get_client", lambda: fake_client, raising=False
    )

    from cli import cmd_lineage_list  # added in Step 3

    args = MagicMock(
        status="PROMOTABLE",
        source="MPS_BANCA_ORTI_APPEND",
        limit=5,
        days=None,
    )
    cmd_lineage_list(args)

    out = capsys.readouterr().out
    assert "r1" in out
    assert "r2" in out
    assert "MPS_BANCA_ORTI_APPEND" in out
    # The query must include the status filter:
    sent_sql = fake_client.query.call_args[0][0]
    assert "current_status" in sent_sql
    assert "source_name" in sent_sql
    assert "LIMIT" in sent_sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lineage_list_cli.py -v`
Expected: FAIL — `cmd_lineage_list` does not exist.

- [ ] **Step 3: Add `cmd_lineage_list` and wire argparse**

Edit `cli.py` — add a new function near `cmd_lineage` (around line 508):

```python
def cmd_lineage_list(args):
    """List raw_objects filtered by status / source / age."""
    from core.bq.client import get_client
    from core.lineage.raw_manifest import F_RAW_OBJECTS, V_RAW_OBJECTS_CURRENT
    from google.cloud import bigquery

    where = ["1=1"]
    params = []
    if args.status:
        where.append("c.current_status = @status")
        params.append(bigquery.ScalarQueryParameter("status", "STRING", args.status))
    if args.source:
        where.append("r.source_name = @source")
        params.append(bigquery.ScalarQueryParameter("source", "STRING", args.source))
    if args.days:
        where.append(
            "r.intake_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)"
        )
        params.append(bigquery.ScalarQueryParameter("days", "INT64", args.days))

    sql = f"""
    SELECT
      r.raw_object_id,
      r.source_name,
      c.current_status,
      r.intake_at,
      r.file_name_original
    FROM `{F_RAW_OBJECTS}` r
    LEFT JOIN `{V_RAW_OBJECTS_CURRENT}` c USING (raw_object_id)
    WHERE {' AND '.join(where)}
    ORDER BY r.intake_at DESC
    LIMIT {int(args.limit)}
    """
    client = get_client()
    qc = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(client.query(sql, job_config=qc).result())

    if not rows:
        print("(no raw_objects match filters)")
        return

    # Tabular output, fixed-width-ish for terminal readability.
    print(
        f"{'raw_object_id':<38} {'status':<12} {'source':<32} {'intake_at':<25} file"
    )
    print("-" * 130)
    for r in rows:
        print(
            f"{r.raw_object_id:<38} "
            f"{(r.current_status or '?'):<12} "
            f"{(r.source_name or '-'):<32} "
            f"{str(r.intake_at):<25} "
            f"{r.file_name_original or '-'}"
        )
```

Edit `cli.py:948-951` (the existing lineage subparser registration) — replace those 4 lines with:

```python
    p_lin = sub.add_parser(
        "lineage", help="Lineage: ispeziona raw_object o lista con filtri"
    )
    p_lin.add_argument("raw_object_id", nargs="?", help="ID singolo (omit con --list)")
    p_lin.add_argument(
        "--list", action="store_true", help="Lista raw_objects con filtri"
    )
    p_lin.add_argument(
        "--status",
        choices=["RAW_ONLY", "CLASSIFIED", "PROMOTABLE", "PROMOTED", "REJECTED"],
    )
    p_lin.add_argument("--source", help="Filtra per source_name")
    p_lin.add_argument("--days", type=int, help="Solo intake negli ultimi N giorni")
    p_lin.add_argument("--limit", type=int, default=20, help="Max righe (default 20)")
```

Then find the `handlers = {...}` dict (around `cli.py:959+`) and replace the `"lineage": cmd_lineage,` entry with a dispatcher. The cleanest minimal change: define a thin wrapper:

```python
def cmd_lineage_dispatch(args):
    """Route to list mode or single-id mode based on --list flag."""
    if args.list:
        cmd_lineage_list(args)
    else:
        if not args.raw_object_id:
            print("ERROR: provide raw_object_id or use --list", file=sys.stderr)
            sys.exit(2)
        cmd_lineage(args)
```

And in the handlers dict:
```python
        "lineage": cmd_lineage_dispatch,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lineage_list_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Manual smoke against BQ**

Run: `hotelops lineage --list --source MPS_BANCA_ORTI_APPEND --limit 5`
Expected: tabular output with up to 5 rows for the pilot source.

Run: `hotelops lineage --list --status PROMOTABLE --limit 10`
Expected: rows in PROMOTABLE state across all sources, or "(no raw_objects match filters)" if empty.

- [ ] **Step 6: Commit**

```bash
git add cli.py tests/test_lineage_list_cli.py
git commit -m "$(cat <<'EOF'
feat(cli): hotelops lineage --list with --status/--source/--days/--limit

Operational visibility over the raw → canonical backlog. Works across all
sources via v_raw_objects_current; complementary to the existing per-id
inspection (hotelops lineage <id>).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: STATUS update + final commit

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: Update STATUS.md**

Apply the following edits manually (date today is YYYY-MM-DD per environment):

1. Bump header date to today.
2. Add to **Completato di recente** (top):

```markdown
- YYYY-MM-DD: **Lineage FK + observability mergiati** — `f_banche_movimenti.raw_object_id STRING NULLABLE` (migration additiva su BQ produzione), single-file mode in `ingest.banca.ingest` (`--file` + `--raw-object-id` + `--societa`), promotion subprocess passa `--raw-object-id`, view `v_raw_promotion_status` (per-source × status), CLI `hotelops lineage --list --status/--source/--days/--limit`. Pilot: smoke produzione su MPS file reale → riga in `f_banche_movimenti` con FK valido che JOIN risolve a `f_raw_objects`. Closes hidden debt: prima d'oggi promote→banca non girava end-to-end (parser non accettava `--file`).
```

3. Roll off the oldest entry to keep ≤10.
4. Mark the related decision (the GCS Raw layer one) as further IMPLEMENTATO with the FK note, or add a new line under **Decisioni aperte → Completato decisioni** if you maintain such a section.
5. Add to **Prossimi passi**:

```markdown
- **Bulk extension FK** — quando una nuova source flippa a `backend: gcs`, aggiungere `raw_object_id` alla sua canonical_table nello stesso commit (template: vedi migration 2026_05_06).
- **Phase 5 cutover `cmd_drop` = `intake + promote`** — pre-condizione ora soddisfatta (promote-MPS funziona end-to-end con FK).
```

- [ ] **Step 2: Commit**

```bash
git add STATUS.md
git commit -m "$(cat <<'EOF'
docs(status): snapshot YYYY-MM-DD — lineage FK + observability live

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Replace YYYY-MM-DD with today's date.)

---

## Self-review checklist

Run before declaring the plan ready:

- [ ] Spec coverage — does every gap from the design conversation map to a task?
  - Gap #1 (FK on canonical) → Tasks 1, 2, 3, 4, 5 ✓
  - Gap #4 (observability) → Tasks 6, 7 ✓
  - Hidden debt (banca single-file mode) → Task 3 ✓
- [ ] Placeholder scan — no "TBD", no "implement appropriate X" without code, no "similar to Task N" without the actual code repeated.
- [ ] Type consistency — `raw_object_id` is `Optional[str]` in Pydantic, `STRING NULLABLE` in BQ, `str | None` in CLI args. No mismatches.
- [ ] Subprocess contract — `--raw-object-id` flag name consistent across promotion (Task 4 cmd builder) and parser argparse (Task 3 main).
- [ ] FACT_HEADER includes `raw_object_id` (Task 3 step 3) AND BancaMovimentoRow has the field (Task 2 step 3) AND the migration adds the column (Task 1) — three sides aligned.

