# PF Engine Extraction (D1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development o superpowers:executing-plans. Step con checkbox `- [ ]`. È un refactor di **spostamento** (le funzioni esistono già): muovi verbatim, aggiorna import, cancella il guscio, tieni i test verdi.

**Goal:** Estrarre il motore di scrittura PF da `verticals/condges/app_scadenzario.py` (deprecato ma **load-bearing**) in un modulo dedicato, aggiornare gli importatori, cancellare il guscio UI. Risultato: niente più file "deprecato" che ospita codice vivo; una sola superficie utente (Cashflow).

**Architecture:** `app_scadenzario.py` (824 righe) = 9 funzioni engine (righe ~64–473) + `main()` UI Streamlit (~474–824). Il Cashflow vertical ha già sostituito la UI. Il motore va in `verticals/condges/pf_rotate/pf_writer.py` (accanto agli altri moduli engine di `pf_rotate`); gli importatori puntano lì; il file vecchio si cancella.

**Tech Stack:** Python 3.11+, openpyxl, pandas, pytest, ruff. Branch: `feat/pf-engine-extraction` (worktree). Test dal worktree con `python -m pytest`.

## Global Constraints
- **Spostamento verbatim**: muovi le funzioni senza cambiarne la logica (è un refactor strutturale, non funzionale). Ogni diff dev'essere "move", non "rewrite".
- **Test = safety net**: ~5 file di test toccano queste funzioni; devono restare verdi a ogni step.
- **Surgical**: non riformattare codice adiacente; ruff solo sui file toccati (mai `ruff format .`).
- **`VOCE_LABELS` vive già in `fornitori_map`** (spostato in PR #37). Se le funzioni engine la usano, importarla da `fornitori_map`, NON ridefinirla.

**Funzioni engine da muovere (da `app_scadenzario.py`):**
`resolve_sheet_name`, `load_fornitori_map`, `_build_month_col_map`, `_find_previsionale_row`, `_find_total_row_and_range`, `_find_supplier_row_by_name`, `_find_supplier_row_by_codice`, `read_pf_sheet`, `write_pf` (+ eventuali costanti modulo che usano, es. `VOCE_TO_SHEET_CANDIDATES` se presente).

**Importatori esterni da aggiornare (verificati 2026-06-19):**
- `verticals/condges/pf_rotate/step3_scadenzario.py` — `write_pf`
- `verticals/condges/pf_generator/previsioni.py` — import multiplo
- `verticals/condges/pf_generator/valida.py` — `_build_month_col_map`
- `verticals/condges/cli_commands.py` — import
- `tests/test_scadenzario.py` — `write_pf`
- `tests/test_pf_generator_assemble.py` — `_build_month_col_map`

---

## Task 1: Crea `pf_writer.py` con le funzioni engine

**Files:**
- Create: `verticals/condges/pf_rotate/pf_writer.py`

- [ ] **Step 1:** Apri `app_scadenzario.py`, identifica le costanti modulo usate dalle 9 funzioni (es. `VOCE_TO_SHEET_CANDIDATES`, eventuali regex/mappe). `VOCE_LABELS` → importa da `fornitori_map`.
- [ ] **Step 2:** Crea `pf_writer.py` con docstring ("Motore di scrittura PF — estratto da app_scadenzario, casa engine accanto a pf_rotate"). Copia **verbatim** le 9 funzioni + costanti necessarie + gli import che servono (openpyxl, pandas, csv, re, `fornitori_map` per VOCE_LABELS).
- [ ] **Step 3:** `python -c "import ast; ast.parse(open('verticals/condges/pf_rotate/pf_writer.py').read()); print('OK')"` + `python -c "from verticals.condges.pf_rotate.pf_writer import write_pf, _build_month_col_map, read_pf_sheet; print('import OK')"`.
- [ ] **Step 4:** Commit: `feat(condges): pf_writer.py — motore scrittura PF estratto (no logica nuova)`.

## Task 2: Aggiorna l'importatore engine `step3_scadenzario`

**Files:** Modify `verticals/condges/pf_rotate/step3_scadenzario.py`

- [ ] **Step 1:** Cambia `from verticals.condges.app_scadenzario import write_pf` → `from verticals.condges.pf_rotate.pf_writer import write_pf`.
- [ ] **Step 2:** `python -m pytest tests/test_pf_rotate_step3.py tests/test_pf_rotate_golden.py -q` → verde.
- [ ] **Step 3:** Commit.

## Task 3: Aggiorna `pf_generator` (previsioni + valida)

**Files:** Modify `verticals/condges/pf_generator/previsioni.py`, `verticals/condges/pf_generator/valida.py`

- [ ] **Step 1:** Sposta gli import da `app_scadenzario` → `pf_rotate.pf_writer` (verifica i nomi esatti: `_build_month_col_map` e quelli in `previsioni`).
- [ ] **Step 2:** `python -m pytest tests/test_pf_generator_assemble.py tests/test_pf_valida.py -q` → verde.
- [ ] **Step 3:** Commit.

## Task 4: Aggiorna `cli_commands` + i test

**Files:** Modify `verticals/condges/cli_commands.py`, `tests/test_scadenzario.py`, `tests/test_pf_generator_assemble.py`

- [ ] **Step 1:** Riassegna gli import a `pf_writer` in `cli_commands.py` e nei due test.
- [ ] **Step 2:** `grep -rn "from verticals.condges.app_scadenzario import" --include='*.py' .` → **0 risultati** (nessuno importa più dal file vecchio).
- [ ] **Step 3:** `python -m pytest tests/test_scadenzario.py -q` → verde.
- [ ] **Step 4:** Commit.

## Task 5: Cancella `app_scadenzario.py` + wiring CLI

**Files:** Delete `verticals/condges/app_scadenzario.py`; Modify `cli.py`

- [ ] **Step 1:** Conferma di nuovo `grep -rn "app_scadenzario" --include='*.py' .` → solo `cli.py` (il launch) e nessun import di funzioni.
- [ ] **Step 2:** `git rm verticals/condges/app_scadenzario.py`.
- [ ] **Step 3:** In `cli.py` rimuovi l'entry `"scadenzario": "verticals/condges/app_scadenzario.py"` e il suo handler/subparser (cerca `scadenzario` in cli.py). 
- [ ] **Step 4:** `python -c "import ast; ast.parse(open('cli.py').read()); print('OK')"` + `grep -rn "app_scadenzario" --include='*.py' .` → 0.
- [ ] **Step 5:** Commit: `refactor(condges): cancella app_scadenzario (UI sostituita da Cashflow; motore in pf_writer)`.

## Task 6: Green finale

- [ ] **Step 1:** `ruff format` + `ruff check` SOLO sui file toccati (lista esplicita; mai `ruff format .`).
- [ ] **Step 2:** `python -m pytest -q` → tutti verdi (atteso ~787±).
- [ ] **Step 3:** Aggiorna CLAUDE.md: rimuovi la nota "app_scadenzario load-bearing" (ora risolta); il motore è `pf_rotate/pf_writer`.
- [ ] **Step 4:** Commit finale.

## Definition of Done
- `pf_writer.py` ospita il motore; **zero** import da `app_scadenzario` (`grep` = 0); `app_scadenzario.py` cancellato; CLI senza `scadenzario`.
- `pytest -q` e `ruff check` (file slice) verdi. Logica invariata (refactor di spostamento).
- CLAUDE.md aggiornato (niente più file deprecato-load-bearing).

## Gotchas (verificare in esecuzione)
- Le funzioni engine potrebbero usare costanti/regex modulo di `app_scadenzario` non ovvie → muoverle insieme.
- `read_pf_sheet`/`write_pf` sono grandi (write_pf ~200 righe) → muovi verbatim, non riscrivere.
- Controlla che `main()` (UI) non definisse helper usati anche dall'engine (in tal caso spostali in pf_writer).
- `VOCE_LABELS` da `fornitori_map` (non ridefinire).

## Out of scope (D2 — task separato)
`tesoreria.py` standalone + `cmd_tesoreria`: candidati-ridondanti col **tab tesoreria di `app_cdg`** (`page_tesoreria`), ma il layer dati tesoreria (`bq_tesoreria_core`, `gen_tesoreria_xlsx`, `export_excel`) è feature separata. **Prima investigare** se lo standalone duplica il tab; poi decidere. NON in questo plan.
