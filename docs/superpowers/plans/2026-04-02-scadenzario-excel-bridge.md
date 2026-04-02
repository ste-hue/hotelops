# Scadenzario → PF Excel Bridge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI command `hotelops scadenzario` that reads the Esolver sintetica scadenze file, maps suppliers to PF voci via d_fornitori, and generates an annotated Excel ponte for Rosa.

**Architecture:** Single module `condges/scadenzario_excel.py` with parse → map → generate pipeline. CLI integration in `cli.py`. No BQ writes. Optional PF Excel comparison for gap analysis.

**Tech Stack:** openpyxl (read + write Excel), csv (read d_fornitori), argparse (CLI)

**Spec:** `docs/superpowers/specs/2026-04-02-scadenzario-excel-bridge-design.md`

**Test data:** `/Users/stefanodellapietra/Desktop/WORK/artifacts/fornitori/situazionesinteticascadenze.xlsx`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `condges/scadenzario_excel.py` | Create | Parse sintetica, map to voci, generate Excel |
| `tests/test_scadenzario.py` | Create | Unit tests for parser, mapper, Excel generator |
| `cli.py` | Modify (~850) | Add `scadenzario` subcommand |

---

### Task 1: Parse sintetica scadenze file

**Files:**
- Create: `tests/test_scadenzario.py`
- Create: `condges/scadenzario_excel.py`

- [ ] **Step 1: Write failing test for parser**

```python
# tests/test_scadenzario.py
"""Tests for scadenzario Excel bridge."""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import date


def _make_sintetica_workbook(rows, header_dates=None):
    """Create a minimal sintetica-style workbook in memory.

    Args:
        rows: list of (col_a_text, totale, scaduto, *bucket_amounts)
        header_dates: list of header strings for cols D+ (default: May, Jun, Jul)
    """
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active

    # Header row
    ws.cell(row=1, column=1, value="Fornitore/Tipo pagamento/Conto")
    ws.cell(row=1, column=2, value="Scadenze - Totale")
    ws.cell(row=1, column=3, value="Scadenze - Scaduto fino al 02/04/2026")
    defaults = header_dates or [
        "Scadenze - In scadenza al 02/05/2026",
        "Scadenze - In scadenza al 02/06/2026",
        "Scadenze - In scadenza al 02/07/2026",
    ]
    for i, h in enumerate(defaults):
        ws.cell(row=1, column=4 + i, value=h)

    # Data rows
    for r_idx, row_data in enumerate(rows, start=2):
        ws.cell(row=r_idx, column=1, value=row_data[0])
        if len(row_data) > 1 and row_data[1] is not None:
            ws.cell(row=r_idx, column=2, value=row_data[1])
        if len(row_data) > 2 and row_data[2] is not None:
            ws.cell(row=r_idx, column=3, value=row_data[2])
        for i, val in enumerate(row_data[3:]):
            if val is not None:
                ws.cell(row=r_idx, column=4 + i, value=val)

    return wb


class TestParseSinteticaScadenze:
    def test_parses_codice_and_nome(self, tmp_path):
        from condges.scadenzario_excel import parse_sintetica_scadenze

        wb = _make_sintetica_workbook([
            ("264 PANORAMA COMPANY S.R.L.", -1000, -500, -500),
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)

        result = parse_sintetica_scadenze(f)
        assert len(result) == 1
        assert result[0]["codice_fornitore"] == 264
        assert result[0]["nome"] == "PANORAMA COMPANY S.R.L."

    def test_parses_buckets_from_headers(self, tmp_path):
        from condges.scadenzario_excel import parse_sintetica_scadenze

        wb = _make_sintetica_workbook([
            ("1 FORNITORE TEST", -1500, -500, -600, -400),
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)

        result = parse_sintetica_scadenze(f)
        r = result[0]
        assert r["totale"] == -1500
        assert r["scaduto"] == -500
        assert r["buckets"] == {5: -600, 6: -400}  # May, Jun from header dates

    def test_skips_rows_without_numeric_prefix(self, tmp_path):
        from condges.scadenzario_excel import parse_sintetica_scadenze

        wb = _make_sintetica_workbook([
            ("264 PANORAMA S.R.L.", -1000, -1000),
            ("Totale", -1000, -1000),  # summary row, no code prefix
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)

        result = parse_sintetica_scadenze(f)
        assert len(result) == 1

    def test_handles_positive_amounts(self, tmp_path):
        """Some suppliers have credit notes (positive amounts)."""
        from condges.scadenzario_excel import parse_sintetica_scadenze

        wb = _make_sintetica_workbook([
            ("1008 MIELE SPA", 2294.28, 2294.28),
        ])
        f = tmp_path / "test.xlsx"
        wb.save(f)

        result = parse_sintetica_scadenze(f)
        assert result[0]["totale"] == 2294.28
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scadenzario.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'condges.scadenzario_excel'`

- [ ] **Step 3: Implement parser**

```python
# condges/scadenzario_excel.py
"""Scadenzario → PF Excel Bridge.

Reads the Esolver 'Situazione sintetica scadenze' export, maps suppliers
to Piano Finanziario voci via d_fornitori, and generates an annotated
Excel for Rosa to update her PF.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, numbers


# ── Parser ─────────────────────────────────────────────────────────────────


def parse_sintetica_scadenze(filepath: Path) -> list[dict]:
    """Parse Esolver 'Situazione sintetica scadenze' Excel.

    Returns list of dicts:
        {codice_fornitore, nome, totale, scaduto, buckets: {month_int: amount}}
    """
    wb = openpyxl.load_workbook(str(filepath), data_only=True)
    ws = wb.active

    # Parse bucket months from header row
    bucket_months = {}  # col_index -> month_int
    for col in range(4, ws.max_column + 1):
        header = ws.cell(row=1, column=col).value
        if not header or "scadenza" not in str(header).lower():
            continue
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(header))
        if m:
            bucket_months[col] = int(m.group(2))  # month from DD/MM/YYYY

    results = []
    for row_idx in range(2, ws.max_row + 1):
        cell_a = ws.cell(row=row_idx, column=1).value
        if not cell_a:
            continue

        # Extract codice_fornitore from prefix "264 PANORAMA..."
        cell_str = str(cell_a).strip()
        m = re.match(r"^(\d+)\s+(.+)$", cell_str)
        if not m:
            continue  # skip summary/header rows

        codice = int(m.group(1))
        nome = m.group(2).strip()

        totale = ws.cell(row=row_idx, column=2).value or 0
        scaduto = ws.cell(row=row_idx, column=3).value or 0

        buckets = {}
        for col, month in bucket_months.items():
            val = ws.cell(row=row_idx, column=col).value
            if val:
                buckets[month] = float(val)

        results.append({
            "codice_fornitore": codice,
            "nome": nome,
            "totale": float(totale),
            "scaduto": float(scaduto),
            "buckets": buckets,
        })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scadenzario.py::TestParseSinteticaScadenze -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add condges/scadenzario_excel.py tests/test_scadenzario.py
git commit -m "feat: add sintetica scadenze parser"
```

---

### Task 2: Map suppliers to PF voci

**Files:**
- Modify: `condges/scadenzario_excel.py`
- Modify: `tests/test_scadenzario.py`

- [ ] **Step 1: Write failing tests for mapper**

Add to `tests/test_scadenzario.py`:

```python
class TestMapToVoci:
    def test_maps_supplier_to_voce(self):
        from condges.scadenzario_excel import map_to_voci

        partite = [
            {"codice_fornitore": 1, "nome": "LE CROISSANT", "totale": -1000,
             "scaduto": -500, "buckets": {5: -500}},
        ]
        fornitori_map = {1: "USCITE_MATERIE_PRIME"}

        mapped, unmapped = map_to_voci(partite, fornitori_map)
        assert "USCITE_MATERIE_PRIME" in mapped
        assert len(mapped["USCITE_MATERIE_PRIME"]) == 1
        assert unmapped == []

    def test_unmapped_supplier_goes_to_unmapped_list(self):
        from condges.scadenzario_excel import map_to_voci

        partite = [
            {"codice_fornitore": 9999, "nome": "UNKNOWN", "totale": -100,
             "scaduto": -100, "buckets": {}},
        ]
        fornitori_map = {1: "USCITE_MATERIE_PRIME"}

        mapped, unmapped = map_to_voci(partite, fornitori_map)
        assert len(unmapped) == 1
        assert unmapped[0]["codice_fornitore"] == 9999

    def test_multiple_suppliers_same_voce(self):
        from condges.scadenzario_excel import map_to_voci

        partite = [
            {"codice_fornitore": 1, "nome": "A", "totale": -500,
             "scaduto": -500, "buckets": {}},
            {"codice_fornitore": 4, "nome": "B", "totale": -300,
             "scaduto": -300, "buckets": {}},
        ]
        fornitori_map = {1: "USCITE_MATERIE_PRIME", 4: "USCITE_MATERIE_PRIME"}

        mapped, unmapped = map_to_voci(partite, fornitori_map)
        assert len(mapped["USCITE_MATERIE_PRIME"]) == 2


class TestLoadFornitoriMap:
    def test_loads_csv(self, tmp_path):
        from condges.scadenzario_excel import load_fornitori_map

        csv_path = tmp_path / "d_fornitori.csv"
        csv_path.write_text(
            "codice_fornitore,nome_esolver,nome_pf,voce_id,is_intercompany\n"
            "1,LE CROISSANT SRL,Le Croissant,USCITE_MATERIE_PRIME,False\n"
            "264,PANORAMA COMPANY S.R.L.,Fitto,USCITE_CANONE_PASSIVO,True\n"
        )

        result = load_fornitori_map(csv_path=csv_path)
        assert result[1] == "USCITE_MATERIE_PRIME"
        assert result[264] == "USCITE_CANONE_PASSIVO"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scadenzario.py -k "TestMapToVoci or TestLoadFornitoriMap" -v`
Expected: FAIL — `cannot import name 'map_to_voci'`

- [ ] **Step 3: Implement mapper functions**

Add to `condges/scadenzario_excel.py`:

```python
# ── Mapper ─────────────────────────────────────────────────────────────────

FORNITORI_CSV = Path(__file__).parent.parent / "core" / "bq" / "dimensioni" / "d_fornitori.csv"


def load_fornitori_map(csv_path: Path = FORNITORI_CSV) -> dict[int, str]:
    """Load d_fornitori CSV, return {codice_fornitore: voce_id}."""
    result = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[int(row["codice_fornitore"])] = row["voce_id"]
    return result


def map_to_voci(
    partite: list[dict], fornitori_map: dict[int, str]
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Map suppliers to PF voci.

    Returns:
        (mapped, unmapped) where mapped = {voce_id: [supplier_dicts]},
        unmapped = [supplier_dicts without voce match]
    """
    mapped: dict[str, list[dict]] = {}
    unmapped: list[dict] = []

    for p in partite:
        voce = fornitori_map.get(p["codice_fornitore"])
        if voce:
            mapped.setdefault(voce, []).append(p)
        else:
            unmapped.append(p)

    return mapped, unmapped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scadenzario.py -k "TestMapToVoci or TestLoadFornitoriMap" -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add condges/scadenzario_excel.py tests/test_scadenzario.py
git commit -m "feat: add supplier-to-voce mapper with CSV loader"
```

---

### Task 3: Generate Excel ponte

**Files:**
- Modify: `condges/scadenzario_excel.py`
- Modify: `tests/test_scadenzario.py`

- [ ] **Step 1: Write failing tests for Excel generation**

Add to `tests/test_scadenzario.py`:

```python
class TestGenerateExcel:
    def _sample_data(self):
        mapped = {
            "USCITE_MATERIE_PRIME": [
                {"codice_fornitore": 1, "nome": "LE CROISSANT",
                 "totale": -1500, "scaduto": -1000, "buckets": {5: -500}},
                {"codice_fornitore": 4, "nome": "GIACINTO",
                 "totale": -400, "scaduto": -400, "buckets": {}},
            ],
            "USCITE_UTENZE": [
                {"codice_fornitore": 18, "nome": "AUSINO",
                 "totale": -600, "scaduto": 0, "buckets": {5: -600}},
            ],
        }
        return mapped

    def test_creates_riepilogo_sheet(self, tmp_path):
        from condges.scadenzario_excel import generate_excel

        out = tmp_path / "test.xlsx"
        generate_excel(self._sample_data(), None, [], out, bucket_months=[5, 6, 7])

        wb = openpyxl.load_workbook(out)
        assert "Riepilogo" in wb.sheetnames

    def test_creates_per_voce_sheets(self, tmp_path):
        from condges.scadenzario_excel import generate_excel

        out = tmp_path / "test.xlsx"
        generate_excel(self._sample_data(), None, [], out, bucket_months=[5, 6, 7])

        wb = openpyxl.load_workbook(out)
        assert "Materie Prime" in wb.sheetnames
        assert "Utenze" in wb.sheetnames

    def test_riepilogo_has_totals(self, tmp_path):
        from condges.scadenzario_excel import generate_excel

        out = tmp_path / "test.xlsx"
        generate_excel(self._sample_data(), None, [], out, bucket_months=[5, 6, 7])

        wb = openpyxl.load_workbook(out, data_only=True)
        ws = wb["Riepilogo"]
        # Find the totals — last data row
        values = {}
        for row in ws.iter_rows(min_row=2, values_only=False):
            if row[0].value and "Totale" in str(row[0].value):
                values["totale_col"] = row[1].value  # scaduto column
        assert values.get("totale_col") is not None

    def test_unmapped_sheet_created_when_needed(self, tmp_path):
        from condges.scadenzario_excel import generate_excel

        out = tmp_path / "test.xlsx"
        unmapped = [{"codice_fornitore": 999, "nome": "UNKNOWN",
                     "totale": -100, "scaduto": -100, "buckets": {}}]
        generate_excel({}, None, unmapped, out, bucket_months=[5])

        wb = openpyxl.load_workbook(out)
        assert "DA VERIFICARE" in wb.sheetnames

    def test_no_unmapped_sheet_when_all_mapped(self, tmp_path):
        from condges.scadenzario_excel import generate_excel

        out = tmp_path / "test.xlsx"
        generate_excel(self._sample_data(), None, [], out, bucket_months=[5])

        wb = openpyxl.load_workbook(out)
        assert "DA VERIFICARE" not in wb.sheetnames
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scadenzario.py::TestGenerateExcel -v`
Expected: FAIL — `cannot import name 'generate_excel'`

- [ ] **Step 3: Implement Excel generator**

Add to `condges/scadenzario_excel.py`:

```python
# ── Voce labels ────────────────────────────────────────────────────────────

VOCE_LABELS = {
    "USCITE_MATERIE_PRIME": "Materie Prime",
    "USCITE_UTENZE": "Utenze",
    "USCITE_SALARI": "Salari e Stipendi",
    "USCITE_TASSE": "Tasse e Imposte",
    "USCITE_COMMISSIONI": "Commissioni",
    "USCITE_MUTUI": "Mutui e Finanziamenti",
    "USCITE_CONSULENZE": "Consulenze",
    "USCITE_CANONE_PASSIVO": "Godimento Beni di Terzi",
    "USCITE_VARIE_EXT": "Varie ed Eventuali",
    "USCITE_SERVIZI_PRODUZIONE": "Canoni e servizi",
    "USCITE_MARKETING": "Marketing",
}

MESI_NOMI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
             "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
BOLD = Font(bold=True)
NUM_FMT = '#,##0'


# ── Excel Generator ───────────────────────────────────────────────────────


def generate_excel(
    mapped: dict[str, list[dict]],
    forecasts: dict[str, dict[int, float]] | None,
    unmapped: list[dict],
    output_path: Path,
    bucket_months: list[int] | None = None,
) -> Path:
    """Generate the Excel ponte.

    Args:
        mapped: {voce_id: [supplier_dicts]} from map_to_voci
        forecasts: optional {voce_id: {month: amount}} from Rosa's PF
        unmapped: suppliers without voce match
        output_path: where to save
        bucket_months: ordered list of month ints for bucket columns
    """
    if bucket_months is None:
        # Collect all months from data
        all_months = set()
        for suppliers in mapped.values():
            for s in suppliers:
                all_months.update(s["buckets"].keys())
        bucket_months = sorted(all_months) if all_months else []

    wb = openpyxl.Workbook()

    # ── Riepilogo sheet ──
    ws = wb.active
    ws.title = "Riepilogo"
    headers = ["Voce PF", "Scaduto"] + [MESI_NOMI[m - 1] for m in bucket_months] + ["Totale"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = BOLD

    row_idx = 2
    grand_scaduto = 0
    grand_buckets = {m: 0 for m in bucket_months}
    grand_total = 0

    for voce_id in sorted(mapped.keys()):
        suppliers = mapped[voce_id]
        label = VOCE_LABELS.get(voce_id, voce_id)
        scaduto = sum(s["scaduto"] for s in suppliers)
        totale = sum(s["totale"] for s in suppliers)
        month_sums = {m: sum(s["buckets"].get(m, 0) for s in suppliers) for m in bucket_months}

        ws.cell(row=row_idx, column=1, value=label)
        cell_s = ws.cell(row=row_idx, column=2, value=round(scaduto))
        cell_s.number_format = NUM_FMT
        if scaduto < 0:
            cell_s.fill = RED_FILL
        for i, m in enumerate(bucket_months):
            c = ws.cell(row=row_idx, column=3 + i, value=round(month_sums[m]) if month_sums[m] else None)
            c.number_format = NUM_FMT
        ws.cell(row=row_idx, column=3 + len(bucket_months), value=round(totale)).number_format = NUM_FMT

        grand_scaduto += scaduto
        for m in bucket_months:
            grand_buckets[m] += month_sums[m]
        grand_total += totale
        row_idx += 1

    # Totals row
    ws.cell(row=row_idx, column=1, value="Totale").font = BOLD
    ws.cell(row=row_idx, column=2, value=round(grand_scaduto)).font = BOLD
    ws.cell(row=row_idx, column=2).number_format = NUM_FMT
    for i, m in enumerate(bucket_months):
        c = ws.cell(row=row_idx, column=3 + i, value=round(grand_buckets[m]) if grand_buckets[m] else None)
        c.font = BOLD
        c.number_format = NUM_FMT
    ws.cell(row=row_idx, column=3 + len(bucket_months), value=round(grand_total)).font = BOLD
    ws.cell(row=row_idx, column=3 + len(bucket_months)).number_format = NUM_FMT

    # ── Per-voce sheets ──
    for voce_id in sorted(mapped.keys()):
        suppliers = mapped[voce_id]
        label = VOCE_LABELS.get(voce_id, voce_id)
        ws_v = wb.create_sheet(title=label[:31])  # Excel max 31 chars

        headers_v = ["Fornitore", "Cod.", "Scaduto"] + [MESI_NOMI[m - 1] for m in bucket_months] + ["Totale"]
        for c, h in enumerate(headers_v, 1):
            ws_v.cell(row=1, column=c, value=h).font = BOLD

        r = 2
        for s in sorted(suppliers, key=lambda x: x["totale"]):
            ws_v.cell(row=r, column=1, value=s["nome"])
            ws_v.cell(row=r, column=2, value=s["codice_fornitore"])
            cell_s = ws_v.cell(row=r, column=3, value=round(s["scaduto"]))
            cell_s.number_format = NUM_FMT
            if s["scaduto"] < 0:
                cell_s.fill = RED_FILL
            for i, m in enumerate(bucket_months):
                val = s["buckets"].get(m)
                c = ws_v.cell(row=r, column=4 + i, value=round(val) if val else None)
                c.number_format = NUM_FMT
            ws_v.cell(row=r, column=4 + len(bucket_months), value=round(s["totale"])).number_format = NUM_FMT
            r += 1

        # Totals row
        r += 1
        ws_v.cell(row=r, column=1, value="Totale scadenzario").font = BOLD
        ws_v.cell(row=r, column=3, value=round(sum(s["scaduto"] for s in suppliers))).font = BOLD
        ws_v.cell(row=r, column=3).number_format = NUM_FMT
        for i, m in enumerate(bucket_months):
            val = sum(s["buckets"].get(m, 0) for s in suppliers)
            c = ws_v.cell(row=r, column=4 + i, value=round(val) if val else None)
            c.font = BOLD
            c.number_format = NUM_FMT
        ws_v.cell(row=r, column=4 + len(bucket_months),
                  value=round(sum(s["totale"] for s in suppliers))).font = BOLD

        # Gap analysis rows (if forecasts provided)
        if forecasts and voce_id in forecasts:
            r += 1
            ws_v.cell(row=r, column=1, value="Rosa prevede").font = BOLD
            for i, m in enumerate(bucket_months):
                val = forecasts[voce_id].get(m)
                if val:
                    ws_v.cell(row=r, column=4 + i, value=round(val)).number_format = NUM_FMT

            r += 1
            ws_v.cell(row=r, column=1, value="Gap (non fatturato)").font = BOLD
            for i, m in enumerate(bucket_months):
                forecast_val = forecasts[voce_id].get(m, 0)
                scad_val = sum(s["buckets"].get(m, 0) for s in suppliers)
                if forecast_val:
                    gap = forecast_val - scad_val
                    ws_v.cell(row=r, column=4 + i, value=round(gap)).number_format = NUM_FMT

    # ── DA VERIFICARE sheet ──
    if unmapped:
        ws_u = wb.create_sheet(title="DA VERIFICARE")
        for c, h in enumerate(["Fornitore", "Cod.", "Totale", "Scaduto"], 1):
            ws_u.cell(row=1, column=c, value=h).font = BOLD
        for r, u in enumerate(unmapped, 2):
            ws_u.cell(row=r, column=1, value=u["nome"])
            ws_u.cell(row=r, column=2, value=u["codice_fornitore"])
            ws_u.cell(row=r, column=3, value=round(u["totale"])).number_format = NUM_FMT
            ws_u.cell(row=r, column=4, value=round(u["scaduto"])).number_format = NUM_FMT

    wb.save(output_path)
    return output_path
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_scadenzario.py -v`
Expected: All 12 tests pass

- [ ] **Step 5: Commit**

```bash
git add condges/scadenzario_excel.py tests/test_scadenzario.py
git commit -m "feat: add Excel ponte generator with per-voce sheets and gap analysis"
```

---

### Task 4: PF Excel forecast parser (optional --pf flag)

**Files:**
- Modify: `condges/scadenzario_excel.py`
- Modify: `tests/test_scadenzario.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_scadenzario.py`:

```python
class TestLoadPfForecasts:
    def test_parses_uscite_rows(self, tmp_path):
        """Test parsing Rosa's PF Excel uscite rows."""
        from condges.scadenzario_excel import load_pf_forecasts

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Piano Finanziario"
        # Row 2: societa + month headers (cols 3-18 = Set2025..Apr2026..Dic2026)
        ws.cell(row=2, column=1, value="ORTI")
        # Row 3: month labels for 2026 cols 9-18 = Apr..Dic (matching real file)
        for i, name in enumerate(["APRILE", "MAGGIO", "GIUGNO"], start=10):
            ws.cell(row=3, column=i, value=name)
        # Row 16: Materie Prime (uscite row in real file)
        ws.cell(row=16, column=1, value="Materie Prime/Consumo")
        ws.cell(row=16, column=10, value=117460)  # Apr
        ws.cell(row=16, column=11, value=40075)    # Mag
        ws.cell(row=16, column=12, value=95000)    # Giu

        f = tmp_path / "pf.xlsx"
        wb.save(f)

        result = load_pf_forecasts(f)
        assert "USCITE_MATERIE_PRIME" in result
        assert result["USCITE_MATERIE_PRIME"][4] == 117460  # April
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scadenzario.py::TestLoadPfForecasts -v`
Expected: FAIL — `cannot import name 'load_pf_forecasts'`

- [ ] **Step 3: Implement PF parser**

Add to `condges/scadenzario_excel.py`:

```python
# ── PF Excel Forecast Parser ──────────────────────────────────────────────

# Map PF Excel row labels to voce_ids
PF_LABEL_TO_VOCE = {
    "salari e stipendi": "USCITE_SALARI",
    "utenze": "USCITE_UTENZE",
    "materie prime/consumo": "USCITE_MATERIE_PRIME",
    "materie prime e consumo": "USCITE_MATERIE_PRIME",
    "tasse e imposte": "USCITE_TASSE",
    "commissioni portali": "USCITE_COMMISSIONI",
    "mutui e finaziamenti": "USCITE_MUTUI",
    "mutui e finanziamenti": "USCITE_MUTUI",
    "consulenze": "USCITE_CONSULENZE",
    "godimento beni di terzi": "USCITE_CANONE_PASSIVO",
    "varie ed eventuali": "USCITE_VARIE_EXT",
    "canoni e servizi": "USCITE_SERVIZI_PRODUZIONE",
}

# Month name to int
MONTH_NAMES = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def load_pf_forecasts(filepath: Path) -> dict[str, dict[int, float]]:
    """Parse Rosa's PF Excel, extract uscite forecasts per voce per month.

    Returns: {voce_id: {month_int: amount}}
    """
    wb = openpyxl.load_workbook(str(filepath), data_only=True)
    ws = wb["Piano Finanziario"]

    # Build column → month map from row 3 headers
    col_to_month: dict[int, int] = {}
    for col in range(3, ws.max_column + 1):
        val = ws.cell(row=3, column=col).value
        if val:
            month = MONTH_NAMES.get(str(val).strip().lower())
            if month:
                col_to_month[col] = month

    # Scan rows 14-27 for uscite labels
    result: dict[str, dict[int, float]] = {}
    for row_idx in range(14, 28):
        label_raw = ws.cell(row=row_idx, column=1).value
        if not label_raw:
            continue
        label = str(label_raw).strip().lower()
        voce_id = PF_LABEL_TO_VOCE.get(label)
        if not voce_id:
            continue

        months: dict[int, float] = {}
        for col, month in col_to_month.items():
            val = ws.cell(row=row_idx, column=col).value
            if val and isinstance(val, (int, float)) and val != 0:
                months[month] = float(val)

        if months:
            result[voce_id] = months

    return result
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_scadenzario.py -v`
Expected: All 13 tests pass

- [ ] **Step 5: Commit**

```bash
git add condges/scadenzario_excel.py tests/test_scadenzario.py
git commit -m "feat: add PF Excel forecast parser for gap analysis"
```

---

### Task 5: CLI integration

**Files:**
- Modify: `cli.py:769-862` (add subcommand)
- Modify: `condges/scadenzario_excel.py` (add main runner)

- [ ] **Step 1: Add runner function to scadenzario_excel.py**

Add at the bottom of `condges/scadenzario_excel.py`:

```python
# ── Runner ─────────────────────────────────────────────────────────────────


def run(
    file: Path | None = None,
    pf: Path | None = None,
    societa: str = "ORTI",
    output: Path | None = None,
) -> Path:
    """Run the full pipeline: parse → map → generate.

    Args:
        file: path to sintetica scadenze Excel (if None, use BQ fallback)
        pf: optional path to Rosa's PF Excel for gap analysis
        societa: ORTI or INTUR
        output: output directory (default: current dir)
    """
    if file:
        partite = parse_sintetica_scadenze(file)
        # Extract bucket months from the file for column headers
        wb = openpyxl.load_workbook(str(file), data_only=True)
        ws = wb.active
        bucket_months = []
        for col in range(4, ws.max_column + 1):
            header = ws.cell(row=1, column=col).value
            if not header or "scadenza" not in str(header).lower():
                continue
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(header))
            if m:
                bucket_months.append(int(m.group(2)))
    else:
        from google.cloud import bigquery
        bq = bigquery.Client(project="hotelops-suite")
        partite = load_from_bq(bq, societa)
        bucket_months = None

    fornitori_map = load_fornitori_map()
    mapped, unmapped = map_to_voci(partite, fornitori_map)

    forecasts = load_pf_forecasts(pf) if pf else None

    out_dir = output or Path(".")
    out_path = out_dir / f"Scadenzario_PF_{societa}_{date.today().isoformat()}.xlsx"

    generate_excel(mapped, forecasts, unmapped, out_path, bucket_months)
    return out_path
```

- [ ] **Step 2: Add BQ fallback loader**

Add to `condges/scadenzario_excel.py` after `load_fornitori_map`:

```python
def load_from_bq(bq_client, societa: str) -> list[dict]:
    """Fallback: load from f_partite_aperte_fornitori, aggregate like sintetica."""
    sql = f"""
    SELECT
        codice_fornitore,
        nome_fornitore AS nome,
        ROUND(SUM(importo_residuo), 2) AS totale,
        ROUND(SUM(CASE WHEN data_scadenza < CURRENT_DATE() THEN importo_residuo ELSE 0 END), 2) AS scaduto,
        EXTRACT(MONTH FROM data_scadenza) AS mese,
        ROUND(SUM(CASE WHEN data_scadenza >= CURRENT_DATE() THEN importo_residuo ELSE 0 END), 2) AS futuro
    FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
    WHERE societa_id = '{societa}'
    GROUP BY codice_fornitore, nome_fornitore, mese
    ORDER BY codice_fornitore, mese
    """
    rows_raw = list(bq_client.query(sql))

    # Aggregate into per-supplier dicts
    by_supplier: dict[int, dict] = {}
    for r in rows_raw:
        code = r.codice_fornitore
        if code not in by_supplier:
            by_supplier[code] = {
                "codice_fornitore": code,
                "nome": r.nome,
                "totale": 0,
                "scaduto": 0,
                "buckets": {},
            }
        by_supplier[code]["totale"] += float(r.totale)
        by_supplier[code]["scaduto"] += float(r.scaduto)
        if r.futuro and r.futuro != 0:
            by_supplier[code]["buckets"][r.mese] = float(r.futuro)

    return list(by_supplier.values())
```

- [ ] **Step 3: Add CLI subcommand to cli.py**

Add after the `classifica` parser block (~line 834) in `cli.py`:

```python
    # scadenzario
    p_scad = sub.add_parser("scadenzario", aliases=["scad"],
                            help="Genera Excel ponte fornitori → voci PF")
    p_scad.add_argument("--file", type=Path, help="Sintetica scadenze Excel (default: BQ)")
    p_scad.add_argument("--pf", type=Path, help="PF Excel di Rosa per gap analysis")
    p_scad.add_argument("--societa", choices=["ORTI", "INTUR"], default="ORTI")
    p_scad.add_argument("--output", type=Path, help="Directory output (default: corrente)")
```

Add the handler function before `cmd_help`:

```python
# ── Scadenzario ────────────────────────────────────────────────────────────

def cmd_scadenzario(args):
    """Genera Excel ponte: scadenzario fornitori → voci PF."""
    from condges.scadenzario_excel import run

    print(f"\n{'═'*60}")
    print(f"  SCADENZARIO → PIANO FINANZIARIO ({args.societa})")
    print(f"{'═'*60}\n")

    if args.file:
        print(f"  Input: {args.file}")
    else:
        print(f"  Input: BigQuery (ultimo snapshot)")
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

Add to the `handlers` dict (~line 842):

```python
        "scadenzario": cmd_scadenzario,
        "scad": cmd_scadenzario,
```

- [ ] **Step 4: Test with real data**

Run: `python -m cli scadenzario --file /Users/stefanodellapietra/Desktop/WORK/artifacts/fornitori/situazionesinteticascadenze.xlsx --output /tmp/`
Expected: creates `/tmp/Scadenzario_PF_ORTI_2026-04-02.xlsx`

Then with PF:
Run: `python -m cli scadenzario --file /Users/stefanodellapietra/Desktop/WORK/artifacts/fornitori/situazionesinteticascadenze.xlsx --pf /Users/stefanodellapietra/Downloads/04_APRILE_ORTI_2026.xlsx --output /tmp/`
Expected: same file but with "Rosa prevede" and "Gap" rows in per-voce sheets

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_scadenzario.py -v && ruff check condges/scadenzario_excel.py cli.py`
Expected: All pass, no lint errors

- [ ] **Step 6: Commit**

```bash
git add condges/scadenzario_excel.py cli.py tests/test_scadenzario.py
git commit -m "feat: add hotelops scadenzario CLI command"
```

---

### Task 6: Update help text and push

**Files:**
- Modify: `cli.py` (help text)

- [ ] **Step 1: Add scadenzario to help text**

In `cmd_help`, add after the `classifica` section:

```python
  scadenzario   Excel ponte: scadenzario fornitori → voci PF
    (alias: scad) hotelops scad --file sintetica.xlsx
                  hotelops scad --file sintetica.xlsx --pf PF_aprile.xlsx
                  hotelops scad --output ~/Desktop/
```

- [ ] **Step 2: Run full test suite**

Run: `pytest -v && ruff check .`
Expected: All tests pass, no lint errors

- [ ] **Step 3: Commit and push**

```bash
git add cli.py
git commit -m "docs: add scadenzario to CLI help text"
git push
```
