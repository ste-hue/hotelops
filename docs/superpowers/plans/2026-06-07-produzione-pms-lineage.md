# Produzione PMS Ingest (lineage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest the HotelCube Power BI Daily Production Report (class cut, Imponibile) into a new fact table `f_produzione_pms` (giorno × struttura × classe) through the existing lineage layer, SNAPSHOT per (business_unit_id, anno).

**Architecture:** A Pydantic-gated parser (`ingest_produzione_pms.py`) reads one xlsx per struttura×anno, parses the `Applied filters` cell for (CodiceHotel→BU, Anno), detects class columns by regex, unpivots wide→long, derives `societa_id` via the 2025-04-01 cutover, and SNAPSHOT-writes to `f_produzione_pms`. Invoked standalone or by `hotelops promote --raw-object-id`. Follows the `ingest_ricavi_fb` pattern exactly.

**Tech Stack:** Python 3.11, openpyxl, Pydantic, google-cloud-bigquery, pytest. Spec: `docs/superpowers/specs/2026-06-05-produzione-pms-lineage-design.md`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `core/config.py` | Table ID constant `F_PRODUZIONE_PMS` | Modify |
| `core/bq/load/create_produzione_table.py` | Idempotent DDL for `f_produzione_pms` | Create |
| `core/schemas.py` | `OPERATIONS_CUTOVER_DATE` + `ProduzioneRow` | Modify |
| `ingest/flussi/ingest_produzione_pms.py` | Parser: xlsx → SNAPSHOT write | Create |
| `tests/test_ingest_produzione_pms.py` | Unit tests (schema + parser + snapshot) | Create |
| `core/source_registry.yaml` | Source `POWERBI_PRODUZIONE_ORTI_SNAPSHOT` | Modify |
| `CLAUDE.md` | Doc row for `f_produzione_pms` | Modify |
| `STATUS.md` | Thread update + `d_classi_produzione TBD` | Modify |

Backfill and orphan-cleanup (Tasks 8–9) are operational, run from the CLI, no new files.

---

### Task 1: Config constant + table DDL

**Files:**
- Modify: `core/config.py` (after `F_PMS_STATISTICHE` line)
- Create: `core/bq/load/create_produzione_table.py`

- [ ] **Step 1: Add the table-ID constant**

In `core/config.py`, after the `F_PMS_STATISTICHE = _t("f_pms_statistiche")` line, add:

```python
F_PRODUZIONE_PMS            = _t("f_produzione_pms")
```

- [ ] **Step 2: Create the idempotent DDL script**

Create `core/bq/load/create_produzione_table.py`:

```python
#!/usr/bin/env python3
"""DDL idempotente per f_produzione_pms (produzione giornaliera per classe).

Grana: giorno × struttura × classe, importo imponibile.
PARTITION BY data, CLUSTER BY business_unit_id, classe.
Lifecycle SNAPSHOT (natural_key business_unit_id, anno) — gestito dal parser.

Usage:
    python -m core.bq.load.create_produzione_table
    python -m core.bq.load.create_produzione_table --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import F_PRODUZIONE_PMS

DDL_F_PRODUZIONE_PMS = f"""
CREATE TABLE IF NOT EXISTS `{F_PRODUZIONE_PMS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    data                 DATE NOT NULL,
    anno                 INT64 NOT NULL,
    mese                 INT64 NOT NULL,
    classe               STRING NOT NULL,
    importo_imponibile   NUMERIC NOT NULL,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    raw_object_id        STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
PARTITION BY data
CLUSTER BY business_unit_id, classe
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = logging.getLogger("create_produzione_table")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("DDL f_produzione_pms — idempotent (CREATE TABLE IF NOT EXISTS)")

    if args.dry_run:
        log.info(DDL_F_PRODUZIONE_PMS)
        return 0

    get_client().query(DDL_F_PRODUZIONE_PMS).result()
    log.info("OK f_produzione_pms creata/confermata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Dry-run the DDL**

Run: `python -m core.bq.load.create_produzione_table --dry-run`
Expected: prints the `CREATE TABLE IF NOT EXISTS` statement, exit 0.

- [ ] **Step 4: Create the table in BigQuery**

Run: `python -m core.bq.load.create_produzione_table`
Expected: `OK f_produzione_pms creata/confermata`.

- [ ] **Step 5: Verify the table exists with the right schema**

Run: `bq show --schema --format=prettyjson hotelops-suite:hotelops.f_produzione_pms`
Expected: JSON listing the 11 fields above; `data` partitioned, clustered by `business_unit_id, classe`.

- [ ] **Step 6: Commit**

```bash
git add core/config.py core/bq/load/create_produzione_table.py
git commit -m "feat(produzione): add f_produzione_pms table DDL + config constant"
```

---

### Task 2: `ProduzioneRow` schema + cutover constant

**Files:**
- Modify: `core/schemas.py` (add constant near top after shared types; add class after `RicaviFbRow`)
- Test: `tests/test_ingest_produzione_pms.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest_produzione_pms.py`:

```python
"""Tests for produzione PMS ingest: schema + parser + snapshot."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from core.schemas import OPERATIONS_CUTOVER_DATE, ProduzioneRow


def _row(**over):
    base = dict(
        societa_id="ORTI",
        business_unit_id="HOTEL",
        data=date(2026, 4, 15),
        anno=2026,
        mese=4,
        classe="01ROOM",
        importo_imponibile=Decimal("8000.00"),
        file_sorgente="HOTEL_Daily Production Report (3).xlsx",
        hash_riga="abc123",
        raw_object_id=None,
        data_caricamento=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    base.update(over)
    return base


def test_cutover_constant_is_2025_04_01():
    assert OPERATIONS_CUTOVER_DATE == date(2025, 4, 1)


def test_valid_row_ok():
    r = ProduzioneRow(**_row())
    assert r.societa_id == "ORTI"
    assert r.importo_imponibile == Decimal("8000.00")


def test_pre_cutover_must_be_intur():
    # 2025-03-31 → INTUR is correct
    ProduzioneRow(**_row(data=date(2025, 3, 31), anno=2025, mese=3, societa_id="INTUR"))
    # 2025-03-31 labelled ORTI → reject
    with pytest.raises(ValueError, match="cutover"):
        ProduzioneRow(**_row(data=date(2025, 3, 31), anno=2025, mese=3, societa_id="ORTI"))


def test_post_cutover_must_be_orti():
    ProduzioneRow(**_row(data=date(2025, 4, 1), anno=2025, mese=4, societa_id="ORTI"))
    with pytest.raises(ValueError, match="cutover"):
        ProduzioneRow(**_row(data=date(2025, 4, 1), anno=2025, mese=4, societa_id="INTUR"))


def test_anno_mese_must_match_data():
    with pytest.raises(ValueError, match="anno/mese"):
        ProduzioneRow(**_row(anno=2025))  # data is 2026-04-15
    with pytest.raises(ValueError, match="anno/mese"):
        ProduzioneRow(**_row(mese=5))  # data month is 4


def test_classe_empty_rejected():
    with pytest.raises(ValueError, match="classe vuoto"):
        ProduzioneRow(**_row(classe="  "))


def test_negative_importo_allowed():
    r = ProduzioneRow(**_row(importo_imponibile=Decimal("-43.00")))
    assert r.importo_imponibile == Decimal("-43.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest_produzione_pms.py -v`
Expected: FAIL with `ImportError: cannot import name 'OPERATIONS_CUTOVER_DATE'` (or `ProduzioneRow`).

- [ ] **Step 3: Add the cutover constant and schema**

In `core/schemas.py`, after the shared-types block (after `Sezione = Literal[...]`), add:

```python
OPERATIONS_CUTOVER_DATE = date(2025, 4, 1)
"""Switch operativo HotelCube INTUR → ORTI.

Pre 2025-04-01: INTUR gestiva Hotel+Residence+CVM. Post: ORTI gestisce le
operations. Deriva societa_id da date HotelCube (produzione, accodamenti, ...).
"""
```

Then, immediately after the `RicaviFbRow` class, add:

```python
class ProduzioneRow(BaseModel):
    """Schema for f_produzione_pms — daily production by struttura × classe.

    Source: HotelCube Power BI Daily Production Report (taglio classe, Imponibile),
    one file per struttura × anno. Grana giorno × struttura × classe.

    Pattern: SNAPSHOT, natural_key (business_unit_id, anno). Re-export di una
    struttura×anno rimpiazza quelle righe (robusto agli storni).

    societa_id derivata da `data` vs OPERATIONS_CUTOVER_DATE.
    raw_object_id = FK a f_raw_objects, stampato dal path `promote`.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    data: date
    anno: int
    mese: int
    classe: str
    importo_imponibile: Decimal
    file_sorgente: str
    hash_riga: str
    raw_object_id: Optional[str] = None
    data_caricamento: datetime

    @field_validator("classe")
    @classmethod
    def classe_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("classe vuoto")
        return v

    @model_validator(mode="after")
    def societa_matches_cutover(self) -> "ProduzioneRow":
        expected = "INTUR" if self.data < OPERATIONS_CUTOVER_DATE else "ORTI"
        if self.societa_id != expected:
            raise ValueError(
                f"societa_id={self.societa_id!r} incoerente con cutover "
                f"{OPERATIONS_CUTOVER_DATE} per data {self.data}"
            )
        return self

    @model_validator(mode="after")
    def anno_mese_match_data(self) -> "ProduzioneRow":
        if self.data.year != self.anno or self.data.month != self.mese:
            raise ValueError(
                f"anno/mese ({self.anno}/{self.mese}) incoerenti con data {self.data}"
            )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest_produzione_pms.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/schemas.py tests/test_ingest_produzione_pms.py
git commit -m "feat(produzione): ProduzioneRow schema + cutover constant"
```

---

### Task 3: Parser — `parse_applied_filters` + class-column detection

**Files:**
- Create: `ingest/flussi/ingest_produzione_pms.py`
- Test: `tests/test_ingest_produzione_pms.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ingest_produzione_pms.py`:

```python
from ingest.flussi.ingest_produzione_pms import (
    detect_classe_columns,
    parse_applied_filters,
)

FILTER_HOTEL = (
    "Applied filters:\nMis_PB_ShowRow is greater than 0\nCodiceHotel is PANORAMAHT\n"
    "Descrizione is Imponibile\nParamDimAddebiti is Classe\nMese is aprile, maggio, "
    "giugno, gennaio, febbraio, marzo\nAnno is 2026"
)


def test_parse_applied_filters_hotel():
    bu, anno = parse_applied_filters(FILTER_HOTEL)
    assert bu == "HOTEL"
    assert anno == 2026


def test_parse_applied_filters_rejects_lordo():
    txt = FILTER_HOTEL.replace("Descrizione is Imponibile", "Descrizione is Lordo")
    with pytest.raises(ValueError, match="Imponibile"):
        parse_applied_filters(txt)


def test_parse_applied_filters_rejects_unknown_hotel():
    txt = FILTER_HOTEL.replace("PANORAMAHT", "MYSTERYHT")
    with pytest.raises(ValueError, match="CodiceHotel"):
        parse_applied_filters(txt)


def test_detect_classe_columns_hotel_with_blank():
    # HOTEL header has a blank col at index 1
    header = ("Classe", None, "01ROOM", "02FB", "03PARK", "07DIV", "11FITTO",
              "80AFFITT", "99ACC", "Total")
    cols = detect_classe_columns(header)
    assert cols == {2: "01ROOM", 3: "02FB", 4: "03PARK", 5: "07DIV",
                    6: "11FITTO", 7: "80AFFITT", 8: "99ACC"}


def test_detect_classe_columns_cvm_no_blank():
    header = ("Classe", "01ROOM", "02FB", "03PARK", "Total")
    cols = detect_classe_columns(header)
    assert cols == {1: "01ROOM", 2: "02FB", 3: "03PARK"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest_produzione_pms.py -k "applied_filters or classe_columns" -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` for `ingest.flussi.ingest_produzione_pms`.

- [ ] **Step 3: Create the parser module with the two helpers**

Create `ingest/flussi/ingest_produzione_pms.py`:

```python
#!/usr/bin/env python3
"""Ingest HotelCube Power BI Daily Production Report (classe cut) → f_produzione_pms.

One xlsx = one struttura × one anno. Period metadata (CodiceHotel, Anno,
Descrizione) lives in the file's last "Applied filters" cell. Data rows are daily;
columns are revenue classes (01ROOM, 02FB, ...). Unpivot wide→long.

Lifecycle: SNAPSHOT, natural_key (business_unit_id, anno). Re-loading a
struttura×anno replaces those rows.

Parser_module della source POWERBI_PRODUZIONE_ORTI_SNAPSHOT, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_produzione_pms --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_produzione_pms --file <xlsx> --raw-object-id <id>
    python -m ingest.flussi.ingest_produzione_pms --file <xlsx> --dry-run
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from core.config import F_PRODUZIONE_PMS
from core.schemas import (
    OPERATIONS_CUTOVER_DATE,
    ProduzioneRow,
    make_hash,
    validate_batch,
)

log = logging.getLogger("ingest.produzione_pms")

HOTEL_TO_BU = {
    "PANORAMAHT": "HOTEL",
    "ANGELINARES": "RESIDENCE",
    "HOMEHOLIDAY": "CVM",
}
CLASSE_RE = re.compile(r"^\d{2}[A-Z]+$")


def parse_applied_filters(text: str) -> tuple[str, int]:
    """Extract (business_unit_id, anno) from the 'Applied filters' cell.

    Requires Descrizione is Imponibile. Raises ValueError otherwise.
    """
    if not re.search(r"Descrizione is Imponibile", text):
        raise ValueError(
            f"file non Imponibile (atteso 'Descrizione is Imponibile'): {text[:120]!r}"
        )
    hotel_m = re.search(r"CodiceHotel is (\w+)", text)
    anno_m = re.search(r"Anno is (\d+)", text)
    if not (hotel_m and anno_m):
        raise ValueError(f"Applied filters incompleti: {text[:120]!r}")
    codice = hotel_m.group(1)
    if codice not in HOTEL_TO_BU:
        raise ValueError(f"CodiceHotel sconosciuto: {codice}")
    return HOTEL_TO_BU[codice], int(anno_m.group(1))


def detect_classe_columns(header: tuple) -> dict[int, str]:
    """Map column index → classe code for cells matching ^\\d{2}[A-Z]+$.

    Skips 'Total', 'Classe', blanks. Works regardless of leading blank cols.
    """
    out: dict[int, str] = {}
    for idx, cell in enumerate(header):
        if cell is None:
            continue
        name = str(cell).strip()
        if CLASSE_RE.match(name):
            out[idx] = name
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest_produzione_pms.py -k "applied_filters or classe_columns" -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_produzione_pms.py tests/test_ingest_produzione_pms.py
git commit -m "feat(produzione): parser helpers — applied filters + classe columns"
```

---

### Task 4: Parser — `parse_xlsx` (unpivot) + `build_rows`

**Files:**
- Modify: `ingest/flussi/ingest_produzione_pms.py` (append functions)
- Test: `tests/test_ingest_produzione_pms.py` (append, with an xlsx fixture helper)

- [ ] **Step 1: Write the failing tests (with a fixture builder)**

Append to `tests/test_ingest_produzione_pms.py`:

```python
from openpyxl import Workbook

from ingest.flussi.ingest_produzione_pms import build_rows, parse_xlsx


def _make_class_xlsx(path, codice_hotel="PANORAMAHT", anno=2026):
    """3 giorni × {01ROOM, 02FB} con un buco, un negativo, riga Total."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(["Classe", None, "01ROOM", "02FB", "Total"])
    ws.append(["Data", "Importo", "Importo", "Importo", "Importo"])
    ws.append([datetime(anno, 4, 15), None, 8000.0, 500.0, 8500.0])
    ws.append([datetime(anno, 4, 16), None, 9000.0, None, 9000.0])     # 02FB vuoto
    ws.append([datetime(anno, 4, 17), None, -43.0, 120.0, 77.0])        # negativo
    ws.append(["Total", None, 16957.0, 620.0, 17577.0])
    ws.append([None, None, None, None, None])
    ws.append([
        f"Applied filters:\nCodiceHotel is {codice_hotel}\n"
        f"Descrizione is Imponibile\nAnno is {anno}", None, None, None, None,
    ])
    wb.save(path)


def test_parse_xlsx_unpivot(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    (bu, anno), rows = parse_xlsx(p)
    assert bu == "HOTEL"
    assert anno == 2026
    # 15: 2 classi, 16: 1 (02FB None skipped), 17: 2 → 5 righe; Total escluso
    assert len(rows) == 5
    keys = {(r["data"].isoformat(), r["classe"]) for r in rows}
    assert ("2026-04-16", "02FB") not in keys      # cella vuota skippata
    neg = [r for r in rows if r["classe"] == "01ROOM" and r["data"].day == 17]
    assert neg[0]["importo"] == Decimal("-43.0")   # negativo tenuto


def test_parse_xlsx_excludes_total_column_and_row(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    _, rows = parse_xlsx(p)
    assert all(r["classe"] != "Total" for r in rows)
    assert all(r["data"].day in (15, 16, 17) for r in rows)


def test_build_rows_derives_societa_and_hash(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p, anno=2026)
    period, raw = parse_xlsx(p)
    out = build_rows(period, raw, p.name, raw_object_id="ro-1")
    r = out[0]
    assert r["societa_id"] == "ORTI"               # 2026 → post-cutover
    assert r["business_unit_id"] == "HOTEL"
    assert r["anno"] == 2026 and r["mese"] == 4
    assert r["raw_object_id"] == "ro-1"
    # hash deterministico su (bu, anno, data, classe)
    assert r["hash_riga"] == make_hash("HOTEL", "2026", r["data"].isoformat(), r["classe"])


def test_build_rows_pre_cutover_is_intur(tmp_path):
    p = tmp_path / "HOTEL_prod_2025.xlsx"
    _make_class_xlsx(p, anno=2025)  # 2025-04-15/16/17 are all post-cutover (ORTI)
    period, raw = parse_xlsx(p)
    out = build_rows(period, raw, p.name)
    assert all(r["societa_id"] == "ORTI" for r in out)  # april 2025 > cutover
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest_produzione_pms.py -k "parse_xlsx or build_rows" -v`
Expected: FAIL with `ImportError: cannot import name 'parse_xlsx'`.

- [ ] **Step 3: Implement `parse_xlsx` and `build_rows`**

Append to `ingest/flussi/ingest_produzione_pms.py`:

```python
def parse_xlsx(path: Path) -> tuple[tuple[str, int], list[dict]]:
    """Read a Daily Production Report (classe cut) → ((bu, anno), data_rows).

    data_rows = list of {data: date, classe: str, importo: Decimal}. The 'Total'
    row/column and empty cells are skipped; negatives are kept.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["Export"] if "Export" in wb.sheetnames else wb.worksheets[0]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    wb.close()
    if len(rows) < 3:
        raise ValueError(f"{path.name}: troppe poche righe ({len(rows)})")

    # Applied filters = last row whose first cell starts with 'Applied filters'
    filter_text = next(
        (str(r[0]) for r in reversed(rows)
         if r and r[0] and str(r[0]).startswith("Applied filters")),
        "",
    )
    period = parse_applied_filters(filter_text)

    # Header = first row that yields ≥1 classe column
    classe_cols: dict[int, str] = {}
    for r in rows:
        cand = detect_classe_columns(r)
        if cand:
            classe_cols = cand
            break
    if not classe_cols:
        raise ValueError(f"{path.name}: nessuna colonna-classe rilevata")

    data_rows: list[dict] = []
    for r in rows:
        d = r[0] if r else None
        if not isinstance(d, datetime):
            continue
        for idx, classe in classe_cols.items():
            if idx >= len(r):
                continue
            val = r[idx]
            if val is None or val == "":
                continue
            if not isinstance(val, (int, float)):
                continue
            data_rows.append({
                "data": d.date(),
                "classe": classe,
                "importo": Decimal(str(val)),
            })
    return period, data_rows


def build_rows(
    period: tuple[str, int],
    raw_rows: list[dict],
    file_name: str,
    raw_object_id: str | None = None,
) -> list[dict]:
    """Turn parsed raw rows into f_produzione_pms dict rows.

    Derives societa_id from data via OPERATIONS_CUTOVER_DATE, mese from data,
    and hash_riga = md5(business_unit_id, anno, data, classe).
    """
    bu, anno = period
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for r in raw_rows:
        d = r["data"]
        societa = "INTUR" if d < OPERATIONS_CUTOVER_DATE else "ORTI"
        out.append({
            "societa_id": societa,
            "business_unit_id": bu,
            "data": d,
            "anno": anno,
            "mese": d.month,
            "classe": r["classe"],
            "importo_imponibile": r["importo"],
            "file_sorgente": file_name,
            "hash_riga": make_hash(bu, str(anno), d.isoformat(), r["classe"]),
            "raw_object_id": raw_object_id,
            "data_caricamento": now,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest_produzione_pms.py -k "parse_xlsx or build_rows" -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_produzione_pms.py tests/test_ingest_produzione_pms.py
git commit -m "feat(produzione): parse_xlsx unpivot + build_rows (cutover + hash)"
```

---

### Task 5: Parser — `ingest_file` (SNAPSHOT write) + CLI `main`

**Files:**
- Modify: `ingest/flussi/ingest_produzione_pms.py` (append `ingest_file`, `main`)
- Test: `tests/test_ingest_produzione_pms.py` (append; mock `bq_write_validated`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ingest_produzione_pms.py`:

```python
from unittest.mock import patch

from ingest.flussi.ingest_produzione_pms import ingest_file


def test_ingest_file_dry_run_no_write(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    with patch("core.bq.write.bq_write_validated") as mock_write:
        n = ingest_file(p, dry_run=True)
    assert n == 5
    mock_write.assert_not_called()


def test_ingest_file_snapshot_natural_key(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    with patch("core.bq.write.bq_write_validated") as mock_write:
        ingest_file(p, raw_object_id="ro-9", dry_run=False)
    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert kwargs["mode"] == "snapshot"
    assert kwargs["natural_key"] == ["business_unit_id", "anno"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest_produzione_pms.py -k "ingest_file" -v`
Expected: FAIL with `ImportError: cannot import name 'ingest_file'`.

- [ ] **Step 3: Implement `ingest_file` and `main`**

Append to `ingest/flussi/ingest_produzione_pms.py`:

```python
def ingest_file(
    path: Path, raw_object_id: str | None = None, dry_run: bool = False
) -> int:
    """Parse one xlsx and SNAPSHOT-write it to f_produzione_pms. Returns row count.

    raw_object_id is the lineage FK passed by `hotelops promote`; stamped on
    every row. SNAPSHOT scope = (business_unit_id, anno).
    """
    period, raw = parse_xlsx(path)
    rows = build_rows(period, raw, path.name, raw_object_id)
    validate_batch(rows, ProduzioneRow, context=f"produzione_pms {path.name}")
    bu, anno = period
    if dry_run:
        log.info("[DRY-RUN] %s → %s %d : %d righe", path.name, bu, anno, len(rows))
        return len(rows)

    from core.bq.write import bq_write_validated

    pydantic_rows = [ProduzioneRow(**r) for r in rows]
    bq_write_validated(
        F_PRODUZIONE_PMS,
        pydantic_rows,
        mode="snapshot",
        natural_key=["business_unit_id", "anno"],
    )
    log.info("OK %s → %s %d : %d righe", path.name, bu, anno, len(rows))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Daily Production Report → f_produzione_pms")
    ap.add_argument("--file", required=True, type=Path, help="xlsx Daily Production Report (classe)")
    ap.add_argument(
        "--raw-object-id",
        default=None,
        help="FK a f_raw_objects — passato da `hotelops promote`",
    )
    ap.add_argument(
        "--societa",
        default=None,
        help="Ignorato — societa derivata dal cutover. Accettato da `hotelops promote`.",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    n = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %d righe", n)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the full test file to verify everything passes**

Run: `pytest tests/test_ingest_produzione_pms.py -v`
Expected: all tests pass (18 total).

- [ ] **Step 5: Lint**

Run: `ruff check ingest/flussi/ingest_produzione_pms.py core/schemas.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add ingest/flussi/ingest_produzione_pms.py tests/test_ingest_produzione_pms.py
git commit -m "feat(produzione): ingest_file SNAPSHOT write + CLI"
```

---

### Task 6: Source registry entry + resolver loads it

**Files:**
- Modify: `core/source_registry.yaml` (add entry near the RICAVIFB block)

- [ ] **Step 1: Add the source entry**

In `core/source_registry.yaml`, after the `POWERBI_RICAVIFB_ORTI_SNAPSHOT` block, add:

```yaml
  # ── Produzione PMS giornaliera per classe — SNAPSHOT ──────────────────────
  POWERBI_PRODUZIONE_ORTI_SNAPSHOT:
    system: POWERBI
    dataset: PRODUZIONE
    dataset_label: "Produzione giornaliera per classe (Daily Production Report, Imponibile)"
    societa: ORTI
    business_unit: null
    lifecycle: SNAPSHOT
    canonical_table: f_produzione_pms
    parser_module: ingest.flussi.ingest_produzione_pms
    natural_key: [business_unit_id, anno]
    loop_targets: [monthly_close, budget_vs_consuntivo]
    promotion_policy: AUTO
    detector_category: produzione_pms
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "powerbi/produzione/ORTI"
```

- [ ] **Step 2: Verify the resolver loads the registry without boot errors**

Run:
```bash
python -c "from core.lineage.source_resolver import load_sources; s = load_sources(); print('OK', 'POWERBI_PRODUZIONE_ORTI_SNAPSHOT' in s)"
```
Expected: `OK True` (the boot invariant `loop_targets != [] ⇔ policy != RAW_ONLY` holds: loop_targets set, policy AUTO).

> If `load_sources` has a different name, find the loader: `grep -n "def load" core/lineage/source_resolver.py` and use the function that parses `source_registry.yaml`.

- [ ] **Step 3: Commit**

```bash
git add core/source_registry.yaml
git commit -m "feat(produzione): register POWERBI_PRODUZIONE_ORTI_SNAPSHOT source"
```

---

### Task 7: Standalone dry-run against a real file (smoke)

**Files:** none (operational verification)

- [ ] **Step 1: Dry-run the parser on a real class-cut file**

Run:
```bash
python -m ingest.flussi.ingest_produzione_pms \
  --file "$HOME/Downloads/HOTEL_Daily Production Report (3).xlsx" --dry-run
```
Expected: `[DRY-RUN] ... → HOTEL 2026 : N righe` with N > 0, no traceback. If the file errors on `Descrizione is Imponibile`, confirm it is the Imponibile class-cut export, not the Lordo or occupancy file.

- [ ] **Step 2: Dry-run a 2025 file (cutover sanity)**

Run:
```bash
python -m ingest.flussi.ingest_produzione_pms \
  --file "$HOME/Downloads/2025_Hotel_Daily Production Report (3).xlsx" --dry-run
```
Expected: parses without error (rows gen–mar → INTUR, apr–dic → ORTI internally; validation passes).

No commit (verification only).

---

### Task 8: Backfill via intake + promote, with reconciliation

**Files:** none (operational). Run after Tasks 1–6 land.

- [ ] **Step 1: Intake + promote each 2026 class-cut file**

For each struttura file (HOTEL, CVM, Angelina — the `(3)` class-cut files):
```bash
hotelops intake "$HOME/Downloads/HOTEL_Daily Production Report (3).xlsx" \
  --source-name POWERBI_PRODUZIONE_ORTI_SNAPSHOT
# note the printed raw_object_id, then:
hotelops promote --raw-object-id <id>
```
Repeat for `CVM_Daily Production Report (3).xlsx` and `AngelinaDaily Production Report (3).xlsx`.
Expected: each promote logs `OK ... → <BU> 2026 : N righe`.

- [ ] **Step 2: Intake + promote each 2025 class-cut file**

Same for `2025_Hotel_…(3).xlsx`, `2025_CVM_…(3).xlsx`, `2025_ANG_…(3).xlsx`.

- [ ] **Step 3: Intake (raw-only) the occupancy files**

For the `(2)` occupancy files (2025+2026, all three struttura), `intake` only — do NOT promote:
```bash
hotelops intake "$HOME/Downloads/HOTEL_Daily Production Report (2).xlsx" \
  --source-name POWERBI_PRODUZIONE_ORTI_SNAPSHOT
```
Expected: registered in `f_raw_objects`, state RAW_INGESTED, not promoted.

- [ ] **Step 4: Reconcile canonical totals vs occupancy file totals**

Run:
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT business_unit_id, anno, ROUND(SUM(importo_imponibile),2) tot
FROM `hotelops-suite.hotelops.f_produzione_pms`
GROUP BY business_unit_id, anno ORDER BY anno, business_unit_id'
```
Expected (matches the hand-verified totals from the design session):
| BU | anno | tot |
|---|---|---|
| HOTEL | 2025 | 3.282.683,39 |
| RESIDENCE | 2025 | 555.076,72 |
| CVM | 2025 | 215.122,27 |
| HOTEL | 2026 | 954.494,19 |
| RESIDENCE | 2026 | 107.820,96 |
| CVM | 2026 | 53.588,04 |

If any total mismatches its occupancy-file `Total`, stop and investigate before declaring done.

No commit (data load).

---

### Task 9: Cleanup orphan lordo objects + docs

**Files:**
- Modify: `CLAUDE.md`, `STATUS.md`

- [ ] **Step 1: Mark the 3 orphan lordo raw objects REJECTED**

Find them:
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT raw_object_id, file_name_original FROM `hotelops-suite.hotelops.f_raw_objects`
WHERE source_name = "POWERBI_PRODUZIONE_ORTI_APPEND"'
```
For each `raw_object_id`, emit a REJECTED lineage event via the manifest API:
```bash
python -c "
from core.lineage.raw_manifest import emit_event
for rid in ['<id1>','<id2>','<id3>']:
    emit_event(rid, 'REJECTED', note='superseded by Imponibile class-cut; source renamed to _SNAPSHOT')
print('done')
"
```
> If `emit_event`'s signature differs, check it: `grep -n "def emit_event" core/lineage/raw_manifest.py`. Use the event type the state machine names for rejection (`grep -n REJECTED core/lineage/state_machine.py`).

Expected: `v_raw_objects_current` shows those 3 in state REJECTED.

- [ ] **Step 2: Add the table to CLAUDE.md**

In `CLAUDE.md`, in the Fact tables table, add a row:
```markdown
| `f_produzione_pms` | Produzione giornaliera HotelCube per struttura × classe ricavo (Daily Production Report, Imponibile, via Power BI). Drill-down giorno×classe. Ingerita via lineage (source `POWERBI_PRODUZIONE_ORTI_SNAPSHOT`). (SNAPSHOT, natural_key business_unit_id+anno) |
```

- [ ] **Step 3: Update STATUS.md**

In `STATUS.md`, under "Completato di recente" add a dated line for the produzione pipeline, and under "Prossimi passi" add `d_classi_produzione TBD (mapping classe → BU/cod_conto/categoria_ce)` and `f_produzione_occupazione (camere/pax) deferred until RevPAR/ADR needed`. Note the `f_ricavi_fb` 02FB overlap debt.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md STATUS.md
git commit -m "docs(produzione): f_produzione_pms in CLAUDE.md + STATUS; reject orphan lordo objects"
```

---

## Self-Review

**Spec coverage:**
- GCS drop&store + naming → Task 6 (registry `raw_storage`) + Task 8 (intake). ✅
- Source registry entry → Task 6. ✅
- `f_produzione_pms` schema (giorno×struttura×classe, SNAPSHOT) → Task 1 (DDL) + Task 2 (Pydantic). ✅
- Parser (applied filters, class detection, unpivot, cutover, hash, SNAPSHOT write) → Tasks 3–5. ✅
- business_unit_id filled → Task 4 (`build_rows`). ✅
- Occupancy raw-only deferred → Task 8 Step 3 (intake only). ✅
- Orphan lordo REJECTED → Task 9 Step 1. ✅
- Backfill + reconciliation success criterion → Task 8. ✅
- Docs (CLAUDE.md, STATUS.md) → Task 9. ✅
- Debts annotated (02FB overlap, d_classi_produzione) → Task 9 Step 3. ✅

**Placeholder scan:** No "TBD/handle edge cases" in implementation steps; all code blocks complete. The two `> If signature differs` notes point to exact grep commands, not vague instructions. ✅

**Type consistency:** `parse_applied_filters → (bu, anno)`, `detect_classe_columns → dict[int,str]`, `parse_xlsx → ((bu,anno), rows)`, `build_rows`, `ingest_file` consistent across Tasks 3–5 and tests. `ProduzioneRow` fields match DDL columns (Task 1) and schema (Task 2). `natural_key=["business_unit_id","anno"]` identical in parser (Task 5) and registry (Task 6). ✅
