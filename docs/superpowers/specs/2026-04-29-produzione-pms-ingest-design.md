# Produzione PMS Ingest — Design Spec

**Date:** 2026-04-29
**Owner:** Stefano (CEO mode — exploratory consolidation)
**Status:** Draft → user review → writing-plans

---

## TL;DR

Ingest the HotelCube Power BI **Daily Production Report** xlsx into a new fact table
`f_produzione_pms`. Lifecycle APPEND with MD5 dedup so re-running the same export every
month only adds the new days. Schema minimale, classe lasciata come stringa opaca,
mapping rimandato. Una costante `OPERATIONS_CUTOVER_DATE = 2025-04-01` deriva
deterministicamente `societa_id` da `data_produzione` (INTUR pre-cutover, ORTI post-).

This is a **CEO-driven exploratory ingest** — primary goal is "i miei dati nel mio
data warehouse, ora". Lenti, mapping, dashboard arrivano dopo, quando emerge una
domanda di business concreta.

---

## Source

**Input file:** `~/Downloads/Daily Production Report.xlsx` (and successivi export)
**Source system:** Power BI dashboard collegato a HotelCube PMS
**Format:** xlsx, sheet unico `Export`, 16 colonne
**Cadenza:** mensile o on-demand (decisione utente)
**Storico:** dati dal 2024-01-01

### File structure

```
Sheet: "Export"
Row 0:  ["Classe", None, "", "01ROOM", "02FB", "03PARK", "04BEALL",
         "05BEOL", "06BEABB", "07DIV", "09BEBAN", "10BEBAR",
         "11FITTO", "80AFFITT", "99ACC", "Total"]
Row 1:  ["Data", "Importo", "Importo", "Importo", ..., "Importo"]
Row 2+: [datetime(YYYY,M,D), None, None, importo_eur_per_classe, ..., total]
```

- Cella `[0][0] = "Classe"` è il signature primario.
- Codici classe seguono pattern `^\d{2}[A-Z]+$` (es. `01ROOM`, `04BEALL`, `99ACC`).
- Colonna `Total` è la somma riga — derivata, non si scrive in BQ.
- Le celle `None`/vuote indicano "nessun ricavo per quella classe quel giorno" → si
  scartano (no rows in BQ per quei giorni-classe).

### Cosa NON è questo file

- ❌ Non è `f_accodamenti` (che è scritturale: corrispettivi, caparre, fatture
  HotelCube). `f_produzione_pms` è la **vista gestionale aggregata** prodotta da
  Power BI partendo da HotelCube.
- ❌ Non è `f_pms_statistiche` (che è per-BU con room/occupancy/ADR/RevPAR). La
  produzione è per-classe ricavi, granularità diversa.
- ❌ Non è `f_movimenti_contabili` (Esolver prima nota). I due dataset si
  riconcilieranno in una view futura, non con un join meccanico ora.

---

## Decisione di dominio: cutover INTUR → ORTI

Fino al **2025-03-31** l'attività operativa HotelCube (Hotel + Residence + CVM)
era a carico di **INTUR**. ORTI faceva solo supermercato pagando 21k€/mese di fitto a
INTUR. Il **2025-04-01** è avvenuto lo switch: ORTI ha rilevato l'operativa, INTUR è
rimasta proprietaria delle mura e del Lido.

Conseguenza: le righe del Daily Production Report del 2024 e del Q1 2025 vanno
attribuite a **INTUR**. Quelle dal 2025-04-01 in poi a **ORTI**.

```python
# core/schemas.py
from datetime import date

OPERATIONS_CUTOVER_DATE = date(2025, 4, 1)
"""Switch operativo HotelCube INTUR → ORTI.

Pre: INTUR gestiva Hotel + Residence + CVM. ORTI faceva solo supermercato.
Post: ORTI gestisce le operations. INTUR resta proprietaria + gestisce Lido.

Impatta tutto ciò che deriva da HotelCube. f_accodamenti hardcoda 'ORTI' anche per
il 2024 → bug retroattivo da risolvere a parte (non in questo spec).
"""
```

**Caveat noto** (non risolto qui): i ricavi spiaggia (classi `04BEALL`, `05BEOL`,
`06BEABB`, `09BEBAN`, `10BEBAR`) anche post-cutover possono comparire in entrambe
le società quando sono ospiti hotel (ORTI) che fruiscono del Lido (INTUR). Questo è
intercompany e si gestisce nelle lenti, non in ingest.

---

## Schema BigQuery

### Tabella: `f_produzione_pms`

| col | tipo | mode | semantica |
|---|---|---|---|
| `data_produzione` | DATE | REQUIRED | data riga del Power BI |
| `classe` | STRING | REQUIRED | codice opaco: `01ROOM`, `04BEALL`, `99ACC`, ... |
| `importo_eur` | NUMERIC | REQUIRED | valore della cella |
| `societa_id` | STRING | REQUIRED | `'ORTI'` o `'INTUR'`, derivata via cutover |
| `file_sorgente` | STRING | NULLABLE | nome file Power BI per audit/lineage |
| `md5_riga` | STRING | REQUIRED | hash di `(data\|classe\|importo\|societa)` |
| `ingestion_ts` | TIMESTAMP | REQUIRED | quando è entrato in BQ |

**Lifecycle:** `APPEND` con dedup MD5 (Invariant I2).

**Partitioning:** `data_produzione` (DATE).
**Clustering:** `(societa_id, classe)`.

### 5-Dimensions governance — debito esplicito

Le altre quattro dimensioni canoniche (`business_unit_id`, `funzione_id`,
`location_id`, `oggetto_id`) restano `NULL` in ingest. La derivazione è demandata a
una futura `d_classi_produzione` (mapping `classe → BU + categoria_ce + ...`).

Decisione consapevole, motivata da CEO-mode YAGNI: store first, classify later.
Documentato in STATUS.md alla voce "Prossimi passi" come `d_classi_produzione TBD`.

---

## Pydantic schema

```python
# core/schemas.py
from decimal import Decimal
from datetime import date, datetime

class ProduzioneRow(BaseModel):
    """Schema for f_produzione_pms — daily production by classe from HotelCube Power BI.

    Lifecycle: APPEND + md5_riga dedup.
    societa_id is derived deterministically from data_produzione vs OPERATIONS_CUTOVER_DATE.
    """
    data_produzione: date
    classe: str
    importo_eur: Decimal
    societa_id: SocietaId
    file_sorgente: Optional[str] = None
    md5_riga: str
    ingestion_ts: str  # ISO timestamp

    @field_validator("classe")
    @classmethod
    def classe_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("classe vuoto")
        return v

    @model_validator(mode="after")
    def societa_matches_cutover(self) -> "ProduzioneRow":
        expected = "INTUR" if self.data_produzione < OPERATIONS_CUTOVER_DATE else "ORTI"
        if self.societa_id != expected:
            raise ValueError(
                f"societa_id={self.societa_id!r} non coerente con cutover "
                f"{OPERATIONS_CUTOVER_DATE} per data {self.data_produzione}"
            )
        return self
```

Esposto in `validate_batch()` come modello e usato dal nuovo pipeline.

---

## File classifier (`ingest/classify.py`)

### Detector signature

```python
def detect_produzione_pms(path: Path) -> Optional[ClassificationResult]:
    """HotelCube Power BI Daily Production Report — XLSX with 'Export' sheet."""
    if path.suffix.lower() != ".xlsx":
        return None

    rows, sheet = _read_xlsx_sample(path, max_rows=3)
    if sheet != "Export" or not rows:
        return None

    row0 = rows[0]
    if len(row0) < 5 or str(row0[0] or "").strip() != "Classe":
        return None

    # Header pattern: at least 3 cells matching ^\d{2}[A-Z]+$ (e.g. 01ROOM, 04BEALL)
    classe_pattern = re.compile(r"^\d{2}[A-Z]+$")
    matches = sum(1 for c in row0[3:] if c and classe_pattern.match(str(c).strip()))
    if matches < 3:
        return None

    return _build_produzione_result(path, confidence=0.95)
```

### Builder

```python
def _build_produzione_result(path: Path, confidence: float) -> ClassificationResult:
    today = datetime.now().strftime("%Y%m%d")
    canonical = f"produzione_pms_{today}.xlsx"
    return ClassificationResult(
        file_path=path,
        file_type="produzione_pms",
        category="produzione_pms",
        lifecycle=LIFECYCLE_APPEND,
        societa=None,                          # multi-società, derivata in pipeline
        canonical_name=canonical,
        dest_folder="produzione_pms",          # no split per società
        pipeline_cmd="python -m ingest.flussi.ingest_produzione_pms --file {dest_file}",
        confidence=confidence,
    )
```

### Posizione nella priority list

Da inserire **prima** di `detect_banca` (che è il più generico) e dopo gli specifici
filename-based. Posizione suggerita: subito dopo `detect_economato`, prima di
`detect_banca`.

### Registry entry

```yaml
# core/registry.yaml
file_types:
  produzione_pms:
    lifecycle: APPEND
    dest_folder: "produzione_pms"
    bq_table: f_produzione_pms
    pipeline: "ingest.flussi.ingest_produzione_pms"
    split_by_societa: false
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        col0_value: "Classe"
        col3_pattern: "^\\d{2}[A-Z]+$"

# Nota: il detector `detect_produzione_pms` resta autoritativo (signatures registry
# sono documentative; la logica vive in classify.py, come per gli altri detector).
```

---

## Pipeline `ingest/flussi/ingest_produzione_pms.py`

### Responsabilità

1. **Read**: apri xlsx, sheet `Export`. Estrai header classi da row 0 (skip cols 0–2),
   skip row 1 ("Importo" labels), itera su row 2+.
2. **Reshape wide→long**: per ogni `(data_row, classe_col)` con `importo` non-null e
   col != "Total", emetti una riga.
3. **Derive `societa_id`**: applica `OPERATIONS_CUTOVER_DATE` su `data_produzione`.
4. **Compute `md5_riga`**: `make_hash(data, classe, importo, societa_id)`.
5. **Pydantic validate**: tutte le righe via `validate_batch(rows, ProduzioneRow,
   context="produzione_pms <filename>")`.
6. **Dedup vs BQ**: `SELECT md5_riga FROM f_produzione_pms` (singolo round-trip), filtra
   localmente le righe con hash già presente.
7. **INSERT**: solo le righe nuove via `bq.insert_rows_json` o equivalente.
8. **Log**: parsed, new, dupes, skipped (None), errors.

### Skeleton

```python
# ingest/flussi/ingest_produzione_pms.py
"""Ingest HotelCube Power BI Daily Production Report → f_produzione_pms.

Lifecycle: APPEND + md5_riga dedup. Re-running the same export = 0 new rows.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from core.bq.client import get_client
from core.config import PROJECT, DATASET
from core.schemas import (
    OPERATIONS_CUTOVER_DATE,
    ProduzioneRow,
    SchemaViolationError,
    make_hash,
    validate_batch,
)

log = logging.getLogger("ingest.produzione_pms")

TABLE = f"{PROJECT}.{DATASET}.f_produzione_pms"


def parse_xlsx(path: Path) -> list[dict]:
    wb = load_workbook(path, read_only=True, data_only=True)
    if "Export" not in wb.sheetnames:
        raise ValueError(f"sheet 'Export' mancante in {path.name}")
    ws = wb["Export"]

    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(rows) < 3:
        return []

    header = rows[0]
    # cols 3..N-1 are classe codes; last col is "Total" (skipped)
    classe_cols: list[tuple[int, str]] = []
    for idx, cell in enumerate(header[3:], start=3):
        if cell is None:
            continue
        name = str(cell).strip()
        if not name or name.lower() == "total":
            continue
        classe_cols.append((idx, name))

    out: list[dict] = []
    for r in rows[2:]:
        if not r or r[0] is None:
            continue
        data_val = r[0]
        if isinstance(data_val, datetime):
            d = data_val.date()
        else:
            continue  # skip righe senza data valida
        for col_idx, classe in classe_cols:
            if col_idx >= len(r):
                continue
            val = r[col_idx]
            if val is None or val == "":
                continue
            try:
                importo = Decimal(str(val))
            except Exception:
                log.warning(f"importo non parsabile {val!r} a riga {d} col {classe}")
                continue
            societa = "INTUR" if d < OPERATIONS_CUTOVER_DATE else "ORTI"
            md5 = make_hash(str(d), classe, str(importo), societa)
            out.append({
                "data_produzione": d.isoformat(),
                "classe": classe,
                "importo_eur": str(importo),  # serialized for JSON insert
                "societa_id": societa,
                "file_sorgente": path.name,
                "md5_riga": md5,
                "ingestion_ts": datetime.now(timezone.utc).isoformat(),
            })
    return out


def existing_hashes(client) -> set[str]:
    q = f"SELECT md5_riga FROM `{TABLE}`"
    return {r.md5_riga for r in client.query(q).result()}


def insert(rows: list[dict], dry_run: bool = False) -> int:
    if not rows:
        return 0
    client = get_client()
    existing = set() if dry_run else existing_hashes(client)
    fresh = [r for r in rows if r["md5_riga"] not in existing]
    if dry_run:
        log.info(f"[DRY-RUN] parsed={len(rows)} new={len(fresh)} dupes={len(rows) - len(fresh)}")
        return len(fresh)
    if not fresh:
        return 0
    errors = client.insert_rows_json(TABLE, fresh)
    if errors:
        raise RuntimeError(f"BQ insert errors: {errors}")
    return len(fresh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    rows = parse_xlsx(args.file)
    validate_batch(rows, ProduzioneRow, context=f"produzione_pms {args.file.name}")
    n = insert(rows, dry_run=args.dry_run)
    log.info(f"ok parsed={len(rows)} new={n}")


if __name__ == "__main__":
    main()
```

(Il plan TDD definirà la versione finale; questo è skeleton di riferimento.)

---

## Test plan (`tests/test_ingest_produzione_pms.py`)

Test mandatori (writing-plans skill produrrà la lista TDD ordinata):

1. **Cutover boundary** — `data_produzione=2025-03-31` → `societa_id=INTUR`;
   `data=2025-04-01` → `societa_id=ORTI`. Pydantic raise se inverti.
2. **Wide→long reshape** — fixture xlsx con 3 giorni × 3 classi = 9 righe attese;
   celle `None` skippate; col `Total` esclusa.
3. **MD5 dedup determinism** — stesse 3 input rows → stesso `md5_riga`. Cambia
   `importo` di 1 cent → hash diverso.
4. **classe vuota** → ValidationError.
5. **Detector** — `detect_produzione_pms` matcha fixture con confidence ≥ 0.9; non
   matcha xlsx generico (no sheet `Export`); non matcha xls/csv.
6. **Pipeline integration** (mock BQ) — re-run idempotente: prima esecuzione
   inserisce N, seconda inserisce 0.
7. **Total exclusion** — colonna `Total` nel fixture mai presente nelle rows
   prodotte.

---

## Files to modify / create

| File | Azione |
|---|---|
| `core/schemas.py` | + `OPERATIONS_CUTOVER_DATE`, + `ProduzioneRow` |
| `core/registry.yaml` | + entry `produzione_pms` |
| `ingest/classify.py` | + `detect_produzione_pms`, `_build_produzione_result`, append a `DETECTORS` |
| `ingest/flussi/ingest_produzione_pms.py` | nuovo file |
| `tests/test_ingest_produzione_pms.py` | nuovo file (≥7 test) |
| `CLAUDE.md` | + riga `f_produzione_pms` in fact tables, gotcha cutover |

---

## Out of scope (YAGNI)

- ❌ `d_classi_produzione` (mapping classe → BU / cod_conto / categoria_ce)
- ❌ `v_produzione_giornaliera` o lenti per Romita-CdG / Antonio-GM
- ❌ Riconciliazione `f_produzione_pms` ↔ `f_accodamenti` ↔ `f_movimenti_contabili`
- ❌ Backfill / fix di `f_accodamenti` per pre-cutover (oggi tutto ORTI; dovrebbe
  essere INTUR per il 2024 e Q1 2025) — bug noto separato, va in STATUS.md
- ❌ Streamlit / CLI dedicato — interrogazione via SQL su BQ
- ❌ Modellazione intercompany ricavi spiaggia ospiti hotel — caveat documentato,
  risolto nelle lenti future

---

## Vault captures (proposed at session close)

1. **Decision** `vault/decisions/2026-04-29_HotelCube_Operating_Entity_Cutover.md`
   — la regola del 2025-04-01, retroattiva. Impatta `f_accodamenti` (oggi sbagliato
   per 2024 + Q1 2025), futuro mapping `d_classi_produzione`, qualunque view che
   joina HotelCube data con `societa_id`.
2. **Vocab fix** `vault/AI_INSTRUCTIONS.md` §Personas / Vocabolario canonico —
   chiarire: **Gasparotto** è il nome dato al *file Master Excel di Roberto Romita*
   (consulente finanziario), non una persona. **Rosa** è invece persona reale
   (amministrazione) + il suo Excel cashflow Drive `1m73vYOl-_174UcYNFxDLowiwwvMrWf7R`,
   integrato via `condges/scadenzario_excel.py`. I due Excel convergono via codici
   Esolver + mapping fornitori; `app_cdg.py` è il porting del file Romita.
3. **Concept** `vault/concepts/INTERCOMPANY_SPIAGGIA.md` — i ricavi BE* attribuiti
   in HotelCube possono comparire sia in ORTI (ospiti hotel che usano Lido) che in
   INTUR (gestione diretta Lido). Rilevante per future lenti di consolidamento.
4. **Meta** (opzionale, bassa priorità) — Stefano ha osservato che ingerire +
   classificare nuovi tipi di file è ripetitivo; possibile candidato di skill
   `add-new-file-type` che orchestra detector + registry + pipeline + tests + vault
   capture. Non bloccante, parking lot.

---

## Invariants compliance check

| Invariant | Status |
|---|---|
| **I1** (Pydantic gate) | ✅ `ProduzioneRow` + `validate_batch` |
| **I2** (lifecycle) | ✅ APPEND scelto, MD5 dedup |
| **I3** (ontology SSOT) | ✅ `societa_id` ⊆ `{ORTI, INTUR}` già canonici, niente nuove entità |
| **I4** (3 dimensioni) | ⚠️ COMPETENZA implicita (revenue accrual). 5-dim: solo `societa_id` riempita, altre NULL come debito esplicito |
| **I5** (classify deterministico) | ✅ regex + sheet name, no LLM |
| **I6** (stagionalità) | n/a (nessun forecast in scope) |
| **I7** (audience umana) | ⚠️ in CEO-mode owner = Stefano. Verticali futuri determineranno l'audience finale |
| **I8** (locality row-selection) | ✅ niente row-selection cross-fonte; APPEND puro |

I4/I7 sono debiti consapevoli, non violazioni. La conversazione di brainstorming li
ha espliciti, non silenziosi.

---

## Next step

Dopo user-review di questo spec, invocare `superpowers:writing-plans` per generare
il plan TDD eseguibile.
