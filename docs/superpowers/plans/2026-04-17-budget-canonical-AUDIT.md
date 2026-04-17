# Audit results — Task 7 of budget canonical plan

Date: 2026-04-18
Branch: `worktree-budget-canonical`

## v_condges_budget_consuntivo.sql

Reads: `hotelops-suite.hotelops.f_budget_mensile` directly (line 47), wrapped in `budget_raw` CTE with `SUM(importo) GROUP BY societa, anno, mese, codice_conto, descrizione` — no fonte precedence.

Action: **migrate to v_budget_canonical** in Task 10. Current implementation double-counts when multiple fonti cover the same `cod_conto`.

## condges/app_cdg.py

Reads: `hotelops-suite.hotelops.f_budget_mensile` directly in `load_budget_base` (line 44-58).

Filter uses a hand-maintained `fonte IN (…)` list:
`CONS2025_IP, MAPPATURA, STRUTTURALI, CONS2025_F, PERSONALE, CONS2025_V, CONS2025_X, APP_BUDGET`.

Issues:
- No exact-code or category precedence — if multiple listed fonti share a `cod_conto`, Streamlit aggregates them (double counts).
- `APP_BUDGET` is not in `RECOGNIZED_FONTI` and T2 confirms it does not exist in `f_budget_mensile` — dead entry.
- Missing `INCIDENZA` and `GASPAROTTO` from the allow-list means those fonti are silently excluded from the CE shown to Gasparotto.

Action: **migrate to v_budget_canonical** in Task 11. Drop the hand-maintained fonte filter; canonical view handles precedence + suppression. Keep the explicit `societa_id`/`anno` filter.

## Other Python / SQL consumers

Extra consumer not in original plan scope, discovered via Step 3 grep:

- **`core/bq/views/v_piano_finanziario_mensile.sql`** (lines 6, 73, 86) — reads `f_budget_mensile` directly. Has its own `ROW_NUMBER()` dedup but partitions by `(societa, cod_conto_norm, anno, mese)` **ordered by `LENGTH(cod_conto_pattern) DESC, ord` — NOT by fonte precedence**. When multiple fonti cover the same `cod_conto`, winners are picked by voce-pattern specificity, not by resolution rule. This view feeds Rosa's Piano Finanziario.

Benign references (no action):
- `core/config.py` — constant definition
- `core/bq/manifest.py` — manifest table list
- `core/schemas.py` — Pydantic contract for ingest
- `ingest/orchestrate.py` — orchestration comment
- `condges/cli_commands.py:139` — `cmd_health` diagnostic block. Per-fonte raw breakdown is correct here; Task 12 adds a CANONICAL block alongside, does not replace.
- `condges/app_cdg.py:931` — error message string only

## Implications for Tasks 9, 10, 11

- **Task 9** (`v_budget_vs_consuntivo`) and **Task 10** (`v_condges_budget_consuntivo.sql`) proceed as planned — both read `f_budget_mensile` and benefit directly from `v_budget_canonical`.
- **Task 11** (`condges/app_cdg.py`) proceeds as planned; migration is clearly warranted and will also drop three sources of latent bug (double counting, dead APP_BUDGET entry, silent exclusion of INCIDENZA/GASPAROTTO).
- **Extension needed**: add a Task 11b (or queue as follow-up) to migrate `v_piano_finanziario_mensile.sql`'s `budget_costi_raw` CTE to read from `v_budget_canonical`. Defer the scope decision to Stefano — this is Rosa-facing and may warrant its own review cycle.
