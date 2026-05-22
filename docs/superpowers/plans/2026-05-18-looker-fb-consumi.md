# Looker F&B — Consumi/Pasti/Ricavi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the BigQuery backend for an F&B Looker — a new table `f_ricavi_fb` with its ingest pipeline, plus 4 filterable views (`v_fb_consumi`, `v_fb_pasti`, `v_fb_ricavi`, `v_fb_kpi`).

**Architecture:** New SNAPSHOT fact table `f_ricavi_fb` fed by `ingest_ricavi_fb.py` parsing the 24 "Produzione Netta Dashboard" xlsx files (period metadata extracted from the file's "Applied filters" cell). 4 views read the three F&B fact tables and expose every dimension as a filterable column — Looker Studio connects to the views and auto-refreshes on each ingest.

**Tech Stack:** Python 3.11, openpyxl, Pydantic, `bq_write_validated` gate, BigQuery SQL views.

**Spec:** `docs/superpowers/specs/2026-05-18-looker-fb-consumi-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `core/schemas.py` | + `RicaviFbRow` Pydantic model |
| `core/config.py` | + `F_RICAVI_FB` table id constant |
| `core/registry.yaml` | + `ricavi_fb` detector signature entry |
| `core/source_registry.yaml` | + `POWERBI_RICAVIFB_ORTI_SNAPSHOT` lineage source |
| `ingest/flussi/ingest_ricavi_fb.py` | Parse Produzione Netta xlsx → `f_ricavi_fb` (SNAPSHOT) |
| `ingest/classify.py` | + `detect_ricavi_fb` detector |
| `core/bq/views/v_fb_consumi.sql` | Cost by category + price/volume variance |
| `core/bq/views/v_fb_pasti.sql` | Meal counts per BU, monthly, YoY |
| `core/bq/views/v_fb_ricavi.sql` | F&B revenue per BU + scontrino medio |
| `core/bq/views/v_fb_kpi.sql` | Monthly global €/pasto + incidenza % |
| `tests/test_ingest_ricavi_fb.py` | Unit tests for the pipeline pure functions |
| `CLAUDE.md` | Documentation of the new table + views |

**Refinements over the spec (decided at plan time):**
- `f_ricavi_fb.netto`/`lordo` are `FLOAT64` (not `NUMERIC`) and the Pydantic fields are `float` — matching the sibling table `f_vendite_fb` (`importo_netto: float`). Consistency with the existing F&B revenue table wins over the spec's `NUMERIC`.
- `v_fb_pasti` is **monthly grain**, not daily. No requirement needs day-level pasti; monthly keeps the view single-grain with a clean baked YoY. All filter dimensions (struttura, tipo_pasto, tipo_ospite, is_staff) are preserved.
- The price/volume decomposition uses the **exact** convention (`effetto_prezzo = ΔP·Q₁`, `effetto_volume = ΔQ·P₀`) whose sum equals `Δcosto` identically — so there is **no residuo column** (the spec's "residuo" line is moot).
- `societa_id` is derived in the pipeline via `OPERATIONS_CUTOVER_DATE` (defined locally in the pipeline module); the Pydantic model does not re-validate the cutover (YAGNI — all 24 files are post-cutover ORTI).
- SNAPSHOT idempotency is verified by a real double-load + row-count check in Task 9, not a mock-BQ unit test.
- **Lineage/GCS integration (added 2026-05-18 per user directive "parti sempre dall'ingestione in GCS"):** ingestion goes through the existing lineage layer. Files are staged to `gs://hotelops-raw` via `hotelops intake --source-name POWERBI_RICAVIFB_ORTI_SNAPSHOT` (registered in `f_raw_objects` with the source label), then `hotelops promote` invokes the parser. `f_ricavi_fb` carries a nullable `raw_object_id` FK like every other fact table. The pipeline `ingest_ricavi_fb.py` is the source's `parser_module` — `promote` invokes it as `python -m ingest.flussi.ingest_ricavi_fb --file <tmp> --raw-object-id <id>`. There is no standalone `--dir` bulk loader (it would bypass GCS).

---

## Task 1: `RicaviFbRow` Pydantic model

**Files:**
- Modify: `core/schemas.py` (add after `VenditaFbRow`, around line 312)
- Test: `tests/test_ingest_ricavi_fb.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_ricavi_fb.py`:

```python
"""Tests for ingest_ricavi_fb — Produzione Netta Dashboard → f_ricavi_fb."""
from datetime import datetime, timezone

import pytest

from core.schemas import RicaviFbRow


def _valid_row() -> dict:
    return {
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "anno": 2025,
        "mese": 8,
        "codice": "RISLFOOD",
        "descrizione": "Risto Lunch Food",
        "netto": 4842.73,
        "lordo": 5327.0,
        "file_sorgente": "HP_2025-08.xlsx",
        "hash_riga": "abc123",
        "data_caricamento": datetime.now(timezone.utc),
    }


def test_ricavi_fb_row_valid():
    row = RicaviFbRow(**_valid_row())
    assert row.business_unit_id == "HOTEL"
    assert row.netto == 4842.73


def test_ricavi_fb_row_mese_out_of_range():
    bad = _valid_row() | {"mese": 13}
    with pytest.raises(ValueError, match="mese fuori range"):
        RicaviFbRow(**bad)


def test_ricavi_fb_row_codice_empty():
    bad = _valid_row() | {"codice": "   "}
    with pytest.raises(ValueError, match="codice vuoto"):
        RicaviFbRow(**bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_ricavi_fb.py -v`
Expected: FAIL with `ImportError: cannot import name 'RicaviFbRow'`

- [ ] **Step 3: Add the model to `core/schemas.py`**

Insert after `VenditaFbRow` (after line 311, before the `# ── f_ricavi_storici ──` comment):

```python
# ── f_ricavi_fb ──────────────────────────────────────────────────────────────


class RicaviFbRow(BaseModel):
    """Schema for f_ricavi_fb — F&B revenue by structure × month × charge code.

    Source: HotelCube Power BI "Produzione Netta Dashboard" XLSX, one file per
    struttura × mese. Drill-down of classe 02FB into ~20 charge codes
    (SCBKFBB, RISLFOOD, DINFOOD, ...).

    Pattern: SNAPSHOT, natural_key (business_unit_id, anno, mese). Re-loading a
    month replaces that structure-month's rows.

    Lato ricavo del food cost. Si incrocia con f_consumi_economato (costo,
    globale) tramite mese, e con f_coperti_giornalieri (pasti) tramite mese × BU.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    anno: int
    mese: int
    codice: str
    descrizione: Optional[str] = None
    netto: float
    lordo: float
    file_sorgente: str
    hash_riga: str
    raw_object_id: Optional[str] = None
    data_caricamento: datetime

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v

    @field_validator("codice")
    @classmethod
    def codice_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("codice vuoto")
        return v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_ricavi_fb.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/schemas.py tests/test_ingest_ricavi_fb.py
git commit -m "feat(schemas): add RicaviFbRow for f_ricavi_fb"
```

---

## Task 2: Config + registry entries

**Files:**
- Modify: `core/config.py` (near line 16, with the other `F_*` constants)
- Modify: `core/registry.yaml`
- Modify: `core/source_registry.yaml`

- [ ] **Step 1: Add the table id to `core/config.py`**

After the line `F_COPERTI_GIORNALIERI       = _t("f_coperti_giornalieri")` add:

```python
F_RICAVI_FB                 = _t("f_ricavi_fb")
```

- [ ] **Step 2: Add the detector signature entry to `core/registry.yaml`**

Under `file_types:`, add:

```yaml
  ricavi_fb:
    lifecycle: SNAPSHOT
    dest_folder: "ricavi_fb"
    bq_table: f_ricavi_fb
    pipeline: "ingest.flussi.ingest_ricavi_fb"
    split_by_societa: false
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_0_2: ["Classe", "Codice", "Descrizione Addebito"]
```

- [ ] **Step 3: Add the lineage source to `core/source_registry.yaml`**

Under `sources:`, add a new source. The name follows the strict 4-token grammar
`<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`. `loop_targets` is non-empty so
`promotion_policy: AUTO` is consistent with the policy-gate invariant
(`loop_targets == [] ⇔ RAW_ONLY`):

```yaml
  # ── Ricavi F&B Produzione Netta — SNAPSHOT ────────────────────────────────
  POWERBI_RICAVIFB_ORTI_SNAPSHOT:
    system: POWERBI
    dataset: RICAVIFB
    dataset_label: "Produzione Netta F&B (export Power BI HotelCube)"
    societa: ORTI
    business_unit: null       # HOTEL/RESIDENCE/CVM derivata per-file da CodiceHotel
    lifecycle: SNAPSHOT
    canonical_table: f_ricavi_fb
    parser_module: ingest.flussi.ingest_ricavi_fb
    natural_key: [business_unit_id, anno, mese]
    loop_targets: [food_cost, monthly_close]
    promotion_policy: AUTO
    detector_category: ricavi_fb
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "powerbi/ricavi_fb/ORTI"
```

- [ ] **Step 4: Verify config imports cleanly**

Run: `python -c "from core.config import F_RICAVI_FB; print(F_RICAVI_FB)"`
Expected: `hotelops-suite.hotelops.f_ricavi_fb`

- [ ] **Step 5: Verify both YAMLs are valid and the source resolves**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('core/registry.yaml')); print('registry.yaml ok')"
python -c "from core.lineage.source_resolver import load_registry; d=load_registry().get('POWERBI_RICAVIFB_ORTI_SNAPSHOT'); print('source ok:', d.canonical_table, d.parser_module)"
```
Expected: `registry.yaml ok` then `source ok: f_ricavi_fb ingest.flussi.ingest_ricavi_fb`. If `load_registry()` raises, the policy-gate invariant or the naming grammar rejected the new source — fix the entry.

- [ ] **Step 6: Commit**

```bash
git add core/config.py core/registry.yaml core/source_registry.yaml
git commit -m "feat(config): register f_ricavi_fb + POWERBI_RICAVIFB_ORTI_SNAPSHOT source"
```

---

## Task 3: Create the `f_ricavi_fb` BigQuery table

**Files:** none (BQ DDL run directly)

The `bq_write_validated` snapshot path issues `DELETE` then `INSERT` — the table must pre-exist.

- [ ] **Step 1: Create the table**

Run:

```bash
bq query --use_legacy_sql=false '
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_ricavi_fb` (
  societa_id STRING NOT NULL,
  business_unit_id STRING NOT NULL,
  anno INT64 NOT NULL,
  mese INT64 NOT NULL,
  codice STRING NOT NULL,
  descrizione STRING,
  netto FLOAT64 NOT NULL,
  lordo FLOAT64 NOT NULL,
  file_sorgente STRING NOT NULL,
  hash_riga STRING NOT NULL,
  raw_object_id STRING,
  data_caricamento TIMESTAMP NOT NULL
)
CLUSTER BY business_unit_id, anno, mese'
```

Expected: `Created hotelops-suite.hotelops.f_ricavi_fb` (or no error).

- [ ] **Step 2: Verify the schema**

Run: `bq show --schema --format=prettyjson hotelops-suite:hotelops.f_ricavi_fb`
Expected: 12 fields, `netto`/`lordo` as `FLOAT64`, `raw_object_id` as a NULLABLE `STRING`, `data_caricamento` as `TIMESTAMP`.

No commit (no repo files changed).

---

## Task 4: Pipeline — `parse_applied_filters`

**Files:**
- Create: `ingest/flussi/ingest_ricavi_fb.py`
- Test: `tests/test_ingest_ricavi_fb.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_ricavi_fb.py`:

```python
from ingest.flussi.ingest_ricavi_fb import parse_applied_filters

_FILTER_TEXT = (
    "Applied filters:\nMis_PB_ShowRow is greater than 0\n"
    "ClasseAddebito is 02FB or 80AFFITT\nCodiceHotel is PANORAMAHT\n"
    "Anno is 2025\nMese is agosto\nGiorno is 1, 2, 3\n"
    "ClasseAddebito is 02FB or "
)


def test_parse_applied_filters_hotel():
    assert parse_applied_filters(_FILTER_TEXT) == ("HOTEL", 2025, 8)


def test_parse_applied_filters_residence_and_cvm():
    ang = _FILTER_TEXT.replace("PANORAMAHT", "ANGELINARES").replace("agosto", "aprile")
    assert parse_applied_filters(ang) == ("RESIDENCE", 2025, 4)
    cvm = _FILTER_TEXT.replace("PANORAMAHT", "HOMEHOLIDAY").replace("2025", "2026")
    assert parse_applied_filters(cvm) == ("CVM", 2026, 8)


def test_parse_applied_filters_incomplete():
    with pytest.raises(ValueError, match="incompleti"):
        parse_applied_filters("Applied filters:\nCodiceHotel is PANORAMAHT\n")


def test_parse_applied_filters_unknown_hotel():
    bad = _FILTER_TEXT.replace("PANORAMAHT", "MISTERY")
    with pytest.raises(ValueError, match="CodiceHotel sconosciuto"):
        parse_applied_filters(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_ricavi_fb.py -k parse_applied_filters -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingest.flussi.ingest_ricavi_fb'`

- [ ] **Step 3: Create the pipeline module with `parse_applied_filters`**

Create `ingest/flussi/ingest_ricavi_fb.py`:

```python
#!/usr/bin/env python3
"""Ingest HotelCube Power BI "Produzione Netta Dashboard" → f_ricavi_fb.

One xlsx file = one struttura × one mese. Period metadata (CodiceHotel, Anno,
Mese) lives in the file's last "Applied filters" cell, not in the data rows.

Lifecycle: SNAPSHOT, natural_key (business_unit_id, anno, mese). Re-loading a
month replaces that structure-month's rows.

È il parser_module della source POWERBI_RICAVIFB_ORTI_SNAPSHOT, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_ricavi_fb --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_ricavi_fb --file <xlsx> --raw-object-id <id>
    python -m ingest.flussi.ingest_ricavi_fb --file <xlsx> --dry-run
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from core.config import F_RICAVI_FB
from core.schemas import RicaviFbRow, make_hash, validate_batch

log = logging.getLogger("ingest.ricavi_fb")

# Switch operativo HotelCube INTUR → ORTI (vedi 2026-04-29-produzione-pms spec).
OPERATIONS_CUTOVER_DATE = date(2025, 4, 1)

HOTEL_TO_BU = {
    "PANORAMAHT": "HOTEL",
    "ANGELINARES": "RESIDENCE",
    "HOMEHOLIDAY": "CVM",
}
MESE_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


def parse_applied_filters(text: str) -> tuple[str, int, int]:
    """Extract (business_unit_id, anno, mese) from the 'Applied filters' cell.

    Raises ValueError if any of the three tokens is missing or unrecognized.
    """
    hotel_m = re.search(r"CodiceHotel is (\w+)", text)
    anno_m = re.search(r"Anno is (\d+)", text)
    mese_m = re.search(r"Mese is (\w+)", text)
    if not (hotel_m and anno_m and mese_m):
        raise ValueError(f"Applied filters incompleti: {text[:120]!r}")
    codice_hotel = hotel_m.group(1)
    if codice_hotel not in HOTEL_TO_BU:
        raise ValueError(f"CodiceHotel sconosciuto: {codice_hotel}")
    mese_nome = mese_m.group(1).lower()
    if mese_nome not in MESE_IT:
        raise ValueError(f"Mese sconosciuto: {mese_nome}")
    return HOTEL_TO_BU[codice_hotel], int(anno_m.group(1)), MESE_IT[mese_nome]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_ricavi_fb.py -k parse_applied_filters -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_ricavi_fb.py tests/test_ingest_ricavi_fb.py
git commit -m "feat(ingest): ricavi_fb pipeline — parse_applied_filters"
```

---

## Task 5: Pipeline — `parse_xlsx`

**Files:**
- Modify: `ingest/flussi/ingest_ricavi_fb.py`
- Test: `tests/test_ingest_ricavi_fb.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_ricavi_fb.py`:

```python
from openpyxl import Workbook

from ingest.flussi.ingest_ricavi_fb import parse_xlsx

_HEADER = [
    "Classe", "Codice", "Descrizione Addebito", "Netto", "Netto A.P.",
    "Diff A. - A.P.", "% A. vs A.P.", "Netto A.P.P.", "Diff A. - A.P.P.",
    "% A. vs A.P.P.", "Lordo", "Lordo A.P.", "Lordo A.P.P.",
]


def _write_fixture(path, codice_hotel, anno, mese_nome, data_rows):
    """data_rows: list of (codice, descrizione, netto, lordo)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(_HEADER)
    for codice, desc, netto, lordo in data_rows:
        ws.append(["02FB", codice, desc, netto, 0, 0, 0, 0, 0, 0, lordo, 0, 0])
    ws.append(["Total", None, None, sum(d[2] for d in data_rows),
               0, 0, 0, 0, 0, 0, sum(d[3] for d in data_rows), 0, 0])
    ws.append([
        f"Applied filters:\nMis_PB_ShowRow is greater than 0\n"
        f"CodiceHotel is {codice_hotel}\nAnno is {anno}\nMese is {mese_nome}\n"
        f"ClasseAddebito is 02FB or "
    ])
    wb.save(path)


def test_parse_xlsx_period_and_rows(tmp_path):
    f = tmp_path / "HP_2025-08.xlsx"
    _write_fixture(f, "PANORAMAHT", 2025, "agosto", [
        ("SCBKFBB", "Scorpori Breakfast Bb", 100.0, 110.0),
        ("RISLFOOD", "Risto Lunch Food", 50.0, 55.0),
    ])
    period, rows = parse_xlsx(f)
    assert period == ("HOTEL", 2025, 8)
    assert len(rows) == 2  # Total row excluded
    assert rows[0] == {"codice": "SCBKFBB",
                       "descrizione": "Scorpori Breakfast Bb",
                       "netto": 100.0, "lordo": 110.0}


def test_parse_xlsx_excludes_total_row(tmp_path):
    f = tmp_path / "ANG_2026-04.xlsx"
    _write_fixture(f, "ANGELINARES", 2026, "aprile", [
        ("BAR", "Bar Residence", 21.0, 23.0),
    ])
    _, rows = parse_xlsx(f)
    assert [r["codice"] for r in rows] == ["BAR"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_ricavi_fb.py -k parse_xlsx -v`
Expected: FAIL with `ImportError: cannot import name 'parse_xlsx'`

- [ ] **Step 3: Add `parse_xlsx` to the pipeline module**

Append to `ingest/flussi/ingest_ricavi_fb.py`:

```python
def parse_xlsx(path: Path) -> tuple[tuple[str, int, int], list[dict]]:
    """Read a Produzione Netta xlsx → (period, data_rows).

    period = (business_unit_id, anno, mese) from the last 'Applied filters' cell.
    data_rows = list of {codice, descrizione, netto, lordo}; the 'Total' row and
    blanks are skipped.

    Column layout (0-indexed): 0 Classe | 1 Codice | 2 Descrizione | 3 Netto |
    ... | 10 Lordo.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["Export"] if "Export" in wb.sheetnames else wb.worksheets[0]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    wb.close()
    if len(rows) < 3:
        raise ValueError(f"{path.name}: troppe poche righe ({len(rows)})")

    period = parse_applied_filters(str(rows[-1][0] or ""))

    data_rows: list[dict] = []
    for r in rows[1:-1]:  # skip header (rows[0]) and filter cell (rows[-1])
        codice = r[1] if len(r) > 1 else None
        netto = r[3] if len(r) > 3 else None
        if not codice or not isinstance(netto, (int, float)):
            continue  # 'Total' row (codice None) and blanks
        lordo = r[10] if len(r) > 10 else None
        data_rows.append({
            "codice": str(codice).strip(),
            "descrizione": (str(r[2]).strip() if len(r) > 2 and r[2] else None),
            "netto": float(netto),
            "lordo": float(lordo) if isinstance(lordo, (int, float)) else 0.0,
        })
    return period, data_rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_ricavi_fb.py -k parse_xlsx -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_ricavi_fb.py tests/test_ingest_ricavi_fb.py
git commit -m "feat(ingest): ricavi_fb pipeline — parse_xlsx"
```

---

## Task 6: Pipeline — `build_rows`

**Files:**
- Modify: `ingest/flussi/ingest_ricavi_fb.py`
- Test: `tests/test_ingest_ricavi_fb.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_ricavi_fb.py`:

```python
from ingest.flussi.ingest_ricavi_fb import build_rows


def test_build_rows_societa_and_fields():
    raw = [{"codice": "RISLFOOD", "descrizione": "Risto Lunch Food",
            "netto": 50.0, "lordo": 55.0}]
    rows = build_rows(("HOTEL", 2025, 8), raw, "HP_2025-08.xlsx")
    assert len(rows) == 1
    r = rows[0]
    assert r["societa_id"] == "ORTI"          # 2025-08 is post-cutover
    assert r["business_unit_id"] == "HOTEL"
    assert r["anno"] == 2025 and r["mese"] == 8
    assert r["file_sorgente"] == "HP_2025-08.xlsx"
    assert r["hash_riga"]  # non-empty


def test_build_rows_hash_changes_with_codice():
    raw_a = [{"codice": "RISLFOOD", "descrizione": "x", "netto": 1.0, "lordo": 1.0}]
    raw_b = [{"codice": "DINFOOD", "descrizione": "x", "netto": 1.0, "lordo": 1.0}]
    h_a = build_rows(("HOTEL", 2025, 8), raw_a, "f.xlsx")[0]["hash_riga"]
    h_b = build_rows(("HOTEL", 2025, 8), raw_b, "f.xlsx")[0]["hash_riga"]
    assert h_a != h_b


def test_build_rows_hash_deterministic():
    raw = [{"codice": "BAR", "descrizione": "Bar", "netto": 9.0, "lordo": 9.9}]
    h1 = build_rows(("CVM", 2026, 4), raw, "a.xlsx")[0]["hash_riga"]
    h2 = build_rows(("CVM", 2026, 4), raw, "b.xlsx")[0]["hash_riga"]
    assert h1 == h2  # hash ignores file name, depends on (bu, anno, mese, codice)


def test_build_rows_stamps_raw_object_id():
    raw = [{"codice": "BAR", "descrizione": "Bar", "netto": 9.0, "lordo": 9.9}]
    rows = build_rows(("CVM", 2026, 4), raw, "f.xlsx", raw_object_id="ro-abc")
    assert rows[0]["raw_object_id"] == "ro-abc"


def test_build_rows_raw_object_id_defaults_none():
    raw = [{"codice": "BAR", "descrizione": "Bar", "netto": 9.0, "lordo": 9.9}]
    rows = build_rows(("CVM", 2026, 4), raw, "f.xlsx")
    assert rows[0]["raw_object_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_ricavi_fb.py -k build_rows -v`
Expected: FAIL with `ImportError: cannot import name 'build_rows'`

- [ ] **Step 3: Add `build_rows` to the pipeline module**

Append to `ingest/flussi/ingest_ricavi_fb.py`:

```python
def _societa_for(anno: int, mese: int) -> str:
    """ORTI post-cutover, INTUR before. All 24 current files are ORTI."""
    return "INTUR" if date(anno, mese, 1) < OPERATIONS_CUTOVER_DATE else "ORTI"


def build_rows(
    period: tuple[str, int, int],
    raw_rows: list[dict],
    file_name: str,
    raw_object_id: str | None = None,
) -> list[dict]:
    """Turn parsed raw rows into f_ricavi_fb dict rows.

    Adds societa_id (cutover-derived), hash_riga (md5 of the natural key plus
    codice), raw_object_id (lineage FK — stamped by the `promote` path, None
    when run standalone), and data_caricamento.
    """
    bu, anno, mese = period
    societa = _societa_for(anno, mese)
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for r in raw_rows:
        codice = r["codice"]
        out.append({
            "societa_id": societa,
            "business_unit_id": bu,
            "anno": anno,
            "mese": mese,
            "codice": codice,
            "descrizione": r.get("descrizione"),
            "netto": r["netto"],
            "lordo": r["lordo"],
            "file_sorgente": file_name,
            "hash_riga": make_hash(bu, str(anno), str(mese), codice),
            "raw_object_id": raw_object_id,
            "data_caricamento": now,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_ricavi_fb.py -k build_rows -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_ricavi_fb.py tests/test_ingest_ricavi_fb.py
git commit -m "feat(ingest): ricavi_fb pipeline — build_rows"
```

---

## Task 7: Pipeline — `ingest_file` + CLI `main`

**Files:**
- Modify: `ingest/flussi/ingest_ricavi_fb.py`

This task wires the parsed rows to the `bq_write_validated` gate and adds the CLI.
The CLI is the source's `parser_module` — `hotelops promote` invokes it as
`python -m ingest.flussi.ingest_ricavi_fb --file <tmp> --raw-object-id <id>`.
One file per invocation (promote handles one raw_object at a time). No `--dir`:
bulk loading is the intake→promote flow in Task 9. Verification is a `--dry-run`
smoke (no BQ writes — the BQ write is exercised for real in Task 9).

- [ ] **Step 1: Add `ingest_file` and `main` to the pipeline module**

Append to `ingest/flussi/ingest_ricavi_fb.py`:

```python
def ingest_file(
    path: Path, raw_object_id: str | None = None, dry_run: bool = False
) -> int:
    """Parse one xlsx and SNAPSHOT-write it to f_ricavi_fb. Returns row count.

    raw_object_id is the lineage FK passed by `hotelops promote`; stamped on
    every row. None when run standalone (e.g. --dry-run).
    """
    period, raw = parse_xlsx(path)
    rows = build_rows(period, raw, path.name, raw_object_id)
    validate_batch(rows, RicaviFbRow, context=f"ricavi_fb {path.name}")
    bu, anno, mese = period
    if dry_run:
        log.info("[DRY-RUN] %s → %s %d-%02d : %d righe",
                 path.name, bu, anno, mese, len(rows))
        return len(rows)

    from core.bq.write import bq_write_validated

    pydantic_rows = [RicaviFbRow(**r) for r in rows]
    bq_write_validated(
        F_RICAVI_FB,
        pydantic_rows,
        mode="snapshot",
        natural_key=["business_unit_id", "anno", "mese"],
    )
    log.info("OK %s → %s %d-%02d : %d righe", path.name, bu, anno, mese, len(rows))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Produzione Netta → f_ricavi_fb")
    ap.add_argument("--file", required=True, type=Path, help="xlsx Produzione Netta")
    ap.add_argument(
        "--raw-object-id",
        default=None,
        help="FK a f_raw_objects — passato da `hotelops promote`",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    n = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %d righe", n)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the full test suite for the module still passes**

Run: `pytest tests/test_ingest_ricavi_fb.py -v`
Expected: PASS (all tests so far — 14).

- [ ] **Step 3: Dry-run smoke against a real file**

Run: `python -m ingest.flussi.ingest_ricavi_fb --file ~/Downloads/HP/HP_2025-08.xlsx --dry-run`
Expected: one line `[DRY-RUN] HP_2025-08.xlsx → HOTEL 2025-08 : N righe`, then `Totale: N righe`. No BQ writes.

- [ ] **Step 4: Lint**

Run: `ruff check ingest/flussi/ingest_ricavi_fb.py`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_ricavi_fb.py
git commit -m "feat(ingest): ricavi_fb pipeline — ingest_file + CLI (parser_module)"
```

---

## Task 8: Classifier `detect_ricavi_fb`

**Files:**
- Modify: `ingest/classify.py` (add detector before `detect_economato`; add to `DETECTORS`)
- Test: `tests/test_ingest_ricavi_fb.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_ricavi_fb.py`:

```python
from ingest.classify import detect_ricavi_fb


def test_detect_ricavi_fb_matches(tmp_path):
    f = tmp_path / "HP_2025-08.xlsx"
    _write_fixture(f, "PANORAMAHT", 2025, "agosto", [
        ("SCBKFBB", "Scorpori Breakfast Bb", 100.0, 110.0),
    ])
    result = detect_ricavi_fb(f)
    assert result is not None
    assert result.file_type == "ricavi_fb"
    assert result.confidence >= 0.9


def test_detect_ricavi_fb_ignores_generic_xlsx(tmp_path):
    f = tmp_path / "random.xlsx"
    wb = Workbook()
    wb.active.append(["foo", "bar", "baz"])
    wb.save(f)
    assert detect_ricavi_fb(f) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_ricavi_fb.py -k detect_ricavi_fb -v`
Expected: FAIL with `ImportError: cannot import name 'detect_ricavi_fb'`

- [ ] **Step 3: Add the detector to `ingest/classify.py`**

Insert immediately before `def detect_economato` (around line 942):

```python
def detect_ricavi_fb(path: Path) -> Optional[ClassificationResult]:
    """HotelCube Power BI 'Produzione Netta Dashboard' — F&B revenue by code.

    Signature: xlsx, sheet 'Export', header first 3 cols exactly
    ['Classe', 'Codice', 'Descrizione Addebito'].
    """
    if path.suffix.lower() != ".xlsx":
        return None
    rows, sheet = _read_xlsx_sample(path)
    if sheet != "Export" or not rows:
        return None
    row0 = [str(c or "").strip() for c in rows[0]]
    if row0[:3] == ["Classe", "Codice", "Descrizione Addebito"]:
        return ClassificationResult(
            file_path=path,
            file_type="ricavi_fb",
            category="ricavi_fb",
            lifecycle=LIFECYCLE_SNAPSHOT,
            societa=None,  # multi-struttura, BU derivata in pipeline
            canonical_name=path.name,  # già nominato <STRUT>_<YYYY-MM>.xlsx
            dest_folder="ricavi_fb",
            pipeline_cmd="python -m ingest.flussi.ingest_ricavi_fb --file {dest_file}",
            confidence=0.95,
        )
    return None
```

- [ ] **Step 4: Register the detector in `DETECTORS`**

In the `DETECTORS` list (around line 1002), add `detect_ricavi_fb` immediately before `detect_economato`:

```python
DETECTORS = [
    detect_accodamenti,
    detect_movimenti_contabili,
    detect_partite_fornitori,
    detect_scheda_contabile,
    detect_bilancino,
    detect_gasparotto,
    detect_piano_finanziario,
    detect_coperti,
    detect_ricavi_fb,  # XLSX 'Export' sheet, header Classe/Codice/Descrizione
    detect_economato,
    detect_banca,
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ingest_ricavi_fb.py -k detect_ricavi_fb -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full classifier suite to check no regression**

Run: `pytest tests/test_classify.py tests/test_ingest_ricavi_fb.py -v`
Expected: all PASS (the 65 classify tests + 16 ricavi_fb tests).

- [ ] **Step 7: Commit**

```bash
git add ingest/classify.py tests/test_ingest_ricavi_fb.py
git commit -m "feat(classify): add detect_ricavi_fb detector"
```

---

## Task 9: Stage to GCS + promote — load the 24 files into `f_ricavi_fb`

**Files:** none (data load + verification via the lineage layer)

The 24 files are loaded the lineage way: `hotelops intake` stages each to
`gs://hotelops-raw` and registers it in `f_raw_objects` (status advances to
CLASSIFIED because the source is passed explicitly); `hotelops promote` then
invokes the parser → `f_ricavi_fb`, stamping `raw_object_id`. All three layers
are idempotent: re-intake dedups on content_hash, re-promote no-ops on PROMOTED,
the parser SNAPSHOT-replaces by natural key.

If `hotelops` is not on PATH in this worktree, use `python cli.py` instead.

- [ ] **Step 1: Intake all 24 files → GCS + f_raw_objects**

Run:

```bash
for f in ~/Downloads/HP/HP_*.xlsx ~/Downloads/ANG/ANG_*.xlsx ~/Downloads/CVM/CVM_*.xlsx; do
  hotelops intake "$f" --source-name POWERBI_RICAVIFB_ORTI_SNAPSHOT
done
```

Expected: 24 invocations, each printing `raw_object_id: <uuid>` and
`source_name: POWERBI_RICAVIFB_ORTI_SNAPSHOT`.

- [ ] **Step 2: Verify the raw objects are registered in GCS**

Run:

```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) n, COUNT(DISTINCT content_hash) distinti, COUNTIF(STARTS_WITH(raw_uri, "gs://")) su_gcs FROM `hotelops-suite.hotelops.f_raw_objects` WHERE source_name = "POWERBI_RICAVIFB_ORTI_SNAPSHOT"'
```

Expected: `n` = 24, `distinti` = 24 (each file content unique), `su_gcs` = 24.

- [ ] **Step 3: Promote each raw object → parser runs → f_ricavi_fb**

Run:

```bash
bq query --use_legacy_sql=false --format=csv \
  'SELECT raw_object_id FROM `hotelops-suite.hotelops.f_raw_objects` WHERE source_name = "POWERBI_RICAVIFB_ORTI_SNAPSHOT"' \
  | tail -n +2 \
  | while read -r id; do hotelops promote --raw-object-id "$id"; done
```

Expected: 24 `status=PROMOTED rows=N` lines.

- [ ] **Step 4: Verify coverage in f_ricavi_fb**

Run:

```bash
bq query --use_legacy_sql=false 'SELECT business_unit_id, anno, COUNT(DISTINCT mese) mesi, COUNT(*) righe, COUNTIF(raw_object_id IS NULL) raw_id_mancanti FROM `hotelops-suite.hotelops.f_ricavi_fb` GROUP BY 1,2 ORDER BY 1,2'
```

Expected: 3 BU (HOTEL/RESIDENCE/CVM) × {2025: 7 mesi, 2026: 1 mese}; `raw_id_mancanti` = 0 (every row carries its lineage FK).

- [ ] **Step 5: Verify idempotency — re-run intake + promote**

Re-run Step 1 and Step 3. Intake should report dedup hits (`deduped` / no new
`f_raw_objects` rows); promote should report `noop=True` (already PROMOTED).
Re-run the Step 4 query → **identical row counts**.

No commit (no repo files changed).

---

## Task 10: View `v_fb_consumi`

**Files:**
- Create: `core/bq/views/v_fb_consumi.sql`

- [ ] **Step 1: Write the view SQL**

Create `core/bq/views/v_fb_consumi.sql`:

```sql
-- v_fb_consumi
-- Costo merce F&B per categoria + scomposizione driver prezzo/volume + YoY.
-- Grana: anno × mese × reparto × classe × categoria × prodotto.
-- Costo = blocco unico cucina-hotel (nessuna struttura: il magazzino non
-- distingue Residence/CVM).
--
-- Driver decomposition (esatta, residuo = 0 per costruzione):
--   effetto_prezzo = (prezzo - prezzo_ap) * quantita      [ΔP · Q1]
--   effetto_volume = (quantita - quantita_ap) * prezzo_ap [ΔQ · P0]
--   effetto_prezzo + effetto_volume = delta_costo
--
-- Fonte: f_consumi_economato, reparti F&B.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_consumi` AS
WITH base AS (
  SELECT
    anno,
    mese,
    DATE(anno, mese, 1) AS periodo,
    reparto_id,
    classe,
    COALESCE(NULLIF(TRIM(categoria_prodotto), ''), '(non classificato)')
      AS categoria_prodotto,
    codice_prodotto,
    ANY_VALUE(descrizione) AS descrizione,
    SUM(quantita)          AS quantita,
    SUM(importo)           AS costo
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('BRK', 'CUCINA', 'CANTINA', 'BANCHETTI', 'BAR_HOTEL', 'EVENTO')
  GROUP BY 1, 2, 3, 4, 5, 6, 7
),
yoy AS (
  SELECT
    *,
    SAFE_DIVIDE(costo, NULLIF(quantita, 0)) AS prezzo_unitario,
    LAG(costo)    OVER w AS costo_ap,
    LAG(quantita) OVER w AS quantita_ap,
    LAG(SAFE_DIVIDE(costo, NULLIF(quantita, 0))) OVER w AS prezzo_unitario_ap
  FROM base
  WINDOW w AS (
    PARTITION BY mese, reparto_id, classe, categoria_prodotto, codice_prodotto
    ORDER BY anno
  )
)
SELECT
  anno, mese, periodo, reparto_id, classe, categoria_prodotto,
  codice_prodotto, descrizione,
  quantita, costo, prezzo_unitario,
  costo_ap, quantita_ap, prezzo_unitario_ap,
  costo - costo_ap                                       AS delta_costo,
  (prezzo_unitario - prezzo_unitario_ap) * quantita      AS effetto_prezzo,
  (quantita - quantita_ap) * prezzo_unitario_ap          AS effetto_volume,
  SAFE_DIVIDE(costo - costo_ap, NULLIF(costo_ap, 0))     AS costo_yoy_pct
FROM yoy
ORDER BY anno, mese, reparto_id, costo DESC;
```

- [ ] **Step 2: Deploy the view**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_fb_consumi.sql`
Expected: no error (view created).

- [ ] **Step 3: Smoke test — rows exist and the driver identity holds**

Run:

```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) righe, ROUND(SUM(ABS(effetto_prezzo + effetto_volume - delta_costo)), 2) AS errore_decomposizione FROM `hotelops-suite.hotelops.v_fb_consumi` WHERE costo_ap IS NOT NULL AND quantita > 0 AND quantita_ap > 0'
```

Expected: `righe` > 0, `errore_decomposizione` = `0.0` — the decomposition is exact when both quantities are non-zero (the filter excludes zero-quantity edge rows where unit price is undefined).

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_fb_consumi.sql
git commit -m "feat(views): v_fb_consumi — cost by category + price/volume variance"
```

---

## Task 11: View `v_fb_pasti`

**Files:**
- Create: `core/bq/views/v_fb_pasti.sql`

- [ ] **Step 1: Write the view SQL**

Create `core/bq/views/v_fb_pasti.sql`:

```sql
-- v_fb_pasti
-- Conteggio pasti per struttura, grana mensile, YoY.
-- Grana: anno × mese × societa × business_unit_id × tipo_pasto × tipo_ospite.
-- is_staff = BU 'HQ' (mensa dipendenti) — esposto, mai sommato alla cieca.
-- BU NULL → '(non assegnato)'.
--
-- Fonte: f_coperti_giornalieri.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_pasti` AS
WITH mensile AS (
  SELECT
    anno,
    mese,
    DATE(anno, mese, 1) AS periodo,
    societa_id,
    COALESCE(business_unit_id, '(non assegnato)') AS business_unit_id,
    tipo_pasto,
    tipo_ospite,
    COALESCE(business_unit_id, '') = 'HQ' AS is_staff,
    SUM(n_coperti) AS n_coperti
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
)
SELECT
  *,
  LAG(n_coperti) OVER w AS n_coperti_ap,
  SAFE_DIVIDE(
    n_coperti - LAG(n_coperti) OVER w,
    NULLIF(LAG(n_coperti) OVER w, 0)
  ) AS coperti_yoy_pct
FROM mensile
WINDOW w AS (
  PARTITION BY mese, business_unit_id, tipo_pasto, tipo_ospite
  ORDER BY anno
)
ORDER BY anno, mese, business_unit_id, tipo_pasto;
```

- [ ] **Step 2: Deploy the view**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_fb_pasti.sql`
Expected: no error.

- [ ] **Step 3: Smoke test**

Run:

```bash
bq query --use_legacy_sql=false 'SELECT business_unit_id, tipo_pasto, SUM(n_coperti) tot FROM `hotelops-suite.hotelops.v_fb_pasti` GROUP BY 1,2 ORDER BY 1,2'
```

Expected: rows for HOTEL/RESIDENCE/CVM/HQ × BRK/LUNCH/DINNER, totals > 0.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_fb_pasti.sql
git commit -m "feat(views): v_fb_pasti — monthly meal counts per BU + YoY"
```

---

## Task 12: View `v_fb_ricavi`

**Files:**
- Create: `core/bq/views/v_fb_ricavi.sql`

- [ ] **Step 1: Write the view SQL**

Create `core/bq/views/v_fb_ricavi.sql`:

```sql
-- v_fb_ricavi
-- Ricavi F&B per business unit + scontrino medio (ricavo netto / coperti BU).
-- Grana: anno × mese × business_unit_id × codice.
-- tipo_pasto / categoria_fb classificati qui dal codice (store-first in tabella).
--
-- Fonti: f_ricavi_fb + f_coperti_giornalieri (denominatore scontrino).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_ricavi` AS
WITH ricavi AS (
  SELECT
    anno,
    mese,
    business_unit_id,
    codice,
    ANY_VALUE(descrizione) AS descrizione,
    SUM(netto) AS netto,
    SUM(lordo) AS lordo
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  GROUP BY 1, 2, 3, 4
),
coperti_bu AS (
  SELECT anno, mese, business_unit_id, SUM(n_coperti) AS coperti_bu
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE business_unit_id IS NOT NULL
  GROUP BY 1, 2, 3
),
classificato AS (
  SELECT
    r.anno,
    r.mese,
    DATE(r.anno, r.mese, 1) AS periodo,
    r.business_unit_id,
    r.codice,
    r.descrizione,
    CASE
      WHEN STARTS_WITH(r.codice, 'SCBKF') OR STARTS_WITH(r.codice, 'BRK')
        THEN 'COLAZIONE'
      WHEN r.codice IN ('RISLFOOD', 'RISLBEV', 'RISLBEVE', 'RISTLUNC')
        THEN 'PRANZO'
      WHEN r.codice IN ('RISDFOOD', 'RISDBEV', 'RISTDINN', 'DINFOOD', 'DINBEV')
        THEN 'CENA'
      WHEN r.codice IN ('BAR', 'RISBFOOD') THEN 'BAR'
      WHEN r.codice = 'BAN' OR STARTS_WITH(r.codice, 'PASQ')
        OR STARTS_WITH(r.codice, 'FERR') THEN 'EVENTI'
      WHEN r.codice = 'ROOMSERV' THEN 'ALTRO'
      ELSE '(da mappare)'
    END AS tipo_pasto,
    CASE
      WHEN r.codice IN ('RISLFOOD', 'RISDFOOD', 'DINFOOD', 'RISBFOOD') THEN 'FOOD'
      WHEN r.codice IN ('RISLBEV', 'RISLBEVE', 'RISDBEV', 'DINBEV') THEN 'BEVERAGE'
      ELSE NULL
    END AS categoria_fb,
    r.netto,
    r.lordo,
    c.coperti_bu
  FROM ricavi r
  LEFT JOIN coperti_bu c USING (anno, mese, business_unit_id)
)
SELECT
  *,
  SAFE_DIVIDE(netto, NULLIF(coperti_bu, 0)) AS ricavo_netto_per_coperto,
  LAG(netto) OVER w AS netto_ap,
  SAFE_DIVIDE(netto - LAG(netto) OVER w, NULLIF(LAG(netto) OVER w, 0))
    AS netto_yoy_pct
FROM classificato
WINDOW w AS (PARTITION BY mese, business_unit_id, codice ORDER BY anno)
ORDER BY anno, mese, business_unit_id, netto DESC;
```

- [ ] **Step 2: Deploy the view**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_fb_ricavi.sql`
Expected: no error.

- [ ] **Step 3: Smoke test — every codice classified, no '(da mappare)'**

Run:

```bash
bq query --use_legacy_sql=false 'SELECT tipo_pasto, COUNT(*) righe, ROUND(SUM(netto)) netto FROM `hotelops-suite.hotelops.v_fb_ricavi` GROUP BY 1 ORDER BY 1'
```

Expected: rows for COLAZIONE/PRANZO/CENA/BAR/EVENTI/ALTRO. If `(da mappare)` appears, a new codice surfaced — add it to the `CASE` in this view and redeploy.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_fb_ricavi.sql
git commit -m "feat(views): v_fb_ricavi — F&B revenue per BU + scontrino medio"
```

---

## Task 13: View `v_fb_kpi`

**Files:**
- Create: `core/bq/views/v_fb_kpi.sql`

- [ ] **Step 1: Write the view SQL**

Create `core/bq/views/v_fb_kpi.sql`:

```sql
-- v_fb_kpi
-- Bridge mensile globale: €/pasto + incidenza % (food cost) + margine.
-- Grana: anno × mese (un valore di gruppo per mese).
-- Costo = reparti cucina-hotel pieni (BRK + CUCINA + CANTINA).
-- Coperti = HOTEL. Ricavi = somma F&B di tutte le BU.
-- KPI globali: il costo è globale, non attribuibile per BU.
--
-- Fonti: f_consumi_economato + f_coperti_giornalieri + f_ricavi_fb.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_kpi` AS
WITH costo AS (
  SELECT anno, mese, SUM(importo) AS costo_cucina
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('BRK', 'CUCINA', 'CANTINA')
  GROUP BY 1, 2
),
coperti AS (
  SELECT anno, mese, SUM(n_coperti) AS coperti_hotel
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE business_unit_id = 'HOTEL'
  GROUP BY 1, 2
),
ricavi AS (
  SELECT anno, mese, SUM(netto) AS ricavi_fb_totali
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  GROUP BY 1, 2
),
keys AS (
  SELECT anno, mese FROM costo
  UNION DISTINCT SELECT anno, mese FROM coperti
  UNION DISTINCT SELECT anno, mese FROM ricavi
),
joined AS (
  SELECT
    k.anno,
    k.mese,
    DATE(k.anno, k.mese, 1)         AS periodo,
    COALESCE(c.costo_cucina, 0)     AS costo_cucina,
    COALESCE(p.coperti_hotel, 0)    AS coperti_hotel,
    COALESCE(r.ricavi_fb_totali, 0) AS ricavi_fb_totali
  FROM keys k
  LEFT JOIN costo   c USING (anno, mese)
  LEFT JOIN coperti p USING (anno, mese)
  LEFT JOIN ricavi  r USING (anno, mese)
)
SELECT
  anno, mese, periodo,
  costo_cucina, coperti_hotel, ricavi_fb_totali,
  SAFE_DIVIDE(costo_cucina, NULLIF(coperti_hotel, 0))    AS euro_per_pasto,
  SAFE_DIVIDE(costo_cucina, NULLIF(ricavi_fb_totali, 0)) AS incidenza_pct,
  ricavi_fb_totali - costo_cucina                        AS margine_fb,
  LAG(costo_cucina)     OVER w AS costo_cucina_ap,
  LAG(coperti_hotel)    OVER w AS coperti_hotel_ap,
  LAG(ricavi_fb_totali) OVER w AS ricavi_fb_totali_ap,
  SAFE_DIVIDE(costo_cucina - LAG(costo_cucina) OVER w,
              NULLIF(LAG(costo_cucina) OVER w, 0))        AS costo_yoy_pct,
  SAFE_DIVIDE(ricavi_fb_totali - LAG(ricavi_fb_totali) OVER w,
              NULLIF(LAG(ricavi_fb_totali) OVER w, 0))    AS ricavi_yoy_pct
FROM joined
WINDOW w AS (PARTITION BY mese ORDER BY anno)
ORDER BY anno, mese;
```

- [ ] **Step 2: Deploy the view**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_fb_kpi.sql`
Expected: no error.

- [ ] **Step 3: Smoke test**

Run:

```bash
bq query --use_legacy_sql=false 'SELECT anno, mese, ROUND(costo_cucina) costo, coperti_hotel, ROUND(ricavi_fb_totali) ricavi, ROUND(euro_per_pasto,2) eur_pasto, ROUND(incidenza_pct,3) incidenza FROM `hotelops-suite.hotelops.v_fb_kpi` ORDER BY anno, mese'
```

Expected: one row per (anno, mese); `euro_per_pasto` and `incidenza_pct` populated where costo and the denominator are both > 0.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_fb_kpi.sql
git commit -m "feat(views): v_fb_kpi — monthly global euro/pasto + incidenza %"
```

---

## Task 14: Documentation update

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add `f_ricavi_fb` to the Fact tables table**

In `CLAUDE.md`, in the "### Fact tables" table, add a row after `f_vendite_fb`:

```
| `f_ricavi_fb` | Ricavi F&B per struttura × mese × codice pasto (Produzione Netta PMS). Drill-down di classe 02FB. (SNAPSHOT, natural_key business_unit_id+anno+mese) |
```

- [ ] **Step 2: Add the 4 views to the Views table**

In the "### Views" table, add after `v_food_cost_categoria`:

```
| `v_fb_consumi` | Looker F&B: costo merce per categoria + scomposizione prezzo/volume + YoY. `core/bq/views/` |
| `v_fb_pasti` | Looker F&B: conteggio pasti per BU, mensile, YoY. `core/bq/views/` |
| `v_fb_ricavi` | Looker F&B: ricavi per BU × codice + scontrino medio + YoY. `core/bq/views/` |
| `v_fb_kpi` | Looker F&B: bridge mensile globale — €/pasto + incidenza % (food cost). `core/bq/views/` |
```

- [ ] **Step 3: Add the CLI commands**

In the `## Commands` block, under the lineage section, add:

```
hotelops intake <xlsx> --source-name POWERBI_RICAVIFB_ORTI_SNAPSHOT  # Ricavi F&B → GCS + f_raw_objects
hotelops promote --raw-object-id <id>                                # → parser → f_ricavi_fb
python -m ingest.flussi.ingest_ricavi_fb --file <xlsx> --dry-run     # Parser standalone, preview
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest`
Expected: all PASS (the pre-existing 507 + the new ricavi_fb tests).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: f_ricavi_fb + v_fb_* views in CLAUDE.md"
```

---

## Done criteria

- `f_ricavi_fb` exists in BQ, loaded with 24 files (3 BU × 8 months) **via the lineage layer** — every row carries a `raw_object_id`, every source file is in `gs://hotelops-raw`. Fully idempotent (re-intake + re-promote = no change).
- `v_fb_consumi`, `v_fb_pasti`, `v_fb_ricavi`, `v_fb_kpi` deployed; smoke queries return data; the price/volume decomposition is exact.
- `pytest` green; `ruff check .` clean.
- Looker Studio can connect to the 4 views as data sources (manual, outside this plan).

**Tracked separately (not in this plan):**
- Netto vs lordo verification on `f_consumi_economato.importo` (data-quality prerequisite — see spec §"Prerequisito data-quality").
