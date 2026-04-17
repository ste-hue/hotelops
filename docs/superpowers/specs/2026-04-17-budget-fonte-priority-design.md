# Budget Fonte Priority — Canonical Resolution Layer

**Date:** 2026-04-17
**Status:** Draft (awaiting user review)
**Author:** Stefano + Claude (tech-lead session)
**Scope:** Eliminate budget double-counting by introducing a single canonical resolution layer for `f_budget_mensile`.

---

## 1. Core invariant

> `f_budget_mensile` is the overlapping raw source set; `v_budget_canonical` is the only resolved budget truth, produced by explicit precedence plus GASPAROTTO-only suppression scopes.

---

## 2. Problem

`f_budget_mensile` holds 2,733 rows across 9 fonti (annual budget data for 2026). Today:

- **75 of 123 conti (61%) appear in more than one fonte.** €12.4M of the €14.6M absolute total sits in conti with ambiguous fonte resolution.
- **`hotelops health` sums across fonti**, printing a misleading "€13M" annual budget — violating CLAUDE.md's own governance rule (*"never mix fonti without explicit filter"*).
- **The fonte-priority rule is duplicated** across two views with **divergent logic**:
  - `v_budget_vs_consuntivo` — simple `ROW_NUMBER` per `(societa, anno, mese, cod_conto)`.
  - `v_budget` — same ranking PLUS a category-level exclusion (PERSONALE/INCIDENZA suppress all GASPAROTTO in the category) PLUS a 4-digit prefix exclusion.
- **Concrete double-count examples confirmed in production:**
  - `INCIDENZA` and `PERSONALE` both carry conto `670101` at €1,226,031 — same payroll, two granularities. Summing inflates by €1.23M.
  - `47.91.01` carries €3.09M across `CONS2025_IP + GASPAROTTO`.
  - `65.11.01` (fitto ORTI→INTUR) carries €2.01M across `GASPAROTTO + STRUTTURALI`.

The root cause is **implicitness**: fonte semantics are not additive but the data model and several consumers treat them as if they were. The resolution rule lives in two view files with different shapes and is invisible to anyone reading `f_budget_mensile` directly.

---

## 3. The Rule

### 3.1 Exact-code precedence (applies across all recognized fonti)

For a given `(societa_id, anno, mese, cod_conto)`, if more than one fonte has a row, the fonte with the highest precedence wins.

### 3.2 Suppression scopes (apply only to GASPAROTTO)

Non-GASPAROTTO sources may also **suppress GASPAROTTO fallback rows** in two additional scopes. Non-GASPAROTTO sources **do not suppress each other** — only exact-code precedence governs their interaction.

- **Category-level suppression** — fonti: `PERSONALE`, `INCIDENZA`. If either covers a `categoria_ce`, all GASPAROTTO rows in that category are suppressed (including sibling codes). Reason: these sources replace an entire category semantically (e.g., PERSONALE is the whole personnel budget; GASPAROTTO's sub-code personnel lines would double-count).
- **Prefix-level suppression (4-digit)** — fonti: `STRUTTURALI`, `MAPPATURA`, `CONS2025_F`, `CONS2025_V`, `CONS2025_IP`, `CONS2025_X`. If a non-GASPAROTTO fonte covers a `(categoria_ce, 4-digit prefix)` pair, GASPAROTTO rows sharing both are suppressed.

### 3.3 Fallback

**GASPAROTTO is the base fallback source.** Non-GASPAROTTO sources suppress or replace it where covered; otherwise GASPAROTTO remains canonical. This is why GASPAROTTO is the lowest precedence and the only fonte subject to suppression scopes.

### 3.4 Precedence order — explicit enumeration

| Rank | Fonte | Semantic rationale |
|---|---|---|
| 1 | `STRUTTURALI` | Explicit structural overrides (fitto, affitti intercompany) — highest authority |
| 2 | `MAPPATURA` | Curated per-BU account mapping layer |
| 3 | `PERSONALE` | Authoritative personnel cost replacement (company × mese) |
| 4 | `INCIDENZA` | Authoritative incidence replacement (per divisione, finer granularity than PERSONALE) |
| 5 | `CONS2025_F` | Targeted historical replacement — costi fissi 2025 |
| 5 | `CONS2025_V` | Targeted historical replacement — costi variabili 2025 |
| 5 | `CONS2025_IP` | Targeted historical replacement — incidenze 2025 |
| 5 | `CONS2025_X` | Targeted historical replacement — oneri finanziari 2025 |
| 6 | `GASPAROTTO` | Base fallback — full CE annual budget, never additive with others |

The `CONS2025_*` family is **enumerated explicitly** (no wildcard). New CONS2025 variants added in future must be added to this list. The `recognized_fonte_set` test will fail until they are. **No silent catch-all `ELSE` branch in SQL.**

---

## 4. Architecture

```
 ┌─────────────────────────┐
 │  f_budget_mensile       │   INGEST/DEBUG ONLY
 │  overlapping raw sources│   contract: no business consumer reads this directly
 └────────────┬────────────┘
              │  applies exact-code precedence + GASPAROTTO-only suppression scopes
              ↓
 ┌─────────────────────────┐
 │  v_budget_canonical     │   SINGLE RESOLVED BUDGET TRUTH
 │                         │   canonical key: (societa_id, anno, mese, cod_conto)
 │                         │   cod_conto = dots stripped (join key)
 │                         │   codice_conto_display = with dots (presentation only)
 │                         │   grain: exactly one row per canonical key
 └────────────┬────────────┘
              │
   ┌──────────┼──────────┬──────────────────────┐
   ↓          ↓          ↓                      ↓
 v_budget   v_budget_vs_  v_condges_budget_    hotelops health
 (pivoted   consuntivo    consuntivo           + future consumers
  monthly)  (+ actuals)   (Looker)
```

---

## 5. Contracts

- **Raw table.** `f_budget_mensile` is **ingest/debug only**. Business or semantic consumers must read `v_budget_canonical` (or a view derived from it). **Any new direct consumer of `f_budget_mensile` is a design violation** and must be refactored to go through the canonical view.
- **Canonical key.** `(societa_id, anno, mese, cod_conto)` with `cod_conto` dots-stripped. Never join on `codice_conto_display`.
- **Rule locality.** Override mechanisms and precedence order live in exactly one place: `v_budget_canonical`. Downstream views may reshape, aggregate, pivot, or join canonical rows, but **may never re-decide row selection, precedence, or suppression logic**.
- **Migration enforcement.** Any consumer reading `f_budget_mensile` directly must either be refactored in this spec **or** explicitly listed as a temporary violation with an owner and deadline. No silent exceptions.
- **Year scope.** `v_budget_canonical` is **all-years, unfiltered**. Consumers filter by year. The canonical view is a semantic resolution layer, not a reporting lens — `CURRENT_DATE()` filters do not belong here.

---

## 6. `v_budget_canonical` output contract (frozen)

| Column | Type | Semantic |
|---|---|---|
| `societa_id` | STRING | `ORTI` or `INTUR` |
| `anno` | INT64 | 4-digit year |
| `mese` | INT64 | 1-12 |
| `cod_conto` | STRING | Canonical join key, dots stripped (e.g., `670101`). Never nullable. |
| `codice_conto_display` | STRING | Presentation form, with dots (e.g., `67.01.01`). Derived from `cod_conto`. |
| `descrizione` | STRING | From winning fonte row, with `d_piano_conti` fallback |
| `tipo_costo` | STRING | `F`/`V`/`P`/`X`/`IP` from winning fonte row |
| `categoria_ce` | STRING | From winning fonte row |
| `importo` | FLOAT64 | The resolved amount for this grain |
| `fonte` | STRING | Which fonte won. Always one of the recognized fonte set, never null, never catch-all. |

- **Grain:** exactly one row per `(societa_id, anno, mese, cod_conto)`.
- **Ordering:** no guarantee. Consumers sort as needed.

---

## 7. Components

### 7.1 Files to create

| File | Purpose |
|---|---|
| `core/bq/views/v_budget_canonical.sql` | The single rule site. Header restates the rule in plain language. |
| `tests/test_budget_canonical.py` | Invariant tests (T1–T4). Defines the `RECOGNIZED_FONTI` Python constant. |
| `docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md` | This spec. |
| Obsidian pointer note in `Obsidian Vault/hotelops/decisions/` | Short entry linking to this spec. |

### 7.2 Files to refactor (logic moves to canonical)

| File | Change |
|---|---|
| `core/bq/views/v_budget.sql` | Collapse to a thin pivot over `v_budget_canonical`. All dedup logic removed. |
| `core/bq/views/v_budget_vs_consuntivo.sql` | Replace its `budget_ranked` / `budget` CTEs with `SELECT FROM v_budget_canonical`. |
| `core/bq/views/v_condges_budget_consuntivo.sql` | Migrate to read from `v_budget_canonical` if it currently reads `f_budget_mensile`. |
| `condges/app_cdg.py` | Migrate any direct read of `f_budget_mensile` to `v_budget_canonical`. |

If `v_condges_budget_consuntivo.sql` or `condges/app_cdg.py` already read `v_budget` or `v_budget_vs_consuntivo`, they inherit the fix for free and do not need direct edits — but the plan's audit step must confirm this.

### 7.3 Files to update

| File | Change |
|---|---|
| `condges/cli_commands.py` (`cmd_health`) | Add a `CANONICAL` block below the per-fonte breakdown (see §8). |
| `CLAUDE.md` | (a) Add `v_budget_canonical` to the Views table. (b) Add a note in Budget sources section linking to this spec. (c) Add governance rule: *"`f_budget_mensile` is ingest/debug only — business consumers read `v_budget_canonical`."* |

---

## 8. `cmd_health` output specification

```
BUDGET 2026:
  RAW SOURCES (per-fonte diagnostic — freshness signal):
    ✓ STRUTTURALI: 84 righe, 7 conti, € 1,336,214/anno
    ✓ MAPPATURA: 492 righe, 23 conti, € 557,853/anno
    ✓ PERSONALE: 12 righe, 1 conti, € 1,226,032/anno
    ✓ INCIDENZA: 81 righe, 1 conti, € 1,226,031/anno
    ✓ CONS2025_F: 348 righe, 29 conti, € 267,544/anno
    ✓ CONS2025_V: 60 righe, 5 conti, € 280,818/anno
    ✓ CONS2025_IP: 240 righe, 20 conti, € 4,436,129/anno
    ✓ CONS2025_X: 36 righe, 3 conti, € 572/anno
    ✓ GASPAROTTO: 1380 righe, 112 conti, € 4,082,942/anno
  CANONICAL (deduplicated budget truth — v_budget_canonical):
    ✓ rows: N (month-grain — one per societa × mese × cod_conto)
    ✓ distinct conti: M (annual unique accounts)
    ✓ annual total: € X
```

Three separate numbers in the canonical block so nobody conflates month-grain with annual-grain.

**Empty canonical handling:** if `v_budget_canonical` returns 0 rows for the displayed year, print `⚠ CANONICAL empty for {year} — check f_budget_mensile and view definition` rather than `€ 0/anno`.

---

## 9. Tests

File: `tests/test_budget_canonical.py`. Marked `@pytest.mark.bq`. Skipped when `HOTELOPS_SKIP_BQ=1`.

The Python constant `RECOGNIZED_FONTI` is defined at the top of the test module and re-exported as the authoritative declaration of recognized fonti. The SQL CASE in `v_budget_canonical.sql` must list exactly these names.

```python
RECOGNIZED_FONTI = {
    "STRUTTURALI", "MAPPATURA", "PERSONALE", "INCIDENZA",
    "CONS2025_F", "CONS2025_V", "CONS2025_IP", "CONS2025_X",
    "GASPAROTTO",
}
```

### T1 — Grain uniqueness

Exactly one row per `(societa_id, anno, mese, cod_conto)` in `v_budget_canonical`. Implicitly also covers "no duplicate winners": if two rows share a grain, ROW_NUMBER produced two `rn=1` candidates that the SQL didn't resolve.

### T2 — Recognized fonte set

Every distinct fonte in `f_budget_mensile` must be in `RECOGNIZED_FONTI`. Failure message instructs the developer to update both `RECOGNIZED_FONTI` and the SQL CASE.

### T3 — Deterministic winner cases (parameterized)

Initial cases:

| societa | anno | mese | cod_conto | expected_fonte | rationale |
|---|---|---|---|---|---|
| ORTI | 2026 | 1 | `670101` | `PERSONALE` | payroll — PERSONALE > INCIDENZA > GASPAROTTO |
| ORTI | 2026 | 1 | `651101` | `STRUTTURALI` | fitto ORTI→INTUR — STRUTTURALI > GASPAROTTO |
| ORTI | 2026 | 1 | `479101` | `CONS2025_IP` | oneri 47 — CONS2025_IP > GASPAROTTO |

Plan phase will add 2 more cases picked from the overlap list to cover MAPPATURA and category-level suppression of a sibling code.

### T4 — Canonical row count sanity

Canonical row count ≤ raw row count at the same `(societa, anno, mese)` scope. Dedup must never invent rows.

---

## 10. Error handling philosophy

- **Fail loud at test time, never silently at query time.**
- No `ELSE` clause in the precedence `CASE` — unrecognized fonti get NULL rank and survive last; T2 catches them in CI.
- No `COALESCE` papering over missing mappings. If `categoria_ce` is NULL on a row, category-level suppression simply doesn't trigger for it. Documented behavior, not a bug.
- `cmd_health` distinguishes empty-canonical (warning) from zero-budget (would be a real €0). See §8.
- BigQuery client errors (auth, 404) bubble up as today — no special wrapping.

---

## 11. Migration order

```
Step 1  Create v_budget_canonical with frozen output contract (§6)
Step 2  Write + run tests/test_budget_canonical.py — verify base before forking
Step 3  Parallel consumer migrations (independent files, no shared state):
          2a  v_budget.sql                 → thin pivot over canonical
          2b  v_budget_vs_consuntivo.sql   → swap CTE
          2c  v_condges_budget_consuntivo.sql  → audit + migrate if needed
          2d  condges/app_cdg.py            → audit + migrate if needed
Step 4  Update cmd_health output (§8)
Step 5  Update CLAUDE.md + write Obsidian decision pointer
Step 6  Final verification: re-run pytest (regression check after consumer
        migrations) and hotelops health (visual confirmation of new output)
```

Steps 2a–2d are parallelizable as separate subagent tasks. Step 1 must complete and Step 2 tests must pass before parallel work begins.

---

## 12. Out of scope (Tech Debt — separate specs)

1. **Operational drift detection (Q6 option B).** A `v_budget_canonical_check` view returning anomalies (duplicate grain rows, unrecognized fonti, suppressed-but-resurfacing rows) consumed by `cmd_health`. Catches data drift after this spec stabilizes the modeling layer.
2. **Override scope as data.** Add `override_scope ∈ {EXACT, PREFIX4, CATEGORY, NONE}` column to `f_budget_mensile`. Eliminates the implicit SQL heuristic. Bigger blast radius — requires migrating existing data and updating ingest pipelines.
3. **Shared `RECOGNIZED_FONTI` constant.** Move from a Python test fixture to a YAML or `core/config.py` constant read by both Python and SQL (via dbt-style templating or query builder). Removes the last small drift risk between `v_budget_canonical.sql` and the test module.
4. **Pipeline observability (`f_pipeline_runs` extension).** Unrelated but parallel-priority work surfaced in the same tech-lead audit. Adds `batch_id` lineage to ingest pipelines.

---

## 13. Open follow-ups

- Investigate `57.11.07.01` overlap between GASPAROTTO and MAPPATURA producing -€555,844 (opposite signs?). Likely a sign-convention bug; surfaced during this audit but out of scope for this spec.
- After this spec lands, the `hotelops health` output for 2026 will show the real canonical budget. Compare against Gasparotto's expected total to confirm no regression in business numbers.
