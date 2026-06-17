# Spiaggia — Corrispettivi giornalieri (MVP 2026) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingerire il Registro Corrispettivi INTUR (RT, giornaliero) in una nuova tabella canonical `f_spiaggia_corrispettivi` e unirlo agli alloggiati PMS (ORTI) in una vista `v_spiaggia_giornaliero` che dà il ricavo totale stabilimento per giorno.

**Architecture:** Parser layout-robusto (openpyxl) per il workbook registro (1 sheet/mese, righe `giorno · data · totale · 22%spiaggia · 10%bar`) → `f_spiaggia_corrispettivi` via lineage (intake→promote) con `bq_write_validated(mode="snapshot")`. Vista BQ LEFT JOIN con `f_produzione_pms` (classi `04BEALL`/`10BEBAR`, già canonical, `societa_id=ORTI`).

**Tech Stack:** Python 3.11, openpyxl, pydantic, google-cloud-bigquery, pytest. Pattern lineage esistente (`ingest/flussi/ingest_spiaggia.py`, `core/lineage/*`).

## Global Constraints

- Project/Dataset BQ: `hotelops-suite` / `hotelops` (da `core/config.py`).
- Ogni riga fact porta le 5 dimensioni: `societa_id, business_unit_id, location_id, oggetto_id, funzione_id`.
- Corrispettivi = **societa INTUR**, business_unit **LIDO**, location **LIDO**, oggetto/funzione **NULL**.
- Split aliquota: **22% = spiaggia, 10% = bar** (colonne registro).
- Ogni scrittura BQ passa da `core.schemas.validate_batch` + `core.bq.write.bq_write_validated`.
- Lifecycle tabella: **SNAPSHOT full-replace per anno**, `natural_key=["societa_id","anno"]` (un file registro = un anno intero; re-export ri-scrive l'anno).
- Il parser è invocato da `hotelops promote` come `python -m ingest.flussi.ingest_spiaggia_corrispettivi --file <xlsx> --raw-object-id <id>`.
- Coercion numerica: celle tipo `" 1,083.00 "` (migliaia con virgola), `" - "` (dash = vuoto/zero), spazi → strip.
- Anno: da header sheet (`ANNO: 2026`) con fallback filename; **mai dall'header se incoerente col contenuto** — validare.

---

### Task 1: Profilare la struttura reale del registro xlsx

**Files:**
- Create: `/tmp/profile_registro.py` (script usa-e-getta, non committato)

**Interfaces:**
- Produces: la struttura cella/sheet osservata, usata per fissare gli indici colonna del parser (Task 4) e i dati della fixture di test.

Il contenuto logico è noto (1 sezione/mese, righe `n · "16-Jun" · totale · 22% · 10%`), ma gli indici colonna esatti e i nomi sheet vanno verificati sul file binario prima di scrivere il parser.

- [ ] **Step 1: Scaricare il registro xlsx in locale**

Chiedere a Stefano il file `INTUR_REGISTRO CORRISPETTIVI SPIAGGIA_2026.xlsx` in locale (es. `~/Downloads/`), oppure esportarlo da Drive (id `1RwaXbXtRL3XQ9iq0nIpj7qG9ixUHn-Wt`).

- [ ] **Step 2: Profilare sheet + righe-dato**

```python
import openpyxl
wb = openpyxl.load_workbook("/Users/stefanodellapietra/Downloads/INTUR_REGISTRO CORRISPETTIVI SPIAGGIA_2026.xlsx", read_only=True, data_only=True)
print("SHEETS:", wb.sheetnames)
for ws in wb.worksheets[:2]:
    print(f"\n### {ws.title}")
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=18, values_only=True)):
        print(i+1, [c for c in row])
wb.close()
```

Run: `python3 /tmp/profile_registro.py`
Expected: vedere se è 1 sheet/mese o uno unico; identificare l'indice colonna di `data` ("16-Jun"), `TOTALE`, `22%`, `10%`, e la cella `ANNO`.

- [ ] **Step 3: Annotare la struttura**

Annotare nel commit message di Task 4 (o in cima al parser) la struttura osservata. Se diverge da "righe con 2ª cella = `D-Mon` seguita da 3 numerici", adeguare `iter_day_rows` (Task 4).

---

### Task 2: Schema `SpiaggiaCorrispettivoRow` + config table id

**Files:**
- Modify: `core/config.py:36` (dopo `F_SPIAGGIA_SPOTS`)
- Modify: `core/schemas.py:1069` (dopo `SpiaggiaSpotRow`)
- Test: `tests/test_ingest_spiaggia_corrispettivi.py`

**Interfaces:**
- Produces: `SpiaggiaCorrispettivoRow` (pydantic), `F_SPIAGGIA_CORRISPETTIVI` (str table id).

- [ ] **Step 1: Write the failing test**

In `tests/test_ingest_spiaggia_corrispettivi.py`:

```python
from datetime import date, datetime, timezone
import pytest
from core.schemas import SpiaggiaCorrispettivoRow


def _now():
    return datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


def test_corrispettivo_row_valid():
    r = SpiaggiaCorrispettivoRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        location_id="LIDO",
        data=date(2026, 6, 16),
        anno=2026,
        mese=6,
        corrispettivo_spiaggia=561.0,
        corrispettivo_bar=517.5,
        corrispettivo_totale=1078.5,
        rt_matricola="RT2CFL018343",
        file_sorgente="registro_2026.xlsx",
        hash_riga="abc",
        data_caricamento=_now(),
    )
    assert r.societa_id == "INTUR"
    assert r.corrispettivo_totale == 1078.5


def test_corrispettivo_row_rejects_bad_societa():
    with pytest.raises(Exception):
        SpiaggiaCorrispettivoRow(
            societa_id="PIPPO", business_unit_id="LIDO",
            data=date(2026, 6, 16), anno=2026, mese=6,
            corrispettivo_spiaggia=1.0, corrispettivo_bar=1.0,
            corrispettivo_totale=2.0,
            file_sorgente="x.xlsx", hash_riga="x", data_caricamento=_now(),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_spiaggia_corrispettivi.py::test_corrispettivo_row_valid -v`
Expected: FAIL with `ImportError: cannot import name 'SpiaggiaCorrispettivoRow'`

- [ ] **Step 3: Add the schema**

In `core/schemas.py` dopo `SpiaggiaSpotRow` (riga ~1069):

```python
class SpiaggiaCorrispettivoRow(BaseModel):
    """Schema per f_spiaggia_corrispettivi — corrispettivi RT giornalieri INTUR.

    1 riga/giorno dal Registro Corrispettivi Spiaggia. Split per aliquota IVA:
    22% = spiaggia, 10% = bar. Lifecycle SNAPSHOT full-replace per anno
    (natural_key societa_id+anno). NON include gli alloggiati (= PMS, societa ORTI).
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    data: _Date
    anno: int
    mese: int
    corrispettivo_spiaggia: float
    corrispettivo_bar: float
    corrispettivo_totale: float
    rt_matricola: Optional[str] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime
```

- [ ] **Step 4: Add the table id**

In `core/config.py` dopo riga 36 (`F_SPIAGGIA_SPOTS`):

```python
F_SPIAGGIA_CORRISPETTIVI    = _t("f_spiaggia_corrispettivi")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ingest_spiaggia_corrispettivi.py -v`
Expected: PASS (2 test)

- [ ] **Step 6: Commit**

```bash
git add core/schemas.py core/config.py tests/test_ingest_spiaggia_corrispettivi.py
git commit -m "feat(spiaggia): schema SpiaggiaCorrispettivoRow + table id"
```

---

### Task 3: DDL `f_spiaggia_corrispettivi`

**Files:**
- Modify: `core/bq/load/create_spiaggia_tables.py` (aggiungere DDL + entry in `ALL_DDL`)

**Interfaces:**
- Consumes: `F_SPIAGGIA_CORRISPETTIVI` da config (Task 2).
- Produces: tabella BQ `f_spiaggia_corrispettivi`.

- [ ] **Step 1: Aggiungere import e DDL**

In `core/bq/load/create_spiaggia_tables.py`, aggiungere `F_SPIAGGIA_CORRISPETTIVI` all'import da `core.config`, poi la costante:

```python
DDL_CORRISPETTIVI = f"""
CREATE TABLE IF NOT EXISTS `{F_SPIAGGIA_CORRISPETTIVI}` (
    societa_id             STRING NOT NULL,
    business_unit_id       STRING NOT NULL,
    location_id            STRING,
    oggetto_id             STRING,
    funzione_id            STRING,
    data                   DATE NOT NULL,
    anno                   INT64 NOT NULL,
    mese                   INT64 NOT NULL,
    corrispettivo_spiaggia FLOAT64,
    corrispettivo_bar      FLOAT64,
    corrispettivo_totale   FLOAT64,
    rt_matricola           STRING,
    raw_object_id          STRING,
    file_sorgente          STRING NOT NULL,
    hash_riga              STRING NOT NULL,
    data_caricamento       TIMESTAMP NOT NULL
)
PARTITION BY data
CLUSTER BY societa_id
"""
```

- [ ] **Step 2: Registrare nel dict ALL_DDL**

Aggiungere a `ALL_DDL`:

```python
    "f_spiaggia_corrispettivi": DDL_CORRISPETTIVI,
```

- [ ] **Step 3: Creare la tabella (dry-run poi reale)**

Run: `python -m core.bq.load.create_spiaggia_tables --dry-run`
Expected: stampa il DDL `f_spiaggia_corrispettivi`.
Run: `python -m core.bq.load.create_spiaggia_tables`
Expected: `OK f_spiaggia_corrispettivi creata/confermata`.

- [ ] **Step 4: Commit**

```bash
git add core/bq/load/create_spiaggia_tables.py
git commit -m "feat(spiaggia): DDL f_spiaggia_corrispettivi (partition data, cluster societa)"
```

---

### Task 4: Parser `ingest_spiaggia_corrispettivi.py`

**Files:**
- Create: `ingest/flussi/ingest_spiaggia_corrispettivi.py`
- Test: `tests/test_ingest_spiaggia_corrispettivi.py` (estendere)

**Interfaces:**
- Consumes: `SpiaggiaCorrispettivoRow`, `validate_batch`, `make_hash` (schemas); `F_SPIAGGIA_CORRISPETTIVI` (config); `bq_write_validated` (write).
- Produces: `to_eur(v)->float|None`, `parse_data(cell,anno)->date|None`, `iter_day_rows(ws,anno)->list[tuple]`, `build_corrispettivo_rows(...)`, `ingest_file(path,raw_object_id,dry_run)->dict`.

- [ ] **Step 1: Write the failing tests** (coercion + row builder + quality gate)

In `tests/test_ingest_spiaggia_corrispettivi.py` aggiungere:

```python
import openpyxl
from ingest.flussi.ingest_spiaggia_corrispettivi import (
    to_eur, parse_data, iter_day_rows, build_corrispettivo_rows, ingest_file,
)
from datetime import date as _d, datetime as _dt, timezone as _tz

_NOW = _dt(2026, 6, 17, tzinfo=_tz.utc)


def test_to_eur():
    assert to_eur(" 1,083.00 ") == 1083.0
    assert to_eur(" - ") is None
    assert to_eur("866.00") == 866.0
    assert to_eur(None) is None
    assert to_eur(527.0) == 527.0


def test_parse_data():
    assert parse_data("16-Jun", 2026) == _d(2026, 6, 16)
    assert parse_data("1-Jul", 2026) == _d(2026, 7, 1)
    assert parse_data("Totale mese", 2026) is None
    assert parse_data(None, 2026) is None


def _make_registro(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Giugno"
    ws["E1"] = "Giugno"; ws["I1"] = "ANNO:"; ws["J1"] = "2026"
    ws["M1"] = "RT"; ws["N1"] = "RT2CFL018343"
    # header rows then day rows: [n, data, totale, 22%, 10%] starting col A
    data = [
        (6, "6-Jun", "866.00", "339.00", "527.00"),
        (16, "16-Jun", "1,078.50", "561.00", "517.50"),
        (None, "Totale mese", "1,944.50", "900.00", "1,044.50"),
    ]
    r0 = 8
    for i, row in enumerate(data):
        for j, val in enumerate(row):
            ws.cell(row=r0 + i, column=1 + j, value=val)
    p = tmp_path / "registro_2026.xlsx"
    wb.save(p)
    return p


def test_iter_day_rows(tmp_path):
    p = _make_registro(tmp_path)
    wb = openpyxl.load_workbook(p, data_only=True)
    rows = iter_day_rows(wb["Giugno"], 2026)
    assert (_d(2026, 6, 6), 866.0, 339.0, 527.0) in rows
    assert (_d(2026, 6, 16), 1078.5, 561.0, 517.5) in rows
    assert len(rows) == 2  # "Totale mese" escluso


def test_build_rows_and_quality_gate(tmp_path):
    p = _make_registro(tmp_path)
    wb = openpyxl.load_workbook(p, data_only=True)
    rows = build_corrispettivo_rows(wb, "registro_2026.xlsx", "raw-1", _NOW)
    assert len(rows) == 2
    r = [x for x in rows if x.data == _d(2026, 6, 16)][0]
    assert r.corrispettivo_spiaggia == 561.0
    assert r.corrispettivo_bar == 517.5
    assert r.corrispettivo_totale == 1078.5
    assert r.societa_id == "INTUR" and r.business_unit_id == "LIDO"
    assert r.rt_matricola == "RT2CFL018343"
    assert r.raw_object_id == "raw-1"


def test_ingest_file_dry_run(tmp_path):
    p = _make_registro(tmp_path)
    counts = ingest_file(p, raw_object_id=None, dry_run=True)
    assert counts["corrispettivi"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest_spiaggia_corrispettivi.py -v`
Expected: FAIL con `ModuleNotFoundError: ingest.flussi.ingest_spiaggia_corrispettivi`

- [ ] **Step 3: Write the parser**

Create `ingest/flussi/ingest_spiaggia_corrispettivi.py`:

```python
#!/usr/bin/env python3
"""Ingest Registro Corrispettivi Spiaggia INTUR (xlsx) → f_spiaggia_corrispettivi.

1 riga/giorno. Split aliquota: 22% = spiaggia, 10% = bar. Un file = un anno.
Lifecycle SNAPSHOT full-replace per anno (natural_key societa_id+anno).

Parser_module della source INTUR_CORRISPETTIVI_SPIAGGIA_INTUR_SNAPSHOT, invocato
da `hotelops promote`:
    python -m ingest.flussi.ingest_spiaggia_corrispettivi --file X.xlsx --raw-object-id Y
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import openpyxl

from core.config import F_SPIAGGIA_CORRISPETTIVI
from core.schemas import SpiaggiaCorrispettivoRow, make_hash, validate_batch

log = logging.getLogger("ingest.spiaggia_corrispettivi")

SOCIETA = "INTUR"
BUSINESS_UNIT = "LIDO"
LOCATION = "LIDO"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_RE = re.compile(r"^\s*(\d{1,2})-([A-Za-z]{3})\s*$")


def to_eur(v: Any) -> Optional[float]:
    """Cella corrispettivo → float. ' 1,083.00 '→1083.0, ' - '/''→None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_data(cell: Any, anno: int) -> Optional[date]:
    """'16-Jun' + anno → date. Datetime cell → date. Altro → None."""
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    if cell is None:
        return None
    m = _DATE_RE.match(str(cell))
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(anno, month, day)
    except ValueError:
        return None


def _find_anno(ws, file_name: str) -> int:
    """Anno dall'header sheet (cella accanto a 'ANNO:'); fallback dal filename."""
    for row in ws.iter_rows(min_row=1, max_row=6, values_only=True):
        for i, c in enumerate(row):
            if isinstance(c, str) and c.strip().upper().startswith("ANNO"):
                for nxt in row[i + 1:]:
                    n = to_eur(nxt)
                    if n and 2018 <= int(n) <= 2035:
                        return int(n)
    m = re.search(r"(20\d{2})", file_name)
    if m:
        return int(m.group(1))
    raise ValueError(f"anno non determinabile per sheet {ws.title} / {file_name}")


def _find_rt(ws) -> Optional[str]:
    for row in ws.iter_rows(min_row=1, max_row=6, values_only=True):
        for i, c in enumerate(row):
            if isinstance(c, str) and c.strip() == "RT":
                for nxt in row[i + 1:]:
                    if isinstance(nxt, str) and nxt.strip().startswith("RT"):
                        return nxt.strip()
    return None


def iter_day_rows(ws, anno: int) -> list[tuple]:
    """Righe-dato del mese → [(data, totale, spiaggia22, bar10)].

    Riga-dato = una cella matcha 'D-Mon'; i 3 numerici a seguire (saltando vuoti)
    sono totale, 22% (spiaggia), 10% (bar). Esclude Totale/riporto/riporta.
    """
    out: list[tuple] = []
    for row in ws.iter_rows(values_only=True):
        d = None
        idx = None
        for i, c in enumerate(row):
            d = parse_data(c, anno)
            if d is not None:
                idx = i
                break
        if d is None:
            continue
        nums = [to_eur(c) for c in row[idx + 1:]]
        nums = [n for n in nums if n is not None]
        if len(nums) < 3:
            continue
        totale, spiaggia, bar = nums[0], nums[1], nums[2]
        out.append((d, totale, spiaggia, bar))
    return out


def build_corrispettivo_rows(
    wb, file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[SpiaggiaCorrispettivoRow]:
    out: list[SpiaggiaCorrispettivoRow] = []
    for ws in wb.worksheets:
        try:
            anno = _find_anno(ws, file_name)
        except ValueError:
            continue
        rt = _find_rt(ws)
        for d, totale, spiaggia, bar in iter_day_rows(ws, anno):
            # Quality gate per-riga: totale ~= spiaggia + bar (tolleranza 0.05)
            if abs((spiaggia + bar) - totale) > 0.05:
                log.warning("riga %s: totale %.2f != spiaggia+bar %.2f",
                            d, totale, spiaggia + bar)
            out.append(SpiaggiaCorrispettivoRow(
                societa_id=SOCIETA,
                business_unit_id=BUSINESS_UNIT,
                location_id=LOCATION,
                oggetto_id=None,
                funzione_id=None,
                data=d,
                anno=d.year,
                mese=d.month,
                corrispettivo_spiaggia=spiaggia,
                corrispettivo_bar=bar,
                corrispettivo_totale=totale,
                rt_matricola=rt,
                raw_object_id=raw_object_id,
                file_sorgente=file_name,
                hash_riga=make_hash("corrispettivi", SOCIETA, d.isoformat()),
                data_caricamento=now,
            ))
    return out


def ingest_file(
    path: Path, raw_object_id: Optional[str] = None, dry_run: bool = False
) -> dict[str, int]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    now = datetime.now(timezone.utc)
    rows = build_corrispettivo_rows(wb, path.name, raw_object_id, now)
    wb.close()
    if rows:
        validate_batch(
            [r.model_dump() for r in rows],
            SpiaggiaCorrispettivoRow,
            context=f"spiaggia_corrispettivi {path.name}",
        )
    if dry_run:
        log.info("[DRY-RUN] corrispettivi → %s : %d righe", F_SPIAGGIA_CORRISPETTIVI, len(rows))
        return {"corrispettivi": len(rows)}

    from core.bq.write import bq_write_validated
    bq_write_validated(
        F_SPIAGGIA_CORRISPETTIVI,
        rows,
        mode="snapshot",
        natural_key=["societa_id", "anno"],
    )
    log.info("OK corrispettivi → %s : %d righe (full-replace anno)",
             F_SPIAGGIA_CORRISPETTIVI, len(rows))
    return {"corrispettivi": len(rows)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Registro Corrispettivi Spiaggia → BQ")
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--raw-object-id", default=None)
    ap.add_argument("--societa", default=None, help="Ignorato — sempre INTUR.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    counts = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %s", counts)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest_spiaggia_corrispettivi.py -v`
Expected: PASS (tutti i test, incl. coercion, parse_data, iter_day_rows, build, dry-run).

- [ ] **Step 5: Smoke sul file vero (dry-run)**

Run: `python -m ingest.flussi.ingest_spiaggia_corrispettivi --file "/Users/stefanodellapietra/Downloads/INTUR_REGISTRO CORRISPETTIVI SPIAGGIA_2026.xlsx" --dry-run`
Expected: `[DRY-RUN] corrispettivi … : N righe` con N = giorni non-zero (giugno 2026: ~11). Verificare a video che 16/06 = spiaggia 561 / bar 517,5.

- [ ] **Step 6: Commit**

```bash
git add ingest/flussi/ingest_spiaggia_corrispettivi.py tests/test_ingest_spiaggia_corrispettivi.py
git commit -m "feat(spiaggia): parser registro corrispettivi INTUR → f_spiaggia_corrispettivi"
```

---

### Task 5: Source registry entry + promote end-to-end

**Files:**
- Modify: `core/source_registry.yaml` (nuova entry dopo `SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT`)

**Interfaces:**
- Consumes: parser `ingest.flussi.ingest_spiaggia_corrispettivi` (Task 4).
- Produces: source `INTUR_CORRISPETTIVI_SPIAGGIA_INTUR_SNAPSHOT` per `hotelops intake/promote`.

- [ ] **Step 1: Aggiungere la entry**

In `core/source_registry.yaml`:

```yaml
  # ── Registro Corrispettivi Spiaggia INTUR — SNAPSHOT ─────────────────────
  INTUR_CORRISPETTIVI_SPIAGGIA_INTUR_SNAPSHOT:
    system: INTUR
    dataset: CORRISPETTIVI_SPIAGGIA
    dataset_label: "Registro Corrispettivi RT Spiaggia (INTUR, giornaliero)"
    societa: INTUR
    business_unit: LIDO
    lifecycle: SNAPSHOT
    canonical_table: f_spiaggia_corrispettivi
    parser_module: ingest.flussi.ingest_spiaggia_corrispettivi
    natural_key: [societa_id, anno]   # SNAPSHOT full-replace per anno
    loop_targets: [cash_control]
    promotion_policy: MANUAL
    detector_category: corrispettivi_spiaggia
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "intur/corrispettivi_spiaggia/INTUR"
```

- [ ] **Step 2: Verificare che il registry carichi (invariante boot)**

Run: `python -c "from core.lineage.source_resolver import load_sources; s=load_sources(); print('INTUR_CORRISPETTIVI_SPIAGGIA_INTUR_SNAPSHOT' in s)"`
Expected: `True` (e nessun errore d'invariante `loop_targets==[] ⇔ RAW_ONLY` — qui loop_targets non vuoto + MANUAL = OK).

> Se la funzione di load ha un nome diverso, usare quella esistente in `core/lineage/source_resolver.py` per istanziare il resolver senza errori.

- [ ] **Step 3: Intake + promote sul file reale**

Run: `hotelops intake "/Users/stefanodellapietra/Downloads/INTUR_REGISTRO CORRISPETTIVI SPIAGGIA_2026.xlsx" --source-name INTUR_CORRISPETTIVI_SPIAGGIA_INTUR_SNAPSHOT`
Expected: stampa un `raw_object_id` (stato RAW_INGESTED), file su `gs://hotelops-raw/...`.
Run: `hotelops promote --raw-object-id <id>`
Expected: parser gira, `OK corrispettivi → … : ~11 righe (full-replace anno)`.

- [ ] **Step 4: Verifica BQ (output-based)**

Run:
```bash
bq query --use_legacy_sql=false 'SELECT data, corrispettivo_spiaggia, corrispettivo_bar, corrispettivo_totale FROM `hotelops-suite.hotelops.f_spiaggia_corrispettivi` ORDER BY data'
```
Expected: giugno 2026, 16/06 = 561 / 517,5 / 1.078,5; ogni riga `raw_object_id` non null; `Σ corrispettivo_totale` MTD ≈ 25.707.

- [ ] **Step 5: Commit**

```bash
git add core/source_registry.yaml
git commit -m "feat(spiaggia): source registry corrispettivi INTUR (lineage intake/promote)"
```

---

### Task 6: Vista `v_spiaggia_giornaliero` (registro INTUR + alloggiati PMS ORTI)

**Files:**
- Create: `core/bq/views/v_spiaggia_giornaliero.sql`

**Interfaces:**
- Consumes: `f_spiaggia_corrispettivi` (Task 4-5), `f_produzione_pms` (esistente).
- Produces: vista `v_spiaggia_giornaliero` (grain = data).

- [ ] **Step 1: Scrivere la vista**

Create `core/bq/views/v_spiaggia_giornaliero.sql`:

```sql
-- v_spiaggia_giornaliero
-- Ricavo totale stabilimento per giorno: corrispettivi diretti INTUR (registro)
-- + alloggiati ORTI (PMS 04BEALL/10BEBAR). Additivo, cross-società.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_giornaliero` AS
WITH alloggiati AS (
  SELECT
    data,
    SUM(IF(classe = '04BEALL', importo_imponibile, 0)) AS alloggiati_spiaggia,
    SUM(IF(classe = '10BEBAR', importo_imponibile, 0)) AS alloggiati_bar
  FROM `hotelops-suite.hotelops.f_produzione_pms`
  WHERE classe IN ('04BEALL', '10BEBAR')
  GROUP BY data
)
SELECT
  c.data,
  c.anno,
  c.mese,
  -- diretti INTUR
  c.corrispettivo_spiaggia                              AS spiaggia_intur,
  c.corrispettivo_bar                                  AS bar_intur,
  -- alloggiati ORTI (PMS)
  COALESCE(a.alloggiati_spiaggia, 0)                   AS spiaggia_orti,
  COALESCE(a.alloggiati_bar, 0)                        AS bar_orti,
  -- totali
  c.corrispettivo_spiaggia + COALESCE(a.alloggiati_spiaggia, 0) AS spiaggia_totale,
  c.corrispettivo_bar + COALESCE(a.alloggiati_bar, 0)          AS bar_totale,
  c.corrispettivo_totale
    + COALESCE(a.alloggiati_spiaggia, 0)
    + COALESCE(a.alloggiati_bar, 0)                    AS stabilimento_totale,
  -- flag qualità
  a.data IS NULL                                       AS flag_manca_pms
FROM `hotelops-suite.hotelops.f_spiaggia_corrispettivi` c
LEFT JOIN alloggiati a USING (data)
```

- [ ] **Step 2: Deploy della vista**

Run: `hotelops deploy-views --dry-run`
Expected: `v_spiaggia_giornaliero` compare nell'ordine di deploy.
Run: `hotelops deploy-views`
Expected: deploy OK, nessun errore.

- [ ] **Step 3: Validazione su set 2025 (dati con entrambe le gambe)**

> Pre-requisito: aver promosso anche il registro **2025** (stesso parser, file 2025) così la vista ha giorni con corrispettivi+PMS. In assenza, validare sul 2026 (PMS mancante → `flag_manca_pms=TRUE`, gamba alloggiati 0).

Run:
```bash
bq query --use_legacy_sql=false 'SELECT data, spiaggia_intur, spiaggia_orti, bar_intur, stabilimento_totale FROM `hotelops-suite.hotelops.v_spiaggia_giornaliero` WHERE data BETWEEN "2025-09-26" AND "2025-09-29" ORDER BY data'
```
Expected (se 2025 promosso): 28/09 → spiaggia_intur 285, spiaggia_orti 186,4, bar_intur 705,5, stabilimento_totale ≈ 1.176,9.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_spiaggia_giornaliero.sql
git commit -m "feat(spiaggia): vista v_spiaggia_giornaliero (corrispettivi INTUR + alloggiati PMS ORTI)"
```

---

### Task 7: Tab "Giornaliero" nell'app Streamlit

**Files:**
- Modify: `verticals/spiaggia/app.py` (aggiungere caricamento vista + sezione)

**Interfaces:**
- Consumes: vista `v_spiaggia_giornaliero` (Task 6).

- [ ] **Step 1: Aggiungere il loader cached**

In `verticals/spiaggia/app.py`, accanto agli altri `@st.cache_data` loader:

```python
@st.cache_data(ttl=300)
def load_giornaliero() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_giornaliero` ORDER BY data")
```

- [ ] **Step 2: Aggiungere la sezione nel render()**

Dentro `render()`, dopo la sezione "Andamenti":

```python
    st.header("Ricavo giornaliero (corrispettivi + alloggiati)")
    g = load_giornaliero()
    if not g.empty:
        if anno_sel is not None and "anno" in g:
            g = g[g["anno"] == anno_sel]
        st.dataframe(
            g[[
                "data", "spiaggia_intur", "spiaggia_orti", "bar_intur",
                "bar_orti", "spiaggia_totale", "bar_totale", "stabilimento_totale",
                "flag_manca_pms",
            ]],
            use_container_width=True,
            height=400,
        )
        st.bar_chart(g.set_index("data")[["spiaggia_totale", "bar_totale"]])
```

- [ ] **Step 3: Smoke dell'app**

Run: `streamlit run verticals/spiaggia/app.py`
Expected: l'app parte, la sezione "Ricavo giornaliero" mostra la tabella + il bar chart spiaggia/bar.

- [ ] **Step 4: Commit**

```bash
git add verticals/spiaggia/app.py
git commit -m "feat(spiaggia): tab ricavo giornaliero nell'app (v_spiaggia_giornaliero)"
```

---

## Note finali

- **CLAUDE.md / manifest:** dopo il merge, eseguire `save game` per registrare `f_spiaggia_corrispettivi` + `v_spiaggia_giornaliero` nella doc e `hotelops manifest`.
- **Fase-next (fuori da questo piano):** parser Moolty (`f_spiaggia_fb_ordini`) + colonna riconciliazione bar `scost_bar = corrispettivo_bar − Σ Moolty` nella vista; Spiagge.it come mix-canale online; backfill registro 2024/2025; riconciliazione alloggiati registro↔PMS; bridge → `cash_control`.
