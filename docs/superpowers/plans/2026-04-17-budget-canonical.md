# Budget Fonte Priority — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate budget double-counting by introducing `v_budget_canonical` as the single resolved budget truth, refactoring all consumers to read from it, and verifying with pytest invariants.

**Architecture:** Long-format canonical view encapsulates exact-code precedence + GASPAROTTO-only suppression scopes (category-level for PERSONALE/INCIDENZA, prefix-level for STRUTTURALI/MAPPATURA/CONS2025_*). Existing views (`v_budget`, `v_budget_vs_consuntivo`, etc.) become thin wrappers. Real-BQ pytest invariants verify grain, fonte recognition, deterministic winners, and row-count sanity.

**Tech Stack:** BigQuery (Standard SQL), Python 3.11, `google-cloud-bigquery`, `pytest 8`, project CLI (`hotelops`).

**Spec:** `docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `core/bq/views/v_budget_canonical.sql` | **Create** | Single rule site for fonte resolution. Header restates rule in plain language. |
| `tests/test_budget_canonical.py` | **Create** | 4 invariant tests + RECOGNIZED_FONTI constant. |
| `tests/conftest.py` | **Modify** | Add `bq_client` fixture (real BQ, skipped when `HOTELOPS_SKIP_BQ=1`). |
| `pyproject.toml` | **Modify** | Register `bq` pytest marker. |
| `core/bq/views/v_budget.sql` | **Modify (collapse)** | Thin pivot over canonical. |
| `core/bq/views/v_budget_vs_consuntivo.sql` | **Modify (swap)** | Replace dedup CTE with `SELECT FROM v_budget_canonical`. |
| `core/bq/views/v_condges_budget_consuntivo.sql` | **Audit + Maybe Modify** | Migrate if it reads `f_budget_mensile` directly. |
| `condges/app_cdg.py` | **Audit + Maybe Modify** | Migrate any direct `f_budget_mensile` reads. |
| `condges/cli_commands.py` | **Modify** | Add CANONICAL block to `cmd_health` output. |
| `CLAUDE.md` | **Modify** | Add view to Views table; add governance rule; link spec. |
| `Obsidian Vault/hotelops/decisions/2026-04-17-budget-canonical.md` | **Create** | Short pointer to the Git spec. |

---

## Pre-flight

Working directory: `/Users/stefanodellapietra/dev/Projects/hotelops` on branch `main`. The spec was committed in `f900114`. All work happens on `main` (Stefano's preference).

BigQuery auth: `gcloud auth application-default login` already active as `stefano@panoramagroup.it` against project `hotelops-suite`.

---

## Task 1: Real-BQ Test Infrastructure

Adds the minimum infrastructure for tests that need to query live BigQuery.

**Files:**
- Modify: `pyproject.toml` (lines around `[tool.pytest.ini_options]`)
- Modify: `tests/conftest.py`

- [ ] **Step 1: Register the `bq` pytest marker**

Edit `pyproject.toml`. Find the `[tool.pytest.ini_options]` block:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

Add a `markers` line:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
    "bq: tests that query live BigQuery (skip with -m 'not bq' or HOTELOPS_SKIP_BQ=1)",
]
```

- [ ] **Step 2: Add `bq_client` fixture to conftest.py**

Edit `tests/conftest.py`. After the existing `mock_bq_client` fixture, append:

```python
import os


@pytest.fixture(scope="session")
def bq_client():
    """Real BigQuery client for invariant tests against live views.

    Skipped when HOTELOPS_SKIP_BQ=1 (CI / offline development).
    Tests using this fixture should also be marked @pytest.mark.bq.
    """
    if os.environ.get("HOTELOPS_SKIP_BQ") == "1":
        pytest.skip("HOTELOPS_SKIP_BQ=1 — skipping live BigQuery test")
    from google.cloud import bigquery
    return bigquery.Client(project="hotelops-suite")
```

- [ ] **Step 3: Verify the marker is registered**

Run: `pytest --markers | grep bq`
Expected output includes: `@pytest.mark.bq: tests that query live BigQuery ...`

- [ ] **Step 4: Verify existing tests still pass**

Run: `pytest -m "not bq"`
Expected: all existing tests pass (we haven't added any `bq`-marked tests yet, so this should be a no-op smoke check).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/conftest.py
git commit -m "$(cat <<'EOF'
test: add real-BQ test infrastructure (bq marker + bq_client fixture)

Enables pytest invariant tests against live BigQuery views.
Tests using the bq_client fixture should be marked @pytest.mark.bq
and can be skipped via HOTELOPS_SKIP_BQ=1 or pytest -m 'not bq'.

Prep for the v_budget_canonical invariant test suite.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create `v_budget_canonical` view

The single rule site. This is the load-bearing artifact. SQL header restates the rule in plain language so anyone reading the file understands without running it.

**Files:**
- Create: `core/bq/views/v_budget_canonical.sql`

- [ ] **Step 1: Create the SQL file**

Create `core/bq/views/v_budget_canonical.sql` with exactly this content:

```sql
-- v_budget_canonical — the resolved budget truth.
--
-- Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md
--
-- THE RULE (do not re-implement downstream — see spec §5 "Rule locality"):
--
-- 1. Exact-code precedence (applies across all recognized fonti):
--      STRUTTURALI > MAPPATURA > PERSONALE > INCIDENZA > CONS2025_* > GASPAROTTO
--    For a given (societa_id, anno, mese, cod_conto), the highest-precedence
--    fonte wins.
--
-- 2. GASPAROTTO-only suppression scopes:
--    - Category-level (PERSONALE, INCIDENZA): if either covers a categoria_ce,
--      ALL GASPAROTTO rows in that category are suppressed (including sibling
--      codes not matched by exact-code).
--    - Prefix-level 4-digit (STRUTTURALI, MAPPATURA, CONS2025_*): if a non-
--      GASPAROTTO fonte covers a (categoria_ce, 4-digit prefix) pair, GASPAROTTO
--      rows sharing both are suppressed.
--    Non-GASPAROTTO sources do NOT suppress each other — only exact-code
--    precedence governs their interaction.
--
-- 3. Fallback: GASPAROTTO is the base; non-GASPAROTTO sources suppress or
--    replace it where covered, otherwise GASPAROTTO remains canonical.
--
-- Canonical key: (societa_id, anno, mese, cod_conto) — cod_conto dots-stripped.
-- Grain: exactly one row per canonical key.
-- Year scope: all years (consumers filter as needed).
--
-- Recognized fonte set (CHANGE TOGETHER with tests/test_budget_canonical.py):
--   STRUTTURALI, MAPPATURA, PERSONALE, INCIDENZA,
--   CONS2025_F, CONS2025_V, CONS2025_IP, CONS2025_X, GASPAROTTO
-- No silent ELSE branch in the precedence CASE — unrecognized fonti get
-- NULL rank and are caught by the recognized_fonte_set test.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_budget_canonical` AS

WITH budget_ranked AS (
  SELECT
    societa_id,
    anno,
    mese,
    REPLACE(codice_conto, '.', '') AS cod_conto,
    codice_conto AS codice_conto_display,
    descrizione,
    tipo_costo,
    categoria_ce,
    importo,
    fonte,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, anno, mese, REPLACE(codice_conto, '.', '')
      ORDER BY CASE fonte
        WHEN 'STRUTTURALI'  THEN 1
        WHEN 'MAPPATURA'    THEN 2
        WHEN 'PERSONALE'    THEN 3
        WHEN 'INCIDENZA'    THEN 4
        WHEN 'CONS2025_F'   THEN 5
        WHEN 'CONS2025_V'   THEN 5
        WHEN 'CONS2025_IP'  THEN 5
        WHEN 'CONS2025_X'   THEN 5
        WHEN 'GASPAROTTO'   THEN 6
        -- No ELSE: unrecognized fonti get NULL rank → sort last → caught
        -- by tests/test_budget_canonical.py::test_recognized_fonte_set.
      END
    ) AS rn
  FROM `hotelops-suite.hotelops.f_budget_mensile`
),

-- Step A: exact-code precedence — keep only rank-1 per canonical key.
budget_exact AS (
  SELECT * FROM budget_ranked WHERE rn = 1
),

-- Step B: identify GASPAROTTO-only suppression scopes.
-- Category-level: PERSONALE or INCIDENZA covering a (societa, anno, categoria_ce).
suppress_category AS (
  SELECT DISTINCT societa_id, anno, categoria_ce
  FROM budget_exact
  WHERE fonte IN ('PERSONALE', 'INCIDENZA')
),

-- Prefix-level: any non-GASPAROTTO fonte covering (societa, anno, categoria_ce, 4-digit prefix).
suppress_prefix AS (
  SELECT DISTINCT
    societa_id,
    anno,
    categoria_ce,
    SUBSTR(cod_conto, 1, 4) AS prefix4
  FROM budget_exact
  WHERE fonte != 'GASPAROTTO'
)

-- Step C: emit canonical rows.
-- Non-GASPAROTTO rows survive unconditionally.
-- GASPAROTTO rows survive only if NOT suppressed by category and NOT by prefix.
SELECT
  b.societa_id,
  b.anno,
  b.mese,
  b.cod_conto,
  b.codice_conto_display,
  COALESCE(p.descrizione, b.descrizione) AS descrizione,
  b.tipo_costo,
  b.categoria_ce,
  b.importo,
  b.fonte
FROM budget_exact b
LEFT JOIN `hotelops-suite.hotelops.d_piano_conti` p
  ON REPLACE(p.codice_conto, '.', '') = b.cod_conto
WHERE
  b.fonte != 'GASPAROTTO'
  OR (
    NOT EXISTS (
      SELECT 1 FROM suppress_category sc
      WHERE sc.societa_id = b.societa_id
        AND sc.anno = b.anno
        AND sc.categoria_ce = b.categoria_ce
    )
    AND NOT EXISTS (
      SELECT 1 FROM suppress_prefix sp
      WHERE sp.societa_id = b.societa_id
        AND sp.anno = b.anno
        AND sp.categoria_ce = b.categoria_ce
        AND sp.prefix4 = SUBSTR(b.cod_conto, 1, 4)
    )
  );
```

- [ ] **Step 2: Deploy the view to BigQuery**

Run:

```bash
bq query --use_legacy_sql=false --project_id=hotelops-suite \
  < core/bq/views/v_budget_canonical.sql
```

Expected output: `Successfully created view ...v_budget_canonical`. If you see a syntax error, fix the SQL before proceeding.

- [ ] **Step 3: Smoke check the view exists and returns rows**

Run:

```bash
bq query --use_legacy_sql=false --format=pretty \
  "SELECT COUNT(*) AS n FROM \`hotelops-suite.hotelops.v_budget_canonical\`"
```

Expected: a single row with `n` between 500 and 2000 (must be > 0 and ≤ raw row count of 2733).

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_budget_canonical.sql
git commit -m "$(cat <<'EOF'
feat(bq): add v_budget_canonical — single resolved budget truth

Canonical view encapsulating fonte resolution per the spec:
- exact-code precedence across all recognized fonti
- GASPAROTTO-only category-level suppression (PERSONALE/INCIDENZA)
- GASPAROTTO-only prefix-level suppression (STRUTTURALI/MAPPATURA/CONS2025_*)
- no silent ELSE branch — unrecognized fonti caught by tests
- all years, no CURRENT_DATE() filter

Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Invariant Test T1 — Grain Uniqueness

The most fundamental invariant: exactly one row per canonical key.

**Files:**
- Create: `tests/test_budget_canonical.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_budget_canonical.py` with:

```python
"""Invariant tests for v_budget_canonical.

These tests query live BigQuery. They are marked @pytest.mark.bq and skipped
when HOTELOPS_SKIP_BQ=1.

The RECOGNIZED_FONTI constant below is the authoritative declaration of which
fonti exist in f_budget_mensile. The SQL CASE in v_budget_canonical.sql must
list exactly these names. Any drift between the two is a bug — caught by
test_recognized_fonte_set.

Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md
"""

from __future__ import annotations

import pytest


RECOGNIZED_FONTI = {
    "STRUTTURALI",
    "MAPPATURA",
    "PERSONALE",
    "INCIDENZA",
    "CONS2025_F",
    "CONS2025_V",
    "CONS2025_IP",
    "CONS2025_X",
    "GASPAROTTO",
}


@pytest.mark.bq
def test_grain_uniqueness(bq_client):
    """T1: Exactly one row per (societa_id, anno, mese, cod_conto).

    Implicitly also covers 'no duplicate winners': if two rows share a grain,
    ROW_NUMBER produced two rn=1 candidates that the SQL didn't resolve.
    """
    sql = """
    SELECT societa_id, anno, mese, cod_conto, COUNT(*) AS n
    FROM `hotelops-suite.hotelops.v_budget_canonical`
    GROUP BY societa_id, anno, mese, cod_conto
    HAVING n > 1
    LIMIT 10
    """
    rows = list(bq_client.query(sql).result())
    assert not rows, (
        f"Grain violation in v_budget_canonical: {len(rows)} duplicate keys. "
        f"First: {dict(rows[0]) if rows else 'n/a'}"
    )
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_budget_canonical.py::test_grain_uniqueness -v`

Expected: PASS. (The view from Task 2 should already satisfy this invariant — `ROW_NUMBER() ... WHERE rn = 1` guarantees uniqueness on the partition key.) If FAIL, the bug is in `v_budget_canonical.sql` — fix the view, redeploy, re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_budget_canonical.py
git commit -m "$(cat <<'EOF'
test(bq): T1 grain uniqueness invariant for v_budget_canonical

Asserts exactly one row per (societa_id, anno, mese, cod_conto) — the
canonical key. Also implicitly covers 'no duplicate winners'.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Invariant Test T2 — Recognized Fonte Set

Catches any new fonte added to `f_budget_mensile` that isn't in the precedence list. Replaces a silent SQL `ELSE` with a loud test failure.

**Files:**
- Modify: `tests/test_budget_canonical.py`

- [ ] **Step 1: Append the test**

Edit `tests/test_budget_canonical.py`. After `test_grain_uniqueness`, append:

```python
@pytest.mark.bq
def test_recognized_fonte_set(bq_client):
    """T2: Every fonte in f_budget_mensile must be in RECOGNIZED_FONTI.

    This protects against silent rank-NULL fallthrough. If this fails, a new
    fonte was added without updating the precedence rule.
    """
    sql = """
    SELECT DISTINCT fonte
    FROM `hotelops-suite.hotelops.f_budget_mensile`
    """
    found = {r["fonte"] for r in bq_client.query(sql).result()}
    unknown = found - RECOGNIZED_FONTI
    assert not unknown, (
        f"Unrecognized fonti in f_budget_mensile: {unknown}.\n"
        f"To fix:\n"
        f"  1. Decide each fonte's precedence rank.\n"
        f"  2. Add to RECOGNIZED_FONTI in tests/test_budget_canonical.py.\n"
        f"  3. Add to the CASE in core/bq/views/v_budget_canonical.sql.\n"
        f"  4. Redeploy the view.\n"
    )
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_budget_canonical.py::test_recognized_fonte_set -v`

Expected: PASS. (Health output earlier confirmed exactly the 9 fonti in `RECOGNIZED_FONTI` are present.) If FAIL, follow the failure message instructions.

- [ ] **Step 3: Commit**

```bash
git add tests/test_budget_canonical.py
git commit -m "$(cat <<'EOF'
test(bq): T2 recognized fonte set invariant

Fails loud if f_budget_mensile contains a fonte not declared in
RECOGNIZED_FONTI. Replaces what would have been a silent SQL ELSE branch
with a CI-detectable error and clear remediation steps.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Invariant Test T3 — Deterministic Winner Cases

Pin known overlaps to expected winning fonte. Three cases verified during the brainstorm; two more added here to cover MAPPATURA and category-level suppression.

**Files:**
- Modify: `tests/test_budget_canonical.py`

- [ ] **Step 1: Identify two more cases via BigQuery**

Run this to find a MAPPATURA winner case:

```bash
bq query --use_legacy_sql=false --format=pretty --max_rows=5 "
SELECT societa_id, anno, mese, REPLACE(codice_conto,'.','') AS cod_conto, fonte, ROUND(importo,0) AS imp
FROM \`hotelops-suite.hotelops.v_budget_canonical\`
WHERE anno = 2026 AND fonte = 'MAPPATURA' AND mese = 1
ORDER BY ABS(importo) DESC
LIMIT 5
"
```

Pick one row. Record `societa_id, anno, mese, cod_conto`. The expected fonte is `MAPPATURA`.

Then run this to find a category-suppression case (a GASPAROTTO row that DID survive vs one that was suppressed):

```bash
bq query --use_legacy_sql=false --format=pretty --max_rows=5 "
WITH suppressed AS (
  SELECT DISTINCT REPLACE(codice_conto,'.','') AS cod_conto
  FROM \`hotelops-suite.hotelops.f_budget_mensile\`
  WHERE fonte = 'GASPAROTTO' AND categoria_ce = 'Costo del Personale'
    AND anno = 2026
)
SELECT s.cod_conto, COUNT(*) AS n_in_canonical
FROM suppressed s
LEFT JOIN \`hotelops-suite.hotelops.v_budget_canonical\` c
  ON c.cod_conto = s.cod_conto AND c.anno = 2026
GROUP BY s.cod_conto
ORDER BY n_in_canonical
LIMIT 5
"
```

Pick a `cod_conto` with `n_in_canonical = 0` — that's a GASPAROTTO row in 'Costo del Personale' that was correctly category-suppressed. The test will assert this code does NOT appear in canonical with fonte = GASPAROTTO.

- [ ] **Step 2: Append the parameterized winner test**

Edit `tests/test_budget_canonical.py`. Append:

```python
# Format: (societa, anno, mese, cod_conto, expected_fonte, rationale)
# Expected fonte must be one of RECOGNIZED_FONTI.
KNOWN_WINNERS = [
    ("ORTI", 2026, 1, "670101", "PERSONALE",
     "payroll — PERSONALE > INCIDENZA > GASPAROTTO"),
    ("ORTI", 2026, 1, "651101", "STRUTTURALI",
     "fitto ORTI→INTUR — STRUTTURALI > GASPAROTTO"),
    ("ORTI", 2026, 1, "479101", "CONS2025_IP",
     "oneri 47 — CONS2025_IP > GASPAROTTO"),
    # TODO during execution: replace these placeholders with the rows
    # discovered in Task 5 Step 1.
    # ("ORTI", 2026, 1, "<cod_conto from Step 1>", "MAPPATURA",
    #  "MAPPATURA wins via exact-code precedence"),
]


@pytest.mark.bq
@pytest.mark.parametrize(
    "societa,anno,mese,cod_conto,expected_fonte,rationale", KNOWN_WINNERS
)
def test_deterministic_winner(
    bq_client, societa, anno, mese, cod_conto, expected_fonte, rationale,
):
    """T3: Known overlapping accounts resolve to the expected fonte."""
    from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig

    sql = """
    SELECT fonte
    FROM `hotelops-suite.hotelops.v_budget_canonical`
    WHERE societa_id = @s AND anno = @a AND mese = @m AND cod_conto = @c
    """
    job_config = QueryJobConfig(query_parameters=[
        ScalarQueryParameter("s", "STRING", societa),
        ScalarQueryParameter("a", "INT64", anno),
        ScalarQueryParameter("m", "INT64", mese),
        ScalarQueryParameter("c", "STRING", cod_conto),
    ])
    rows = list(bq_client.query(sql, job_config=job_config).result())
    assert len(rows) == 1, (
        f"Expected exactly 1 row for ({societa}, {anno}, {mese}, {cod_conto}), "
        f"got {len(rows)}"
    )
    assert rows[0]["fonte"] == expected_fonte, (
        f"For ({societa}, {anno}, {mese}, {cod_conto}): "
        f"expected fonte={expected_fonte} ({rationale}), got {rows[0]['fonte']}"
    )
```

- [ ] **Step 3: Append the category-suppression test using the cod_conto from Step 1**

Append (substituting the real cod_conto discovered in Step 1):

```python
@pytest.mark.bq
def test_category_level_suppression_drops_gasparotto_siblings(bq_client):
    """T3 (variant): A GASPAROTTO sibling code in 'Costo del Personale' must
    be suppressed by PERSONALE/INCIDENZA category-level coverage, even when
    PERSONALE has no row at the exact cod_conto.

    cod_conto chosen during plan execution from f_budget_mensile rows where
    fonte=GASPAROTTO AND categoria_ce='Costo del Personale' AND the row was
    successfully suppressed (i.e., has n_in_canonical = 0).
    """
    suppressed_cod_conto = "<FILL FROM STEP 1>"  # replace before running

    from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig

    sql = """
    SELECT COUNT(*) AS n
    FROM `hotelops-suite.hotelops.v_budget_canonical`
    WHERE cod_conto = @c AND fonte = 'GASPAROTTO' AND anno = 2026
    """
    job_config = QueryJobConfig(query_parameters=[
        ScalarQueryParameter("c", "STRING", suppressed_cod_conto),
    ])
    n = next(bq_client.query(sql, job_config=job_config).result())["n"]
    assert n == 0, (
        f"GASPAROTTO row for {suppressed_cod_conto} should be suppressed by "
        f"category-level rule (PERSONALE/INCIDENZA covers 'Costo del Personale'), "
        f"but {n} GASPAROTTO rows survived."
    )
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_budget_canonical.py -v -k "deterministic_winner or category_level_suppression"`

Expected: all PASS. If a parameterized case fails, the rationale points at where the rule broke.

- [ ] **Step 5: Commit**

```bash
git add tests/test_budget_canonical.py
git commit -m "$(cat <<'EOF'
test(bq): T3 deterministic winner + category suppression invariants

Pins known overlap resolutions:
- 670101 → PERSONALE (payroll)
- 651101 → STRUTTURALI (fitto intercompany)
- 479101 → CONS2025_IP (oneri 47)
- a GASPAROTTO 'Costo del Personale' sibling code must be category-suppressed

Each case carries a rationale so test failures are self-explaining.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Invariant Test T4 — Row Count Sanity

Dedup must never invent rows. Canonical row count ≤ raw row count at any `(societa, anno, mese)` scope.

**Files:**
- Modify: `tests/test_budget_canonical.py`

- [ ] **Step 1: Append the test**

Edit `tests/test_budget_canonical.py`. Append:

```python
@pytest.mark.bq
def test_canonical_never_expands_raw(bq_client):
    """T4: Canonical row count ≤ raw row count at the (societa, anno, mese)
    scope. Dedup must reduce or preserve, never invent.
    """
    sql = """
    WITH raw AS (
      SELECT societa_id, anno, mese, COUNT(*) AS n_raw
      FROM `hotelops-suite.hotelops.f_budget_mensile`
      GROUP BY societa_id, anno, mese
    ),
    canon AS (
      SELECT societa_id, anno, mese, COUNT(*) AS n_canon
      FROM `hotelops-suite.hotelops.v_budget_canonical`
      GROUP BY societa_id, anno, mese
    )
    SELECT
      r.societa_id, r.anno, r.mese, r.n_raw, COALESCE(c.n_canon, 0) AS n_canon
    FROM raw r
    LEFT JOIN canon c USING (societa_id, anno, mese)
    WHERE COALESCE(c.n_canon, 0) > r.n_raw
    LIMIT 10
    """
    rows = list(bq_client.query(sql).result())
    assert not rows, (
        f"Dedup expanded rows in {len(rows)} (societa, anno, mese) scopes. "
        f"First: {dict(rows[0]) if rows else 'n/a'}"
    )
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_budget_canonical.py::test_canonical_never_expands_raw -v`

Expected: PASS.

- [ ] **Step 3: Run the full canonical test suite**

Run: `pytest tests/test_budget_canonical.py -v`

Expected: all 4+ tests PASS (T1, T2, T3 parameterized × N, T3 category, T4).

- [ ] **Step 4: Commit**

```bash
git add tests/test_budget_canonical.py
git commit -m "$(cat <<'EOF'
test(bq): T4 row count sanity invariant

Canonical row count ≤ raw row count per (societa, anno, mese) scope.
Dedup must reduce or preserve, never invent. Closes the 4-test load-bearing
invariant set for v_budget_canonical.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Audit Existing Consumers

Before parallel refactors, determine which consumers actually need code changes vs. inherit the fix automatically. Output: an audit note that pins down Task 9 and Task 10 scope.

**Files:**
- Read-only: `core/bq/views/v_condges_budget_consuntivo.sql`
- Read-only: `condges/app_cdg.py`

- [ ] **Step 1: Audit `v_condges_budget_consuntivo.sql`**

Read `core/bq/views/v_condges_budget_consuntivo.sql`. Look for which table/view it reads from.

Decision tree:
- Reads `f_budget_mensile` directly → **needs migration** in Task 9.
- Reads `v_budget` or `v_budget_vs_consuntivo` → **inherits fix from Tasks 8a/8b**, no direct edit needed.
- Reads `v_budget_canonical` → already correct (impossible since we just created it, but document anyway).

Record finding in the next step's commit message.

- [ ] **Step 2: Audit `condges/app_cdg.py`**

Run:

```bash
grep -n "f_budget_mensile\|v_budget\|v_budget_canonical" condges/app_cdg.py
```

Same decision tree as Step 1. Record finding.

- [ ] **Step 3: Audit any other Python that reads budget**

Run:

```bash
grep -rn "f_budget_mensile" --include="*.py" --include="*.sql" \
  | grep -v "^docs/" \
  | grep -v "ingest/flussi/ingest_gasparotto.py" \
  | grep -v "core/bq/load/load_budget_costi.py" \
  | grep -v "core/bq/views/v_budget" \
  | grep -v "tests/test_budget_canonical.py"
```

Any unexpected hits are additional consumers. If found, add them to the migration list (extend Task 9 or 10) and note them in the audit summary.

- [ ] **Step 4: Write audit summary as a single commit (no code change)**

Create `docs/superpowers/plans/2026-04-17-budget-canonical-AUDIT.md` with content like:

```markdown
# Audit results — Task 7 of budget canonical plan

## v_condges_budget_consuntivo.sql
Reads: <table or view name found in Step 1>
Action: <"migrate to v_budget_canonical" | "inherits fix, no edit needed">

## condges/app_cdg.py
Reads: <table or view name(s) found in Step 2>
Action: <"migrate to v_budget_canonical" | "inherits fix, no edit needed">

## Other Python consumers
<list any extras from Step 3, or "none">

## Implications for Tasks 9 and 10
<one paragraph>
```

Then commit:

```bash
git add docs/superpowers/plans/2026-04-17-budget-canonical-AUDIT.md
git commit -m "$(cat <<'EOF'
docs(plan): audit budget consumers before parallel refactor

Records which consumers need direct migration vs which inherit the fix
through v_budget / v_budget_vs_consuntivo. Pins down the scope of
Tasks 9 and 10.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Tasks 8 & 9 & 10 — Parallel Consumer Migrations

**These three tasks are independent (different files, no shared state) and may run as parallel subagents per the spec's migration order §11.**

Each task captures its own "before" query, performs the edit, redeploys (if SQL), and verifies the "after" query matches the canonical baseline.

---

## Task 8: Refactor `v_budget.sql` — Thin Pivot Over Canonical

Collapse `v_budget` to a pivot-only view. All dedup logic moves out.

**Files:**
- Modify: `core/bq/views/v_budget.sql`

- [ ] **Step 1: Capture baseline**

Run and save the output to a scratch file:

```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT societa_id, cod_conto, ROUND(totale_annuo, 0) AS totale
   FROM \`hotelops-suite.hotelops.v_budget\`
   WHERE anno = 2026 ORDER BY societa_id, cod_conto" \
  > /tmp/v_budget_before.csv
wc -l /tmp/v_budget_before.csv
```

Record the row count for the next step's comparison.

- [ ] **Step 2: Replace `v_budget.sql` with the thin pivot**

Overwrite `core/bq/views/v_budget.sql` with exactly:

```sql
-- v_budget: Budget mensile pivottato per cod_conto, 12 colonne mensili.
--
-- Reshape only — precedence/suppression live in v_budget_canonical.
-- Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_budget` AS

SELECT
  societa_id,
  anno,
  cod_conto,
  codice_conto_display,
  descrizione,
  tipo_costo,
  categoria_ce,
  fonte,
  SUM(IF(mese =  1, importo, 0)) AS gen,
  SUM(IF(mese =  2, importo, 0)) AS feb,
  SUM(IF(mese =  3, importo, 0)) AS mar,
  SUM(IF(mese =  4, importo, 0)) AS apr,
  SUM(IF(mese =  5, importo, 0)) AS mag,
  SUM(IF(mese =  6, importo, 0)) AS giu,
  SUM(IF(mese =  7, importo, 0)) AS lug,
  SUM(IF(mese =  8, importo, 0)) AS ago,
  SUM(IF(mese =  9, importo, 0)) AS sett,
  SUM(IF(mese = 10, importo, 0)) AS ott,
  SUM(IF(mese = 11, importo, 0)) AS nov,
  SUM(IF(mese = 12, importo, 0)) AS dic,
  SUM(importo) AS totale_annuo
FROM `hotelops-suite.hotelops.v_budget_canonical`
GROUP BY
  societa_id, anno, cod_conto, codice_conto_display,
  descrizione, tipo_costo, categoria_ce, fonte
ORDER BY societa_id, categoria_ce, cod_conto;
```

- [ ] **Step 3: Deploy the refactored view**

```bash
bq query --use_legacy_sql=false --project_id=hotelops-suite \
  < core/bq/views/v_budget.sql
```

Expected: `Successfully created view ...v_budget`.

- [ ] **Step 4: Capture post-refactor output and diff**

```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT societa_id, cod_conto, ROUND(totale_annuo, 0) AS totale
   FROM \`hotelops-suite.hotelops.v_budget\`
   WHERE anno = 2026 ORDER BY societa_id, cod_conto" \
  > /tmp/v_budget_after.csv
diff /tmp/v_budget_before.csv /tmp/v_budget_after.csv
```

Expected: empty diff (no business numbers should change — we're moving the same logic). If diff is non-empty, investigate before committing — the original `v_budget.sql` may have had subtle quirks the canonical view doesn't reproduce.

- [ ] **Step 5: Re-run canonical tests as regression check**

```bash
pytest tests/test_budget_canonical.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add core/bq/views/v_budget.sql
git commit -m "$(cat <<'EOF'
refactor(bq): collapse v_budget to thin pivot over v_budget_canonical

All dedup logic (exact-code precedence + GASPAROTTO suppression scopes)
moves to v_budget_canonical. v_budget keeps only its presentation
responsibility: long → wide pivot with monthly columns + annual total.

Verified: SELECT (societa, cod_conto, totale_annuo) WHERE anno=2026
produces identical CSV before/after the refactor.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Refactor `v_budget_vs_consuntivo.sql` — Swap Dedup CTE

Replace the local `budget_ranked` / `budget` CTEs with a `SELECT FROM v_budget_canonical`. Keep actuals join unchanged.

**Files:**
- Modify: `core/bq/views/v_budget_vs_consuntivo.sql`

- [ ] **Step 1: Capture baseline**

```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT societa_id, cod_conto, mese, ROUND(budget, 0) AS b, ROUND(consuntivo, 0) AS c
   FROM \`hotelops-suite.hotelops.v_budget_vs_consuntivo\`
   WHERE anno = 2026 ORDER BY societa_id, cod_conto, mese" \
  > /tmp/v_budget_vs_consuntivo_before.csv
wc -l /tmp/v_budget_vs_consuntivo_before.csv
```

**Important:** The current `v_budget_vs_consuntivo` uses the WEAKER dedup logic (per Section 2 of the spec). The "after" CSV WILL differ from "before" — that's the expected behavior of this refactor: it's the bug fix. Record the before-row-count so you can size the diff.

- [ ] **Step 2: Replace `v_budget_vs_consuntivo.sql`**

Overwrite `core/bq/views/v_budget_vs_consuntivo.sql` with:

```sql
-- v_budget_vs_consuntivo: Budget vs Consuntivo per (societa, cod_conto, mese).
--
-- Budget side reads from v_budget_canonical — the single resolved budget truth.
-- Do NOT re-implement precedence or suppression here. See spec §5 "Rule locality".
-- Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_budget_vs_consuntivo` AS

WITH budget AS (
  SELECT
    societa_id,
    anno,
    mese,
    cod_conto,
    codice_conto_display,
    descrizione AS budget_descrizione,
    tipo_costo,
    categoria_ce,
    importo AS budget_mensile,
    fonte AS budget_fonte
  FROM `hotelops-suite.hotelops.v_budget_canonical`
  WHERE anno = EXTRACT(YEAR FROM CURRENT_DATE())
),

actuals AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM data_registrazione) AS anno,
    EXTRACT(MONTH FROM data_registrazione) AS mese,
    cod_conto,
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
  WHERE EXTRACT(YEAR FROM data_registrazione) = EXTRACT(YEAR FROM CURRENT_DATE())
  GROUP BY societa_id, EXTRACT(YEAR FROM data_registrazione),
           EXTRACT(MONTH FROM data_registrazione), cod_conto
),

pdc AS (
  SELECT
    REPLACE(codice_conto, '.', '') AS cod_conto,
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
  COALESCE(b.cod_conto, a.cod_conto) AS cod_conto,
  COALESCE(b.codice_conto_display, a.codice_conto_display) AS codice_conto_display,
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
  AND b.cod_conto = a.cod_conto
LEFT JOIN pdc
  ON COALESCE(b.cod_conto, a.cod_conto) = pdc.cod_conto;
```

- [ ] **Step 3: Deploy**

```bash
bq query --use_legacy_sql=false --project_id=hotelops-suite \
  < core/bq/views/v_budget_vs_consuntivo.sql
```

Expected: `Successfully created view ...v_budget_vs_consuntivo`.

- [ ] **Step 4: Capture after, characterize the diff**

```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT societa_id, cod_conto, mese, ROUND(budget, 0) AS b, ROUND(consuntivo, 0) AS c
   FROM \`hotelops-suite.hotelops.v_budget_vs_consuntivo\`
   WHERE anno = 2026 ORDER BY societa_id, cod_conto, mese" \
  > /tmp/v_budget_vs_consuntivo_after.csv

diff /tmp/v_budget_vs_consuntivo_before.csv /tmp/v_budget_vs_consuntivo_after.csv \
  | head -50
```

Expected: a non-empty diff. The differences should be GASPAROTTO rows that were correctly suppressed by category-level or prefix-level rules in canonical but survived in the old weaker logic.

Spot-check: confirm the diff lines are indeed GASPAROTTO suppressions, not arbitrary value changes. Run:

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT cod_conto, budget_fonte, ROUND(budget,0) AS b
FROM \`hotelops-suite.hotelops.v_budget_vs_consuntivo\`
WHERE anno = 2026 AND mese = 1 AND categoria_ce = 'Costo del Personale'
ORDER BY cod_conto LIMIT 20
"
```

Expected: no GASPAROTTO rows in 'Costo del Personale' (PERSONALE/INCIDENZA suppress them).

- [ ] **Step 5: Re-run canonical tests**

```bash
pytest tests/test_budget_canonical.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add core/bq/views/v_budget_vs_consuntivo.sql
git commit -m "$(cat <<'EOF'
refactor(bq): v_budget_vs_consuntivo reads from v_budget_canonical

Replaces local budget_ranked + budget CTEs (weaker dedup logic) with a
SELECT FROM v_budget_canonical. Eliminates the divergence between this
view and v_budget — both now share the same resolution rule.

Behavior change: GASPAROTTO rows previously surviving in 'Costo del
Personale' and other category/prefix-suppressed scopes are now correctly
dropped on the budget side. This is the bug fix from spec §2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Migrate `v_condges_budget_consuntivo.sql` (conditional)

Conditional on Task 7 audit: only act if the file reads `f_budget_mensile` directly. Otherwise mark the task as no-op.

**Files:**
- Maybe modify: `core/bq/views/v_condges_budget_consuntivo.sql`

- [ ] **Step 1: Re-check audit conclusion from Task 7**

Read `docs/superpowers/plans/2026-04-17-budget-canonical-AUDIT.md` produced in Task 7. If the conclusion is *"inherits fix, no edit needed"* → skip to Step 4 (no-op commit).

If *"migrate to v_budget_canonical"* → proceed to Step 2.

- [ ] **Step 2: Capture baseline**

```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT * FROM \`hotelops-suite.hotelops.v_condges_budget_consuntivo\` LIMIT 1000" \
  > /tmp/v_condges_budget_consuntivo_before.csv
wc -l /tmp/v_condges_budget_consuntivo_before.csv
```

- [ ] **Step 3: Edit the SQL to read from `v_budget_canonical`**

Read the current file. Replace any `FROM \`hotelops-suite.hotelops.f_budget_mensile\`` reference with the appropriate `SELECT ... FROM \`hotelops-suite.hotelops.v_budget_canonical\``. Preserve all other logic. Update the file header comment to note the new dependency.

Deploy:

```bash
bq query --use_legacy_sql=false --project_id=hotelops-suite \
  < core/bq/views/v_condges_budget_consuntivo.sql
```

Capture after:

```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT * FROM \`hotelops-suite.hotelops.v_condges_budget_consuntivo\` LIMIT 1000" \
  > /tmp/v_condges_budget_consuntivo_after.csv
diff /tmp/v_condges_budget_consuntivo_before.csv /tmp/v_condges_budget_consuntivo_after.csv | head -30
```

Expected: differences correspond to suppressed GASPAROTTO rows (same character as Task 9).

Re-run pytest:

```bash
pytest tests/test_budget_canonical.py -v
```

- [ ] **Step 4: Commit (with appropriate message)**

If the audit said no edit was needed (Step 1 short-circuit), commit nothing — note in the next task.

If you edited the file:

```bash
git add core/bq/views/v_condges_budget_consuntivo.sql
git commit -m "$(cat <<'EOF'
refactor(bq): v_condges_budget_consuntivo reads from v_budget_canonical

Migrates Looker view from direct f_budget_mensile reads to the canonical
view, inheriting the resolved fonte priority + GASPAROTTO suppression.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Migrate `condges/app_cdg.py` (conditional)

Same conditional pattern as Task 10.

**Files:**
- Maybe modify: `condges/app_cdg.py`

- [ ] **Step 1: Re-check audit conclusion**

Read the audit doc from Task 7. If the conclusion was *"inherits fix"* → skip to Step 4.

- [ ] **Step 2: Identify the queries to change**

Run:

```bash
grep -n "f_budget_mensile" condges/app_cdg.py
```

For each hit, decide:
- If the query was using a `WHERE fonte = ...` filter to handle dedup manually → replace with `FROM v_budget_canonical` and drop the filter.
- If the query was reading raw → replace with `FROM v_budget_canonical`.

- [ ] **Step 3: Edit and verify**

Make the edits. Run the Streamlit app locally:

```bash
streamlit run condges/app_cdg.py
```

Spot-check the affected screens (CE riclassificato, Budget vs Consuntivo) — totals should be sane and no longer double-counted. Stop the server (Ctrl+C).

Run `ruff` to catch any import or syntax issue:

```bash
ruff check condges/app_cdg.py
```

- [ ] **Step 4: Commit**

If you edited:

```bash
git add condges/app_cdg.py
git commit -m "$(cat <<'EOF'
refactor(condges): app_cdg.py reads from v_budget_canonical

Migrates Streamlit Controllo di Gestione's budget queries from raw
f_budget_mensile to the canonical view. CE riclassificato + Budget vs
Consuntivo now show deduplicated totals.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If no edit needed: skip the commit. Note in Task 12 that no app_cdg.py change was required.

---

## Task 12: Update `cmd_health` Output

Add the CANONICAL block per spec §8.

**Files:**
- Modify: `condges/cli_commands.py` (the `cmd_health` function — find its current location with `grep -n "def cmd_health" condges/cli_commands.py`)

- [ ] **Step 1: Locate the current BUDGET 2026 block in `cmd_health`**

Run:

```bash
grep -n "BUDGET 2026\|f_budget_mensile" condges/cli_commands.py
```

This identifies the section that prints per-fonte breakdown and the SQL it uses.

- [ ] **Step 2: Add the CANONICAL block after the per-fonte loop**

Read the section identified in Step 1 to understand current formatting (use the existing `✓` / `⚠` / `fmt_eur` style). Add — immediately after the existing per-fonte print loop — a new block that:

1. Queries `v_budget_canonical` for the current year.
2. Prints `CANONICAL (deduplicated budget truth — v_budget_canonical):`.
3. Then 3 lines: `rows: N (month-grain)`, `distinct conti: M (annual unique accounts)`, `annual total: € X`.
4. If 0 rows for the displayed year, prints the warning instead: `⚠ CANONICAL empty for {year} — check f_budget_mensile and view definition`.

The new block (insert this Python code at the right place):

```python
    # ── CANONICAL: deduplicated budget truth ─────────────────────────────
    sql_canon = f"""
    SELECT
      COUNT(*) AS rows_canon,
      COUNT(DISTINCT cod_conto) AS distinct_conti,
      SUM(importo) AS annual_total
    FROM `hotelops-suite.hotelops.v_budget_canonical`
    WHERE anno = {anno}
    """
    canon_rows = list(client.query(sql_canon).result())
    canon = canon_rows[0] if canon_rows else None

    print("  CANONICAL (deduplicated budget truth — v_budget_canonical):")
    if not canon or (canon["rows_canon"] or 0) == 0:
        print(
            f"    ⚠ CANONICAL empty for {anno} — "
            f"check f_budget_mensile and view definition"
        )
    else:
        rows_n = canon["rows_canon"]
        distinct_n = canon["distinct_conti"]
        annual = canon["annual_total"] or 0
        print(f"    ✓ rows: {rows_n} (month-grain — one per societa × mese × cod_conto)")
        print(f"    ✓ distinct conti: {distinct_n} (annual unique accounts)")
        print(f"    ✓ annual total: {fmt_eur(annual)}/anno")
```

Use whatever `client` and `anno` and `fmt_eur` symbols are already in scope in `cmd_health` — match the surrounding pattern. If imports are needed, add at the top of the function (or top of the module if appropriate).

Also: change the per-fonte block's heading line (currently `BUDGET 2026:`) to clearly label it as raw:

Before (in current code):
```python
print("\n  BUDGET 2026:")
```

After:
```python
print(f"\n  BUDGET {anno}:")
print("    RAW SOURCES (per-fonte diagnostic — freshness signal):")
```

Adjust subsequent per-fonte print lines to use 4-space indent if they currently use 2 — keep visual consistency with the new RAW SOURCES sub-header.

- [ ] **Step 3: Run `hotelops health` and visually confirm output**

```bash
hotelops health 2>&1 | grep -A 30 "BUDGET"
```

Expected output (numbers are illustrative; the canonical total should be smaller than the raw sum since duplicates are removed):

```
  BUDGET 2026:
    RAW SOURCES (per-fonte diagnostic — freshness signal):
      ✓ STRUTTURALI: 84 righe, 7 conti, € 1,336,214/anno
      ✓ MAPPATURA: 492 righe, 23 conti, € 557,853/anno
      ...
      ✓ GASPAROTTO: 1380 righe, 112 conti, € 4,082,942/anno
    CANONICAL (deduplicated budget truth — v_budget_canonical):
      ✓ rows: <N> (month-grain — one per societa × mese × cod_conto)
      ✓ distinct conti: <M> (annual unique accounts)
      ✓ annual total: € <X>/anno
```

If the RAW sum was around €13M and the canonical total is meaningfully lower (e.g., €8-10M), that is the bug fix manifesting numerically. Record the actual canonical number — Stefano + Gasparotto can sanity-check it.

- [ ] **Step 4: Lint**

```bash
ruff check condges/cli_commands.py
ruff format --check condges/cli_commands.py
```

If format check fails, run `ruff format condges/cli_commands.py`.

- [ ] **Step 5: Commit**

```bash
git add condges/cli_commands.py
git commit -m "$(cat <<'EOF'
feat(cli): cmd_health adds CANONICAL block + labels raw sources clearly

BUDGET output now distinguishes:
  - RAW SOURCES: per-fonte diagnostic (freshness signal, not additive)
  - CANONICAL: deduplicated budget truth from v_budget_canonical
    (rows, distinct conti, annual total — three separate numbers
    so month-grain is never confused with annual-grain)

Stops printing the misleading sum across overlapping fonti that the
spec §2 identified as the root surface bug.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add `v_budget_canonical` to the Views table**

Read `CLAUDE.md` and find the `### Views` table (look for `v_piano_finanziario_mensile`). Add a new row at the top of the table (before `v_piano_finanziario_mensile`):

```markdown
| `v_budget_canonical` | **Single resolved budget truth** — applies fonte precedence + GASPAROTTO suppression. All budget consumers read this, not `f_budget_mensile`. See `docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md`. `core/bq/views/` |
```

- [ ] **Step 2: Add a note to the Budget Sources subsection**

Find the heading `### Budget sources`. After the existing table, append a paragraph:

```markdown
**Resolution rule:** the fonti above are **alternative lenses, not additive**. Resolution to a single canonical value per `(societa, anno, mese, cod_conto)` happens in `v_budget_canonical` via exact-code precedence + GASPAROTTO-only suppression scopes (category-level for PERSONALE/INCIDENZA, 4-digit-prefix for STRUTTURALI/MAPPATURA/CONS2025_*). Full rule: `docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md`.
```

- [ ] **Step 3: Add a Governance Rule**

Find the `## Governance Rules` heading. Append a new bullet at the end of the list:

```markdown
- `f_budget_mensile` is **ingest/debug only** — business consumers read `v_budget_canonical` (or a view derived from it). Direct reads of `f_budget_mensile` outside `ingest/` and `core/bq/load/` are a design violation.
```

- [ ] **Step 4: Bump the Last checkpoint date**

At the very top of `CLAUDE.md`, find the line:

```markdown
**Last checkpoint:** 2026-04-04 | **Version:** 0.5.0
```

Change to:

```markdown
**Last checkpoint:** 2026-04-17 | **Version:** 0.5.1
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude): document v_budget_canonical + budget governance rule

- adds v_budget_canonical to Views table
- adds resolution-rule note to Budget Sources section, linking spec
- adds governance rule: f_budget_mensile is ingest/debug only;
  business consumers must read v_budget_canonical
- bumps Last checkpoint to 2026-04-17

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Obsidian Decision Pointer

Cross-reference this work in the Obsidian vault so the decision index stays current.

**Files:**
- Create: `/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops/decisions/2026-04-17-budget-canonical.md`

- [ ] **Step 1: Create the pointer note**

The vault is OUTSIDE the git repo. Create the file with content:

```markdown
# Budget canonical resolution layer (2026-04-17)

**Status:** implemented (commit series ending TBD on 2026-04-17)
**Authoritative spec:** `docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md` in the `hotelops` repo.
**Plan:** `docs/superpowers/plans/2026-04-17-budget-canonical.md` in the `hotelops` repo.

## Summary

`f_budget_mensile` holds 9 overlapping fonti; 75 of 123 conti appeared in more than one. `hotelops health` was summing across fonti and printing a misleading €13M. Two views (`v_budget`, `v_budget_vs_consuntivo`) had divergent dedup logic.

Fix: introduced `v_budget_canonical` as the single resolved budget truth, with explicit precedence (`STRUTTURALI > MAPPATURA > PERSONALE > INCIDENZA > CONS2025_* > GASPAROTTO`) and GASPAROTTO-only suppression scopes (category-level for PERSONALE/INCIDENZA, 4-digit-prefix for the others).

`f_budget_mensile` is now ingest/debug only.

## Why this lives in Git, not here

This decision governs executable system behavior. The spec, plan, and code all travel together in version control. This vault note is the decision-index pointer; the source of truth is the `hotelops` repo.

## Follow-ups (separate specs)

1. Operational drift detection (`v_budget_canonical_check` + `hotelops health` integration).
2. `override_scope` column on `f_budget_mensile` to make suppression explicit as data.
3. Move `RECOGNIZED_FONTI` to a YAML shared by Python + SQL templating.
4. `f_pipeline_runs` extension to ingest pipelines (unrelated but parallel-priority).
```

- [ ] **Step 2: Verify the file exists**

```bash
ls -la "/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops/decisions/2026-04-17-budget-canonical.md"
```

Expected: file shows up with size > 0.

- [ ] **Step 3: No commit (the vault is not a git repo)**

The Obsidian vault is outside the `hotelops` git repo, so there's nothing to `git add`. Stefano syncs the vault separately. Note in the next task's verification that the pointer was written.

---

## Task 15: Final Verification

Closes the plan. Confirms no regression and surfaces the new canonical numbers for stakeholder review.

- [ ] **Step 1: Full pytest run**

```bash
pytest tests/test_budget_canonical.py -v
pytest -m "not bq"
```

Expected: both PASS. The first runs the canonical invariants; the second confirms no regression in the broader test suite.

- [ ] **Step 2: Full `hotelops health`**

```bash
hotelops health 2>&1
```

Expected: BUDGET section now shows `RAW SOURCES` and `CANONICAL` blocks per Task 12 Step 3. All other sections unchanged from the baseline at the start of the plan.

- [ ] **Step 3: Capture the canonical annual total for Stefano + Gasparotto sanity check**

Note the value of `annual total: € X` from the CANONICAL block. Compare it conceptually to:
- The previous (broken) sum across fonti: ~€13.4M.
- Gasparotto's expected "real" 2026 annual budget total (Stefano knows this from external context).

The canonical number should be **lower than €13.4M** (since duplicates removed) and should match Gasparotto's expected within rounding.

- [ ] **Step 4: Spot-check `app_cdg.py` Streamlit (if it was modified in Task 11)**

If Task 11 modified the app:

```bash
streamlit run condges/app_cdg.py
```

Visually verify the CE riclassificato and Budget vs Consuntivo screens render and totals are sane. Stop the server.

If Task 11 was no-op, skip this step.

- [ ] **Step 5: Final summary commit (no code change)**

Append a note to `docs/superpowers/plans/2026-04-17-budget-canonical-AUDIT.md` (the audit file from Task 7):

```markdown

---

## Final verification (Task 15)

- pytest tests/test_budget_canonical.py: **all PASS**
- pytest -m "not bq": **all PASS** (no regression)
- hotelops health BUDGET output: shows RAW SOURCES + CANONICAL blocks correctly
- Canonical annual total 2026: **€ <recorded value>**
- Diff vs broken sum (€13.4M): **€ <delta>** less, attributable to suppressed GASPAROTTO duplicates
- Gasparotto sanity check: <pending Stefano review | matches expected within X%>

Plan complete.
```

```bash
git add docs/superpowers/plans/2026-04-17-budget-canonical-AUDIT.md
git commit -m "$(cat <<'EOF'
docs(plan): close budget canonical plan — verification results

All 4 invariant tests pass. hotelops health output reflects the new
RAW + CANONICAL split. Canonical annual total recorded for Gasparotto
sanity check.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist (run mentally before handing off)

- [ ] Every spec section (§1–§13) is covered by at least one task.
- [ ] No "TBD" or "TODO" outside of the explicit Task 5 placeholder for the cod_conto values discovered in-flight.
- [ ] Every code block compiles in isolation (Python imports stated, SQL standalone).
- [ ] Type/name consistency: `cod_conto` is dots-stripped throughout; `codice_conto_display` is the dotted form throughout.
- [ ] Migration order matches spec §11: setup → canonical view → tests → parallel consumer migrations → health → docs → verification.
- [ ] All commit messages reference the spec or commit type (`feat`, `refactor`, `test`, `docs`).
