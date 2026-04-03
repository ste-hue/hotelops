# Scadenzario Write-Back to PF Excel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically transfer supplier payment data from Esolver sintetica into Rosa's PF Excel, cascading overdue amounts into the current month.

**Architecture:** Parse sintetica → cascade scaduto into current month → map suppliers to PF voci via d_fornitori → match suppliers to PF detail sheet rows by nome_pf → write amounts into correct month columns → save updated PF Excel.

**Tech Stack:** openpyxl (already used), existing `parse_sintetica_scadenze()` and `load_fornitori_map()` from `condges/scadenzario_excel.py`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `condges/scadenzario_excel.py` | Modify | Add `cascade_scaduto()` and `write_back_to_pf()` functions |
| `cli.py` | Modify | Wire `--write-back` flag on scadenzario subcommand |
| `tests/test_scadenzario.py` | Modify | Add tests for cascade + write-back |

## Key Data Mappings

### Sintetica columns → Calendar months

| Sintetica col | Header | Calendar month |
|---|---|---|
| 3 | Scaduto fino al 02/04/2026 | **→ cascade into April (current month)** |
| 4 | In scadenza al 02/05/2026 | May |
| 5 | In scadenza al 02/06/2026 | June |
| 6 | In scadenza al 02/07/2026 | July |
| 7 | In scadenza al 02/08/2026 | August |
| 8 | In scadenza al 02/09/2026 | September |
| 9 | In scadenza al 02/10/2026 | October |
| 10 | Oltre il 02/10/2026 | → November (first month after last bucket) |

### PF detail sheet month columns (row 2 headers)

| Col | Month (2025) | Col | Month (2026) |
|-----|------|-----|------|
| C4 | SETTEMBRE | C8 | GENNAIO |
| C5 | OTTOBRE | C9 | FEBBRAIO |
| C6 | NOVEMBRE | C10 | MARZO |
| C7 | DICEMBRE | C11 | APRILE |
| | | C12 | MAGGIO |
| | | C13 | GIUGNO |
| | | C14 | LUGLIO |
| | | C15 | AGOSTO |
| | | C16 | SETTEMBRE |
| | | C17 | OTTOBRE |
| | | C18 | NOVEMBRE |
| | | C19 | DICEMBRE |

### Voce ID → PF Sheet Name

| voce_id | Sheet name (exact, including typos/spaces) |
|---------|---------------------------------------------|
| USCITE_MATERIE_PRIME | `Materie Prime-Consumo ` (trailing space) |
| USCITE_UTENZE | `Utenze` |
| USCITE_SALARI | `Salari e Stipendi` |
| USCITE_TASSE | `Tasse e Imposte` |
| USCITE_COMMISSIONI | `Commisisoni Portali` (typo is real) |
| USCITE_MUTUI | `Mutui e Finaziamenti` (typo is real) |
| USCITE_CONSULENZE | `Consulenze` |
| USCITE_CANONE_PASSIVO | `Godimento Beni di Terzi` |
| USCITE_VARIE_EXT | ` Varie ed Eventuali` (leading space) |
| USCITE_SERVIZI_PRODUZIONE | `Canoni e servizi` |
| USCITE_MARKETING | (no sheet — skip) |

### Supplier matching

d_fornitori.csv has `nome_pf` — the exact name Rosa uses in her PF detail sheets. Match by scanning column B of each detail sheet for exact match. If no `nome_pf` in d_fornitori (empty field), the supplier's amounts still aggregate into the voce total but no individual row is written.

---

## Task 1: Add cascade_scaduto() function

**Files:**
- Test: `tests/test_scadenzario.py`
- Modify: `condges/scadenzario_excel.py`

- [ ] **Step 1: Write failing test for cascade logic**

```python
def test_cascade_scaduto_moves_overdue_to_current_month():
    """Scaduto amounts should be added to the current month bucket."""
    from condges.scadenzario_excel import cascade_scaduto

    suppliers = [
        {
            "codice_fornitore": 1,
            "nome": "ACME",
            "totale": 1500,
            "scaduto": 500,
            "buckets": {5: 600, 6: 400},
        },
        {
            "codice_fornitore": 2,
            "nome": "BETA",
            "totale": 300,
            "scaduto": 300,
            "buckets": {},
        },
    ]
    result = cascade_scaduto(suppliers, current_month=4)

    # Scaduto should be added to April bucket
    assert result[0]["buckets"][4] == 500
    assert result[0]["buckets"][5] == 600  # unchanged
    assert result[0]["buckets"][6] == 400  # unchanged
    assert result[0]["scaduto"] == 0  # cleared after cascade

    # Supplier with only scaduto
    assert result[1]["buckets"][4] == 300
    assert result[1]["scaduto"] == 0


def test_cascade_scaduto_adds_to_existing_current_month():
    """If current month already has an amount, scaduto is added to it."""
    from condges.scadenzario_excel import cascade_scaduto

    suppliers = [
        {
            "codice_fornitore": 1,
            "nome": "ACME",
            "totale": 1000,
            "scaduto": 200,
            "buckets": {4: 300, 5: 500},
        },
    ]
    result = cascade_scaduto(suppliers, current_month=4)
    assert result[0]["buckets"][4] == 500  # 300 + 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scadenzario.py::test_cascade_scaduto_moves_overdue_to_current_month -v`
Expected: FAIL — `cascade_scaduto` not found

- [ ] **Step 3: Implement cascade_scaduto**

Add to `condges/scadenzario_excel.py` after the `map_to_voci` function:

```python
def cascade_scaduto(
    suppliers: list[dict], current_month: int | None = None
) -> list[dict]:
    """Move overdue (scaduto) amounts into the current month bucket.

    Mutates suppliers in-place and returns them for chaining.
    """
    if current_month is None:
        current_month = date.today().month

    for s in suppliers:
        if s["scaduto"] and s["scaduto"] != 0:
            s["buckets"][current_month] = s["buckets"].get(current_month, 0) + s["scaduto"]
            s["scaduto"] = 0
    return suppliers
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scadenzario.py::test_cascade_scaduto_moves_overdue_to_current_month tests/test_scadenzario.py::test_cascade_scaduto_adds_to_existing_current_month -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add condges/scadenzario_excel.py tests/test_scadenzario.py
git commit -m "feat: add cascade_scaduto to roll overdue into current month"
```

---

## Task 2: Add write_back_to_pf() function

**Files:**
- Test: `tests/test_scadenzario.py`
- Modify: `condges/scadenzario_excel.py`

- [ ] **Step 1: Write failing test for write-back**

```python
import openpyxl
from pathlib import Path
import tempfile
import shutil


def _make_pf_fixture(tmp_path: Path) -> Path:
    """Create a minimal PF Excel that mimics Rosa's layout."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Piano Finanziario"
    # Row 1: year markers
    ws.cell(row=1, column=3, value=2025)
    ws.cell(row=1, column=7, value=2026)
    # Row 2: calendar month names
    months_2025 = ["SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE"]
    months_2026 = [
        "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO",
        "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE",
        "NOVEMBRE", "DICEMBRE",
    ]
    for i, m in enumerate(months_2025):
        ws.cell(row=2, column=3 + i, value=m)
    for i, m in enumerate(months_2026):
        ws.cell(row=2, column=7 + i, value=m)
    # Row 14: Salari total, Row 16: Materie Prime total
    ws.cell(row=14, column=1, value="Salari e Stipendi")
    ws.cell(row=16, column=1, value="Materie Prime/Consumo")

    # Create detail sheet "Materie Prime-Consumo " (trailing space!)
    ws_mp = wb.create_sheet("Materie Prime-Consumo ")
    # Row 2: month headers (offset: starts at col 4)
    for i, m in enumerate(months_2025):
        ws_mp.cell(row=2, column=4 + i, value=m)
    for i, m in enumerate(months_2026):
        ws_mp.cell(row=2, column=8 + i, value=m)
    # Row 4: voce total
    ws_mp.cell(row=4, column=2, value="Materie Prime e Consumo")
    # Row 5+: suppliers
    ws_mp.cell(row=5, column=2, value="Le Croissant srl")
    ws_mp.cell(row=6, column=2, value="Giacinto Di Palma")
    ws_mp.cell(row=7, column=2, value="PREVISIONALE")
    ws_mp.cell(row=7, column=11, value=60000)  # April previsionale

    out = tmp_path / "PF_test.xlsx"
    wb.save(out)
    return out


def test_write_back_to_pf_places_amounts_correctly(tmp_path):
    """write_back_to_pf should update supplier rows in the PF detail sheet."""
    from condges.scadenzario_excel import write_back_to_pf, VOCE_TO_SHEET

    pf_path = _make_pf_fixture(tmp_path)

    # Mapped data: after cascade, Le Croissant has April=14277, May=0
    mapped = {
        "USCITE_MATERIE_PRIME": [
            {
                "codice_fornitore": 1,
                "nome": "LE CROISSANT SRL",
                "totale": 14277,
                "scaduto": 0,
                "buckets": {4: 14277},
            },
            {
                "codice_fornitore": 4,
                "nome": "Giacinto Di Palma",
                "totale": 390,
                "scaduto": 0,
                "buckets": {4: 390},
            },
        ],
    }

    fornitori_map_full = {
        1: {"voce_id": "USCITE_MATERIE_PRIME", "nome_pf": "Le Croissant srl"},
        4: {"voce_id": "USCITE_MATERIE_PRIME", "nome_pf": "Giacinto Di Palma"},
    }

    out = write_back_to_pf(pf_path, mapped, fornitori_map_full)

    # Verify the output Excel
    wb = openpyxl.load_workbook(out, data_only=True)
    ws_mp = wb["Materie Prime-Consumo "]

    # April is column 11 on detail sheets (col 8=GENNAIO + 3 = APRILE)
    # Le Croissant is row 5
    assert ws_mp.cell(row=5, column=11).value == 14277
    # Giacinto Di Palma is row 6
    assert ws_mp.cell(row=6, column=11).value == 390
    # PREVISIONALE row should be untouched
    assert ws_mp.cell(row=7, column=11).value == 60000


def test_write_back_preserves_non_scadenzario_data(tmp_path):
    """Months/rows not touched by sintetica should remain unchanged."""
    from condges.scadenzario_excel import write_back_to_pf

    pf_path = _make_pf_fixture(tmp_path)

    # Write some existing data first
    wb = openpyxl.load_workbook(pf_path)
    ws_mp = wb["Materie Prime-Consumo "]
    ws_mp.cell(row=5, column=12, value=9999)  # May, Le Croissant — manually entered
    wb.save(pf_path)

    mapped = {
        "USCITE_MATERIE_PRIME": [
            {
                "codice_fornitore": 1,
                "nome": "LE CROISSANT SRL",
                "totale": 14277,
                "scaduto": 0,
                "buckets": {4: 14277},  # only April
            },
        ],
    }
    fornitori_map_full = {
        1: {"voce_id": "USCITE_MATERIE_PRIME", "nome_pf": "Le Croissant srl"},
    }

    out = write_back_to_pf(pf_path, mapped, fornitori_map_full)
    wb = openpyxl.load_workbook(out)
    ws_mp = wb["Materie Prime-Consumo "]

    # April should be updated
    assert ws_mp.cell(row=5, column=11).value == 14277
    # May should be preserved
    assert ws_mp.cell(row=5, column=12).value == 9999
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scadenzario.py::test_write_back_to_pf_places_amounts_correctly -v`
Expected: FAIL — `write_back_to_pf` not found

- [ ] **Step 3: Implement write_back_to_pf**

Add to `condges/scadenzario_excel.py`:

```python
# ── Voce → PF Sheet mapping ──────────────────────────────────────────────

VOCE_TO_SHEET = {
    "USCITE_MATERIE_PRIME": "Materie Prime-Consumo ",
    "USCITE_UTENZE": "Utenze",
    "USCITE_SALARI": "Salari e Stipendi",
    "USCITE_TASSE": "Tasse e Imposte",
    "USCITE_COMMISSIONI": "Commisisoni Portali",
    "USCITE_MUTUI": "Mutui e Finaziamenti",
    "USCITE_CONSULENZE": "Consulenze",
    "USCITE_CANONE_PASSIVO": "Godimento Beni di Terzi",
    "USCITE_VARIE_EXT": " Varie ed Eventuali",
    "USCITE_SERVIZI_PRODUZIONE": "Canoni e servizi",
}

MONTH_NAMES_IT = {
    "GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4,
    "MAGGIO": 5, "GIUGNO": 6, "LUGLIO": 7, "AGOSTO": 8,
    "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12,
}


def load_fornitori_map_full(csv_path: Path = FORNITORI_CSV) -> dict[int, dict]:
    """Load d_fornitori CSV, return {codice_fornitore: {voce_id, nome_pf}}."""
    result = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[int(row["codice_fornitore"])] = {
                "voce_id": row["voce_id"],
                "nome_pf": row.get("nome_pf", "").strip(),
            }
    return result


def _build_month_col_map(ws) -> dict[int, int]:
    """Scan row 2 of a detail sheet, return {calendar_month: column}."""
    col_map = {}
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=2, column=col).value
        if val and str(val).strip().upper() in MONTH_NAMES_IT:
            month = MONTH_NAMES_IT[str(val).strip().upper()]
            # Only take the 2026 instance (second occurrence for months 9-12)
            if month not in col_map or col > col_map[month]:
                col_map[month] = col
    return col_map


def _find_supplier_row(ws, nome_pf: str, max_row: int = 200) -> int | None:
    """Find the row in a detail sheet where column B matches nome_pf."""
    target = nome_pf.strip().lower()
    for r in range(3, min(ws.max_row + 1, max_row)):
        val = ws.cell(row=r, column=2).value
        if val and str(val).strip().lower() == target:
            return r
    return None


def write_back_to_pf(
    pf_path: Path,
    mapped: dict[str, list[dict]],
    fornitori_map_full: dict[int, dict],
    output_path: Path | None = None,
) -> Path:
    """Write cascaded scadenzario amounts into Rosa's PF Excel.

    Opens the PF Excel, finds each supplier's row in the matching
    detail sheet, and writes the monthly amounts. Saves to output_path
    (default: overwrites pf_path).
    """
    wb = openpyxl.load_workbook(str(pf_path))
    out = output_path or pf_path

    for voce_id, suppliers in mapped.items():
        sheet_name = VOCE_TO_SHEET.get(voce_id)
        if not sheet_name or sheet_name not in wb.sheetnames:
            continue

        ws = wb[sheet_name]
        month_col = _build_month_col_map(ws)

        for s in suppliers:
            info = fornitori_map_full.get(s["codice_fornitore"], {})
            nome_pf = info.get("nome_pf", "")
            if not nome_pf:
                continue

            row = _find_supplier_row(ws, nome_pf)
            if row is None:
                continue

            for month, amount in s["buckets"].items():
                col = month_col.get(month)
                if col and amount:
                    ws.cell(row=row, column=col, value=round(amount, 2))

    wb.save(out)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scadenzario.py::test_write_back_to_pf_places_amounts_correctly tests/test_scadenzario.py::test_write_back_preserves_non_scadenzario_data -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add condges/scadenzario_excel.py tests/test_scadenzario.py
git commit -m "feat: add write_back_to_pf to update Rosa PF Excel from sintetica"
```

---

## Task 3: Wire CLI --write-back flag

**Files:**
- Modify: `cli.py:703-728` (cmd_scadenzario function)
- Modify: `cli.py:873-876` (argparse for scadenzario)

- [ ] **Step 1: Update argparse to add --write-back flag**

In `cli.py` around line 873, after the existing `--output` argument:

```python
p_scad.add_argument("--write-back", action="store_true",
                     help="Write cascaded amounts back into --pf Excel (requires --pf)")
```

- [ ] **Step 2: Update cmd_scadenzario to handle write-back**

Replace the `cmd_scadenzario` function:

```python
def cmd_scadenzario(args):
    """Genera Excel ponte: scadenzario fornitori → voci PF."""
    from condges.scadenzario_excel import (
        cascade_scaduto,
        load_fornitori_map,
        load_fornitori_map_full,
        map_to_voci,
        parse_sintetica_scadenze,
        run,
        write_back_to_pf,
    )

    print(f"\n{'═'*60}")
    print(f"  SCADENZARIO → PIANO FINANZIARIO ({args.societa})")
    print(f"{'═'*60}\n")

    if args.write_back:
        if not args.pf:
            print("  ❌ --write-back requires --pf <PF Excel path>")
            return
        if not args.file:
            print("  ❌ --write-back requires --file <sintetica Excel path>")
            return

        print(f"  Sintetica: {args.file}")
        print(f"  PF Excel:  {args.pf}")

        partite, bucket_months = parse_sintetica_scadenze(args.file)
        print(f"  Fornitori trovati: {len(partite)}")

        cascade_scaduto(partite)
        print("  ✓ Scaduto cascaded into current month")

        fornitori_map = load_fornitori_map()
        mapped, unmapped = map_to_voci(partite, fornitori_map)
        print(f"  Mappati: {sum(len(v) for v in mapped.values())} | Non mappati: {len(unmapped)}")

        fornitori_full = load_fornitori_map_full()
        out = write_back_to_pf(args.pf, mapped, fornitori_full)

        print(f"\n  ✅ PF aggiornato: {out}")
        if unmapped:
            print(f"  ⚠️  {len(unmapped)} fornitori non mappati (non scritti)")
            for u in unmapped[:5]:
                print(f"     - {u['codice_fornitore']} {u['nome']}: €{u['totale']:,.0f}")
            if len(unmapped) > 5:
                print(f"     ... e altri {len(unmapped) - 5}")
    else:
        if args.file:
            print(f"  Input: {args.file}")
        else:
            print("  Input: BigQuery (ultimo snapshot)")
        if args.pf:
            print(f"  PF Rosa: {args.pf}")

        out = run(
            file=args.file,
            pf=args.pf,
            societa=args.societa,
            output=args.output,
        )
        print(f"\n  ✅ Excel generato: {out}")

    print(f"{'═'*60}\n")
```

- [ ] **Step 3: Run existing tests to make sure nothing broke**

Run: `pytest tests/test_scadenzario.py -v`
Expected: All existing + new tests PASS

- [ ] **Step 4: Manual test**

Run:
```bash
hotelops scadenzario --file ~/Desktop/WORK/artifacts/fornitori/situazionesinteticascadenze.xlsx --pf ~/Downloads/"ORTI Piano Finanziario 2026.xlsx" --write-back
```

Expected: PF Excel updated with cascaded sintetica amounts in the supplier rows.

- [ ] **Step 5: Commit**

```bash
git add cli.py
git commit -m "feat: add --write-back flag to scadenzario CLI command"
```

---

## Task 4: Handle _build_month_col_map for duplicate months (Sep-Dec appear twice)

**Files:**
- Test: `tests/test_scadenzario.py`
- Modify: `condges/scadenzario_excel.py`

The PF detail sheets have SETTEMBRE-DICEMBRE twice (2025 and 2026). The sintetica only has forward-looking months (May 2026+), so we need the 2026 columns. The current `_build_month_col_map` takes the rightmost (highest column) occurrence, which is the 2026 one. This task adds a test to confirm this behavior.

- [ ] **Step 1: Write test confirming correct month resolution for duplicate months**

```python
def test_build_month_col_map_takes_2026_columns(tmp_path):
    """For months that appear twice (Sep-Dec), use the 2026 column."""
    from condges.scadenzario_excel import _build_month_col_map

    wb = openpyxl.Workbook()
    ws = wb.active
    # 2025 months: C4=SETTEMBRE, C5=OTTOBRE, C6=NOVEMBRE, C7=DICEMBRE
    ws.cell(row=2, column=4, value="SETTEMBRE")
    ws.cell(row=2, column=5, value="OTTOBRE")
    ws.cell(row=2, column=6, value="NOVEMBRE")
    ws.cell(row=2, column=7, value="DICEMBRE")
    # 2026 months: C8=GENNAIO ... C16=SETTEMBRE, C17=OTTOBRE, C18=NOVEMBRE, C19=DICEMBRE
    months_2026 = ["GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO",
                   "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE",
                   "NOVEMBRE", "DICEMBRE"]
    for i, m in enumerate(months_2026):
        ws.cell(row=2, column=8 + i, value=m)

    col_map = _build_month_col_map(ws)

    # September should be col 16 (2026), not col 4 (2025)
    assert col_map[9] == 16
    assert col_map[10] == 17
    assert col_map[11] == 18
    assert col_map[12] == 19
    # Forward months should work
    assert col_map[4] == 11  # APRILE
    assert col_map[5] == 12  # MAGGIO
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_scadenzario.py::test_build_month_col_map_takes_2026_columns -v`
Expected: PASS (already implemented correctly)

- [ ] **Step 3: Commit**

```bash
git add tests/test_scadenzario.py
git commit -m "test: verify month column resolution for duplicate months in PF"
```

---

## Task 5: Run full test suite and manual verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Run ruff**

Run: `ruff check condges/scadenzario_excel.py cli.py && ruff format condges/scadenzario_excel.py cli.py`

- [ ] **Step 3: Manual end-to-end test**

```bash
# Make a copy of Rosa's PF first
cp ~/Downloads/"ORTI Piano Finanziario 2026.xlsx" /tmp/PF_backup.xlsx

# Run write-back
hotelops scadenzario \
  --file ~/Desktop/WORK/artifacts/fornitori/situazionesinteticascadenze.xlsx \
  --pf ~/Downloads/"ORTI Piano Finanziario 2026.xlsx" \
  --write-back
```

Open the updated PF Excel and verify:
1. "Materie Prime-Consumo " sheet: Le Croissant (row 51) has 14277 in April column
2. "Utenze" sheet: Acqua - Ausino has 12556 in May column
3. "Canoni e servizi" sheet: Proxima Service has amounts filled
4. Other sheets/rows untouched
5. PREVISIONALE rows untouched

- [ ] **Step 4: Final commit if any fixes needed**
