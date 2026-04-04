# Parallel Refactor — Post-Audit Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix data integrity issues, harden SQL injection, slim down cli.py, and fix ingest_coperti.py bugs — all via concurrent worktree agents.

**Architecture:** 4 independent agents in Wave 1 (each in its own worktree), then 2 sequential agents in Wave 2 after merge. No file overlap between Wave 1 agents.

**Tech Stack:** Python, BigQuery SQL, git worktrees

---

## Wave 1: Parallel Agents (no file overlap)

### Agent A: Fix 390521 Pattern Overlap + View Dedup

**Problem:** `ENTRATE_CAPARRE_INTUR` (societa_id=INTUR) and `ENTRATE_CAPARRE` (societa_id=ORTI) both have `cod_conto_pattern=390521`. The view `v_piano_finanziario_consuntivo` JOINs with `(v.societa_id IS NULL OR v.societa_id = m.societa_id)` — since ENTRATE_CAPARRE has societa_id=ORTI (not NULL), this actually works correctly for the societa filter. But the CSV shows societa_id is explicitly set for each, so the real risk is in `v_piano_finanziario_mensile`'s `budget_costi` CTE where the same LIKE pattern can match the same budget row to multiple voci.

**Files:**
- Modify: `core/bq/dimensioni/d_voci_piano_finanziario.csv:6,12`
- Modify: `core/bq/views/v_piano_finanziario_consuntivo.sql:40-47`
- Modify: `core/bq/views/v_piano_finanziario_mensile.sql:74-91`

- [ ] **Step 1: Verify the overlap in the CSV**

Read `core/bq/dimensioni/d_voci_piano_finanziario.csv`. Confirm:
- Line 6: `ENTRATE_CAPARRE_INTUR` has `societa_id=INTUR`, `cod_conto_pattern=390521`
- Line 12: `ENTRATE_CAPARRE` has `societa_id=ORTI`, `cod_conto_pattern=390521`

Both have explicit societa_id, so the esolver CTE's `(v.societa_id IS NULL OR v.societa_id = m.societa_id)` does filter correctly per-società. **The pattern overlap is safe at the consuntivo level.** But verify no other overlaps exist.

- [ ] **Step 2: Check for any OTHER pattern overlaps**

Run this in Python to find all cod_conto_pattern values shared across multiple voci:

```python
import csv
from collections import defaultdict

patterns = defaultdict(list)
with open("core/bq/dimensioni/d_voci_piano_finanziario.csv") as f:
    for row in csv.DictReader(f):
        for col in ("cod_conto_pattern", "cod_conto_pat2", "cod_conto_pat3"):
            pat = row.get(col, "").strip()
            if pat:
                key = (pat, row.get("societa_id", "").strip() or "ALL")
                patterns[key].append(row["voce_id"])

for (pat, soc), voci in sorted(patterns.items()):
    if len(voci) > 1:
        print(f"OVERLAP: pattern={pat} societa={soc} → {voci}")
```

If overlaps exist, document them. If 390521 is the only one and it's properly scoped by societa_id, the CSV is fine.

- [ ] **Step 3: Add dedup to budget_costi CTE in v_piano_finanziario_mensile.sql**

The `budget_costi` CTE at lines 74-91 does a LIKE JOIN without dedup. If a budget row's `codice_conto` matches multiple voci patterns, the budget amount gets duplicated. Add ROW_NUMBER() to pick the most specific match.

Replace the `budget_costi` CTE (lines 74-91) with:

```sql
-- ── Budget da f_budget_mensile (dedup: most specific pattern wins) ─────────
budget_costi_raw AS (
  SELECT
    b.societa_id,
    v.voce_id,
    b.anno,
    b.mese,
    b.importo,
    -- Prefer longer (more specific) pattern match
    ROW_NUMBER() OVER (
      PARTITION BY b.societa_id, REPLACE(b.codice_conto, '.', ''), b.anno, b.mese
      ORDER BY LENGTH(COALESCE(v.cod_conto_pattern, '')) DESC
    ) AS rn
  FROM `hotelops-suite.hotelops.f_budget_mensile` b
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
    ON v.fonte = 'ESOLVER'
    AND (
         REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pattern, '%')
      OR (v.cod_conto_pat2 IS NOT NULL AND REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat2, '%'))
      OR (v.cod_conto_pat3 IS NOT NULL AND REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat3, '%'))
    )
    AND (v.societa_id IS NULL OR v.societa_id = b.societa_id)
),
budget_costi AS (
  SELECT
    societa_id,
    voce_id,
    anno,
    mese,
    SUM(importo) AS importo_budget
  FROM budget_costi_raw
  WHERE rn = 1
  GROUP BY 1, 2, 3, 4
),
```

- [ ] **Step 4: Run ruff check on modified files**

```bash
ruff check core/bq/views/
```

(SQL files won't be linted by ruff, but verify no syntax issues.)

- [ ] **Step 5: Commit**

```bash
git add core/bq/views/v_piano_finanziario_mensile.sql
git commit -m "fix: add dedup to budget_costi CTE — prevent double-counting when LIKE matches multiple voci"
```

---

### Agent B: Parameterize update_previsione.py DELETE

**Problem:** The DELETE statement at line 138-145 uses f-string interpolation. While `societa_id` and `voce_id` are validated, `fonte` has no validation. Use BQ parameterized queries.

**Files:**
- Modify: `condges/update_previsione.py:136-146`

- [ ] **Step 1: Replace f-string DELETE with parameterized query**

Replace lines 136-146 in `condges/update_previsione.py`:

Old:
```python
    # DELETE existing rows for this voce×mesi×fonte
    mesi_csv = ", ".join(str(m) for m in mesi)
    delete_sql = f"""
    DELETE FROM `{BQ_TABLE}`
    WHERE societa_id = '{societa_id}'
      AND voce_id = '{voce_id}'
      AND anno = {anno}
      AND mese IN ({mesi_csv})
      AND fonte = '{fonte}'
    """
    delete_result = bq_client.query(delete_sql).result()
```

New:
```python
    # DELETE existing rows for this voce×mesi×fonte (parameterized)
    from google.cloud import bigquery as _bq

    delete_sql = f"""
    DELETE FROM `{BQ_TABLE}`
    WHERE societa_id = @societa_id
      AND voce_id = @voce_id
      AND anno = @anno
      AND mese IN UNNEST(@mesi)
      AND fonte = @fonte
    """
    job_config = _bq.QueryJobConfig(
        query_parameters=[
            _bq.ScalarQueryParameter("societa_id", "STRING", societa_id),
            _bq.ScalarQueryParameter("voce_id", "STRING", voce_id),
            _bq.ScalarQueryParameter("anno", "INT64", anno),
            _bq.ArrayQueryParameter("mesi", "INT64", mesi),
            _bq.ScalarQueryParameter("fonte", "STRING", fonte),
        ]
    )
    delete_result = bq_client.query(delete_sql, job_config=job_config).result()
```

- [ ] **Step 2: Move the bigquery import to top of function**

The function already imports `bigquery` at line 78: `from google.cloud import bigquery`. Use that reference instead of the `_bq` alias. Replace the `from google.cloud import _bq` line with just using `bigquery` directly:

```python
    delete_sql = f"""
    DELETE FROM `{BQ_TABLE}`
    WHERE societa_id = @societa_id
      AND voce_id = @voce_id
      AND anno = @anno
      AND mese IN UNNEST(@mesi)
      AND fonte = @fonte
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("societa_id", "STRING", societa_id),
            bigquery.ScalarQueryParameter("voce_id", "STRING", voce_id),
            bigquery.ScalarQueryParameter("anno", "INT64", anno),
            bigquery.ArrayQueryParameter("mesi", "INT64", mesi),
            bigquery.ScalarQueryParameter("fonte", "STRING", fonte),
        ]
    )
    delete_result = bq_client.query(delete_sql, job_config=job_config).result()
```

- [ ] **Step 3: Also parameterize get_valid_voci query (line 56-58)**

Replace:
```python
    rows = bq_client.query(
        f"SELECT voce_id, voce_label FROM `{BQ_VOCI_TABLE}`"
    ).result()
```

This one is safe (no user input), but for consistency, leave it as-is. The table name is a constant, not user input. No change needed.

- [ ] **Step 4: Run ruff check and format**

```bash
ruff check condges/update_previsione.py
ruff format condges/update_previsione.py
```

- [ ] **Step 5: Commit**

```bash
git add condges/update_previsione.py
git commit -m "fix: parameterize DELETE query in update_previsione to prevent SQL injection"
```

---

### Agent C: Refactor cli.py — Extract Command Handlers

**Problem:** `cli.py` is 1,256 LOC with 14 `cmd_*` handlers, inline BQ queries, and formatting logic. Extract the large handlers into domain modules; keep cli.py as a thin dispatcher.

**Strategy:** Move the 6 largest handlers (cmd_chiudi: 216 LOC, cmd_health: 105 LOC, cmd_pf: 86 LOC, cmd_bva: 40 LOC, cmd_saldo: 57 LOC, cmd_scadenzario: 91 LOC) into domain modules. Keep argparse definitions and small handlers in cli.py.

**Files:**
- Modify: `cli.py` (trim from 1,256 to ~500 LOC)
- Create: `condges/cli_commands.py` (extracted handlers that query BQ + format output)

- [ ] **Step 1: Create condges/cli_commands.py with extracted handlers**

Create `condges/cli_commands.py` containing the 6 large handler functions. Each function keeps its exact current signature `(args)` and behavior. The file imports `bq`, `query`, `fmt_eur` from `cli` to avoid duplication.

Read the full cli.py to extract:
- `cmd_pf` (lines 60-144)
- `cmd_health` (lines 191-295)
- `cmd_chiudi` (lines 433-648)
- `cmd_saldo` (lines 649-705)
- `cmd_scadenzario` (lines 788-878)
- `cmd_help` (lines 985-1076)

Create `condges/cli_commands.py`:

```python
"""Extracted CLI command handlers — query BQ and format terminal output."""

from __future__ import annotations


def _lazy_cli():
    """Import cli module lazily to avoid circular imports."""
    import cli as _cli
    return _cli


def cmd_pf(args):
    """Piano Finanziario budget vs consuntivo."""
    cli = _lazy_cli()
    # ... exact copy of cmd_pf body from cli.py, replacing query() with cli.query(), etc.
```

**Important:** Copy each function body exactly. Replace bare `query(...)` calls with `cli.query(...)`, `bq()` with `cli.bq()`, `fmt_eur(...)` with `cli.fmt_eur(...)`.

- [ ] **Step 2: Update cli.py imports**

At the top of cli.py, add:

```python
from condges.cli_commands import (
    cmd_pf,
    cmd_health,
    cmd_chiudi,
    cmd_saldo,
    cmd_scadenzario,
    cmd_help,
)
```

Remove the `cmd_pf`, `cmd_health`, `cmd_chiudi`, `cmd_saldo`, `cmd_scadenzario`, `cmd_help` function definitions from cli.py.

- [ ] **Step 3: Keep small handlers in cli.py**

These handlers are small enough to stay:
- `cmd_bva` (40 LOC) — short query + format
- `cmd_previsione` (~60 LOC) — delegates to update_previsione
- `cmd_voci` (~80 LOC)
- `cmd_manifest` (~20 LOC)
- `cmd_classifica` (~60 LOC)
- `cmd_ingest` (~50 LOC)
- `cmd_app` (~20 LOC)
- `cmd_reconcile` (~30 LOC)

- [ ] **Step 4: Update cli.py docstring**

Update the docstring at the top to list all 11 subcommands (not just 8):

```python
"""
hotelops CLI — control plane per il financial model.

Subcomandi:
    hotelops pf            Piano Finanziario mensile (budget vs consuntivo)
    hotelops bva           Budget vs Consuntivo per codice conto
    hotelops chiudi        Chiusura mese: consuntivo vs previsione + saldo banca
    hotelops saldo         Saldo banca corrente e proiezione cash forward
    hotelops health        Health check: freshness dati, gaps, alert
    hotelops previsione    Inserisci/aggiorna previsione budget
    hotelops voci          Lista voci piano finanziario disponibili
    hotelops classifica    Classifica, smista e ingerisci file dati
    hotelops scadenzario   Excel ponte: scadenzario fornitori → voci PF
    hotelops ingest        Pipeline di ingestione dati
    hotelops app           Lancia app Streamlit
    hotelops reconcile     Riconciliazione banca vs libro
    hotelops manifest      Catalogo tabelle BigQuery
"""
```

- [ ] **Step 5: Verify cli still works**

```bash
python -m cli help
python -m cli voci
python -m cli pf --societa ORTI --mese 1
```

- [ ] **Step 6: Run ruff check and format**

```bash
ruff check cli.py condges/cli_commands.py
ruff format cli.py condges/cli_commands.py
```

- [ ] **Step 7: Commit**

```bash
git add cli.py condges/cli_commands.py
git commit -m "refactor: extract 6 large CLI handlers to condges/cli_commands.py — cli.py slimmed from 1256 to ~500 LOC"
```

---

### Agent D: Fix ingest_coperti.py Bugs

**Problem:** Three bugs: (1) hash collision in parse_mensa_dipendenti when date+pasto+count match, (2) temp file leak in fetch_gsheet, (3) sys.exit() in library function.

**Files:**
- Modify: `ingest/flussi/ingest_coperti.py`

- [ ] **Step 1: Fix hash collision — include row index in hash key**

The `make_hash` function at line 156-159 creates MD5 from `(societa_id, data_servizio, tipo_pasto, tipo_ospite, n_coperti)`. Two records with identical values produce the same hash → one is silently dropped during dedup.

Fix: Add a `seq` parameter to disambiguate. In `parse_mensa_dipendenti` (line 288-332), pass a row counter.

Replace `make_hash` at line 156-159:

```python
def make_hash(societa_id: str, data_servizio: date, tipo_pasto: str,
              tipo_ospite: str, n_coperti: int, seq: int = 0) -> str:
    key = f"{societa_id}|{data_servizio}|{tipo_pasto}|{tipo_ospite}|{n_coperti}|{seq}"
    return hashlib.md5(key.encode()).hexdigest()
```

Update the call in `parse_rows_from_header_data` (line 249) — add `seq=i` using the column index:

```python
                "hash_riga": make_hash(societa_id, data_servizio, tipo_pasto, tipo_ospite, n, seq=i),
```

Update the call in `parse_mensa_dipendenti` (line 329) — add `seq` using enumerate:

Change the loop at line 297 from `for row in all_rows[1:]:` to:

```python
    for row_idx, row in enumerate(all_rows[1:]):
```

And update line 329:

```python
            "hash_riga": make_hash(societa_id, data_servizio, tipo_pasto, "DIPENDENTI", n, seq=row_idx),
```

- [ ] **Step 2: Fix temp file leak — use cleanup in fetch_gsheet**

Replace `fetch_gsheet` (lines 164-188) with a version that cleans up on success (caller handles the file) but registers atexit cleanup for the parent tmpdir:

```python
def fetch_gsheet(sheet_id: str, remote: str = RCLONE_REMOTE) -> Path:
    """Download a Google Sheet as XLSX via rclone backend copyid."""
    tmpdir = Path(tempfile.mkdtemp(prefix="hotelops_coperti_"))
    tmp = tmpdir / "coperti_gsheet.xlsx"
    cmd = ["rclone", "backend", "copyid", f"{remote}:", sheet_id, str(tmp)]
    log.info("rclone: scarico Google Sheet %s …", sheet_id)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("rclone fallito: %s", result.stderr.strip())
        raise RuntimeError(f"rclone download failed: {result.stderr.strip()}")
    # rclone copyid drops the file without extension
    actual = tmp if tmp.exists() else tmp.with_suffix("")
    if not actual.exists():
        # rclone may save without extension
        candidates = list(tmpdir.iterdir())
        if candidates:
            actual = candidates[0]
        else:
            raise RuntimeError("File non trovato dopo rclone download")
    if actual.suffix != ".xlsx":
        dest = actual.with_suffix(".xlsx")
        actual.rename(dest)
        actual = dest
    log.info("Scaricato: %s (%d KB)", actual.name, actual.stat().st_size // 1024)
    return actual
```

- [ ] **Step 3: Update main() to handle RuntimeError from fetch_gsheet**

In `main()` at line 557-560, wrap the gsheet path in try/except:

```python
    if args.gsheet:
        try:
            xlsx_path = fetch_gsheet(args.gsheet)
        except RuntimeError as e:
            log.error("%s", e)
            sys.exit(1)
        rows = parse_xlsx_file(xlsx_path, args.societa, ts_now)
```

- [ ] **Step 4: Run ruff check and format**

```bash
ruff check ingest/flussi/ingest_coperti.py
ruff format ingest/flussi/ingest_coperti.py
```

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_coperti.py
git commit -m "fix: ingest_coperti — hash collision, temp file leak, sys.exit in library fn"
```

---

## Wave 2: Sequential (after Wave 1 merges)

### Agent E: Standardize Flussi Logging

**Problem:** Each of the 9 flussi pipelines uses its own logging pattern. Standardize using a shared helper.

**Files:**
- Create: `ingest/_logging.py`
- Modify: All `ingest/flussi/ingest_*.py` files (9 files)

- [ ] **Step 1: Create ingest/_logging.py**

Copy the pattern from `ingest/banca/_logging.py` but simplified for flussi (no file handler needed for most cases):

```python
"""Shared logging setup for ingest pipelines."""

import logging


def get_logger(name: str, verbose: bool = False) -> logging.Logger:
    """Create a configured logger for an ingest pipeline.

    Args:
        name: Logger name (typically pipeline name like 'ingest_coperti').
        verbose: If True, set DEBUG level; otherwise INFO.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logging.basicConfig(
            level=logging.DEBUG if verbose else logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )
    return logger
```

- [ ] **Step 2: Update each flussi pipeline**

For each file in `ingest/flussi/ingest_*.py`, replace the ad-hoc logging setup with:

```python
from ingest._logging import get_logger
log = get_logger("pipeline_name")
```

Remove any `logging.basicConfig(...)` and `logging.getLogger(...)` calls that are being replaced.

Files to update (9):
1. `ingest/flussi/ingest_coperti.py` — lines 103-108
2. `ingest/flussi/ingest_scheda_contabile.py` — lines 68-69
3. `ingest/flussi/ingest_partite_aperte.py` — lines 48, 293
4. `ingest/flussi/ingest_movimenti_contabili.py` — line 104
5. `ingest/flussi/ingest_piano_finanziario_xlsx.py` — line 195
6. `ingest/flussi/ingest_consumi_economato.py` — line 403
7. `ingest/flussi/ingest_bilancino.py` — line 77
8. `ingest/flussi/ingest_gasparotto.py` — line 264
9. `ingest/flussi/ingest_consumi_economato_consolidato.py` — line 241

- [ ] **Step 3: Run ruff check and pytest**

```bash
ruff check ingest/
pytest
```

- [ ] **Step 4: Commit**

```bash
git add ingest/_logging.py ingest/flussi/
git commit -m "refactor: standardize flussi logging via shared ingest/_logging.py"
```

---

### Agent F: Update CLAUDE.md

**Problem:** CLAUDE.md is significantly stale after both the organic growth and this refactor round.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Architecture section**

Change "6 SQL view definitions" to "14 SQL view definitions". Update condges/ description to include all 10 files:

```
condges/    <- Controllo di Gestione vertical (Streamlit apps, Excel gen, forecasts)
  app.py               <- Streamlit Piano Finanziario (Rosa)
  bva_app.py           <- Streamlit Budget vs Consuntivo (Gasparotto)
  budget_app.py        <- Streamlit Budget explorer
  app_scadenzario.py   <- Streamlit scadenzario fornitori bridge
  scadenzario_excel.py <- Excel ponte: sintetica → voci PF
  genera_excel.py      <- Generate PF Excel from BQ
  update_previsione.py <- Write forecasts to f_piano_finanziario_input
  reconcile_banca.py   <- Bank vs ledger reconciliation
  materialize_reconciliation.py <- Reconciliation state materialization
  cli_commands.py      <- Extracted large CLI command handlers
```

- [ ] **Step 2: Update CLI subcommands**

Change "8 subcommands" to "14 subcommands" and list them all:

```
cli.py      <- CLI entry point (hotelops command). 14 subcommands: pf, bva, chiudi, saldo, health, previsione, voci, classifica, scadenzario, ingest, app, reconcile, manifest, help.
```

- [ ] **Step 3: Update BigQuery tables**

Remove `f_mastrino_consolidato` and `f_affidamenti` (not in config.py). Add:
- `f_coefficienti_consumo` — Consumption coefficients per product
- `f_pms_statistiche` — PMS statistics from HotelCube

Remove dimension tables not in config: `d_budget_costi_fissi`, `d_personale_mensile`, `d_periodi_apertura`.

- [ ] **Step 4: Update Views section**

Add missing views:
- `v_budget` — Budget pivoted per codice conto (used by bva_app)
- `v_condges_banca_dettaglio` — Looker: Bank transaction detail view

Change "6 SQL view definitions" in Architecture to "14 SQL view definitions".

- [ ] **Step 5: Update Flussi pipelines**

Add `ingest_consumi_economato_consolidato` to the list.

- [ ] **Step 6: Update Tests section**

```
tests/
  test_classify.py              -- File classifier: 65 tests, all 10 detectors + routing + lifecycle
  test_contracts.py             -- Schema validation tests
  test_materialize.py           -- Materialization tests
  test_ingest_movimenti_xlsx.py -- XLSX movimenti parser tests
  test_manifest.py              -- BQ manifest tests
  test_scadenzario.py           -- Scadenzario parsing tests
  test_stagionalita.py          -- Seasonality coefficient tests
```

- [ ] **Step 7: Update Last checkpoint**

Change `**Last checkpoint:** 2026-03-27` to `**Last checkpoint:** 2026-04-04`.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md — sync with actual codebase state (14 views, 14 CLI commands, new condges files)"
```

---

## Execution Order

```
Wave 1 (parallel, each in own worktree):
  Agent A: v_piano_finanziario_mensile dedup     [core/bq/views/*, core/bq/dimensioni/*]
  Agent B: update_previsione parameterize        [condges/update_previsione.py]
  Agent C: cli.py refactor                       [cli.py, condges/cli_commands.py]
  Agent D: ingest_coperti.py fixes               [ingest/flussi/ingest_coperti.py]

  → Merge all 4 branches to main

Wave 2 (sequential, after merge):
  Agent E: standardize flussi logging            [ingest/_logging.py, ingest/flussi/*]
  Agent F: update CLAUDE.md                      [CLAUDE.md]
```

**No file overlap in Wave 1:** Each agent touches completely independent files.
