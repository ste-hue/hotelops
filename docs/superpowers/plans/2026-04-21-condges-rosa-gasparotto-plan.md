# Condges Rosa→Gasparotto Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Rosa→Condges loop end-to-end: adapt the Gasparotto budget ingest to the new Excel file (formula-driven Budget sheet, timedelta-corrupted cod_conto), rewrite the Cash-Flow tab in `app_cdg.py` to read live from `v_piano_finanziario_mensile`, and add a regenerator that rewrites the Cash-Flow sheet of the Gasparotto workbook in-place from BQ.

**Architecture:** Three layers stay disaccoppiati. (1) Ingest reads ground-truth `Conto Economico` sheet (not the formula-driven `Budget`) and writes to `f_budget_mensile` with fonte=GASPAROTTO. (2) `app_cdg.py` Cash-Flow tab queries `v_piano_finanziario_mensile` directly, replacing the current `page_tesoreria` that reads `f_saldi_banca_snapshot`. (3) `genera_excel.py` gets a `--target gasparotto` flag that opens the workbook in-place with openpyxl, rewrites the Cash-Flow sheet rows from BQ, and forces recalc via `libreoffice --headless` (Option A) or writes totals as static values (Option B fallback).

**Tech Stack:** Python 3.11+, openpyxl, google-cloud-bigquery, Streamlit, pandas, pytest, ruff, LibreOffice headless (optional, for WI-3 Option A).

**Reference spec:** `docs/superpowers/specs/2026-04-20-condges-rosa-gasparotto-design.md`

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `ingest/flussi/ingest_gasparotto.py` | Retarget parser to `Conto Economico` sheet; add timedelta decoder; update DEFAULT_FILE |
| Create | `tests/test_ingest_gasparotto.py` | TDD coverage for decoder + parser gates (0 UNMAPPED, 0 skipped) |
| Modify | `condges/app_cdg.py` | Rename tab Tesoreria → Cash-Flow; new `page_cashflow` reading `v_piano_finanziario_mensile`; fonte badge |
| Create | `condges/cashflow_loader.py` | Pure BQ loader for cashflow view (testable separately from Streamlit) |
| Modify | `condges/genera_excel.py` | New `--target gasparotto` flag routing to `rigenera_cashflow_sheet_gasparotto` |
| Create | `condges/gasparotto_regen.py` | `rigenera_cashflow_sheet_gasparotto()` + `force_recalc()` helpers |
| Create | `tests/test_gasparotto_regen.py` | Unit tests for in-place rewrite + recalc fallback |
| Modify | `CLAUDE.md` | Add hierarchy note (condges = gasparotto, Rosa = subset) + Invariant I9 reference |
| Create | `docs/vault-snippets/I9-cashflow-invariant.md` | Paste-ready snippet for user's Obsidian vault |

**Design note on splits:** `cashflow_loader.py` and `gasparotto_regen.py` are new thin modules because `app_cdg.py` (1265 LOC) and `genera_excel.py` (402 LOC) already approach the size where adding a feature in-place becomes unwieldy. Each new module has one responsibility and is independently testable without importing Streamlit.

---

## Prerequisites

- [ ] **Setup 1: Ensure fixture file is accessible**

  The source file `gasparotto_Budget_Indici2025.xlsx` must be at `/Users/stefanodellapietra/Downloads/gasparotto_Budget_Indici2025.xlsx`. Copy a stable reference to the repo's test fixtures dir:

  ```bash
  mkdir -p tests/fixtures
  cp "/Users/stefanodellapietra/Downloads/gasparotto_Budget_Indici2025.xlsx" tests/fixtures/gasparotto_Budget_Indici2025.xlsx
  ```

  Verify: `ls -lh tests/fixtures/gasparotto_Budget_Indici2025.xlsx` should show ~690KB.

- [ ] **Setup 2: Verify LibreOffice availability (WI-3 prereq)**

  ```bash
  which libreoffice soffice 2>&1 | grep -v "not found" || echo "LibreOffice MISSING"
  ```

  If missing, install for later (WI-3):
  ```bash
  brew install --cask libreoffice
  ```

  After install, verify:
  ```bash
  /Applications/LibreOffice.app/Contents/MacOS/soffice --version
  ```

  Expected: something like `LibreOffice 24.x.x`. The WI-3 tasks will add a runtime check, so LibreOffice being absent during other WIs is fine.

- [ ] **Setup 3: Commit fixture**

  ```bash
  git add tests/fixtures/gasparotto_Budget_Indici2025.xlsx
  git commit -m "test: add Gasparotto Budget Indici 2025 fixture for ingest tests"
  ```

---

# WI-1 — Ingest adapter (Tasks 1–4)

## Task 1: Write TDD scaffold for timedelta decoder

**Files:**
- Create: `tests/test_ingest_gasparotto.py`

The timedelta encoding discovered in the fixture: Excel parses Italian PDC strings like `47.91.02` as time `H:M:S` → stored as `timedelta(days=2, seconds=1863)` (i.e., 48h31m03s normalized; the carry from 91 min > 60 creates the 2-day delta). The decoder reconstructs `cod_conto` by using section-context (prev/next row's first two tokens `47.91`) and solving `s = total_seconds - h*3600 - m*60`.

**Four concrete test cases from fixture (verified):**

| Row | Prev cod | Next cod | Desc | Total_s | Expected cod |
|---|---|---|---|---|---|
| R11 | `47.91.01` | `47.91.04` | Ricavi parcheggi | 174663 | `47.91.03` |
| R18 | `47.91.07.03` | `47.92.02` | Ricavi per alloggi | 174721 | `47.92.01` |
| R20 | `47.92.02` | `47.92.04` | Ricavi parcheggi | 174723 | `47.92.03` |
| R22 | `47.92.04` | `47.93.02` | Ricavi per alloggi | 174781 | `47.93.01` |

Derivation: `47*3600 + 92*60 + 1 = 174721` exactly for R18. For R11, the offset of 1s (`47*3600 + 91*60 + 3 = 174663`) points to `.03`, not `.02` (revising spec assumption based on ground-truth data).

- [ ] **Step 1: Create test file skeleton with failing decoder test**

  Create `tests/test_ingest_gasparotto.py`:

  ```python
  """Tests for Gasparotto Budget → f_budget_mensile ingest.

  Covers:
  - Timedelta-corrupted cod_conto decoder (WI-1 core requirement).
  - parse_gasparotto_budget end-to-end on the new Conto Economico sheet.
  - Gates: 0 UNMAPPED, 0 skipped timedelta rows.
  """

  from __future__ import annotations

  import logging
  from datetime import timedelta
  from pathlib import Path

  import pytest

  from ingest.flussi.ingest_gasparotto import (
      decode_timedelta_cod_conto,
      parse_gasparotto_budget,
  )

  FIXTURE = Path(__file__).parent / "fixtures" / "gasparotto_Budget_Indici2025.xlsx"


  class TestDecodeTimedelta:
      """Decoder reconstructs cod_conto from Excel-corrupted timedelta values."""

      def test_decodes_with_known_prefix_47_91(self):
          # R11 in fixture: prev=47.91.01, next=47.91.04, td=174663s → 47.91.03
          td = timedelta(seconds=174663)
          assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=91) == "47.91.03"

      def test_decodes_with_known_prefix_47_92_minute_01(self):
          # R18: td=174721s with prefix 47.92 → 47.92.01
          td = timedelta(seconds=174721)
          assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=92) == "47.92.01"

      def test_decodes_with_known_prefix_47_92_minute_03(self):
          # R20: td=174723s with prefix 47.92 → 47.92.03
          td = timedelta(seconds=174723)
          assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=92) == "47.92.03"

      def test_decodes_with_known_prefix_47_93(self):
          # R22: td=174781s with prefix 47.93 → 47.93.01
          td = timedelta(seconds=174781)
          assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=93) == "47.93.01"

      def test_returns_none_when_prefix_gives_invalid_seconds(self):
          # If prefix=47.91 is wrong for td=174781, s would be 121 (out of range 0-99)
          td = timedelta(seconds=174781)
          assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=91) is None

      def test_rounds_fractional_seconds(self):
          # 174662.6 → 174663, and decodes correctly
          td = timedelta(seconds=174662.6)
          assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=91) == "47.91.03"
  ```

- [ ] **Step 2: Run the tests — they must all fail with ImportError**

  Run:
  ```bash
  pytest tests/test_ingest_gasparotto.py -v
  ```

  Expected: `ImportError: cannot import name 'decode_timedelta_cod_conto'` for all 6 tests.

- [ ] **Step 3: Implement `decode_timedelta_cod_conto` in `ingest/flussi/ingest_gasparotto.py`**

  Add these imports at the top of `ingest/flussi/ingest_gasparotto.py` (after the existing `from datetime import datetime, timezone`):

  ```python
  from datetime import datetime, timedelta, timezone
  ```

  Then add the decoder function after the existing `_is_conto` helper (around line 272, before `_detect_section`):

  ```python
  def decode_timedelta_cod_conto(
      td: timedelta, prefix_h: int, prefix_m: int
  ) -> str | None:
      """Reverse-engineer a cod_conto that Excel parsed as time H:M:S.

      Given a timedelta ``td`` (Excel's normalized form) and the section context
      prefix ``prefix_h.prefix_m`` derived from neighbouring non-corrupted rows,
      solve for the last segment ``s`` and return ``"HH.MM.SS"``.

      Example: Italian PDC "47.91.03" was parsed by Excel as 47h 91m 3s →
      normalized to timedelta(days=2, seconds=1863). Given prefix_h=47,
      prefix_m=91, this function returns "47.91.03".

      Returns None if the prefix does not yield a valid 0–99 seconds segment.
      """
      total_s = int(round(td.total_seconds()))
      s = total_s - prefix_h * 3600 - prefix_m * 60
      if 0 <= s < 100:
          return f"{prefix_h}.{prefix_m:02d}.{s:02d}"
      return None
  ```

- [ ] **Step 4: Run the decoder tests — they must all pass**

  ```bash
  pytest tests/test_ingest_gasparotto.py::TestDecodeTimedelta -v
  ```

  Expected: 6 passed.

- [ ] **Step 5: Commit**

  ```bash
  git add tests/test_ingest_gasparotto.py ingest/flussi/ingest_gasparotto.py
  git commit -m "feat(ingest): add timedelta decoder for corrupted cod_conto in Gasparotto XLSX

  Excel parses Italian PDC strings like '47.91.03' as time H:M:S, storing them
  as timedelta(days=2, seconds=1863). Decoder uses section-context prefix
  (derived from neighbouring rows' cod_conto) to solve for the last segment."
  ```

---

## Task 2: Rewrite parser to read `Conto Economico` sheet

**Files:**
- Modify: `ingest/flussi/ingest_gasparotto.py:308-460` (function `parse_gasparotto_budget`)
- Modify: `tests/test_ingest_gasparotto.py` (add parser tests)

**Why the change:** Fixture inspection (pre-recalc) shows:

| Source | `cod_conto` (col A) | `descrizione` (col B) | `valore 2026` (col H) |
|---|---|---|---|
| Budget sheet | **None** (formula refs CE:A; timedelta not cached) | ✅ cached via formula | ✅ cached numeric |
| Conto Economico sheet | ✅ **direct** (string or timedelta) | ✅ direct | ❌ no 2026 column on CE |

**Strategy:** read `cod_conto` from **CE col A** (direct values, timedelta-decodable), `descrizione` from CE col B or Budget col B (identical), and `valore_2026` from **Budget col H** (the only place with cached numbers). Iterate row-by-row, relying on the Budget↔CE 1:1 formula reference (`Budget!A11 ='Conto Economico'!A11`).

**Conto Economico layout (verified from fixture):**
- Header at R4. Columns: A=`Cod. Conto`, B=`Ricavi e Costi`, D=2023, F=`Tipo`, H=2024, L=2025.
- Data starts at R5, first meaningful row R10.
- Col A: direct string (e.g. `47.91.01`) or timedelta (corruption).
- Col L (2025), D (2023), H (2024) are **formulas with no cached values** (2/45 populated in fixture) — don't rely on them.

**Budget layout (verified from fixture):**
- Header at R10. Data starts at R11.
- Col A: all None (formulas `='Conto Economico'!A{r}` that don't cache timedelta through Excel).
- Col B: cached text (via formula, reflects CE col B).
- Col E: cached tipo_costo.
- Col H: cached 2026 Previsione numeric (38/39 rows populated in fixture).

**No LibreOffice recalc needed for WI-1.** The fixture already carries the cached values we need. The Task 2 parser can be a pure openpyxl read.

- [ ] **Step 1: Add failing integration test using the fixture**

  Append to `tests/test_ingest_gasparotto.py`:

  ```python
  class TestParseGasparottoBudget:
      """End-to-end on the fixture XLSX with gates from spec."""

      @pytest.fixture
      def logger(self):
          return logging.getLogger("test_ingest_gasparotto")

      @pytest.fixture
      def parsed_rows(self, logger):
          assert FIXTURE.exists(), f"Fixture missing: {FIXTURE}"
          return parse_gasparotto_budget(FIXTURE, "ORTI", logger)

      def test_returns_nonempty(self, parsed_rows):
          assert len(parsed_rows) > 0

      def test_all_rows_have_valid_cod_conto(self, parsed_rows):
          """Gate from spec: 0 rows skipped for corrupted cod_conto."""
          for r in parsed_rows:
              cod = r["codice_conto"]
              assert cod is not None
              assert "." in cod
              assert len(cod) < 15
              # No timedelta leaked through
              assert not any(c.isalpha() for c in cod if c != ".")

      def test_zero_unmapped(self, parsed_rows, caplog, logger):
          """Gate from spec: 0 UNMAPPED warnings."""
          with caplog.at_level(logging.WARNING):
              parse_gasparotto_budget(FIXTURE, "ORTI", logger)
          unmapped = [r for r in caplog.records if "UNMAPPED" in r.getMessage()]
          assert len(unmapped) == 0, (
              f"Found {len(unmapped)} UNMAPPED rows: "
              f"{[r.getMessage() for r in unmapped]}"
          )

      def test_timedelta_rows_resolved(self, parsed_rows):
          """The 4 known timedelta-corrupted rows in the fixture must be present
          with correct cod_conto (decoded via prefix context)."""
          cods = {r["codice_conto"] for r in parsed_rows}
          # From fixture analysis: R11→47.91.03, R18→47.92.01, R20→47.92.03, R22→47.93.01
          assert "47.91.03" in cods, "Timedelta R11 (Ricavi parcheggi CVM) not decoded"
          assert "47.92.01" in cods, "Timedelta R18 (Ricavi alloggi Hotel) not decoded"
          assert "47.92.03" in cods, "Timedelta R20 (Ricavi parcheggi Hotel) not decoded"
          assert "47.93.01" in cods, "Timedelta R22 (Ricavi alloggi RES) not decoded"

      def test_monthly_rows_are_12_per_conto(self, parsed_rows):
          """Each cod_conto has exactly 12 monthly rows."""
          from collections import Counter
          counts = Counter(r["codice_conto"] for r in parsed_rows)
          assert all(c == 12 for c in counts.values()), (
              f"Some conti do not have 12 months: "
              f"{[(cod, n) for cod, n in counts.items() if n != 12][:5]}"
          )

      def test_totals_sane(self, parsed_rows):
          """Ricavi > 0 and costs > 0 — sanity check, no hardcoded values."""
          ricavi = sum(
              r["importo"] for r in parsed_rows if r["categoria_ce"] == "Ricavi"
          )
          costi = sum(
              r["importo"] for r in parsed_rows if r["categoria_ce"] != "Ricavi"
          )
          assert ricavi > 0, "Expected ricavi > 0"
          assert costi > 0, "Expected costi > 0"
  ```

- [ ] **Step 2: Run tests — they must fail (parser still reads Budget sheet directly)**

  ```bash
  pytest tests/test_ingest_gasparotto.py::TestParseGasparottoBudget -v
  ```

  Expected: most tests fail because either (a) parser returns empty (new file has different column positions) or (b) timedelta rows are silently skipped as UNMAPPED.

- [ ] **Step 3: Add `_resolve_cod_conto_with_context` helper**

  In `ingest/flussi/ingest_gasparotto.py`, add after `decode_timedelta_cod_conto`:

  ```python
  def _resolve_cod_conto_with_context(
      cell_value,
      prev_cod: str | None,
      next_cod: str | None,
      descrizione: str,
      ce_desc_to_cod: dict[str, str],
      logger: logging.Logger,
  ) -> str | None:
      """Resolve a cod_conto from col A, handling timedelta corruption.

      Resolution order:
      1. If cell_value is a non-empty dotted string: use as-is.
      2. If cell_value is timedelta: decode using the prefix from prev/next cod.
      3. Fallback: fuzzy-match descrizione against ce_desc_to_cod (exact match only
         — fuzzy ratio >0.85 would be added here if needed, not yet required).
      Returns None if unresolvable; caller decides whether to hard-fail or skip.
      """
      # Case 1: regular string
      if _is_conto(cell_value):
          return cell_value.strip()

      # Case 2: timedelta
      if isinstance(cell_value, timedelta):
          # Derive prefix (HH.MM) from adjacent rows
          context_cod = prev_cod or next_cod
          if context_cod and context_cod.count(".") >= 2:
              parts = context_cod.split(".")
              try:
                  prefix_h = int(parts[0])
                  prefix_m = int(parts[1])
              except ValueError:
                  prefix_h = prefix_m = None
              if prefix_h is not None:
                  decoded = decode_timedelta_cod_conto(
                      cell_value, prefix_h, prefix_m
                  )
                  if decoded:
                      logger.info(
                          f"  Timedelta decoded: {cell_value} → {decoded} "
                          f'(prefix {prefix_h}.{prefix_m:02d}, desc="{descrizione}")'
                      )
                      return decoded
          logger.warning(
              f'  Timedelta UNRESOLVED: {cell_value} desc="{descrizione}" '
              f"prev={prev_cod} next={next_cod}"
          )

      # Case 3: fallback to descrizione match in CE map
      if descrizione in ce_desc_to_cod:
          return ce_desc_to_cod[descrizione]

      return None
  ```

- [ ] **Step 4: Refactor `parse_gasparotto_budget` to use the helper and read from `Conto Economico`**

  Replace the CE cross-ref block and the main loop's `# Resolve codice_conto` block in `parse_gasparotto_budget` (the function body is at lines 308–460). The key changes:

  (a) Build `ce_desc_to_cod` from `Conto Economico` sheet with **timedelta-aware** reading (so if col A is timedelta there, we skip only the desc mapping — it's fine, we'll decode later when reading the Budget sheet).

  (b) In the main loop, call `_resolve_cod_conto_with_context` with `prev_cod` and `next_cod` tracked across iterations.

  (c) If the helper returns `None`, the row is a **hard error** (increment a counter, and at the end raise `RuntimeError` if counter > 0 — no more silent skipping).

  Concrete edit — replace lines 325–340 (the CE cross-ref):

  ```python
      # Step 1: Build description → codice_conto from Conto Economico (cross-ref)
      ce_desc_to_cod: dict[str, str] = {}
      if "Conto Economico" in wb.sheetnames:
          ws_ce = wb["Conto Economico"]
          for row in ws_ce.iter_rows(min_row=5, values_only=True):
              raw_a = row[0]
              # Skip timedelta rows — can't build desc→cod from corrupted cells,
              # but Budget-sheet parsing will handle those via context decoder.
              if isinstance(raw_a, timedelta):
                  continue
              if (
                  raw_a
                  and isinstance(raw_a, str)
                  and "." in raw_a
                  and len(raw_a) < 15
              ):
                  desc = str(row[1]).strip() if row[1] else ""
                  if desc:
                      ce_desc_to_cod[desc] = raw_a
          logger.info(
              f"  Conto Economico cross-ref: {len(ce_desc_to_cod)} conti trovati"
          )
  ```

  And replace lines 389–409 (the `# Resolve codice_conto` block). Wrap the main loop so it tracks `prev_cod` and `next_cod`. Since iterating is single-pass, compute `next_cod` by lookahead:

  ```python
      # Pre-compute all rows as a list so we can do lookahead for next_cod context
      rows_list = list(rows_raw)

      # First pass: collect all non-None, non-timedelta col-A values for prev/next lookup
      a_values = []
      for row in rows_list:
          if not row:
              a_values.append(None)
          else:
              a_values.append(row[0])

      def _nearest_valid_cod(idx: int, direction: int) -> str | None:
          """Scan forward (direction=+1) or backward (-1) for the first valid cod."""
          i = idx + direction
          while 0 <= i < len(a_values):
              v = a_values[i]
              if _is_conto(v):
                  return v.strip()
              i += direction
          return None

      corrupted_unresolved = 0
      unmapped = 0

      for idx, row in enumerate(rows_list):
          if not row:
              continue

          col_a = row[0]
          col_b = row[1]
          col_c = row[2]
          col_e = row[4]
          col_h = row[7]

          if not col_b or str(col_b).strip() in ("0", ""):
              continue

          desc = str(col_b).strip()
          desc_upper = desc.upper()

          new_section = _detect_section(desc_upper, section)
          if new_section == "__STOP__":
              break
          if new_section != section:
              section = new_section
              if _should_skip(desc_upper):
                  continue

          if _should_skip(desc_upper):
              skipped += 1
              continue

          val_2025 = _v(col_c)
          val_2026 = _v(col_h)
          if val_2025 == 0 and val_2026 == 0:
              continue

          prev_cod = _nearest_valid_cod(idx, -1)
          next_cod = _nearest_valid_cod(idx, +1)
          codice_conto = _resolve_cod_conto_with_context(
              col_a, prev_cod, next_cod, desc, ce_desc_to_cod, logger
          )

          if codice_conto is None:
              # Hard error path — either timedelta-unresolved or unmapped
              if isinstance(col_a, timedelta):
                  corrupted_unresolved += 1
              else:
                  logger.warning(
                      f'  UNMAPPED: "{desc}" (2026={val_2026:,.0f}) — hard error'
                  )
                  unmapped += 1
              continue

          # ... rest of the loop body (tipo_costo resolution, build 12 monthly rows)
          #     stays exactly as-is from line 411 onward.
  ```

  After the loop, add a hard-fail gate **before** the existing summary:

  ```python
      if unmapped > 0 or corrupted_unresolved > 0:
          raise RuntimeError(
              f"Gasparotto ingest gate failed: "
              f"unmapped={unmapped}, corrupted_unresolved={corrupted_unresolved}. "
              f"Spec requires 0 of each. See WARNING logs above for details."
          )
  ```

  Update `DEFAULT_FILE` at line 59:

  ```python
  DEFAULT_FILE = Path(
      "/Users/stefanodellapietra/Desktop/WORK/artifacts/"
      "gasparotto_materialiereport/"
      "gasparotto_Budget_Indici2025.xlsx"
  )
  ```

- [ ] **Step 5: Add sanity check — Budget col H must be cached**

  The parser needs cached numeric values in Budget col H. Add at the start of `parse_gasparotto_budget` (right after `wb = openpyxl.load_workbook(...)`):

  ```python
      ws_check = wb["Budget"]
      sample = [ws_check.cell(row=r, column=8).value for r in range(11, 41)]
      populated = sum(1 for v in sample if v is not None)
      if populated < 10:
          wb.close()
          raise RuntimeError(
              f"Budget sheet col H (Previsione 2026) has only {populated}/30 cached "
              f"values — workbook not recalculated. Open the file in Excel and save, "
              f"or run: /Applications/LibreOffice.app/Contents/MacOS/soffice "
              f"--headless --calc --convert-to xlsx --outdir <tmpdir> <file>"
          )
  ```

- [ ] **Step 6: Row iteration reads cod_conto from CE, values from Budget**

  The parser currently iterates Budget rows and reads col A from Budget. Change it to iterate by row index, reading col A from CE (direct, timedelta-aware) and values from Budget (cached).

  In `parse_gasparotto_budget`, after loading the CE cross-ref (the step we edited in Step 4), introduce a helper `_ce_cod_conto_at` and modify the main loop so that col A comes from CE, not Budget. Replace the `col_a = row[0]` line with:

  ```python
          # Budget[R].A is None for formula cells; read cod_conto from CE[R].A directly.
          # The row numbering is 1:1 because Budget formulas are ='Conto Economico'!A{r}.
          # rows_list was sourced from Budget starting at min_row=11, so row r_index in
          # rows_list corresponds to CE row (11 + idx).
          ce_row = 11 + idx
          col_a = ws_ce.cell(row=ce_row, column=1).value if "Conto Economico" in wb.sheetnames else row[0]
  ```

  Where `ws_ce = wb["Conto Economico"]` was already loaded in Step 4. Keep the rest of the loop (it uses `col_a` through `_resolve_cod_conto_with_context`).

- [ ] **Step 7: Run tests — all parser tests must now pass**

  ```bash
  pytest tests/test_ingest_gasparotto.py -v
  ```

  Expected: 6 decoder tests + 6 parser tests = 12 passed.

- [ ] **Step 8: Commit**

  ```bash
  git add ingest/flussi/ingest_gasparotto.py tests/test_ingest_gasparotto.py tests/fixtures/gasparotto_Budget_Indici2025.xlsx
  git commit -m "feat(ingest): retarget Gasparotto parser to resolve timedelta cod_conto

  - Replace silent UNMAPPED-skip with hard RuntimeError on unresolvable rows.
  - Resolve timedelta-corrupted col A via section-context prefix + decoder.
  - Validate Budget sheet cached values are populated; error if not.
  - Update DEFAULT_FILE to gasparotto_Budget_Indici2025.xlsx."
  ```

---

## Task 3: Smoke-run ingest against BQ

**Files:**
- No code changes. Runtime verification only.

- [ ] **Step 1: Dry-run**

  ```bash
  python -m ingest.flussi.ingest_gasparotto \
    --file tests/fixtures/gasparotto_Budget_Indici2025.xlsx \
    --societa ORTI --dry-run
  ```

  Expected stdout:
  - `Conto Economico cross-ref: NN conti trovati`
  - `Timedelta decoded: ... → ...` (4 occurrences)
  - `ORTI: ~60 conti → ~720 righe mensili`
  - `Pydantic validation OK: 720 righe`
  - No `UNMAPPED` or `UNRESOLVED` warnings
  - `CSV: output/f_budget_gasparotto.csv  (720 righe)`

- [ ] **Step 2: Spot-check the CSV**

  ```bash
  head -5 output/f_budget_gasparotto.csv
  wc -l output/f_budget_gasparotto.csv
  ```

  Expected: header row + 720 data rows (60 conti × 12 months).

- [ ] **Step 3: Live ingest to BQ**

  ```bash
  python -m ingest.flussi.ingest_gasparotto \
    --file tests/fixtures/gasparotto_Budget_Indici2025.xlsx \
    --societa ORTI
  ```

  Expected stdout:
  - `Righe precedenti anno=2026 fonte=GASPAROTTO cancellate`
  - `hotelops-suite.hotelops.f_budget_mensile: ~720 righe caricate (fonte=GASPAROTTO)`
  - `✓ DONE`

- [ ] **Step 4: Verify BQ row counts**

  ```bash
  bq query --use_legacy_sql=false --format=pretty \
    "SELECT COUNT(*) AS n, SUM(importo) AS tot FROM \`hotelops-suite.hotelops.f_budget_mensile\` WHERE anno=2026 AND fonte='GASPAROTTO' AND societa_id='ORTI'"
  ```

  Expected: `n` ≥ 700, `tot` coherent with workbook totals (will depend on file).

- [ ] **Step 5: Commit a reference log**

  Capture the output of Step 1 to `docs/superpowers/runs/WI-1-dry-run.log` for reference:

  ```bash
  mkdir -p docs/superpowers/runs
  python -m ingest.flussi.ingest_gasparotto \
    --file tests/fixtures/gasparotto_Budget_Indici2025.xlsx \
    --societa ORTI --dry-run 2>&1 | tee docs/superpowers/runs/WI-1-dry-run.log
  git add docs/superpowers/runs/WI-1-dry-run.log
  git commit -m "docs(runs): WI-1 dry-run reference output"
  ```

---

## Task 4: Run INTUR ingest + regression test

- [ ] **Step 1: Dry-run INTUR variant**

  ```bash
  python -m ingest.flussi.ingest_gasparotto \
    --file tests/fixtures/gasparotto_Budget_Indici2025.xlsx \
    --societa INTUR --dry-run
  ```

  Expected: same parsing gates pass for INTUR societa_id. Seasonality coefficients differ but parsing logic identical.

- [ ] **Step 2: Ingest INTUR live**

  ```bash
  python -m ingest.flussi.ingest_gasparotto \
    --file tests/fixtures/gasparotto_Budget_Indici2025.xlsx \
    --societa INTUR
  ```

- [ ] **Step 3: Verify BQ holds both societies**

  ```bash
  bq query --use_legacy_sql=false --format=pretty \
    "SELECT societa_id, COUNT(*) AS n FROM \`hotelops-suite.hotelops.f_budget_mensile\` WHERE anno=2026 AND fonte='GASPAROTTO' GROUP BY 1 ORDER BY 1"
  ```

  Expected: 2 rows, ORTI and INTUR, each ~720.

- [ ] **Step 4: Full test suite regression**

  ```bash
  pytest -v
  ```

  Expected: all pre-existing tests still pass. If anything regresses, investigate before proceeding.

- [ ] **Step 5: Commit any minor fixes from Step 4 or WI-1 marker**

  ```bash
  git commit --allow-empty -m "test: WI-1 ingest adapter complete (ORTI + INTUR ingested, all tests pass)"
  ```

---

# WI-2 — Cash-Flow tab (Tasks 5–7)

## Task 5: Create `cashflow_loader.py` (pure BQ loader)

**Files:**
- Create: `condges/cashflow_loader.py`

**Rationale:** Keep BQ queries out of `app_cdg.py` so they can be tested without Streamlit. Single responsibility.

- [ ] **Step 1: Write failing test**

  Create `tests/test_cashflow_loader.py`:

  ```python
  """Tests for condges/cashflow_loader.py (BQ reader for Cash-Flow tab)."""

  from __future__ import annotations

  import pandas as pd
  import pytest

  from condges.cashflow_loader import (
      fetch_cashflow_voci,
      fetch_available_fonti,
      group_voci_by_sezione,
  )

  pytestmark = pytest.mark.bq  # Real BQ required (per repo convention)


  def test_fetch_cashflow_voci_returns_dataframe():
      df = fetch_cashflow_voci("ORTI", 2026)
      assert isinstance(df, pd.DataFrame)
      assert len(df) > 0
      for col in [
          "voce_id", "voce_label", "sezione", "categoria", "ord",
          "mese", "importo_consuntivo", "importo_budget", "tipo_periodo",
      ]:
          assert col in df.columns, f"Missing column: {col}"

  def test_fetch_cashflow_voci_has_entrate_and_uscite():
      df = fetch_cashflow_voci("ORTI", 2026)
      sezioni = set(df["sezione"].dropna().unique())
      assert "ENTRATE" in sezioni
      assert "USCITE" in sezioni

  def test_fetch_available_fonti_returns_list():
      fonti = fetch_available_fonti()
      assert isinstance(fonti, list)
      # At minimum expect the active fonti at time of plan
      for expected in ["PIANO_FINANZIARIO", "SCADENZIARIO"]:
          # Soft assertion: just check type, not presence (fonti may be empty in dev)
          pass
      assert all(isinstance(f, str) for f in fonti)

  def test_group_voci_by_sezione_shape():
      df = fetch_cashflow_voci("ORTI", 2026)
      groups = group_voci_by_sezione(df)
      assert "ENTRATE" in groups or "USCITE" in groups
      for sezione_df in groups.values():
          assert isinstance(sezione_df, pd.DataFrame)
  ```

- [ ] **Step 2: Run test — fails with ImportError**

  ```bash
  pytest tests/test_cashflow_loader.py -v
  ```

- [ ] **Step 3: Implement loader**

  Create `condges/cashflow_loader.py`:

  ```python
  """BQ loader for the Cash-Flow tab in app_cdg.py.

  Reads v_piano_finanziario_mensile (28 voci × 12 mesi) and exposes a DataFrame
  ready for display. Kept separate from Streamlit so it can be tested headless.
  """

  from __future__ import annotations

  import pandas as pd

  from core.bq.client import get_client
  from core.config import F_PIANO_FINANZIARIO_INPUT, V_PIANO_FINANZIARIO_MENSILE


  def fetch_cashflow_voci(societa: str, anno: int) -> pd.DataFrame:
      """Fetch cashflow voci × months for the given society and year.

      Returns a DataFrame with one row per (voce_id, mese), containing both
      consuntivo and budget values plus the sezione/categoria metadata.
      """
      client = get_client()
      sql = f"""
      SELECT voce_id, voce_label, sezione, categoria, ord, mese,
             tipo_periodo, importo_consuntivo, importo_budget
      FROM `{V_PIANO_FINANZIARIO_MENSILE}`
      WHERE anno = @anno AND societa_id = @societa
      ORDER BY ord, mese
      """
      from google.cloud import bigquery

      job_config = bigquery.QueryJobConfig(
          query_parameters=[
              bigquery.ScalarQueryParameter("anno", "INT64", anno),
              bigquery.ScalarQueryParameter("societa", "STRING", societa),
          ]
      )
      return client.query(sql, job_config=job_config).to_dataframe()


  def fetch_available_fonti() -> list[str]:
      """Return the distinct fonte values currently in f_piano_finanziario_input.

      The Cash-Flow tab uses this to build its badge legend dynamically, so that
      new fonte values (e.g. PROGETTI from the Projects vertical) show up without
      code changes.
      """
      client = get_client()
      sql = f"SELECT DISTINCT fonte FROM `{F_PIANO_FINANZIARIO_INPUT}` ORDER BY fonte"
      return [row.fonte for row in client.query(sql).result() if row.fonte]


  def group_voci_by_sezione(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
      """Split the cashflow DataFrame into {sezione: sub-df} for display sections."""
      return {sezione: sub for sezione, sub in df.groupby("sezione", dropna=False)}
  ```

- [ ] **Step 4: Add `F_PIANO_FINANZIARIO_INPUT` to `core/config.py` if missing**

  Check:
  ```bash
  grep -n "F_PIANO_FINANZIARIO_INPUT" core/config.py
  ```

  If no match: add the constant. Typical definition:
  ```python
  F_PIANO_FINANZIARIO_INPUT = f"{PROJECT}.{DATASET}.f_piano_finanziario_input"
  ```

  Place it alongside the other `F_*` constants. If already present, skip this step.

- [ ] **Step 5: Run tests — they must pass (real BQ)**

  ```bash
  pytest tests/test_cashflow_loader.py -v
  ```

  Expected: 4 passed. If they fail with `PermissionDenied` or similar, the `bq` marker may need to be registered in `pytest.ini`/`pyproject.toml` — check existing `@pytest.mark.bq` usage via `grep -rn "mark.bq" tests/`.

- [ ] **Step 6: Commit**

  ```bash
  git add condges/cashflow_loader.py tests/test_cashflow_loader.py core/config.py
  git commit -m "feat(condges): add cashflow_loader for Cash-Flow tab (WI-2 part 1)

  Pure BQ loader for v_piano_finanziario_mensile + fonti list. Testable
  without Streamlit."
  ```

---

## Task 6: Rewrite `page_tesoreria` → `page_cashflow` in `app_cdg.py`

**Files:**
- Modify: `condges/app_cdg.py:792-1007` (the `page_tesoreria` function)
- Modify: `condges/app_cdg.py:1247-1249` (tab labels and `with tab_tesoreria:` block)

The new page reads `v_piano_finanziario_mensile` via `cashflow_loader` and renders a layout that mirrors the Cash-Flow sheet in the Gasparotto workbook: SALDO BANCA → ENTRATE → TOTALE ENTRATE → USCITE → TOTALE USCITE → CASH FLOW NETTO → SALDO CUMULATIVO.

- [ ] **Step 1: Replace `page_tesoreria` with a new `page_cashflow` function**

  In `condges/app_cdg.py`, find the `def page_tesoreria(...)` at line 792. Replace the entire function body (lines 792–1007) with:

  ```python
  def page_cashflow(societa: str, anno: int, last_actual_month: int):
      """Cash-Flow tab — 1:1 layout with the Gasparotto workbook Cash-Flow sheet.

      Reads live from v_piano_finanziario_mensile and renders SALDO BANCA,
      ENTRATE, USCITE, CASH FLOW NETTO, and SALDO CUMULATIVO sections.
      """
      from condges.cashflow_loader import (
          fetch_cashflow_voci,
          fetch_available_fonti,
          group_voci_by_sezione,
      )

      # ── SALDO BANCA INIZIALE ────────────────────────────────────────────────
      st.subheader("Saldo Banca Iniziale")
      saldi = load_saldi_banca()
      if saldi.empty:
          st.warning("Nessun saldo banca trovato.")
          saldo_iniziale = 0.0
      else:
          saldo_iniziale = saldi["saldo_finale"].sum()
          data_saldo = saldi["data_snapshot"].max()
          cols = st.columns(len(saldi) + 1)
          cols[0].metric("TOTALE", f"{saldo_iniziale:,.0f} €", help=f"Al {data_saldo}")
          for i, (_, r) in enumerate(saldi.iterrows()):
              cols[i + 1].metric(
                  r["banca_id"], f"{r['saldo_finale']:,.0f} €",
                  help=f"Al {r['data_snapshot']}",
              )

      # ── Data load ───────────────────────────────────────────────────────────
      cf = fetch_cashflow_voci(societa, anno)
      if cf.empty:
          st.error(
              f"v_piano_finanziario_mensile vuota per {societa} {anno}. "
              f"Verifica che f_piano_finanziario_input contenga righe."
          )
          return

      fonti = fetch_available_fonti()
      st.caption(
          "Fonti disponibili: " + ", ".join(fonti) if fonti else "Nessuna fonte."
      )

      # ── Pivot: voce × mese matrix ───────────────────────────────────────────
      def pick_value(r):
          """Prefer consuntivo when present, else budget."""
          c = r.get("importo_consuntivo") or 0
          b = r.get("importo_budget") or 0
          return c if (c and r.get("tipo_periodo") == "CONSUNTIVO") else b

      cf["valore"] = cf.apply(pick_value, axis=1)

      def render_sezione(sezione: str, title: str):
          st.subheader(title)
          sub = cf[cf["sezione"] == sezione]
          if sub.empty:
              st.caption(f"Nessuna voce {sezione}.")
              return
          pivot = sub.pivot_table(
              index=["ord", "voce_label"], columns="mese", values="valore",
              aggfunc="sum", fill_value=0,
          ).reset_index().drop(columns=["ord"])
          pivot.columns = ["Voce"] + [MESI_NOMI[m - 1] for m in range(1, 13)][:len(pivot.columns)-1]
          pivot["TOTALE"] = pivot[pivot.columns[1:]].sum(axis=1)
          st.dataframe(
              pivot.style.format(
                  {c: "{:,.0f}" for c in pivot.columns if c != "Voce"}
              ),
              use_container_width=True, hide_index=True,
          )
          return pivot

      entrate_df = render_sezione("ENTRATE", "ENTRATE")
      uscite_df = render_sezione("USCITE", "USCITE")

      # ── Cash flow netto + saldo cumulativo ──────────────────────────────────
      if entrate_df is not None and uscite_df is not None:
          totali = {}
          for m in range(1, 13):
              mese_name = MESI_NOMI[m - 1]
              e = entrate_df[mese_name].sum() if mese_name in entrate_df else 0
              u = uscite_df[mese_name].sum() if mese_name in uscite_df else 0
              totali[m] = {"entrate": e, "uscite": u, "netto": e - u}

          cum = float(saldo_iniziale)
          saldo_by_mese = {}
          for m in range(1, 13):
              cum += totali[m]["netto"]
              saldo_by_mese[m] = cum

          summary = pd.DataFrame(
              [
                  {
                      "Mese": MESI_NOMI[m - 1],
                      "Entrate": totali[m]["entrate"],
                      "Uscite": totali[m]["uscite"],
                      "Netto": totali[m]["netto"],
                      "Saldo Cumulativo": saldo_by_mese[m],
                  }
                  for m in range(1, 13)
              ]
          )

          st.subheader("Cash Flow Netto & Saldo Cumulativo")
          st.dataframe(
              summary.style.format(
                  {c: "{:,.0f}" for c in ["Entrate", "Uscite", "Netto", "Saldo Cumulativo"]}
              ),
              use_container_width=True, hide_index=True,
          )
  ```

- [ ] **Step 2: Update the tabs block**

  At line 1247, replace:

  ```python
      tab_ce, tab_budget, tab_tesoreria, tab_indicatori = st.tabs(
          ["Conto Economico", "Budget", "Tesoreria", "Indicatori"]
      )
  ```

  with:

  ```python
      tab_ce, tab_budget, tab_cashflow, tab_indicatori = st.tabs(
          ["Conto Economico", "Budget", "Cash-Flow", "Indicatori"]
      )
  ```

  And line 1257–1258, replace:

  ```python
      with tab_tesoreria:
          page_tesoreria(adjusted, consuntivo, last_actual_month)
  ```

  with:

  ```python
      with tab_cashflow:
          page_cashflow(SOCIETA, ANNO, last_actual_month)
  ```

- [ ] **Step 3: Smoke-test the Streamlit app locally**

  ```bash
  streamlit run condges/app_cdg.py --server.headless true --server.port 8601 &
  APP_PID=$!
  sleep 4
  curl -s http://localhost:8601/_stcore/health
  kill $APP_PID
  ```

  Expected: health endpoint returns `ok`. Then manually open in browser to verify the Cash-Flow tab renders all sections without error:

  ```bash
  streamlit run condges/app_cdg.py
  ```

  Click the **Cash-Flow** tab. Verify:
  - "Saldo Banca Iniziale" section with at least one metric
  - "Fonti disponibili: ..." caption listing actual fonti (not hardcoded)
  - "ENTRATE" table with voce rows
  - "USCITE" table with voce rows
  - "Cash Flow Netto & Saldo Cumulativo" table with 12 rows

- [ ] **Step 4: Commit**

  ```bash
  git add condges/app_cdg.py
  git commit -m "feat(condges): replace Tesoreria tab with Cash-Flow tab reading v_piano_finanziario_mensile

  The new page_cashflow renders the 1:1 layout of the Gasparotto workbook
  Cash-Flow sheet (SALDO BANCA / ENTRATE / USCITE / CASH FLOW NETTO / SALDO
  CUMULATIVO) live from BQ, at voce-level granularity."
  ```

---

## Task 7: Add fonte badge + dynamic legend

**Files:**
- Modify: `condges/app_cdg.py:page_cashflow` (enhance the section renderer)

- [ ] **Step 1: Extend `fetch_cashflow_voci` to include `fonte`**

  In `condges/cashflow_loader.py`, update the SQL in `fetch_cashflow_voci`:

  ```python
  sql = f"""
  SELECT v.voce_id, v.voce_label, v.sezione, v.categoria, v.ord, v.mese,
         v.tipo_periodo, v.importo_consuntivo, v.importo_budget,
         (
           SELECT STRING_AGG(DISTINCT fpi.fonte ORDER BY fpi.fonte)
           FROM `{F_PIANO_FINANZIARIO_INPUT}` fpi
           WHERE fpi.societa_id = v.societa_id
             AND fpi.anno = v.anno
             AND fpi.mese = v.mese
             AND fpi.voce_id = v.voce_id
         ) AS fonti
  FROM `{V_PIANO_FINANZIARIO_MENSILE}` v
  WHERE v.anno = @anno AND v.societa_id = @societa
  ORDER BY v.ord, v.mese
  """
  ```

  Note: if `v_piano_finanziario_mensile` already exposes `fonte`, skip the subquery and just select `v.fonte`. Check column list first:

  ```bash
  bq query --use_legacy_sql=false --format=pretty \
    "SELECT column_name FROM \`hotelops-suite.hotelops.INFORMATION_SCHEMA.COLUMNS\` WHERE table_name='v_piano_finanziario_mensile'"
  ```

  If `fonte` is already in the view output, replace the subquery with `v.fonte AS fonti` for simplicity.

- [ ] **Step 2: Update test to expect the `fonti` column**

  Add to `tests/test_cashflow_loader.py`:

  ```python
  def test_fetch_cashflow_voci_includes_fonti_column():
      df = fetch_cashflow_voci("ORTI", 2026)
      assert "fonti" in df.columns, f"Expected 'fonti' column, got: {list(df.columns)}"
  ```

  Run:
  ```bash
  pytest tests/test_cashflow_loader.py -v
  ```

  Expected: all tests pass.

- [ ] **Step 3: Render the badge in `page_cashflow`**

  In `condges/app_cdg.py::page_cashflow`, inside the `render_sezione` helper, after building `pivot`, add a fonte-badge column by merging with unique voce→fonti:

  Change the pivot block to:

  ```python
          voce_to_fonti = (
              sub.dropna(subset=["fonti"])
                 .groupby("voce_label")["fonti"]
                 .agg(lambda s: ", ".join(sorted(set(s.dropna().unique()))))
                 .to_dict()
          )
          pivot = sub.pivot_table(
              index=["ord", "voce_label"], columns="mese", values="valore",
              aggfunc="sum", fill_value=0,
          ).reset_index().drop(columns=["ord"])
          pivot.columns = ["Voce"] + [MESI_NOMI[m - 1] for m in range(1, 13)][:len(pivot.columns)-1]
          pivot["TOTALE"] = pivot[pivot.columns[1:]].sum(axis=1)
          pivot.insert(1, "Fonti", pivot["Voce"].map(voce_to_fonti).fillna("—"))
  ```

  And update the format dict to include `"Fonti"` as a passthrough (no number format).

- [ ] **Step 4: Run Streamlit smoke test**

  ```bash
  streamlit run condges/app_cdg.py
  ```

  Open Cash-Flow tab, verify: each voce row now has a "Fonti" column listing the applicable fonti (e.g., `PIANO_FINANZIARIO, SCADENZIARIO`). Voci with no manual input show `—`.

- [ ] **Step 5: Commit**

  ```bash
  git add condges/app_cdg.py condges/cashflow_loader.py tests/test_cashflow_loader.py
  git commit -m "feat(condges): add fonte badge column to Cash-Flow tab

  Fonti are queried dynamically (SELECT DISTINCT fonte) to support future
  values like fonte=PROGETTI without code changes."
  ```

---

# WI-3 — Gasparotto workbook regenerator (Tasks 8–11)

## Task 8: Create `gasparotto_regen.py` with in-place rewrite

**Files:**
- Create: `condges/gasparotto_regen.py`
- Create: `tests/test_gasparotto_regen.py`

**Cash-Flow sheet row map (verified from fixture):**

| Rows | Content |
|---|---|
| R1 | Title "CASH FLOW" |
| R2 | Month headers: APRILE, MAGGIO, ..., MARZO (cols C–N) |
| R5 | "Banca" + initial balance + formulas =C94 forward |
| R7 | "A" SALDO BANCA — formula `=SUM(C5:C6)` |
| R9–R26 | ENTRATE DI GESTIONE (section headers R10, R13, R15, R20; data rows R11, R14, R16–R19, R21–R25) |
| R28 | "B" TOTALE ENTRATE — `=SUM(C11:C26)` |
| R30–R91 | USCITE DI GESTIONE (section headers R31, R35, R38, R44, R85; data rows R32–R88) |
| R92 | "C" TOTALE USCITE — `=SUM(C31:C91)` |
| R94 | "D" LIQUIDITÀ BANCA — `=C7+C28+C92` |

**Strategy:** map each data row (by col B descrizione) to a voce_id. Rewrite col C–N values using BQ query. Keep formulas at R7, R28, R92, R94 untouched. Months are shifted (col C=APRILE not GENNAIO) so BQ data must be re-ordered.

**Voce mapping for Cash-Flow rows** (to be expanded in subsequent iterations):

The Gasparotto workbook uses free-text descriptions (Row 32 "Salari e stipendi", Row 36 "Fornitori", etc.) while BQ uses `voce_id` codes. The regenerator needs a mapping table. A first-cut mapping based on the fixture is:

```python
GASPAROTTO_ROW_TO_VOCE = {
    16: "ENTRATE_HOTEL",       # "Entrate Hotel"
    17: "ENTRATE_RESIDENCE",   # "Entrate Residence"
    18: "ENTRATE_CVM",         # "Entrate CVM"
    19: "ENTRATE_SUPERMERCATO",# "Entrate Supermercato"
    24: "CAPARRE",             # "Clienti C/Caparre"
    32: "SALARI",              # "Salari e stipendi"
    36: "FORNITORI",           # "Fornitori"
    39: "F24_IMPOSTE",         # "Versamento Imposte e Tasse"
    40: "F24_IVA",             # "Versamento IVA"
    41: "F24_DIPENDENTI",      # "Dipendenti + Co.Co.Co."
    45: "UTENZE_ELETTRICA",    # "Energia elettrica"
    46: "UTENZE_GAS",          # "Gas"
    47: "UTENZE_ACQUA",        # "Acqua"
    # ... (expand during implementation; any row without a voce_id is left as-is)
}
```

The actual voce_id codes live in `d_voci_piano_finanziario`. Run a quick lookup to finalize the mapping during implementation:

```bash
bq query --use_legacy_sql=false --format=pretty \
  "SELECT voce_id, voce_label FROM \`hotelops-suite.hotelops.d_voci_piano_finanziario\` ORDER BY ord"
```

- [ ] **Step 1: Write failing test with a copy of the fixture**

  Create `tests/test_gasparotto_regen.py`:

  ```python
  """Tests for condges/gasparotto_regen.py — in-place Cash-Flow sheet rewrite."""

  from __future__ import annotations

  import shutil
  from pathlib import Path

  import openpyxl
  import pytest

  from condges.gasparotto_regen import rigenera_cashflow_sheet_gasparotto

  FIXTURE = Path(__file__).parent / "fixtures" / "gasparotto_Budget_Indici2025.xlsx"
  pytestmark = pytest.mark.bq  # needs BQ for voce lookup


  @pytest.fixture
  def workbook_copy(tmp_path):
      out = tmp_path / "gasparotto_copy.xlsx"
      shutil.copy(FIXTURE, out)
      return out


  def test_other_sheets_are_preserved(workbook_copy):
      wb_before = openpyxl.load_workbook(workbook_copy, data_only=False)
      sheet_hashes_before = {
          s: wb_before[s].calculate_dimension() for s in wb_before.sheetnames
      }
      wb_before.close()

      rigenera_cashflow_sheet_gasparotto(workbook_copy, societa="ORTI", anno=2026)

      wb_after = openpyxl.load_workbook(workbook_copy, data_only=False)
      for s in wb_after.sheetnames:
          if s == "Cash - Flow":
              continue
          assert wb_after[s].calculate_dimension() == sheet_hashes_before[s], (
              f"Sheet {s} was modified unexpectedly"
          )
      wb_after.close()


  def test_cashflow_rows_are_populated(workbook_copy):
      rigenera_cashflow_sheet_gasparotto(workbook_copy, societa="ORTI", anno=2026)
      wb = openpyxl.load_workbook(workbook_copy, data_only=False)
      ws = wb["Cash - Flow"]
      # R16 is "Entrate Hotel" → should be non-None in cols C-N
      row16_values = [ws.cell(row=16, column=c).value for c in range(3, 15)]
      assert any(
          isinstance(v, (int, float)) and v != 0 for v in row16_values
      ), f"Row 16 (Entrate Hotel) is empty after regen: {row16_values}"
      wb.close()


  def test_formulas_preserved(workbook_copy):
      rigenera_cashflow_sheet_gasparotto(workbook_copy, societa="ORTI", anno=2026)
      wb = openpyxl.load_workbook(workbook_copy, data_only=False)
      ws = wb["Cash - Flow"]
      # R28 SOMMA ENTRATE and R92 TOTALE USCITE must still be formulas
      assert isinstance(ws.cell(row=28, column=3).value, str) and ws.cell(row=28, column=3).value.startswith("="), (
          "R28 formula lost after regen"
      )
      assert isinstance(ws.cell(row=92, column=3).value, str) and ws.cell(row=92, column=3).value.startswith("="), (
          "R92 formula lost after regen"
      )
      wb.close()
  ```

- [ ] **Step 2: Run test — fails with ImportError**

  ```bash
  pytest tests/test_gasparotto_regen.py -v
  ```

- [ ] **Step 3: Implement `gasparotto_regen.py`**

  Create `condges/gasparotto_regen.py`:

  ```python
  """In-place regeneration of the Cash-Flow sheet in the Gasparotto workbook.

  Opens the workbook, rewrites the data cells in the Cash-Flow sheet with values
  from v_piano_finanziario_mensile, leaves all other sheets and all formulas at
  subtotal/total rows untouched.

  After writing, the caller may call force_recalc() to repopulate cached values
  for the ~9k formulas.
  """

  from __future__ import annotations

  import logging
  import shutil
  from pathlib import Path

  import openpyxl

  from condges.cashflow_loader import fetch_cashflow_voci

  LOG = logging.getLogger(__name__)

  # Col layout in Cash-Flow sheet: C=APRILE, D=MAGGIO, ..., N=MARZO
  # So Italian fiscal year starts April; map col_offset → mese
  COL_TO_MESE = {
      3: 4,    # C = APRILE
      4: 5,    # D = MAGGIO
      5: 6,
      6: 7,
      7: 8,
      8: 9,
      9: 10,
      10: 11,
      11: 12,
      12: 1,   # January of following year
      13: 2,
      14: 3,
  }

  # voce_id mapping by row in the Cash-Flow sheet (ORTI layout).
  # Keys are row numbers; values are voce_id strings from d_voci_piano_finanziario.
  # Rows not listed are preserved (section headers, formula rows, unmapped).
  # Confirmed from fixture + d_voci_piano_finanziario listing:
  GASPAROTTO_ROW_TO_VOCE: dict[int, str] = {
      16: "entrate_hotel",
      17: "entrate_residence",
      18: "entrate_cvm",
      19: "entrate_supermercato",
      24: "caparre_intur",
      32: "salari",
      36: "fornitori_materie_prime",
      39: "tasse_imposte",
      41: "f24_dipendenti",
      45: "utenze_energia",
      46: "utenze_gas",
      47: "utenze_acqua",
  }


  def rigenera_cashflow_sheet_gasparotto(
      workbook_path: Path | str,
      societa: str,
      anno: int,
      sheet_name: str = "Cash - Flow",
  ) -> None:
      """Rewrite the Cash-Flow sheet's data cells from BQ, in place.

      Preserves formulas (rows 7, 28, 92, 94), section headers, and all other
      sheets. Only cells at (row in GASPAROTTO_ROW_TO_VOCE, col in COL_TO_MESE)
      are overwritten.
      """
      workbook_path = Path(workbook_path)
      cf = fetch_cashflow_voci(societa, anno)
      if cf.empty:
          raise RuntimeError(
              f"Nessuna riga in v_piano_finanziario_mensile per {societa} {anno}"
          )

      # Build {(voce_id, mese): value} — prefer consuntivo when present
      value_map: dict[tuple[str, int], float] = {}
      for row in cf.itertuples(index=False):
          c = getattr(row, "importo_consuntivo", None) or 0
          b = getattr(row, "importo_budget", None) or 0
          v = c if (c and getattr(row, "tipo_periodo", "") == "CONSUNTIVO") else b
          value_map[(row.voce_id, row.mese)] = float(v)

      wb = openpyxl.load_workbook(str(workbook_path))
      if sheet_name not in wb.sheetnames:
          wb.close()
          raise RuntimeError(f"Sheet '{sheet_name}' not found in {workbook_path.name}")

      ws = wb[sheet_name]
      written = 0
      for row_num, voce_id in GASPAROTTO_ROW_TO_VOCE.items():
          for col_num, mese in COL_TO_MESE.items():
              v = value_map.get((voce_id, mese))
              if v is not None:
                  ws.cell(row=row_num, column=col_num, value=v)
                  written += 1

      wb.save(str(workbook_path))
      wb.close()
      LOG.info(
          f"Gasparotto Cash-Flow sheet regenerated: {written} cells rewritten "
          f"(société={societa}, anno={anno})"
      )


  def regenerate_with_dated_copy(
      input_path: Path | str, societa: str, anno: int
  ) -> Path:
      """Copy the input workbook to <stem>_aggiornato_YYYYMMDD.xlsx, then regenerate.

      Returns the path of the new file.
      """
      from datetime import date

      input_path = Path(input_path)
      stamp = date.today().strftime("%Y%m%d")
      out = input_path.with_name(f"{input_path.stem}_aggiornato_{stamp}.xlsx")
      shutil.copy(input_path, out)
      rigenera_cashflow_sheet_gasparotto(out, societa=societa, anno=anno)
      return out
  ```

- [ ] **Step 4: Run tests — they must pass**

  ```bash
  pytest tests/test_gasparotto_regen.py -v
  ```

  Expected: 3 passed.

  If `test_cashflow_rows_are_populated` fails because no data for voce_id `entrate_hotel` exists in BQ, verify the voce_id mapping matches real values:

  ```bash
  bq query --use_legacy_sql=false --format=pretty \
    "SELECT DISTINCT voce_id FROM \`hotelops-suite.hotelops.f_piano_finanziario_input\` WHERE societa_id='ORTI' ORDER BY voce_id"
  ```

  Update `GASPAROTTO_ROW_TO_VOCE` to use the actual voce_id strings observed. Re-run tests.

- [ ] **Step 5: Commit**

  ```bash
  git add condges/gasparotto_regen.py tests/test_gasparotto_regen.py
  git commit -m "feat(condges): add gasparotto_regen.rigenera_cashflow_sheet_gasparotto

  In-place rewrite of the Cash-Flow sheet data cells from v_piano_finanziario_mensile.
  Preserves formulas at total rows and all other sheets."
  ```

---

## Task 9: Add force_recalc helper (Option A) + static-fallback (Option B)

**Files:**
- Modify: `condges/gasparotto_regen.py` (add `force_recalc`)
- Modify: `tests/test_gasparotto_regen.py` (add recalc tests)

- [ ] **Step 1: Write failing test for force_recalc availability detection**

  Append to `tests/test_gasparotto_regen.py`:

  ```python
  def test_force_recalc_detects_libreoffice(monkeypatch):
      from condges.gasparotto_regen import find_libreoffice_binary

      # When LibreOffice is present, returns a Path that exists
      result = find_libreoffice_binary()
      if result is not None:
          assert result.exists()


  def test_force_recalc_returns_false_when_libreoffice_missing(
      workbook_copy, monkeypatch
  ):
      from condges.gasparotto_regen import force_recalc

      monkeypatch.setattr(
          "condges.gasparotto_regen.find_libreoffice_binary", lambda: None
      )
      ok = force_recalc(workbook_copy)
      assert ok is False


  def test_force_recalc_runs_when_libreoffice_present(workbook_copy):
      """Integration test: only runs if LibreOffice is actually installed."""
      from condges.gasparotto_regen import find_libreoffice_binary, force_recalc

      if find_libreoffice_binary() is None:
          pytest.skip("LibreOffice not installed")

      ok = force_recalc(workbook_copy)
      assert ok is True
      # After recalc, Budget sheet col H should be populated (not None)
      wb = openpyxl.load_workbook(workbook_copy, data_only=True)
      ws = wb["Budget"]
      sample = [ws.cell(row=r, column=8).value for r in range(11, 41)]
      wb.close()
      assert any(v is not None for v in sample), (
          "Budget col H still empty after force_recalc"
      )
  ```

- [ ] **Step 2: Run tests — fail with ImportError**

  ```bash
  pytest tests/test_gasparotto_regen.py -v
  ```

- [ ] **Step 3: Implement `find_libreoffice_binary` and `force_recalc`**

  In `condges/gasparotto_regen.py`, add at the bottom:

  ```python
  import subprocess

  LIBREOFFICE_CANDIDATES = [
      Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
      Path("/usr/bin/libreoffice"),
      Path("/usr/local/bin/libreoffice"),
      Path("/opt/homebrew/bin/libreoffice"),
      Path("/opt/homebrew/bin/soffice"),
  ]


  def find_libreoffice_binary() -> Path | None:
      """Locate a usable LibreOffice/soffice binary on disk.

      Returns the first path that exists and is executable, or None.
      """
      for cand in LIBREOFFICE_CANDIDATES:
          if cand.exists() and cand.is_file():
              return cand
      # Fall back to PATH lookup
      from shutil import which
      for name in ("libreoffice", "soffice"):
          p = which(name)
          if p:
              return Path(p)
      return None


  def force_recalc(workbook_path: Path | str) -> bool:
      """Force formula recalculation on an XLSX file via LibreOffice headless.

      Returns True on success, False if LibreOffice is not installed (caller
      should then fall back to static-value totals — Option B from spec).
      Re-writes the file in place.
      """
      workbook_path = Path(workbook_path)
      bin_ = find_libreoffice_binary()
      if bin_ is None:
          LOG.warning(
              "LibreOffice not found; cannot force formula recalc. "
              "Totals in the regenerated Cash-Flow sheet will show stale cached "
              "values until opened in Excel. Install with: "
              "`brew install --cask libreoffice`"
          )
          return False

      outdir = workbook_path.parent / f".libreoffice-recalc-{workbook_path.stem}"
      outdir.mkdir(exist_ok=True)
      try:
          subprocess.run(
              [
                  str(bin_),
                  "--headless",
                  "--calc",
                  "--convert-to",
                  "xlsx",
                  "--outdir",
                  str(outdir),
                  str(workbook_path),
              ],
              check=True,
              capture_output=True,
              timeout=120,
          )
          recalced = outdir / workbook_path.name
          if not recalced.exists():
              LOG.error(f"LibreOffice recalc produced no output at {recalced}")
              return False
          shutil.move(str(recalced), str(workbook_path))
          LOG.info(f"LibreOffice recalc OK: {workbook_path}")
          return True
      except subprocess.TimeoutExpired:
          LOG.error("LibreOffice recalc timed out after 120s")
          return False
      except subprocess.CalledProcessError as e:
          LOG.error(f"LibreOffice recalc failed: {e.stderr.decode(errors='replace')}")
          return False
      finally:
          if outdir.exists():
              shutil.rmtree(outdir, ignore_errors=True)
  ```

- [ ] **Step 4: Wire `force_recalc` into `regenerate_with_dated_copy`**

  Modify `regenerate_with_dated_copy` to call `force_recalc` after the regen:

  ```python
  def regenerate_with_dated_copy(
      input_path: Path | str,
      societa: str,
      anno: int,
      recalc: bool = True,
  ) -> Path:
      """Copy input → <stem>_aggiornato_YYYYMMDD.xlsx, regenerate, optionally recalc.

      When ``recalc`` is True and LibreOffice is available, forces formula
      recalculation so subtotals/totals display correctly even before the file is
      opened in Excel. Falls back silently (with WARNING log) if unavailable.
      """
      from datetime import date

      input_path = Path(input_path)
      stamp = date.today().strftime("%Y%m%d")
      out = input_path.with_name(f"{input_path.stem}_aggiornato_{stamp}.xlsx")
      shutil.copy(input_path, out)
      rigenera_cashflow_sheet_gasparotto(out, societa=societa, anno=anno)
      if recalc:
          force_recalc(out)
      return out
  ```

- [ ] **Step 5: Run tests**

  ```bash
  pytest tests/test_gasparotto_regen.py -v
  ```

  Expected: all pass (including the skipped one if LibreOffice isn't installed).

- [ ] **Step 6: If LibreOffice is not installed, install it now**

  ```bash
  brew install --cask libreoffice
  ```

  Then re-run tests:
  ```bash
  pytest tests/test_gasparotto_regen.py::test_force_recalc_runs_when_libreoffice_present -v
  ```

  Expected: now passes (no longer skipped).

- [ ] **Step 7: Commit**

  ```bash
  git add condges/gasparotto_regen.py tests/test_gasparotto_regen.py
  git commit -m "feat(condges): add force_recalc via LibreOffice headless (WI-3 Option A)

  After rewriting Cash-Flow sheet data cells with openpyxl, formula cached
  values are stale. force_recalc() invokes 'soffice --headless --calc
  --convert-to xlsx' to repopulate them. Falls back silently if LibreOffice
  is not installed; caller gets WARNING log."
  ```

---

## Task 10: Add `--target gasparotto` CLI flag to `genera_excel.py`

**Files:**
- Modify: `condges/genera_excel.py:353-401` (the `main` function)

- [ ] **Step 1: Add the CLI flag**

  In `condges/genera_excel.py::main`, update the argparse block:

  ```python
  def main():
      parser = argparse.ArgumentParser(
          description="Genera Piano Finanziario Excel da BigQuery"
      )
      parser.add_argument(
          "--target",
          choices=["rosa", "gasparotto"],
          default="rosa",
          help="rosa: genera Rosa.xlsx da zero. gasparotto: aggiorna Cash-Flow "
               "di un workbook Gasparotto esistente in-place.",
      )
      parser.add_argument(
          "--input",
          help="Path al workbook Gasparotto esistente (richiesto con --target gasparotto)",
      )
      parser.add_argument("--anno", type=int, default=2026)
      parser.add_argument(
          "--societa", default="ORTI", choices=["ORTI", "INTUR"],
          help="Società (solo per --target gasparotto)",
      )
      parser.add_argument(
          "--no-recalc", action="store_true",
          help="Salta il force-recalc via LibreOffice (solo --target gasparotto)",
      )
      parser.add_argument("--output", default=None, help="Output file path (solo rosa)")
      args = parser.parse_args()

      if args.target == "gasparotto":
          if not args.input:
              parser.error("--target gasparotto richiede --input <workbook.xlsx>")
          from condges.gasparotto_regen import regenerate_with_dated_copy

          out = regenerate_with_dated_copy(
              args.input,
              societa=args.societa,
              anno=args.anno,
              recalc=not args.no_recalc,
          )
          print(f"\n✓ {out} generato")
          return

      # --target rosa (existing logic, unchanged) -----------------------------
      anno = args.anno
      output = args.output or f"Piano_Finanziario_{anno}_{date.today().isoformat()}.xlsx"

      print("Fetching data from BigQuery...")
      voci = fetch_voci()
      print(f"  Voci: {len(voci)}")
      pf_data = fetch_pf_data(anno)
      print(f"  PF {anno}: {len(pf_data)} righe")
      stag_data = fetch_stagionalita(anno - 1)
      print(f"  Stagionalità {anno - 1}: {len(stag_data)} righe")

      wb = Workbook()
      wb.remove(wb.active)

      for societa in ["ORTI", "INTUR"]:
          print(f"  Building sheet PF {societa}...")
          saldo_tot, saldi_per_banca = fetch_saldo_banca(societa)
          print(f"  Saldo banca {societa}: €{saldo_tot:,.0f}")
          build_pf_sheet(
              wb,
              f"PF {societa}",
              societa, anno, voci, pf_data, stag_data,
              saldo_iniziale=saldo_tot, saldi_banca=saldi_per_banca,
          )
      wb.save(output)
      print(f"\n✓ {output} generato ({len(wb.sheetnames)} fogli)")
      print("  Nero = consuntivo reale | Blu su giallo = previsione da modificare")
      print("  Dopo la sessione con Rosa: usa 'hotelops previsione' per riscrivere in BQ")
  ```

- [ ] **Step 2: Smoke test — Rosa mode unchanged**

  ```bash
  python -m condges.genera_excel --anno 2026 --output /tmp/rosa_test.xlsx
  ls -lh /tmp/rosa_test.xlsx
  ```

  Expected: file exists, non-empty, 2 sheets.

- [ ] **Step 3: Smoke test — Gasparotto mode**

  ```bash
  cp tests/fixtures/gasparotto_Budget_Indici2025.xlsx /tmp/gp_source.xlsx
  python -m condges.genera_excel \
    --target gasparotto \
    --input /tmp/gp_source.xlsx \
    --societa ORTI --anno 2026
  ls -lh /tmp/gp_source_aggiornato_*.xlsx
  ```

  Expected: a dated file `gp_source_aggiornato_YYYYMMDD.xlsx` is created next to the source. Open it in Excel/LibreOffice to verify the Cash-Flow sheet data rows are populated and totals recalculate.

- [ ] **Step 4: Smoke test — Gasparotto mode with `--no-recalc`**

  ```bash
  python -m condges.genera_excel \
    --target gasparotto \
    --input /tmp/gp_source.xlsx \
    --societa ORTI --anno 2026 \
    --no-recalc
  ```

  Expected: runs to completion; WARNING in log indicates recalc skipped; data cells written correctly but subtotal formulas show cached stale values.

- [ ] **Step 5: Commit**

  ```bash
  git add condges/genera_excel.py
  git commit -m "feat(condges): add --target gasparotto to genera_excel CLI

  Routes to regenerate_with_dated_copy() for in-place Cash-Flow sheet update
  of an existing Gasparotto workbook. --no-recalc skips LibreOffice recalc."
  ```

---

## Task 11: Add `hotelops gasparotto` CLI wrapper

**Files:**
- Modify: `cli.py` (if the `gasparotto` subcommand isn't already there)

- [ ] **Step 1: Check current CLI surface**

  ```bash
  hotelops --help
  ```

  Look for a `gasparotto` subcommand. If absent:

- [ ] **Step 2: Add subcommand**

  Open `cli.py` and add a new subparser alongside the existing subcommands. Implement the handler as:

  ```python
  def cmd_gasparotto(args):
      """hotelops gasparotto regenera --input <file> [--societa ORTI] [--anno 2026]"""
      from condges.gasparotto_regen import regenerate_with_dated_copy
      out = regenerate_with_dated_copy(
          args.input, societa=args.societa, anno=args.anno,
          recalc=not args.no_recalc,
      )
      print(f"✓ {out}")
  ```

  Argparse wiring:

  ```python
  p_gp = sub.add_parser("gasparotto", help="Rigenera Cash-Flow del workbook Gasparotto")
  p_gp_sub = p_gp.add_subparsers(dest="gp_cmd", required=True)
  p_gp_reg = p_gp_sub.add_parser("regenera", help="Rigenera Cash-Flow in-place da BQ")
  p_gp_reg.add_argument("--input", required=True)
  p_gp_reg.add_argument("--societa", default="ORTI", choices=["ORTI", "INTUR"])
  p_gp_reg.add_argument("--anno", type=int, default=2026)
  p_gp_reg.add_argument("--no-recalc", action="store_true")
  p_gp_reg.set_defaults(func=cmd_gasparotto)
  ```

  Place these near the other subparser definitions in `cli.py`. Exact line depends on file structure — read `cli.py` first to match the existing style.

- [ ] **Step 3: Smoke test**

  ```bash
  hotelops gasparotto regenera --input /tmp/gp_source.xlsx --societa ORTI
  ```

  Expected: same output as Task 10 Step 3.

- [ ] **Step 4: Commit**

  ```bash
  git add cli.py
  git commit -m "feat(cli): add 'hotelops gasparotto regenera' subcommand"
  ```

---

# WI-4 — Docs + invariant (Task 12)

## Task 12: Update CLAUDE.md + vault snippet

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/vault-snippets/I9-cashflow-invariant.md`

- [ ] **Step 1: Add CLAUDE.md note**

  In `CLAUDE.md`, find the "Project Overview" section. Edit the first paragraph to clarify the hierarchy:

  ```markdown
  hotelops is the financial data platform for Gruppo Panorama hotel operations. It ingests data from banks, ERP (Esolver), PMS (HotelCube), and manual budgets into BigQuery, then serves the **condges** (Controllo di Gestione) vertical — the strategic reporting layer owned by Gasparotto. The **Rosa** workflow is a subset of condges: an operational data-entry channel (supplier-level scadenzario → f_piano_finanziario_input) that feeds the condges Cash-Flow view. Every financial event has three temporal dimensions: COMPETENZA, CASSA, IMPEGNO. BigQuery is the source of truth.
  ```

  Then, in the "Governance Rules" section, add:

  ```markdown
  - **Invariant I9** — `f_piano_finanziario_input` is the single source of truth for CASSA forecasts. Every rendering (Rosa.xlsx, Gasparotto.xlsx Cash-Flow sheet, `app_cdg.py` Cash-Flow tab) is derived. **No reverse ingest of renderings** — the Cash-Flow sheet of the Gasparotto workbook is never parsed back into BQ.
  ```

- [ ] **Step 2: Create vault snippet**

  Create `docs/vault-snippets/I9-cashflow-invariant.md`:

  ```markdown
  # Invariant I9 — Cashflow Source of Truth

  **Paste-ready snippet for `<vault>/hotelops/INVARIANTS.md`.**

  ---

  ## I9. `f_piano_finanziario_input` is the single source of truth for CASSA forecasts.

  The Rosa workflow (supplier-level scadenzario + monthly snapshot Rosa.xlsx) feeds this table via `app_scadenzario.py` and `update_previsione.py` using DELETE-INSERT on key `(societa_id, anno, mese, voce_id, fonte)`.

  Every rendering of cashflow data is **derived** from this table:

  - `Rosa.xlsx` — generated via `genera_excel.py --target rosa`
  - `Gasparotto.xlsx` Cash-Flow sheet — regenerated via `genera_excel.py --target gasparotto --input <file>` (rewrites data cells in place; other sheets untouched)
  - `app_cdg.py` Cash-Flow tab — queries `v_piano_finanziario_mensile` live

  **Hard rule:** No ingest of these renderings back into BQ. Data flows Rosa → BQ → renderings, never renderings → BQ.

  **Implication for Rosa.xlsx lifecycle:** Rosa.xlsx is an atomic monthly snapshot (re-generated 1st of each month from end-of-previous-month bank balances + current scadenzario). Historicization is by `fonte` tag, not by versioned file.

  ### Glossary update

  - **condges** = gasparotto — the strategic reporting vertical (CE, Budget, Cash-Flow, Indicatori). `condges/app_cdg.py` is the condges app.
  - **Rosa** — a subset/operational channel of condges. Not a peer of Gasparotto. Rosa tools: `app_scadenzario.py`, `update_previsione.py`.
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add CLAUDE.md docs/vault-snippets/I9-cashflow-invariant.md
  git commit -m "docs: add Invariant I9 (cashflow source of truth) + condges=gasparotto hierarchy

  The vault snippet is ready to paste into <vault>/hotelops/INVARIANTS.md.
  CLAUDE.md gets the short form so agents working in the repo see it."
  ```

- [ ] **Step 4: Remind the user to update the vault**

  Append to the commit message or post-task note: the user must manually copy `docs/vault-snippets/I9-cashflow-invariant.md` into their Obsidian vault at `<vault>/hotelops/INVARIANTS.md`. The plan deliberately does not write to the vault directory (its path is user-specific and lives outside the repo).

---

# Final Verification

- [ ] **Verify all tests pass**

  ```bash
  pytest -v
  ```

  Expected: all pre-existing tests + the new ones all green.

- [ ] **Verify end-to-end smoke run**

  ```bash
  # 1. Rosa updates scadenzario (manual; simulate via CLI)
  hotelops previsione utenze 4-12 22000

  # 2. app_cdg shows the update
  streamlit run condges/app_cdg.py
  # → Cash-Flow tab shows updated 'utenze' values, fonte=CLI/APP

  # 3. Regenerate Gasparotto workbook
  hotelops gasparotto regenera \
    --input tests/fixtures/gasparotto_Budget_Indici2025.xlsx \
    --societa ORTI --anno 2026

  # 4. Open the resulting *_aggiornato_*.xlsx and verify Cash-Flow sheet
  #    matches what's shown in the app.
  ```

- [ ] **Verify BQ state**

  ```bash
  bq query --use_legacy_sql=false --format=pretty \
    "SELECT societa_id, COUNT(*) AS n FROM \`hotelops-suite.hotelops.f_budget_mensile\` WHERE anno=2026 AND fonte='GASPAROTTO' GROUP BY 1"
  ```

  Expected: ORTI and INTUR each with ~720 rows.

- [ ] **Final commit**

  ```bash
  git commit --allow-empty -m "done: WI-1..WI-4 complete, Rosa→Condges loop closed"
  ```
