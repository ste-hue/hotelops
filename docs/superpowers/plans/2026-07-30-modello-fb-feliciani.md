# Modello F&B per Feliciani — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Excel-modello a 8 fogli per il consulente F&B (Cruscotto con target, Breakfast, Coperti completi, Consumi, Menu engineering) su viste BQ nuove + canonical `f_menu_engineering`.

**Architecture:** Due viste BQ additive (`v_fb_coperti_giornaliero`, `v_fb_modello_mensile`) + promozione della source menu engineering (parser → `f_menu_engineering`, pattern OTB `snapshot_date` da intake) + estensione del generatore `verticals/fb/genera_report_feliciani.py` da 4 a 8 fogli.

**Tech Stack:** Python 3.11+, BigQuery (client `google.cloud.bigquery`), openpyxl, pandas, Pydantic (`core/schemas.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-30-modello-fb-feliciani-design.md`

## Global Constraints

- Decisione (a): DIPENDENTI/COURTESY/PM **fuori** dal denominatore ricavo-e-margine/coperto; visibili come costo (outlet MENSA_STAFF, leakage courtesy).
- Decisione (b): margini/food-cost su base **netto** (`f_vendite_fb`, `f_consumi_economato`, `f_ricavi_fb`); lordo POS solo per scontrino cassa/giornaliero.
- Ogni write BQ passa da `bq_write_validated` (I1/I9); parser accetta `--societa` + `--raw-object-id` (contratto promote).
- Esclusioni consumi UoM-rotti (verbatim da `v_fb_kpi`): `'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009','BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001'`.
- Codici ricavo breakfast (verbatim da `v_fb_kpi`): `'SCBKFBB','BRKADULT','BRKBABY','BRKEXT','BRKEXTC'`.
- Vista = file in `core/bq/views/`, deploy con `hotelops deploy-views`. Commit atomici per task, staging per nome (working tree ha dirty di altre sessioni).

---

### Task 1: Canonical `f_menu_engineering` (config + schema + DDL)

**Files:**
- Modify: `core/config.py` (blocco costanti `F_*`, vicino a `F_RISTOCUBE_ORDERS = _t("f_ristocube_orders")`)
- Modify: `core/schemas.py` (nuova classe accanto a `RistocubeOrderRow`, riga ~1152)
- Create: `core/bq/load/create_menu_engineering_table.py`
- Test: `tests/test_ingest_menu_engineering.py` (nuovo — validazione Pydantic)

**Interfaces:**
- Produces: `core.config.F_MENU_ENGINEERING` (str table id); `core.schemas.MenuEngineeringRow` (Pydantic, campi sotto); tabella BQ `hotelops-suite.hotelops.f_menu_engineering`.

- [ ] **Step 1: Costante in config**

In `core/config.py`, dopo `F_RISTOCUBE_ORDERS`:

```python
F_MENU_ENGINEERING          = _t("f_menu_engineering")
```

- [ ] **Step 2: Test Pydantic fallisce**

`tests/test_ingest_menu_engineering.py`:

```python
"""Test parser menu engineering (RistoCube Engineering F&B Data.xlsx)."""
from datetime import date, datetime, timezone

from core.schemas import MenuEngineeringRow


def _row_base() -> dict:
    return {
        "hash_riga": "abc123",
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "snapshot_date": date(2026, 7, 30),
        "sala": "BAR",
        "piatto": "SO000006",
        "descrizione": "COCA COLA ZERO CL.33",
        "tipo": "SOFT DRINK",
        "m_class": None,
        "prezzo_unitario": 4.55,
        "costo_unitario": 0.8088,
        "quantita": 561.0,
        "incidenza_pct": 0.0827,
        "costo_totale": 453.74,
        "listino": 2552.55,
        "vendita": 2528.62,
        "importo_addebitato": 1091.59,
        "importo_fatturato": 954.98,
        "file_sorgente": "Engineering F&B Data.xlsx",
        "raw_object_id": "98f431e0-f9e9-477d-948f-42345be90865",
        "data_caricamento": datetime.now(timezone.utc),
    }


def test_menu_engineering_row_valida():
    r = MenuEngineeringRow(**_row_base())
    assert r.piatto == "SO000006"
    assert r.snapshot_date == date(2026, 7, 30)
```

Run: `pytest tests/test_ingest_menu_engineering.py -v` → Expected: FAIL `ImportError: cannot import name 'MenuEngineeringRow'`

- [ ] **Step 3: Schema Pydantic**

In `core/schemas.py`, dopo `RistocubeOrderRow`:

```python
class MenuEngineeringRow(BaseModel):
    """Schema for f_menu_engineering — menu engineering RistoCube per piatto.

    Source: "Engineering F&B Data.xlsx" — CUMULATO sul periodo del filtro
    Power BI, senza data nel contenuto: `snapshot_date` fa fede dall'intake
    (pattern OTB). Le foto si accumulano; l'ultima foto si seleziona con
    MAX(snapshot_date). Unica fonte col costo unitario per piatto.
    """

    hash_riga: str
    societa_id: SocietaId
    business_unit_id: str
    snapshot_date: date
    sala: str
    piatto: str
    descrizione: Optional[str] = None
    tipo: Optional[str] = None
    m_class: Optional[str] = None
    prezzo_unitario: Optional[float] = None
    costo_unitario: Optional[float] = None
    quantita: Optional[float] = None
    incidenza_pct: Optional[float] = None
    costo_totale: Optional[float] = None
    listino: Optional[float] = None
    vendita: Optional[float] = None
    importo_addebitato: Optional[float] = None
    importo_fatturato: Optional[float] = None
    file_sorgente: str
    raw_object_id: Optional[str] = None
    data_caricamento: datetime
```

Run: `pytest tests/test_ingest_menu_engineering.py -v` → Expected: PASS

- [ ] **Step 4: Script DDL (pattern `create_pec_tables.py`)**

`core/bq/load/create_menu_engineering_table.py`:

```python
#!/usr/bin/env python3
"""DDL idempotente per f_menu_engineering (pre-crea PRIMA del primo promote —
lezione chicken-egg PEC: filter_new_rows_by_hash esplode su tabella inesistente).

Usage:
    python -m core.bq.load.create_menu_engineering_table [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import F_MENU_ENGINEERING

DDL = f"""
CREATE TABLE IF NOT EXISTS `{F_MENU_ENGINEERING}` (
    hash_riga            STRING NOT NULL,
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    snapshot_date        DATE NOT NULL,
    sala                 STRING NOT NULL,
    piatto               STRING NOT NULL,
    descrizione          STRING,
    tipo                 STRING,
    m_class              STRING,
    prezzo_unitario      FLOAT64,
    costo_unitario       FLOAT64,
    quantita             FLOAT64,
    incidenza_pct        FLOAT64,
    costo_totale         FLOAT64,
    listino              FLOAT64,
    vendita              FLOAT64,
    importo_addebitato   FLOAT64,
    importo_fatturato    FLOAT64,
    file_sorgente        STRING NOT NULL,
    raw_object_id        STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

log = logging.getLogger("create_menu_engineering_table")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.dry_run:
        log.info("[DRY-RUN]\n%s", DDL)
        return 0
    get_client().query(DDL).result()
    log.info("OK %s", F_MENU_ENGINEERING)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Esegui DDL e verifica**

Run: `python -m core.bq.load.create_menu_engineering_table`
Verifica: `python -c "from google.cloud import bigquery; c=bigquery.Client(project='hotelops-suite'); print([f.name for f in c.get_table('hotelops-suite.hotelops.f_menu_engineering').schema])"` → 21 colonne.

- [ ] **Step 6: Commit**

```bash
git add core/config.py core/schemas.py core/bq/load/create_menu_engineering_table.py tests/test_ingest_menu_engineering.py
git commit -m "feat(fb): canonical f_menu_engineering (schema+DDL) per modello Feliciani"
```

---

### Task 2: Parser `ingest_menu_engineering` + flip registry + promote

**Files:**
- Create: `ingest/flussi/ingest_menu_engineering.py`
- Modify: `core/source_registry.yaml` (entry `POWERBI_MENUENGINEERING_ORTI_SNAPSHOT`: `loop_targets: [fb_model]`, `promotion_policy: AUTO`, rimuovi i commenti "nome TARGET")
- Test: `tests/test_ingest_menu_engineering.py` (estendi)

**Interfaces:**
- Consumes: `MenuEngineeringRow`, `F_MENU_ENGINEERING` (Task 1).
- Produces: `parse_xlsx(path: Path, snapshot_date: date, raw_object_id: str | None) -> list[dict]`; CLI `python -m ingest.flussi.ingest_menu_engineering --file X [--societa ORTI] [--raw-object-id Y] [--dry-run]`; righe in `f_menu_engineering`.

Layout file (sheet unico, header riga 0):
`M | Tipo | Sala | Piatto | Descrizione Piatto | Prz. Unit. | Costo Unit. | Qtà | %Inc. | Costo | Listino | Vendita | Importo Add. | Importo Fatt.`
Righe da SCARTARE: `Sala == 'Total'` o `Piatto` vuoto (subtotali/Total/footer "Applied filters"). Righe coperto (`Piatto` che inizia con `COP`) si TENGONO (`tipo` vuoto → None).

- [ ] **Step 1: Test parser fallisce**

Aggiungi a `tests/test_ingest_menu_engineering.py`:

```python
from pathlib import Path

from openpyxl import Workbook

from ingest.flussi.ingest_menu_engineering import parse_xlsx

HEADER = ["M", "Tipo", "Sala", "Piatto", "Descrizione Piatto", "Prz. Unit.",
          "Costo Unit.", "Qtà", "%Inc.", "Costo", "Listino", "Vendita",
          "Importo Add.", "Importo Fatt."]


def _fixture_xlsx(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(HEADER)
    ws.append(["", "", "BAR", "COPBAR", "COPERTO BAR", 0, 0, 11285, 0.67, 0, 0, 0, 0, 0])
    ws.append(["", "", "Total", None, None, 0, 0, 16782, 1, 0, 0, 0, 0, 0])
    ws.append(["", "SOFT DRINK", "BAR", "SO000006", "COCA COLA ZERO CL.33",
               4.55, 0.8088, 561, 0.0827, 453.74, 2552.55, 2528.62, 1091.59, 954.98])
    ws.append(["Total", None, None, None, None, 0, 0, 44879, None, None, None, None, None, None])
    ws.append(["Applied filters:\nSala is BAR,", None, None, None, None, None, None, None, None, None, None, None, None, None])
    p = tmp_path / "Engineering F&B Data.xlsx"
    wb.save(p)
    return p


def test_parse_scarta_totali_e_footer(tmp_path):
    from datetime import date
    rows = parse_xlsx(_fixture_xlsx(tmp_path), snapshot_date=date(2026, 7, 30),
                      raw_object_id="rid-1")
    assert len(rows) == 2  # COPBAR + SO000006; Total/footer scartati
    so = next(r for r in rows if r["piatto"] == "SO000006")
    assert so["tipo"] == "SOFT DRINK"
    assert so["costo_unitario"] == 0.8088
    assert so["snapshot_date"] == date(2026, 7, 30)
    cop = next(r for r in rows if r["piatto"] == "COPBAR")
    assert cop["tipo"] is None


def test_hash_include_snapshot_date(tmp_path):
    from datetime import date
    r1 = parse_xlsx(_fixture_xlsx(tmp_path), snapshot_date=date(2026, 7, 30), raw_object_id=None)
    r2 = parse_xlsx(_fixture_xlsx(tmp_path), snapshot_date=date(2026, 8, 15), raw_object_id=None)
    assert r1[0]["hash_riga"] != r2[0]["hash_riga"]  # foto diverse si accumulano
```

Run: `pytest tests/test_ingest_menu_engineering.py -v` → FAIL `ModuleNotFoundError`

- [ ] **Step 2: Parser**

`ingest/flussi/ingest_menu_engineering.py`:

```python
#!/usr/bin/env python3
"""Ingest menu engineering RistoCube → f_menu_engineering.

Una riga per (snapshot_date × sala × piatto). Il file è un CUMULATO senza data
nel contenuto: snapshot_date fa fede dall'intake del raw object (pattern OTB,
cfr. ingest_andamento_prenotazioni._snapshot_date_from_raw). Le foto si
accumulano — mai DELETE della foto precedente.

È il parser_module di POWERBI_MENUENGINEERING_ORTI_SNAPSHOT, invocato da
`hotelops promote` come:
    python -m ingest.flussi.ingest_menu_engineering --file X --societa ORTI --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_menu_engineering --file <xlsx> --dry-run
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from core.config import F_MENU_ENGINEERING
from core.schemas import MenuEngineeringRow, make_hash, validate_batch

log = logging.getLogger("ingest.menu_engineering")

SOCIETA_ID = "ORTI"
BUSINESS_UNIT_ID = "HOTEL"


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def parse_xlsx(path: Path, snapshot_date: date, raw_object_id: str | None) -> list[dict]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for r in rows[1:]:
        if not r or len(r) < 14:
            continue
        sala, piatto = _s(r[2]), _s(r[3])
        if piatto is None or sala in (None, "Total"):
            continue  # subtotali, riga Total finale, footer "Applied filters"
        out.append({
            "hash_riga": make_hash(str(snapshot_date), sala, piatto),
            "societa_id": SOCIETA_ID,
            "business_unit_id": BUSINESS_UNIT_ID,
            "snapshot_date": snapshot_date,
            "sala": sala,
            "piatto": piatto,
            "descrizione": _s(r[4]),
            "tipo": _s(r[1]),
            "m_class": _s(r[0]),
            "prezzo_unitario": _f(r[5]),
            "costo_unitario": _f(r[6]),
            "quantita": _f(r[7]),
            "incidenza_pct": _f(r[8]),
            "costo_totale": _f(r[9]),
            "listino": _f(r[10]),
            "vendita": _f(r[11]),
            "importo_addebitato": _f(r[12]),
            "importo_fatturato": _f(r[13]),
            "file_sorgente": path.name,
            "raw_object_id": raw_object_id,
            "data_caricamento": now,
        })
    return out


def _snapshot_date_from_raw(raw_object_id: str) -> date:
    """La data della foto non è nel file: fa fede l'intake del raw object."""
    from google.cloud import bigquery

    from core.bq.client import get_client
    from core.config import PROJECT

    client = get_client()
    sql = (
        f"SELECT DATE(intake_at) d FROM `{PROJECT}.hotelops.f_raw_objects` "
        "WHERE raw_object_id = @rid"
    )
    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("rid", "STRING", raw_object_id)]))
    rows = list(job.result())
    if not rows:
        raise SystemExit(f"raw_object_id {raw_object_id} non trovato in f_raw_objects")
    return rows[0][0]


def ingest_file(path: Path, raw_object_id: str | None, dry_run: bool) -> int:
    snapshot_date = (
        _snapshot_date_from_raw(raw_object_id) if raw_object_id else date.today()
    )
    rows = parse_xlsx(path, snapshot_date=snapshot_date, raw_object_id=raw_object_id)
    validate_batch(rows, MenuEngineeringRow, context=f"menu_engineering {path.name}")
    if dry_run:
        log.info("[DRY-RUN] %s : %d righe (snapshot %s)", path.name, len(rows), snapshot_date)
        return len(rows)

    from core.bq.dedup import filter_new_rows_by_hash
    from core.bq.write import bq_write_validated

    new_rows = filter_new_rows_by_hash(F_MENU_ENGINEERING, rows, "hash_riga")
    if not new_rows:
        log.info("Foto già presente — niente da scrivere (%s)", path.name)
        return 0
    bq_write_validated(F_MENU_ENGINEERING, [MenuEngineeringRow(**r) for r in new_rows], mode="append")
    log.info("OK %s : %d righe (snapshot %s)", path.name, len(new_rows), snapshot_date)
    return len(new_rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest menu engineering → f_menu_engineering")
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--raw-object-id", default=None)
    ap.add_argument("--societa", default=None, help="Accettato da promote — sempre ORTI")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.societa and args.societa != SOCIETA_ID:
        raise SystemExit(f"societa {args.societa} != {SOCIETA_ID}: file menu engineering è ORTI")

    from core.pipeline_run import PipelineRun

    with PipelineRun("ingest_menu_engineering", societa_id=SOCIETA_ID,
                     file_sorgente=args.file.name):
        n = ingest_file(args.file, args.raw_object_id, args.dry_run)
        log.info("Totale: %d righe", n)


if __name__ == "__main__":
    main()
```

Run: `pytest tests/test_ingest_menu_engineering.py -v` → PASS

- [ ] **Step 3: Dry-run sul file vero**

Run: `python -m ingest.flussi.ingest_menu_engineering --file "/Users/stefanodellapietra/Downloads/Engineering F&B Data.xlsx" --dry-run`
Expected: ~780-806 righe (808 righe file − header − Total/subtotali/footer), nessuna eccezione Pydantic.

- [ ] **Step 4: Flip registry**

In `core/source_registry.yaml`, entry `POWERBI_MENUENGINEERING_ORTI_SNAPSHOT`:
- `loop_targets: []` → `loop_targets: [fb_model]`
- `promotion_policy: RAW_ONLY` → `promotion_policy: AUTO`
- Nei commenti: rimuovi `# nome TARGET — parser non scritto` (ora esistono); aggiorna la nota: sostituisci la frase "Se promosso in futuro: snapshot_date da intake_at (pattern OTB), mai dal contenuto." con "Promosso 2026-07-30 (consumer: modello F&B Feliciani): snapshot_date da intake_at (pattern OTB), foto accumulate, hash su (snapshot_date, sala, piatto)."

- [ ] **Step 5: Promote del raw object già intakato + verifica**

Due foto intakate il 2026-07-30: `98f431e0…` (Engineering F&B Data.xlsx, periodo corto) e
`e82f7176…` (Data from Power BI (3).xlsx, periodo pieno — 834 righe, qty 60.338). L'hash è
`(snapshot_date, sala, piatto)` → una sola foto per giorno: si promuove la **più completa**,
la prima resta CLASSIFIED (superseded, pattern re-export bilancini aprile).

```bash
hotelops promote --raw-object-id e82f7176-dca9-4e2c-b644-7b04834fd87d
```

Verifica (output-based):

```bash
python -c "
from google.cloud import bigquery
c = bigquery.Client(project='hotelops-suite')
for r in c.query('''SELECT COUNT(*) tot, COUNTIF(raw_object_id IS NOT NULL) fk,
  COUNT(DISTINCT sala) sale, MIN(snapshot_date) snap
  FROM \`hotelops-suite.hotelops.f_menu_engineering\`''').result(): print(dict(r))
for r in c.query('''SELECT current_status FROM \`hotelops-suite.hotelops.v_raw_objects_current\`
  WHERE raw_object_id='e82f7176-dca9-4e2c-b644-7b04834fd87d' ''').result(): print(dict(r))"
```

Expected: tot ≈ dry-run count, fk == tot, snap == 2026-07-30, status PROMOTED.

- [ ] **Step 6: Commit**

```bash
git add ingest/flussi/ingest_menu_engineering.py core/source_registry.yaml tests/test_ingest_menu_engineering.py
git commit -m "feat(ingest): parser menu_engineering + flip AUTO (loop fb_model), prima foto promossa"
```

---

### Task 3: Vista `v_fb_coperti_giornaliero`

**Files:**
- Create: `core/bq/views/v_fb_coperti_giornaliero.sql`

**Interfaces:**
- Consumes: `f_coperti_giornalieri` (colonne: `data_servizio, tipo_pasto ∈ {BRK,LUNCH,DINNER}, tipo_ospite ∈ {HOTEL,RESIDENCE,CVM,ESTERNI,DIPENDENTI,COURTESY,PM}, business_unit_id, n_coperti`).
- Produces: vista `v_fb_coperti_giornaliero` — grana `data × tipo_pasto`, colonne: `hotel, residence, cvm, esterni, paganti, dipendenti, courtesy_pm, non_paganti, totale`.

- [ ] **Step 1: SQL**

```sql
-- v_fb_coperti_giornaliero
-- Coperti giornalieri per pasto con split PAGANTI / NON PAGANTI.
-- Decisione 2026-07-30 (spec modello-fb-feliciani): DIPENDENTI, COURTESY e PM
-- sono fuori dal denominatore di ogni metrica per-coperto a valle; qui restano
-- visibili come colonne dedicate. Fonte: f_coperti_giornalieri (Hoxell, daily).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_coperti_giornaliero` AS
SELECT
  data_servizio,
  tipo_pasto,
  SUM(IF(tipo_ospite = 'HOTEL', n_coperti, 0)) AS hotel,
  SUM(IF(tipo_ospite = 'RESIDENCE', n_coperti, 0)) AS residence,
  SUM(IF(tipo_ospite = 'CVM', n_coperti, 0)) AS cvm,
  SUM(IF(tipo_ospite = 'ESTERNI', n_coperti, 0)) AS esterni,
  SUM(IF(tipo_ospite NOT IN ('DIPENDENTI', 'COURTESY', 'PM'), n_coperti, 0)) AS paganti,
  SUM(IF(tipo_ospite = 'DIPENDENTI', n_coperti, 0)) AS dipendenti,
  SUM(IF(tipo_ospite IN ('COURTESY', 'PM'), n_coperti, 0)) AS courtesy_pm,
  SUM(IF(tipo_ospite IN ('DIPENDENTI', 'COURTESY', 'PM'), n_coperti, 0)) AS non_paganti,
  SUM(n_coperti) AS totale
FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
GROUP BY 1, 2
```

- [ ] **Step 2: Deploy + quadratura**

Run: `hotelops deploy-views` → 37 views.
Quadratura: somma `totale` della vista == `SUM(n_coperti)` della base, e `paganti + non_paganti == totale` su 10 giorni campione:

```bash
python -c "
from google.cloud import bigquery
c = bigquery.Client(project='hotelops-suite')
for r in c.query('''
SELECT (SELECT SUM(totale) FROM \`hotelops-suite.hotelops.v_fb_coperti_giornaliero\`) v,
       (SELECT SUM(n_coperti) FROM \`hotelops-suite.hotelops.f_coperti_giornalieri\`) b''').result(): print(dict(r))
for r in c.query('''SELECT COUNTIF(paganti + non_paganti != totale) errori
  FROM \`hotelops-suite.hotelops.v_fb_coperti_giornaliero\`''').result(): print(dict(r))"
```

Expected: v == b, errori == 0.

- [ ] **Step 3: Commit**

```bash
git add core/bq/views/v_fb_coperti_giornaliero.sql
git commit -m "feat(bq): v_fb_coperti_giornaliero (split paganti/non paganti per pasto)"
```

---

### Task 4: Vista `v_fb_modello_mensile`

**Files:**
- Create: `core/bq/views/v_fb_modello_mensile.sql`

**Interfaces:**
- Consumes: `f_coperti_giornalieri`, `f_consumi_economato` (reparto_id, codice_prodotto, importo, anno, mese), `f_ricavi_fb` (codice, netto, anno, mese, business_unit_id).
- Produces: vista `v_fb_modello_mensile` — grana `anno × mese × outlet` con outlet ∈ {BREAKFAST, RISTORANTE, BAR, MENSA_STAFF}; colonne: `anno, mese, periodo (DATE), outlet, coperti_paganti, coperti_non_paganti, ricavo_netto, costo_netto, margine, food_cost_pct, ricavo_per_coperto, costo_per_coperto, margine_per_coperto, has_costi (BOOL), has_ricavi (BOOL)`.

Mappature (Global Constraints per esclusioni UoM e codici breakfast):
- BREAKFAST: coperti = tipo_pasto BRK (paganti); ricavo = codici breakfast `f_ricavi_fb`; costo = reparto BRK.
- RISTORANTE: coperti = LUNCH+DINNER paganti; ricavo = codici food `v_fb_kpi` (`'RISLFOOD','RISDFOOD','DINFOOD','RISBFOOD','RISTLUNC','RISTDINN','ROOMSERV','BAN','BANB','BRUNCH','PASQAD','FERRAD','FERRBA','PARTY'`); costo = reparto CUCINA.
- BAR: coperti = NULL (il POS li ha, il PMS no — per-coperto bar resta sul giornaliero); ricavo = codici beverage (`'BAR','BARHOTEL','RISLBEVE','RISLBEV','RISDBEV','DINBEV','LUNBAR','PROSECCO','APERIDIN'`); costo = reparto CANTINA.
- MENSA_STAFF: coperti_non_paganti = DIPENDENTI (LUNCH+DINNER); ricavo = 0; costo = NULL (non separabile da CUCINA — dichiararlo in Definizioni).

- [ ] **Step 1: SQL**

```sql
-- v_fb_modello_mensile
-- Il P&L mensile per outlet del modello F&B (spec 2026-07-30-modello-fb-feliciani).
-- Base NETTO ovunque (decisione b). Denominatore = soli coperti PAGANTI (decisione a).
-- has_costi/has_ricavi = gating: un mese senza costi NON deve mostrare margini falsi.
-- BAR: coperti NULL (il PMS non li ha; il per-coperto bar vive sul giornaliero POS).
-- MENSA_STAFF: costo NULL (i pasti staff escono da CUCINA, non separabili).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_modello_mensile` AS
WITH esclusi AS (
  SELECT codice FROM UNNEST([
    'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009',
    'BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001'
  ]) AS codice
),
costi AS (
  SELECT
    anno, mese,
    CASE reparto_id WHEN 'BRK' THEN 'BREAKFAST'
                    WHEN 'CUCINA' THEN 'RISTORANTE'
                    WHEN 'CANTINA' THEN 'BAR' END AS outlet,
    SUM(importo) AS costo_netto
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('BRK', 'CUCINA', 'CANTINA')
    AND codice_prodotto NOT IN (SELECT codice FROM esclusi)
  GROUP BY 1, 2, 3
),
coperti AS (
  SELECT
    EXTRACT(YEAR FROM data_servizio) AS anno,
    EXTRACT(MONTH FROM data_servizio) AS mese,
    CASE WHEN tipo_pasto = 'BRK' THEN 'BREAKFAST' ELSE 'RISTORANTE' END AS outlet,
    SUM(IF(tipo_ospite NOT IN ('DIPENDENTI','COURTESY','PM'), n_coperti, 0)) AS coperti_paganti,
    SUM(IF(tipo_ospite IN ('COURTESY','PM'), n_coperti, 0)) AS coperti_non_paganti
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  GROUP BY 1, 2, 3
),
mensa AS (
  SELECT
    EXTRACT(YEAR FROM data_servizio) AS anno,
    EXTRACT(MONTH FROM data_servizio) AS mese,
    'MENSA_STAFF' AS outlet,
    0 AS coperti_paganti,
    SUM(n_coperti) AS coperti_non_paganti
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE tipo_ospite = 'DIPENDENTI'
  GROUP BY 1, 2, 3
),
ricavi AS (
  SELECT
    anno, mese,
    CASE
      WHEN codice IN ('SCBKFBB','BRKADULT','BRKBABY','BRKEXT','BRKEXTC') THEN 'BREAKFAST'
      WHEN codice IN ('RISLFOOD','RISDFOOD','DINFOOD','RISBFOOD','RISTLUNC','RISTDINN',
                      'ROOMSERV','BAN','BANB','BRUNCH','PASQAD','FERRAD','FERRBA','PARTY')
        THEN 'RISTORANTE'
      WHEN codice IN ('BAR','BARHOTEL','RISLBEVE','RISLBEV','RISDBEV','DINBEV',
                      'LUNBAR','PROSECCO','APERIDIN') THEN 'BAR'
    END AS outlet,
    SUM(netto) AS ricavo_netto
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  WHERE business_unit_id = 'HOTEL'
  GROUP BY 1, 2, 3
  HAVING outlet IS NOT NULL
),
base AS (
  SELECT anno, mese, outlet FROM costi
  UNION DISTINCT SELECT anno, mese, outlet FROM coperti
  UNION DISTINCT SELECT anno, mese, outlet FROM mensa
  UNION DISTINCT SELECT anno, mese, outlet FROM ricavi
)
SELECT
  b.anno, b.mese, DATE(b.anno, b.mese, 1) AS periodo, b.outlet,
  COALESCE(cp.coperti_paganti, m.coperti_paganti) AS coperti_paganti,
  COALESCE(cp.coperti_non_paganti, m.coperti_non_paganti) AS coperti_non_paganti,
  r.ricavo_netto,
  co.costo_netto,
  IF(r.ricavo_netto IS NOT NULL AND co.costo_netto IS NOT NULL,
     r.ricavo_netto - co.costo_netto, NULL) AS margine,
  SAFE_DIVIDE(co.costo_netto, r.ricavo_netto) AS food_cost_pct,
  SAFE_DIVIDE(r.ricavo_netto, NULLIF(COALESCE(cp.coperti_paganti, 0), 0)) AS ricavo_per_coperto,
  SAFE_DIVIDE(co.costo_netto, NULLIF(COALESCE(cp.coperti_paganti, 0), 0)) AS costo_per_coperto,
  IF(r.ricavo_netto IS NOT NULL AND co.costo_netto IS NOT NULL,
     SAFE_DIVIDE(r.ricavo_netto - co.costo_netto,
                 NULLIF(COALESCE(cp.coperti_paganti, 0), 0)), NULL) AS margine_per_coperto,
  co.costo_netto IS NOT NULL AS has_costi,
  r.ricavo_netto IS NOT NULL AS has_ricavi
FROM base b
LEFT JOIN costi co USING (anno, mese, outlet)
LEFT JOIN coperti cp USING (anno, mese, outlet)
LEFT JOIN mensa m USING (anno, mese, outlet)
LEFT JOIN ricavi r USING (anno, mese, outlet)
```

- [ ] **Step 2: Deploy + quadratura vs v_fb_kpi**

Run: `hotelops deploy-views` → 38 views.
Quadratura su un mese chiuso (2026-06): `costo_netto` BREAKFAST/RISTORANTE/BAR devono coincidere al centesimo con `costo_breakfast/costo_ristorante/costo_bar` di `v_fb_kpi`, e `ricavo_netto` con `ricavi_breakfast/food/beverage`:

```bash
python -c "
from google.cloud import bigquery
c = bigquery.Client(project='hotelops-suite')
for r in c.query('''
SELECT m.outlet, m.costo_netto, m.ricavo_netto,
       k.costo_breakfast, k.costo_ristorante, k.costo_bar,
       k.ricavi_breakfast, k.ricavi_food, k.ricavi_beverage
FROM \`hotelops-suite.hotelops.v_fb_modello_mensile\` m
JOIN \`hotelops-suite.hotelops.v_fb_kpi\` k USING (anno, mese)
WHERE m.anno=2026 AND m.mese=6 ORDER BY m.outlet''').result(): print(dict(r))"
```

Expected: BREAKFAST.costo_netto == costo_breakfast, RISTORANTE.costo_netto == costo_ristorante, BAR.costo_netto == costo_bar; idem ricavi. Se `f_consumi_economato`/`f_ricavi_fb` non coprono giugno 2026, ripetere su 2025-08 (mese chiuso certo) — has_costi FALSE sui mesi scoperti è il comportamento atteso, non un errore.

- [ ] **Step 3: Commit**

```bash
git add core/bq/views/v_fb_modello_mensile.sql
git commit -m "feat(bq): v_fb_modello_mensile (P&L netto per outlet, gating has_costi)"
```

---

### Task 5: Generatore — foglio "Coperti Completi"

**Files:**
- Modify: `verticals/fb/genera_report_feliciani.py`
- Test: `tests/test_fb_report_feliciani.py` (estendi)

**Interfaces:**
- Consumes: `v_fb_coperti_giornaliero` (Task 3), helper `_write_sheet(ws, headers, rows, formats)` esistente.
- Produces: `query_coperti_completi(client, days) -> pd.DataFrame` (colonne = vista, ordinata per data_servizio, tipo_pasto in ordine BRK<LUNCH<DINNER); `add_sheet_coperti(wb, df) -> None` che crea il foglio "Coperti Completi".

- [ ] **Step 1: Test fallisce**

Aggiungi a `tests/test_fb_report_feliciani.py`:

```python
from openpyxl import Workbook

from verticals.fb.genera_report_feliciani import add_sheet_coperti


def _df_coperti() -> pd.DataFrame:
    return pd.DataFrame([
        {"data_servizio": date(2026, 7, 20), "tipo_pasto": "BRK", "hotel": 120,
         "residence": 8, "cvm": 2, "esterni": 0, "paganti": 130,
         "dipendenti": 0, "courtesy_pm": 3, "non_paganti": 3, "totale": 133},
        {"data_servizio": date(2026, 7, 20), "tipo_pasto": "DINNER", "hotel": 30,
         "residence": 0, "cvm": 0, "esterni": 5, "paganti": 35,
         "dipendenti": 14, "courtesy_pm": 2, "non_paganti": 16, "totale": 51},
    ])


def test_add_sheet_coperti():
    wb = Workbook()
    add_sheet_coperti(wb, _df_coperti())
    ws = wb["Coperti Completi"]
    assert ws.max_row == 3
    header = [ws.cell(1, c).value for c in range(1, 11)]
    assert header == ["Data", "Pasto", "Hotel", "Residence", "CVM", "Esterni",
                      "Paganti", "Dipendenti", "Courtesy/PM", "Totale"]
    assert ws.cell(2, 7).value == 130  # paganti BRK
```

Run: `pytest tests/test_fb_report_feliciani.py::test_add_sheet_coperti -v` → FAIL ImportError

- [ ] **Step 2: Implementazione**

In `genera_report_feliciani.py`:

```python
PASTO_ORDER = {"BRK": 0, "LUNCH": 1, "DINNER": 2}


def query_coperti_completi(client, days: int) -> pd.DataFrame:
    from google.cloud import bigquery

    q = f"""
    SELECT * FROM `{PROJECT}.{DATASET}.v_fb_coperti_giornaliero`
    WHERE data_servizio >= DATE_SUB(
      (SELECT MAX(data_servizio) FROM `{PROJECT}.{DATASET}.v_fb_coperti_giornaliero`),
      INTERVAL @days - 1 DAY)
    """
    job = client.query(q, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", days)]))
    df = pd.DataFrame([dict(r) for r in job.result()])
    if df.empty:
        return df
    df["_ord"] = df["tipo_pasto"].map(PASTO_ORDER).fillna(9)
    return df.sort_values(["data_servizio", "_ord"]).drop(columns="_ord").reset_index(drop=True)


def add_sheet_coperti(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Coperti Completi")
    rows = [
        [r["data_servizio"], r["tipo_pasto"], r["hotel"], r["residence"], r["cvm"],
         r["esterni"], r["paganti"], r["dipendenti"], r["courtesy_pm"], r["totale"]]
        for _, r in df.iterrows()
    ]
    _write_sheet(
        ws,
        ["Data", "Pasto", "Hotel", "Residence", "CVM", "Esterni", "Paganti",
         "Dipendenti", "Courtesy/PM", "Totale"],
        rows,
        dict.fromkeys(range(2, 10), FMT_INT),
    )
```

Run: `pytest tests/test_fb_report_feliciani.py -v` → PASS

- [ ] **Step 3: Commit**

```bash
git add verticals/fb/genera_report_feliciani.py tests/test_fb_report_feliciani.py
git commit -m "feat(fb): foglio Coperti Completi (paganti/non paganti per pasto)"
```

---

### Task 6: Generatore — fogli "Cruscotto", "Breakfast", "Consumi"

**Files:**
- Modify: `verticals/fb/genera_report_feliciani.py`
- Test: `tests/test_fb_report_feliciani.py` (estendi)

**Interfaces:**
- Consumes: `v_fb_modello_mensile` (Task 4), `f_consumi_economato`, `_write_sheet`, `FMT_EURO/FMT_RATIO/FMT_INT/FMT_PCT`.
- Produces: `query_modello_mensile(client, months=13) -> pd.DataFrame`; `query_consumi_reparto(client, months=13) -> pd.DataFrame` (anno, mese, reparto_id, outlet, importo); `add_sheet_cruscotto(wb, df) -> None`; `add_sheet_breakfast(wb, df) -> None`; `add_sheet_consumi(wb, df_reparti, df_modello) -> None`.

Regole (dal Global Constraints + spec):
- Cruscotto: una riga per mese × outlet; le colonne margine/food-cost/€-per-coperto sono **vuote quando `has_costi` è False**, e la riga porta suffisso " (in corso — senza costi)" sul mese se `has_costi` False. Colonne finali `Target €/cop` e `Δ vs Target` LASCIATE VUOTE (formattate) — le compila Feliciani.
- Breakfast: filtro outlet == BREAKFAST; colonne Mese, Coperti, Costo, **Costo/Coperto** (testa), Ricavo esplicito, note gating come sopra.
- Consumi: mese × reparto (i 3 mappati + riga "ALTRI REPARTI" aggregata), € e €/coperto outlet (join df_modello per coperti_paganti).

- [ ] **Step 1: Test fallisce**

```python
from verticals.fb.genera_report_feliciani import add_sheet_cruscotto


def _df_modello() -> pd.DataFrame:
    return pd.DataFrame([
        {"anno": 2026, "mese": 6, "periodo": date(2026, 6, 1), "outlet": "RISTORANTE",
         "coperti_paganti": 1000, "coperti_non_paganti": 200, "ricavo_netto": 40000.0,
         "costo_netto": 12000.0, "margine": 28000.0, "food_cost_pct": 0.30,
         "ricavo_per_coperto": 40.0, "costo_per_coperto": 12.0,
         "margine_per_coperto": 28.0, "has_costi": True, "has_ricavi": True},
        {"anno": 2026, "mese": 7, "periodo": date(2026, 7, 1), "outlet": "RISTORANTE",
         "coperti_paganti": 1100, "coperti_non_paganti": 180, "ricavo_netto": None,
         "costo_netto": None, "margine": None, "food_cost_pct": None,
         "ricavo_per_coperto": None, "costo_per_coperto": None,
         "margine_per_coperto": None, "has_costi": False, "has_ricavi": False},
    ])


def test_cruscotto_gating_mese_senza_costi():
    wb = Workbook()
    add_sheet_cruscotto(wb, _df_modello())
    ws = wb["Cruscotto"]
    assert ws.max_row == 3
    # mese chiuso: margine/cop presente
    assert ws.cell(2, 8).value == 28.0
    # mese senza costi: margine vuoto, mese marcato
    assert ws.cell(3, 8).value is None
    assert "in corso" in str(ws.cell(3, 1).value)
```

Run: `pytest tests/test_fb_report_feliciani.py::test_cruscotto_gating_mese_senza_costi -v` → FAIL

- [ ] **Step 2: Implementazione**

```python
OUTLET_ORDER = {"BREAKFAST": 0, "RISTORANTE": 1, "BAR": 2, "MENSA_STAFF": 3}


def query_modello_mensile(client, months: int = 13) -> pd.DataFrame:
    from google.cloud import bigquery

    q = f"""
    SELECT * FROM `{PROJECT}.{DATASET}.v_fb_modello_mensile`
    WHERE periodo >= DATE_SUB(
      (SELECT MAX(periodo) FROM `{PROJECT}.{DATASET}.v_fb_modello_mensile`),
      INTERVAL @months MONTH)
    ORDER BY periodo, outlet
    """
    job = client.query(q, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("months", "INT64", months)]))
    df = pd.DataFrame([dict(r) for r in job.result()])
    if df.empty:
        return df
    df["_ord"] = df["outlet"].map(OUTLET_ORDER).fillna(9)
    return df.sort_values(["periodo", "_ord"]).drop(columns="_ord").reset_index(drop=True)


def _label_mese(r) -> str:
    label = f"{r['anno']}-{r['mese']:02d}"
    if not r["has_costi"]:
        label += " (in corso — senza costi)"
    return label


def add_sheet_cruscotto(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Cruscotto")
    rows = []
    for _, r in df.iterrows():
        chiuso = bool(r["has_costi"])
        rows.append([
            _label_mese(r), r["outlet"], r["coperti_paganti"], r["coperti_non_paganti"],
            r["ricavo_per_coperto"] if r["has_ricavi"] else None,
            r["costo_per_coperto"] if chiuso else None,
            r["food_cost_pct"] if chiuso else None,
            r["margine_per_coperto"] if chiuso else None,
            None, None,  # Target €/cop, Δ vs Target — compila Feliciani
        ])
    _write_sheet(
        ws,
        ["Mese", "Outlet", "Coperti Paganti", "Coperti Non Paganti", "Ricavo/Cop",
         "Costo/Cop", "Food Cost %", "Margine/Cop", "Target Margine/Cop", "Δ vs Target"],
        rows,
        {2: FMT_INT, 3: FMT_INT, 4: FMT_EURO, 5: FMT_EURO, 6: "0.0%",
         7: FMT_EURO, 8: FMT_EURO, 9: FMT_EURO},
    )


def add_sheet_breakfast(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Breakfast")
    brk = df[df["outlet"] == "BREAKFAST"]
    rows = [
        [_label_mese(r), r["coperti_paganti"],
         r["costo_netto"] if r["has_costi"] else None,
         r["costo_per_coperto"] if r["has_costi"] else None,
         r["ricavo_netto"] if r["has_ricavi"] else None]
        for _, r in brk.iterrows()
    ]
    _write_sheet(
        ws,
        ["Mese", "Coperti", "Costo Economato", "Costo/Coperto",
         "Ricavo Esplicito (il grosso è in tariffa camera)"],
        rows,
        {1: FMT_INT, 2: FMT_EURO, 3: FMT_EURO, 4: FMT_EURO},
    )
    ws.column_dimensions["E"].width = 42


def query_consumi_reparto(client, months: int = 13) -> pd.DataFrame:
    from google.cloud import bigquery

    q = f"""
    SELECT anno, mese,
      IF(reparto_id IN ('BRK','CUCINA','CANTINA'), reparto_id, 'ALTRI') AS reparto,
      CASE reparto_id WHEN 'BRK' THEN 'BREAKFAST' WHEN 'CUCINA' THEN 'RISTORANTE'
                      WHEN 'CANTINA' THEN 'BAR' END AS outlet,
      SUM(importo) AS importo
    FROM `{PROJECT}.{DATASET}.f_consumi_economato`
    WHERE codice_prodotto NOT IN (
      'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009',
      'BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001')
      AND DATE(anno, mese, 1) >= DATE_SUB(
        (SELECT DATE(MAX(anno), MAX(mese), 1) FROM `{PROJECT}.{DATASET}.f_consumi_economato`),
        INTERVAL @months MONTH)
    GROUP BY 1, 2, 3, 4
    ORDER BY 1, 2, 3
    """
    job = client.query(q, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("months", "INT64", months)]))
    return pd.DataFrame([dict(r) for r in job.result()])


def add_sheet_consumi(wb: Workbook, df_reparti: pd.DataFrame, df_modello: pd.DataFrame) -> None:
    ws = wb.create_sheet("Consumi")
    cop = {
        (r["anno"], r["mese"], r["outlet"]): r["coperti_paganti"]
        for _, r in df_modello.iterrows()
    }
    rows = []
    for _, r in df_reparti.iterrows():
        denominatore = cop.get((r["anno"], r["mese"], r["outlet"]))
        rows.append([
            f"{r['anno']}-{r['mese']:02d}", r["reparto"], r["outlet"] or "—",
            r["importo"],
            (r["importo"] / denominatore) if denominatore else None,
        ])
    _write_sheet(
        ws,
        ["Mese", "Reparto", "Outlet", "Consumo €", "€/Coperto Pagante"],
        rows,
        {3: FMT_EURO, 4: FMT_EURO},
    )
```

Run: `pytest tests/test_fb_report_feliciani.py -v` → PASS

- [ ] **Step 3: Commit**

```bash
git add verticals/fb/genera_report_feliciani.py tests/test_fb_report_feliciani.py
git commit -m "feat(fb): fogli Cruscotto (target Feliciani), Breakfast, Consumi con gating mese chiuso"
```

---

### Task 7: Generatore — foglio "Menu Engineering"

**Files:**
- Modify: `verticals/fb/genera_report_feliciani.py`
- Test: `tests/test_fb_report_feliciani.py` (estendi)

**Interfaces:**
- Consumes: `f_menu_engineering` (Task 2), `f_vendite_fb`, `_write_sheet`.
- Produces: `query_menu_engineering(client, days) -> pd.DataFrame` (piatto, descrizione, tipo, sala, costo_unitario, prezzo_medio_netto, qty, margine_unitario, margine_totale); `classifica_quadranti(df) -> pd.DataFrame` (aggiunge colonna `quadrante`); `add_sheet_menu_engineering(wb, df) -> None`.

Regole (spec §5.6 + §8): costi unitari dall'**ultima foto** (`MAX(snapshot_date)`); qty e prezzo medio netto da `f_vendite_fb` sul periodo `--days` (le qty del file cumulate su periodo ignoto NON si usano). Quadranti su mediane: popolarità = qty vs mediana; margine = margine_unitario vs mediana → Star (alta/alto), Cavallo (alta/basso), Enigma (bassa/alto), Cane (bassa/basso). Esclusi piatti COP* e righe senza costo unitario o senza vendite nel periodo.

- [ ] **Step 1: Test quadranti fallisce**

```python
from verticals.fb.genera_report_feliciani import classifica_quadranti


def test_classifica_quadranti_mediane():
    df = pd.DataFrame([
        {"piatto": "A", "qty": 100.0, "margine_unitario": 10.0},
        {"piatto": "B", "qty": 100.0, "margine_unitario": 2.0},
        {"piatto": "C", "qty": 10.0, "margine_unitario": 10.0},
        {"piatto": "D", "qty": 10.0, "margine_unitario": 2.0},
    ])
    out = classifica_quadranti(df)
    q = dict(zip(out["piatto"], out["quadrante"]))
    assert q == {"A": "Star", "B": "Cavallo", "C": "Enigma", "D": "Cane"}
```

Run: `pytest tests/test_fb_report_feliciani.py::test_classifica_quadranti_mediane -v` → FAIL

- [ ] **Step 2: Implementazione**

```python
def query_menu_engineering(client, days: int) -> pd.DataFrame:
    from google.cloud import bigquery

    q = f"""
    WITH ultima_foto AS (
      SELECT sala, piatto, costo_unitario, tipo, descrizione
      FROM `{PROJECT}.{DATASET}.f_menu_engineering`
      WHERE snapshot_date = (SELECT MAX(snapshot_date)
                             FROM `{PROJECT}.{DATASET}.f_menu_engineering`)
        AND costo_unitario IS NOT NULL AND costo_unitario > 0
        AND NOT STARTS_WITH(piatto, 'COP')
    ),
    vendite AS (
      SELECT codice_articolo AS piatto, SUM(quantita) AS qty,
             SAFE_DIVIDE(SUM(importo_netto), SUM(quantita)) AS prezzo_medio_netto
      FROM `{PROJECT}.{DATASET}.f_vendite_fb`
      WHERE data_servizio >= DATE_SUB(
        (SELECT MAX(data_servizio) FROM `{PROJECT}.{DATASET}.f_vendite_fb`),
        INTERVAL @days - 1 DAY)
      GROUP BY 1
      HAVING qty > 0
    )
    SELECT
      f.piatto, ANY_VALUE(f.descrizione) AS descrizione, ANY_VALUE(f.tipo) AS tipo,
      ANY_VALUE(f.costo_unitario) AS costo_unitario,
      v.qty, v.prezzo_medio_netto,
      v.prezzo_medio_netto - ANY_VALUE(f.costo_unitario) AS margine_unitario,
      (v.prezzo_medio_netto - ANY_VALUE(f.costo_unitario)) * v.qty AS margine_totale
    FROM ultima_foto f
    JOIN vendite v USING (piatto)
    GROUP BY f.piatto, v.qty, v.prezzo_medio_netto
    ORDER BY margine_totale DESC
    """
    job = client.query(q, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", days)]))
    return pd.DataFrame([dict(r) for r in job.result()])


def classifica_quadranti(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    med_qty = out["qty"].median()
    med_margine = out["margine_unitario"].median()
    def _q(r):
        alta = r["qty"] >= med_qty
        alto = r["margine_unitario"] >= med_margine
        return {(True, True): "Star", (True, False): "Cavallo",
                (False, True): "Enigma", (False, False): "Cane"}[(alta, alto)]
    out["quadrante"] = out.apply(_q, axis=1)
    return out


def add_sheet_menu_engineering(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Menu Engineering")
    rows = [
        [r["descrizione"] or r["piatto"], r["tipo"], r["qty"], r["prezzo_medio_netto"],
         r["costo_unitario"], r["margine_unitario"], r["margine_totale"], r["quadrante"]]
        for _, r in df.iterrows()
    ]
    _write_sheet(
        ws,
        ["Piatto", "Categoria", "Qty Periodo", "Prezzo Medio Netto", "Costo Unitario",
         "Margine Unitario", "Margine Totale", "Quadrante"],
        rows,
        {2: FMT_INT, 3: FMT_EURO, 4: FMT_EURO, 5: FMT_EURO, 6: FMT_EURO},
    )
    ws.column_dimensions["A"].width = 38
```

Run: `pytest tests/test_fb_report_feliciani.py -v` → PASS

- [ ] **Step 3: Commit**

```bash
git add verticals/fb/genera_report_feliciani.py tests/test_fb_report_feliciani.py
git commit -m "feat(fb): foglio Menu Engineering (quadranti su mediane, costi ultima foto)"
```

---

### Task 8: Assemblaggio 8 fogli + foglio Definizioni + run reale

**Files:**
- Modify: `verticals/fb/genera_report_feliciani.py` (`build_workbook`, `genera_report`, docstring)
- Test: `tests/test_fb_report_feliciani.py` (aggiorna `test_build_workbook_4_sheet_e_valori`)

**Interfaces:**
- Consumes: tutte le `add_sheet_*` e `query_*` dei task precedenti.
- Produces: `build_workbook(df_giorni, df_top, df_trend, df_coperti, df_modello, df_reparti, df_menu) -> Workbook` con ordine fogli: `["Cruscotto", "Giornaliero Servizio", "Coperti Completi", "Breakfast", "Consumi", "Menu Engineering", "Definizioni", "Trend Settimanale"]`. Il vecchio foglio "Top Articoli" è assorbito da Menu Engineering; "Riepilogo Giornaliero"+"Breakdown Categorie" si fondono in "Giornaliero Servizio" (colonne di entrambi, una riga per data × servizio).

- [ ] **Step 1: Aggiorna test workbook**

Sostituisci `test_build_workbook_4_sheet_e_valori` con:

```python
def test_build_workbook_8_fogli():
    df = _df_due_settimane_complete()
    wb = build_workbook(
        df_giorni=df,
        df_trend=build_trend_settimanale(df),
        df_coperti=_df_coperti(),
        df_modello=_df_modello(),
        df_reparti=pd.DataFrame([
            {"anno": 2026, "mese": 6, "reparto": "CUCINA", "outlet": "RISTORANTE",
             "importo": 12000.0}]),
        df_menu=classifica_quadranti(pd.DataFrame([
            {"piatto": "PD.00004", "descrizione": "GNOCCHI", "tipo": "PRIMI PIATTI",
             "qty": 100.0, "prezzo_medio_netto": 14.0, "costo_unitario": 4.0,
             "margine_unitario": 10.0, "margine_totale": 1000.0}])),
    )
    assert wb.sheetnames == [
        "Cruscotto", "Giornaliero Servizio", "Coperti Completi", "Breakfast",
        "Consumi", "Menu Engineering", "Definizioni", "Trend Settimanale",
    ]
```

Run → FAIL (build_workbook ha ancora la vecchia firma)

- [ ] **Step 2: Riscrivi `build_workbook` + foglio Definizioni + `genera_report`**

`build_workbook` nuova firma (kwargs espliciti come nel test). Il foglio "Giornaliero Servizio" = colonne di Riepilogo + Breakdown in un'unica `_write_sheet` (Data, Servizio, Comande, Coperti, Ricavi lordi, Coperto Medio, Articoli, Art/Cop, Bevande/Cop, Food/Cop, Antipasti/Cop, Primi/Cop, Secondi/Cop, Dessert/Cop, Vino/10Cop). Il foglio "Definizioni" è statico:

```python
DEFINIZIONI = [
    ("Base valore", "Cruscotto/Breakfast/Consumi/Menu Engineering = NETTO (imponibile). "
     "Giornaliero Servizio = LORDO IVA (POS cassa). Mai confrontare le due basi."),
    ("Denominatore per-coperto", "Solo coperti PAGANTI (esclusi DIPENDENTI, COURTESY, PM). "
     "La mensa staff è un costo, non un cliente."),
    ("Mese (in corso — senza costi)", "I consumi economato arrivano a mese chiuso: "
     "margine e food cost compaiono solo dopo l'ingest consumi."),
    ("Breakfast", "Il ricavo colazione è quasi tutto DENTRO la tariffa camera: la metrica "
     "di governo è il costo/coperto, non il margine esplicito."),
    ("Bar (mensile)", "Il PMS non conta i coperti bar: il per-coperto bar vive nel foglio "
     "Giornaliero Servizio (fonte POS)."),
    ("Menu Engineering", "Costi unitari dall'ultima foto RistoCube; quantità e prezzi medi "
     "netti dal venduto del periodo del report. Quadranti su mediane."),
    ("Fonti e freschezza", "POS comande e vendite: a export. Coperti: giornalieri (Hoxell). "
     "Consumi e ricavi PMS: mensili."),
]


def add_sheet_definizioni(wb: Workbook) -> None:
    ws = wb.create_sheet("Definizioni")
    _write_sheet(ws, ["Voce", "Definizione"], [list(t) for t in DEFINIZIONI], {})
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 100
```

`genera_report` orchestra: chiama le 6 query (giornaliero, coperti, modello, reparti, menu+quadranti, trend da giornaliero) e `build_workbook`; `--days` resta il periodo del giornaliero/menu (default 30, per Feliciani stagione = 800), `--months 13` per la parte mensile.

Run: `pytest tests/test_fb_report_feliciani.py -v` → PASS (tutti)

- [ ] **Step 3: Suite completa + lint**

Run: `python -m pytest -q` → tutte verdi. `ruff check . && ruff format verticals/fb tests/test_fb_report_feliciani.py`

- [ ] **Step 4: Run reale + validazione output**

```bash
python -m verticals.fb.genera_report_feliciani --output ~/Desktop/modello_fb_feliciani_$(date +%Y%m%d).xlsx --days 800
```

Validazione (output-based, non exit-code):
1. Aprire il workbook con openpyxl: 8 fogli nell'ordine atteso.
2. Cruscotto: un mese chiuso (es. 2026-05 o ultimo con has_costi) ha margine/cop valorizzato; i mesi senza consumi mostrano "(in corso — senza costi)" e celle margine vuote.
3. Breakfast: costo/coperto di un mese chiuso ≈ valore noto da `v_fb_kpi` (costo_breakfast/pax_breakfast) — confronto al centesimo via query.
4. Menu Engineering: nessun COP*, quadranti popolati, top margine_totale plausibile (Star attesi tra gnocchi/spritz).
5. Coperti Completi: spot-check un giorno vs `f_coperti_giornalieri`.

- [ ] **Step 5: Commit finale**

```bash
git add verticals/fb/genera_report_feliciani.py tests/test_fb_report_feliciani.py
git commit -m "feat(fb): modello 8 fogli per Feliciani (cruscotto target, definizioni, assemblaggio)"
```

---

## Self-review (fatto in scrittura)

- **Spec coverage**: §4 promozione menu engineering → T1+T2; §6 viste → T3+T4; fogli 1-8 → T5 (3), T6 (1,4,5), T7 (6), T8 (2,7,8 + assemblaggio); decisioni a/b → Global Constraints + T4/T6; trappole §8 → gating has_costi (T4/T6), qty da vendite non dal file (T7).
- **Tipi coerenti**: `add_sheet_*(wb, df)`, `query_*(client, ...) -> pd.DataFrame`, firme ripetute nei task che le consumano.
- **Non coperto (deliberato, da spec §7)**: persistenza target, valore-board, ricette, alert.
