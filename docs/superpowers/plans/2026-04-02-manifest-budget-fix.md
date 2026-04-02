# Manifest & Budget Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `hotelops manifest` command that generates a YAML catalog of all BQ tables, and fix the budget double-counting in `v_budget_vs_consuntivo`.

**Architecture:** Two independent components. (1) `core/bq/manifest.py` queries BQ INFORMATION_SCHEMA + table data to produce `core/bq/manifest.yaml` with row counts, freshness, column stats per table. CLI wires it as `hotelops manifest`. (2) The budget CTE in `v_budget_vs_consuntivo` gets a `ROW_NUMBER()` priority window to pick the best fonte per codice_conto×mese.

**Tech Stack:** Python 3.11+, google-cloud-bigquery, PyYAML, pytest.

---

### Task 1: Manifest generator — core logic

**Files:**
- Create: `core/bq/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the test for column stats helper**

```python
# tests/test_manifest.py
"""Tests for manifest generation helpers."""

from core.bq.manifest import _column_stats


def test_column_stats_few_values():
    """When distinct <= 30, list all values."""
    stats = _column_stats(
        col_name="societa_id",
        col_type="STRING",
        distinct=2,
        values=["ORTI", "INTUR"],
        sample=None,
        min_val=None,
        max_val=None,
    )
    assert stats["type"] == "STRING"
    assert stats["distinct"] == 2
    assert stats["values"] == ["ORTI", "INTUR"]
    assert "sample" not in stats


def test_column_stats_many_values():
    """When distinct > 100, show count + sample."""
    stats = _column_stats(
        col_name="descrizione",
        col_type="STRING",
        distinct=891,
        values=None,
        sample=["Prosecco", "Farina", "Olio"],
        min_val=None,
        max_val=None,
    )
    assert stats["distinct"] == 891
    assert stats["sample"] == ["Prosecco", "Farina", "Olio"]
    assert "values" not in stats


def test_column_stats_numeric():
    """Numeric columns get min/max."""
    stats = _column_stats(
        col_name="importo",
        col_type="FLOAT",
        distinct=500,
        values=None,
        sample=None,
        min_val=-234.5,
        max_val=1890.0,
    )
    assert stats["min"] == -234.5
    assert stats["max"] == 1890.0


def test_column_stats_date():
    """Date columns get min/max as strings."""
    stats = _column_stats(
        col_name="data_op",
        col_type="DATE",
        distinct=365,
        values=None,
        sample=None,
        min_val="2025-01-01",
        max_val="2026-03-27",
    )
    assert stats["min"] == "2025-01-01"
    assert stats["max"] == "2026-03-27"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.bq.manifest'`

- [ ] **Step 3: Implement the column stats helper and table list**

```python
# core/bq/manifest.py
"""
Generate manifest.yaml — a metadata catalog of all BQ tables.

Each table gets: row count, freshness (date range), sources, and
per-column stats (type, distinct values or samples, min/max).

Usage:
    from core.bq.manifest import generate_manifest
    manifest = generate_manifest()  # returns dict
    generate_manifest(output_path="core/bq/manifest.yaml")  # writes file
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import yaml

from core.config import PROJECT, DATASET

log = logging.getLogger(__name__)

# Tables to catalog (all facts + dimensions from config.py)
TABLES = [
    "f_banche_movimenti",
    "f_movimenti_contabili",
    "f_budget_mensile",
    "f_piano_finanziario_input",
    "f_consumi_economato",
    "f_coperti_giornalieri",
    "f_bilancino",
    "f_partite_aperte_fornitori",
    "f_saldi_banca_snapshot",
    "f_accodamenti",
    "f_ricavi_storici",
    "d_voci_piano_finanziario",
    "d_piano_conti",
    "d_categorie_conti",
    "d_fornitori",
    "d_anagrafica_fornitori",
    "d_mapping_piano_finanziario",
    "d_coefficienti_stagionalita",
]

# Columns likely to hold date/freshness info (checked in order)
DATE_CANDIDATES = [
    "data_registrazione",
    "data_operazione",
    "data_caricamento",
    "data_ingresso",
    "data_snapshot",
    "data_servizio",
    "data_documento",
]

# Columns likely to hold source file info
SOURCE_CANDIDATES = ["file_sorgente", "fonte"]

# Thresholds for value listing
VALUES_THRESHOLD = 30  # list all values if distinct <= this
SAMPLE_THRESHOLD = 100  # show top-N if distinct > VALUES_THRESHOLD
SAMPLE_SIZE = 10


def _column_stats(
    col_name: str,
    col_type: str,
    distinct: int,
    values: list | None,
    sample: list | None,
    min_val,
    max_val,
) -> dict:
    """Build stats dict for a single column."""
    stats: dict = {"type": col_type}

    if col_type in ("FLOAT", "INTEGER", "NUMERIC"):
        if min_val is not None:
            stats["min"] = min_val
        if max_val is not None:
            stats["max"] = max_val
        if distinct is not None:
            stats["distinct"] = distinct
        return stats

    if col_type in ("DATE", "TIMESTAMP", "DATETIME"):
        if min_val is not None:
            stats["min"] = str(min_val) if not isinstance(min_val, str) else min_val
        if max_val is not None:
            stats["max"] = str(max_val) if not isinstance(max_val, str) else max_val
        if distinct is not None:
            stats["distinct"] = distinct
        return stats

    # STRING columns
    if distinct is not None:
        stats["distinct"] = distinct
    if distinct is not None and distinct <= VALUES_THRESHOLD and values:
        stats["values"] = values
    elif sample:
        stats["sample"] = sample

    return stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_manifest.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/bq/manifest.py tests/test_manifest.py
git commit -m "feat: add manifest column stats helper with tests"
```

---

### Task 2: Manifest generator — BQ introspection

**Files:**
- Modify: `core/bq/manifest.py`
- Test: manual (`hotelops manifest --table f_consumi_economato`)

This task adds the BQ query logic. No unit tests for BQ calls — tested via integration.

- [ ] **Step 1: Add `_introspect_table()` function**

Append to `core/bq/manifest.py`:

```python
def _get_client():
    from google.cloud import bigquery
    return bigquery.Client(project=PROJECT)


def _introspect_table(client, table_name: str) -> dict:
    """Query BQ for metadata about a single table."""
    full_id = f"{PROJECT}.{DATASET}.{table_name}"

    # 1. Get row count and schema
    try:
        table_ref = client.get_table(full_id)
    except Exception as e:
        log.warning("Table %s not found: %s", table_name, e)
        return {"error": f"not found: {e}"}

    row_count = table_ref.num_rows
    schema = [(f.name, f.field_type) for f in table_ref.schema]

    result: dict = {
        "rows": row_count,
        "columns": {},
    }

    if row_count == 0:
        for col_name, col_type in schema:
            result["columns"][col_name] = {"type": col_type}
        return result

    # 2. Find date column for freshness
    col_names = [c[0] for c in schema]
    date_col = None
    for candidate in DATE_CANDIDATES:
        if candidate in col_names:
            date_col = candidate
            break

    if date_col:
        q = f"SELECT MIN({date_col}) AS mn, MAX({date_col}) AS mx FROM `{full_id}`"
        for row in client.query(q).result():
            mn = row.mn
            mx = row.mx
            if mn is not None:
                result["freshness"] = {
                    "date_column": date_col,
                    "min": str(mn.date() if isinstance(mn, datetime) else mn),
                    "max": str(mx.date() if isinstance(mx, datetime) else mx),
                }

    # 3. Find sources
    for src_col in SOURCE_CANDIDATES:
        if src_col in col_names:
            q = f"SELECT DISTINCT {src_col} AS val FROM `{full_id}` WHERE {src_col} IS NOT NULL ORDER BY val"
            sources = [row.val for row in client.query(q).result()]
            if sources:
                result["sources"] = {src_col: sources}
            break

    # 4. Per-column stats
    for col_name, col_type in schema:
        if col_name in ("hash_riga",):
            result["columns"][col_name] = {"type": col_type}
            continue

        if col_type in ("FLOAT", "INTEGER", "NUMERIC"):
            q = f"""
            SELECT
              COUNT(DISTINCT {col_name}) AS dist,
              MIN({col_name}) AS mn,
              MAX({col_name}) AS mx
            FROM `{full_id}`
            """
            for row in client.query(q).result():
                result["columns"][col_name] = _column_stats(
                    col_name, col_type,
                    distinct=row.dist, values=None, sample=None,
                    min_val=row.mn, max_val=row.mx,
                )

        elif col_type in ("DATE", "TIMESTAMP", "DATETIME"):
            q = f"""
            SELECT
              COUNT(DISTINCT {col_name}) AS dist,
              MIN({col_name}) AS mn,
              MAX({col_name}) AS mx
            FROM `{full_id}`
            """
            for row in client.query(q).result():
                mn = row.mn
                mx = row.mx
                result["columns"][col_name] = _column_stats(
                    col_name, col_type,
                    distinct=row.dist, values=None, sample=None,
                    min_val=str(mn.date() if isinstance(mn, datetime) else mn) if mn else None,
                    max_val=str(mx.date() if isinstance(mx, datetime) else mx) if mx else None,
                )

        elif col_type == "STRING":
            q = f"SELECT COUNT(DISTINCT {col_name}) AS dist FROM `{full_id}`"
            dist = 0
            for row in client.query(q).result():
                dist = row.dist

            values = None
            sample = None
            if dist <= VALUES_THRESHOLD:
                q = f"SELECT DISTINCT {col_name} AS val FROM `{full_id}` WHERE {col_name} IS NOT NULL ORDER BY val"
                values = [row.val for row in client.query(q).result()]
            elif dist <= SAMPLE_THRESHOLD:
                q = f"""
                SELECT {col_name} AS val, COUNT(*) AS n
                FROM `{full_id}` WHERE {col_name} IS NOT NULL
                GROUP BY {col_name} ORDER BY n DESC LIMIT {SAMPLE_SIZE}
                """
                values = [row.val for row in client.query(q).result()]
            else:
                q = f"""
                SELECT {col_name} AS val, COUNT(*) AS n
                FROM `{full_id}` WHERE {col_name} IS NOT NULL
                GROUP BY {col_name} ORDER BY n DESC LIMIT 5
                """
                sample = [row.val for row in client.query(q).result()]

            result["columns"][col_name] = _column_stats(
                col_name, col_type,
                distinct=dist, values=values, sample=sample,
                min_val=None, max_val=None,
            )

        elif col_type == "BOOLEAN":
            result["columns"][col_name] = {"type": col_type}
        else:
            result["columns"][col_name] = {"type": col_type}

    return result
```

- [ ] **Step 2: Add `generate_manifest()` function**

Append to `core/bq/manifest.py`:

```python
def _yaml_representer_date(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data))


def generate_manifest(
    output_path: str | Path | None = None,
    tables: list[str] | None = None,
) -> dict:
    """Generate manifest dict and optionally write to YAML file.

    Args:
        output_path: If given, write YAML to this path.
        tables: If given, only catalog these tables. Default: all TABLES.

    Returns:
        The manifest dict.
    """
    client = _get_client()
    target_tables = tables or TABLES

    manifest = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": PROJECT,
        "dataset": DATASET,
        "tables": {},
    }

    for table_name in target_tables:
        log.info("Introspecting %s ...", table_name)
        manifest["tables"][table_name] = _introspect_table(client, table_name)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Custom representer for date objects
        yaml.add_representer(date, _yaml_representer_date)

        with open(path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)
        log.info("Manifest written to %s", path)

    return manifest
```

- [ ] **Step 3: Test manually with a single table**

Run: `python -c "from core.bq.manifest import generate_manifest; m = generate_manifest(tables=['f_consumi_economato']); import json; print(json.dumps(m, indent=2, default=str))"`

Expected: JSON output showing rows=15572, columns with reparto_id distinct=22, etc.

- [ ] **Step 4: Commit**

```bash
git add core/bq/manifest.py
git commit -m "feat: add BQ introspection for manifest generation"
```

---

### Task 3: CLI subcommand `hotelops manifest`

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Add `cmd_manifest` function**

Add after the `cmd_health` function (around line 227) in `cli.py`:

```python
# ── Manifest: catalogo tabelle BQ ──────────────────────────────────────────

def cmd_manifest(args):
    """Genera manifest.yaml — catalogo di tutte le tabelle BQ."""
    from core.bq.manifest import generate_manifest, TABLES
    from pathlib import Path
    import json

    output = args.output or "core/bq/manifest.yaml"
    tables = [args.table] if args.table else None

    print(f"\n  Generating manifest for {len(tables or TABLES)} tables → {output}")
    manifest = generate_manifest(output_path=output, tables=tables)

    n_tables = len(manifest["tables"])
    total_rows = sum(t.get("rows", 0) for t in manifest["tables"].values())
    print(f"  ✓ {n_tables} tables cataloged, {total_rows:,} total rows")
    print(f"  ✓ Written to {output}")
```

- [ ] **Step 2: Register the subcommand in `main()`**

In `cli.py`, add after the `classifica` parser block (around line 811):

```python
    # manifest
    p_manifest = sub.add_parser("manifest", help="Genera catalogo tabelle BQ")
    p_manifest.add_argument("--table", help="Singola tabella (default: tutte)")
    p_manifest.add_argument("--output", help="Output path (default: core/bq/manifest.yaml)")
```

In the `handlers` dict (around line 819), add:

```python
        "manifest": cmd_manifest,
```

- [ ] **Step 3: Update help text**

In the `cmd_help` function text, add under UTILITÀ:

```
  manifest        Genera catalogo metadata tabelle BQ (manifest.yaml)
                    hotelops manifest                tutte le tabelle
                    hotelops manifest --table f_consumi_economato
```

- [ ] **Step 4: Test the command**

Run: `python -m cli manifest --table f_consumi_economato`

Expected: output showing "1 tables cataloged" and file written to `core/bq/manifest.yaml`.

- [ ] **Step 5: Generate the full manifest**

Run: `python -m cli manifest`

Expected: all 18 tables cataloged. Inspect `core/bq/manifest.yaml` to verify content.

- [ ] **Step 6: Commit**

```bash
git add cli.py core/bq/manifest.yaml
git commit -m "feat: add hotelops manifest CLI command"
```

---

### Task 4: Fix budget double-counting in v_budget_vs_consuntivo

**Files:**
- Modify: `core/bq/views/v_budget_vs_consuntivo.sql` (if it exists locally, otherwise create it)
- Deploy via BQ

The current `budget` CTE does `SUM(importo)` grouped by `codice_conto, mese` — this sums across all 9 fonti. Fix: add a priority-based dedup using `ROW_NUMBER()`.

- [ ] **Step 1: Check if the view SQL exists locally**

Run: `ls core/bq/views/v_budget_vs_consuntivo.sql 2>/dev/null || echo "NOT LOCAL"`

The CLAUDE.md says this view is "BQ-only (no local SQL)". If it doesn't exist locally, create it.

- [ ] **Step 2: Write the fixed view SQL**

Create or update `core/bq/views/v_budget_vs_consuntivo.sql`:

```sql
-- v_budget_vs_consuntivo: Budget vs Consuntivo per codice conto
-- Fix: priorità fonti — dove esiste una fonte specifica, vince su GASPAROTTO.
-- Ordine: STRUTTURALI > MAPPATURA > PERSONALE > INCIDENZA > CONS2025_* > GASPAROTTO

WITH budget_ranked AS (
  SELECT
    societa_id,
    anno,
    mese,
    REPLACE(codice_conto, '.', '') AS cod_conto_norm,
    codice_conto,
    descrizione,
    tipo_costo,
    categoria_ce,
    importo,
    fonte,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, anno, mese, REPLACE(codice_conto, '.', '')
      ORDER BY CASE fonte
        WHEN 'STRUTTURALI' THEN 1
        WHEN 'MAPPATURA' THEN 2
        WHEN 'PERSONALE' THEN 3
        WHEN 'INCIDENZA' THEN 4
        WHEN 'CONS2025_F' THEN 5
        WHEN 'CONS2025_V' THEN 5
        WHEN 'CONS2025_IP' THEN 5
        WHEN 'CONS2025_X' THEN 5
        WHEN 'GASPAROTTO' THEN 6
        ELSE 7
      END
    ) AS rn
  FROM `hotelops-suite.hotelops.f_budget_mensile`
  WHERE anno = 2026
),

budget AS (
  SELECT
    societa_id,
    anno,
    mese,
    cod_conto_norm,
    codice_conto,
    descrizione AS budget_descrizione,
    tipo_costo,
    categoria_ce,
    importo AS budget_mensile,
    fonte AS budget_fonte
  FROM budget_ranked
  WHERE rn = 1
),

actuals AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM data_registrazione) AS anno,
    EXTRACT(MONTH FROM data_registrazione) AS mese,
    cod_conto AS cod_conto_norm,
    CASE
      WHEN LENGTH(cod_conto) >= 6 THEN
        CONCAT(SUBSTR(cod_conto, 1, 2), '.', SUBSTR(cod_conto, 3, 2), '.', SUBSTR(cod_conto, 5))
      ELSE cod_conto
    END AS codice_conto_display,
    SUM(imp_dare) AS tot_dare,
    SUM(imp_avere) AS tot_avere,
    SUM(imp_dare - imp_avere) AS consuntivo_netto,
    COUNT(*) AS n_movimenti
  FROM `hotelops-suite.hotelops.f_movimenti_contabili`
  WHERE EXTRACT(YEAR FROM data_registrazione) = 2026
  GROUP BY societa_id, EXTRACT(YEAR FROM data_registrazione),
           EXTRACT(MONTH FROM data_registrazione), cod_conto
),

pdc AS (
  SELECT
    REPLACE(codice_conto, '.', '') AS cod_conto_norm,
    codice_conto,
    descrizione,
    tipo_conto,
    sezione
  FROM `hotelops-suite.hotelops.d_piano_conti`
)

SELECT
  COALESCE(b.societa_id, a.societa_id) AS societa_id,
  COALESCE(b.anno, a.anno) AS anno,
  COALESCE(b.mese, a.mese) AS mese,
  COALESCE(b.cod_conto_norm, a.cod_conto_norm) AS cod_conto,
  COALESCE(b.codice_conto, a.codice_conto_display) AS codice_conto_display,
  COALESCE(pdc.descrizione, b.budget_descrizione) AS descrizione,
  COALESCE(pdc.tipo_conto, 'CE') AS tipo_conto,
  COALESCE(pdc.sezione, '') AS sezione,
  b.tipo_costo,
  b.categoria_ce,
  b.budget_fonte,

  COALESCE(b.budget_mensile, 0) AS budget,
  COALESCE(a.consuntivo_netto, 0) AS consuntivo,
  COALESCE(a.n_movimenti, 0) AS n_movimenti,

  COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0) AS delta,

  SAFE_DIVIDE(
    COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0),
    ABS(NULLIF(b.budget_mensile, 0))
  ) AS delta_pct,

  CASE
    WHEN b.budget_mensile IS NULL AND a.consuntivo_netto IS NOT NULL THEN 'SOLO_CONSUNTIVO'
    WHEN a.consuntivo_netto IS NULL AND b.budget_mensile IS NOT NULL THEN 'SOLO_BUDGET'
    WHEN ABS(COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0)) < 1 THEN 'OK'
    WHEN COALESCE(a.consuntivo_netto, 0) > COALESCE(b.budget_mensile, 0) * 1.1 THEN 'OVER_10PCT'
    WHEN COALESCE(a.consuntivo_netto, 0) < COALESCE(b.budget_mensile, 0) * 0.9 THEN 'UNDER_10PCT'
    ELSE 'IN_RANGE'
  END AS status

FROM budget b
FULL OUTER JOIN actuals a
  ON b.societa_id = a.societa_id
  AND b.anno = a.anno
  AND b.mese = a.mese
  AND b.cod_conto_norm = a.cod_conto_norm
LEFT JOIN pdc
  ON COALESCE(b.cod_conto_norm, a.cod_conto_norm) = pdc.cod_conto_norm
```

- [ ] **Step 3: Deploy the view to BQ**

Run: `python -c "
from google.cloud import bigquery
from pathlib import Path

client = bigquery.Client(project='hotelops-suite')
sql = Path('core/bq/views/v_budget_vs_consuntivo.sql').read_text()
view_id = 'hotelops-suite.hotelops.v_budget_vs_consuntivo'
view = bigquery.Table(view_id)
view.view_query = sql
client.update_table(view, ['view_query'])
print('View updated')
"`

Expected: "View updated"

- [ ] **Step 4: Verify the fix — compare old vs new budget for known double-counted code**

Run: `python -m cli bva --mese 1 --limit 5`

Check that `65.11.01` (Canoni passivi affitto d'azienda) now shows ~83,907 (STRUTTURALI only), NOT ~85,210 (STRUTTURALI + GASPAROTTO).

- [ ] **Step 5: Commit**

```bash
git add core/bq/views/v_budget_vs_consuntivo.sql
git commit -m "fix: budget fonte priority in v_budget_vs_consuntivo

ROW_NUMBER dedup picks highest-priority fonte per codice_conto×mese.
STRUTTURALI > MAPPATURA > PERSONALE > INCIDENZA > CONS2025_* > GASPAROTTO.
Eliminates double-counting from overlapping budget fonti."
```

---

### Task 5: Update CLAUDE.md and ontology

**Files:**
- Modify: `CLAUDE.md`
- Modify: `core/ontology.yaml`

- [ ] **Step 1: Add manifest command to CLAUDE.md**

In the Commands section of `CLAUDE.md`, under the existing commands, add:

```
hotelops manifest                          # Generate BQ table catalog (manifest.yaml)
hotelops manifest --table f_consumi_economato  # Single table
```

- [ ] **Step 2: Update ontology — add manifest reference**

In `core/ontology.yaml`, at the end of the file (or in a new section), add:

```yaml
# ══════════════════════════════════════════════════════════════════════════════
# MANIFEST
# ══════════════════════════════════════════════════════════════════════════════
# Auto-generated catalog of what's inside each BQ table.
# Regenerate: hotelops manifest
# Location: core/bq/manifest.yaml

manifest:
  path: core/bq/manifest.yaml
  generated_by: "hotelops manifest"
  note: "L'ontologia dice cosa significa. Il manifest dice cosa c'e' dentro."
```

- [ ] **Step 3: Update f_budget_mensile entry in ontology to note priority**

In `core/ontology.yaml`, update the `f_budget_mensile` entry's `note` field:

```yaml
  f_budget_mensile:
    # ... existing fields ...
    note: "Fonti con priorita': STRUTTURALI > MAPPATURA > PERSONALE > INCIDENZA > CONS2025_* > GASPAROTTO. v_budget_vs_consuntivo usa ROW_NUMBER per dedup."
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md core/ontology.yaml
git commit -m "docs: add manifest command and budget priority to CLAUDE.md and ontology"
```
