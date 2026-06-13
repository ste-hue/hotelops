# Vertical Spiaggia (fase 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingerire il dump JSON completo di Spiagge.it in 3 tabelle canonical BigQuery (full-replace via lineage), esporle in 4 viste, e servirle in un'app Streamlit interna cercabile vestita Panorama Beach.

**Architecture:** Un dump JSON (DB completo) → `hotelops intake` (GCS + `f_raw_objects`, dedup content-hash) → `hotelops promote` (MANUAL) → un parser `ingest/flussi/ingest_spiaggia.py` che fa fan-out 1→3 full-replace in `f_spiaggia_reservations` / `f_spiaggia_cash_flows` / `f_spiaggia_spots`. Sopra, viste `v_spiaggia_*` e app Streamlit. Full-replace ottenuto con `bq_write_validated(mode="snapshot", natural_key=["societa_id"])`: ogni riga è `INTUR`, quindi il DELETE chirurgico del gate cancella l'intera tabella prima del re-insert.

**Tech Stack:** Python 3.11, Pydantic, google-cloud-bigquery, openpyxl non serve (è JSON), Streamlit + plotly + db-dtypes (dashboard extras).

**Spec:** `docs/superpowers/specs/2026-06-13-spiaggia-vertical-design.md`

**⚠️ Deviazione consapevole dallo spec (legenda metodi pagamento):** lo spec prevedeva una dimensione `d_spiaggia_metodi` (CSV + loader + DDL) per decodificare i codici `method`. Il piano la sostituisce con un **dict `METHOD_LABELS` in-parser** che stampa `method_label` direttamente sulle righe canonical. Motivo: la legenda Spiagge.it è ignota (tutte le label sarebbero placeholder), il full-replace re-promote è la routine normale (quindi aggiornare le label = riempire il dict + re-promote, non serve una tabella aggiornabile a parte), e si evitano 3 artefatti per un lookup di 4 righe. Se preferisci la tabella-dimensione, è un cambio isolato al Task 5 + un nuovo task DDL/loader.

---

## File Structure

| File | Responsabilità | Azione |
|---|---|---|
| `core/config.py` | Table id constants `F_SPIAGGIA_*` | Modify |
| `core/schemas.py` | 3 Pydantic row models | Modify |
| `core/bq/load/create_spiaggia_tables.py` | DDL idempotente 3 tabelle | Create |
| `ingest/flussi/ingest_spiaggia.py` | Parser fan-out 1→3 full-replace | Create |
| `core/source_registry.yaml` | Entry `SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT` | Modify |
| `core/bq/views/v_spiaggia_prenotazioni.sql` | Vista prenotazioni arricchite | Create |
| `core/bq/views/v_spiaggia_cassa.sql` | Vista cassa per giorno × metodo | Create |
| `core/bq/views/v_spiaggia_occupazione.sql` | Vista occupazione ombrelloni/giorno | Create |
| `core/bq/views/v_spiaggia_kpi.sql` | Vista KPI mensili | Create |
| `verticals/spiaggia/__init__.py` | Package marker | Create |
| `verticals/spiaggia/app.py` | Streamlit app Panorama Beach | Create |
| `tests/test_ingest_spiaggia.py` | Test parser (coercion, extract, build) | Create |

---

## Task 1: Table id constants in config

**Files:**
- Modify: `core/config.py` (dopo la riga `F_PROGETTO_EVENTI = _t("f_progetto_eventi")`)

- [ ] **Step 1: Aggiungi le 3 costanti**

In `core/config.py`, subito dopo la riga `F_PROGETTO_EVENTI             = _t("f_progetto_eventi")`, aggiungi:

```python
F_SPIAGGIA_RESERVATIONS     = _t("f_spiaggia_reservations")
F_SPIAGGIA_CASH_FLOWS       = _t("f_spiaggia_cash_flows")
F_SPIAGGIA_SPOTS            = _t("f_spiaggia_spots")
```

- [ ] **Step 2: Verifica l'import**

Run: `python -c "from core.config import F_SPIAGGIA_RESERVATIONS, F_SPIAGGIA_CASH_FLOWS, F_SPIAGGIA_SPOTS; print(F_SPIAGGIA_RESERVATIONS, F_SPIAGGIA_CASH_FLOWS, F_SPIAGGIA_SPOTS)"`
Expected: `hotelops-suite.hotelops.f_spiaggia_reservations hotelops-suite.hotelops.f_spiaggia_cash_flows hotelops-suite.hotelops.f_spiaggia_spots`

- [ ] **Step 3: Commit**

```bash
git add core/config.py
git commit -m "feat(spiaggia): table id constants f_spiaggia_*

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Pydantic row models

**Files:**
- Modify: `core/schemas.py` (aggiungi 3 classi dopo `class RistocubeOrderRow` / prima di `class PipelineRunRow`, o in coda alle row classes)
- Test: `tests/test_ingest_spiaggia.py`

I tre modelli portano le 5 dimensioni (societa_id required, business_unit_id required, location_id/oggetto_id/funzione_id Optional) + `raw_object_id` FK + `file_sorgente`/`hash_riga`/`data_caricamento` come gli altri schemi.

- [ ] **Step 1: Scrivi il test di validazione (fallisce)**

Crea `tests/test_ingest_spiaggia.py`:

```python
from datetime import date, datetime, timezone

import pytest

from core.schemas import (
    SpiaggiaCashFlowRow,
    SpiaggiaReservationRow,
    SpiaggiaSpotRow,
)


def _now():
    return datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)


def test_reservation_row_valid():
    r = SpiaggiaReservationRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        location_id="LIDO",
        oggetto_id="7",
        id=4402425,
        spot_type="umbrella",
        spot_name="7",
        status=1,
        seasonal=False,
        deleted=False,
        online=True,
        start_date=date(2020, 6, 19),
        end_date=date(2020, 6, 19),
        beds=2,
        chairs=0,
        first_name="Jessica",
        last_name="Neely",
        email="jess@example.com",
        gross_booking_value=35.0,
        file_sorgente="dump.json",
        hash_riga="abc",
        data_caricamento=_now(),
    )
    assert r.id == 4402425
    assert r.societa_id == "INTUR"


def test_reservation_row_rejects_bad_societa():
    with pytest.raises(Exception):
        SpiaggiaReservationRow(
            societa_id="PIPPO",
            business_unit_id="LIDO",
            id=1,
            seasonal=False,
            deleted=False,
            online=False,
            file_sorgente="d.json",
            hash_riga="x",
            data_caricamento=_now(),
        )


def test_cash_flow_row_valid_negative_amount():
    c = SpiaggiaCashFlowRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        id=3055414,
        reservation_id=4402426,
        method=1,
        method_label="metodo_1",
        amount=-35.0,
        date=date(2020, 6, 10),
        deleted=False,
        file_sorgente="dump.json",
        hash_riga="def",
        data_caricamento=_now(),
    )
    assert c.amount == -35.0


def test_spot_row_valid():
    s = SpiaggiaSpotRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        location_id="LIDO",
        oggetto_id="7",
        id=1394619,
        uuid="7be4bfed-9905-4ec3-836e-5a745bf3d558",
        name="7",
        type="umbrella",
        sector=0,
        file_sorgente="dump.json",
        hash_riga="ghi",
        data_caricamento=_now(),
    )
    assert s.type == "umbrella"
```

- [ ] **Step 2: Esegui il test, verifica che fallisce**

Run: `pytest tests/test_ingest_spiaggia.py -v`
Expected: FAIL con `ImportError: cannot import name 'SpiaggiaReservationRow'`

- [ ] **Step 3: Aggiungi i 3 modelli in `core/schemas.py`**

Inserisci queste 3 classi tra `class RistocubeOrderRow(BaseModel):` (finisce intorno a riga 958) e `class PipelineRunRow(BaseModel):`:

```python
class SpiaggiaReservationRow(BaseModel):
    """Schema per f_spiaggia_reservations — prenotazioni ombrellone Spiagge.it.

    Source: dump JSON completo Spiagge.it (Panorama Beach), tabella reservations.
    Lifecycle SNAPSHOT full-replace (natural_key societa_id: ogni dump è il DB
    intero, il DELETE chirurgico su societa_id='INTUR' svuota la tabella).
    raw_object_id = FK a f_raw_objects, stampato dal path `promote`.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    id: int
    license_code: Optional[str] = None
    spot_type: Optional[str] = None
    spot_name: Optional[str] = None
    status: Optional[int] = None
    seasonal: bool = False
    deleted: bool = False
    online: bool = False
    hotel: Optional[str] = None
    hotel_room: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    beds: Optional[int] = None
    chairs: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    list_total: Optional[float] = None
    paid_total: Optional[float] = None
    gross_booking_value: Optional[float] = None
    discount: Optional[float] = None
    channel: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_company: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime


class SpiaggiaCashFlowRow(BaseModel):
    """Schema per f_spiaggia_cash_flows — movimenti cassa Spiagge.it.

    amount: float con segno (negativo = storno). method = codice intero grezzo,
    method_label = decodifica best-effort (legenda Spiagge.it ignota, vedi
    METHOD_LABELS nel parser). Lifecycle SNAPSHOT full-replace come reservations.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    id: int
    reservation_id: Optional[int] = None
    method: Optional[int] = None
    method_label: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[date] = None
    receipt_id: Optional[int] = None
    invoice_id: Optional[int] = None
    deleted: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime


class SpiaggiaSpotRow(BaseModel):
    """Schema per f_spiaggia_spots — mappa postazioni (ombrelloni + elementi).

    Tabella-dimensione: la mappa fisica della spiaggia. Lifecycle SNAPSHOT
    full-replace come reservations.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    id: int
    uuid: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    sector: Optional[int] = None
    price_list_id: Optional[int] = None
    pos_x: Optional[int] = None
    pos_y: Optional[int] = None
    element_type: Optional[str] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime
```

- [ ] **Step 4: Esegui il test, verifica che passa**

Run: `pytest tests/test_ingest_spiaggia.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add core/schemas.py tests/test_ingest_spiaggia.py
git commit -m "feat(spiaggia): Pydantic row models per le 3 tabelle canonical

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: DDL idempotente delle 3 tabelle

**Files:**
- Create: `core/bq/load/create_spiaggia_tables.py`

Pattern: copia `create_produzione_table.py` (CREATE TABLE IF NOT EXISTS, `--dry-run`).

- [ ] **Step 1: Crea lo script DDL**

Crea `core/bq/load/create_spiaggia_tables.py`:

```python
#!/usr/bin/env python3
"""DDL idempotente per le 3 tabelle canonical del vertical spiaggia.

f_spiaggia_reservations / f_spiaggia_cash_flows / f_spiaggia_spots.
Lifecycle SNAPSHOT full-replace (natural_key societa_id) — gestito dal parser
ingest.flussi.ingest_spiaggia.

Usage:
    python -m core.bq.load.create_spiaggia_tables
    python -m core.bq.load.create_spiaggia_tables --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import (
    F_SPIAGGIA_CASH_FLOWS,
    F_SPIAGGIA_RESERVATIONS,
    F_SPIAGGIA_SPOTS,
)

DDL_RESERVATIONS = f"""
CREATE TABLE IF NOT EXISTS `{F_SPIAGGIA_RESERVATIONS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    location_id          STRING,
    oggetto_id           STRING,
    funzione_id          STRING,
    id                   INT64 NOT NULL,
    license_code         STRING,
    spot_type            STRING,
    spot_name            STRING,
    status               INT64,
    seasonal             BOOL,
    deleted              BOOL,
    online               BOOL,
    hotel                STRING,
    hotel_room           STRING,
    start_date           DATE,
    end_date             DATE,
    beds                 INT64,
    chairs               INT64,
    first_name           STRING,
    last_name            STRING,
    email                STRING,
    phone                STRING,
    list_total           FLOAT64,
    paid_total           FLOAT64,
    gross_booking_value  FLOAT64,
    discount             FLOAT64,
    channel              STRING,
    invoice_number       STRING,
    invoice_company      STRING,
    utm_source           STRING,
    utm_medium           STRING,
    utm_campaign         STRING,
    created_at           TIMESTAMP,
    updated_at           TIMESTAMP,
    raw_object_id        STRING,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    data_caricamento     TIMESTAMP NOT NULL
)
CLUSTER BY spot_name
"""

DDL_CASH_FLOWS = f"""
CREATE TABLE IF NOT EXISTS `{F_SPIAGGIA_CASH_FLOWS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    location_id          STRING,
    oggetto_id           STRING,
    funzione_id          STRING,
    id                   INT64 NOT NULL,
    reservation_id       INT64,
    method               INT64,
    method_label         STRING,
    amount               FLOAT64,
    date                 DATE,
    receipt_id           INT64,
    invoice_id           INT64,
    deleted              BOOL,
    created_at           TIMESTAMP,
    updated_at           TIMESTAMP,
    raw_object_id        STRING,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    data_caricamento     TIMESTAMP NOT NULL
)
CLUSTER BY reservation_id
"""

DDL_SPOTS = f"""
CREATE TABLE IF NOT EXISTS `{F_SPIAGGIA_SPOTS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    location_id          STRING,
    oggetto_id           STRING,
    funzione_id          STRING,
    id                   INT64 NOT NULL,
    uuid                 STRING,
    name                 STRING,
    type                 STRING,
    sector               INT64,
    price_list_id        INT64,
    pos_x                INT64,
    pos_y                INT64,
    element_type         STRING,
    raw_object_id        STRING,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

ALL_DDL = {
    "f_spiaggia_reservations": DDL_RESERVATIONS,
    "f_spiaggia_cash_flows": DDL_CASH_FLOWS,
    "f_spiaggia_spots": DDL_SPOTS,
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = logging.getLogger("create_spiaggia_tables")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.dry_run:
        for name, ddl in ALL_DDL.items():
            log.info("--- %s ---%s", name, ddl)
        return 0

    client = get_client()
    for name, ddl in ALL_DDL.items():
        client.query(ddl).result()
        log.info("OK %s creata/confermata", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verifica il dry-run (no credenziali necessarie)**

Run: `python -m core.bq.load.create_spiaggia_tables --dry-run`
Expected: stampa i 3 blocchi DDL, exit 0.

- [ ] **Step 3: Commit**

```bash
git add core/bq/load/create_spiaggia_tables.py
git commit -m "feat(spiaggia): DDL idempotente delle 3 tabelle canonical

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Parser — helper di coercion + estrazione tabelle

**Files:**
- Create: `ingest/flussi/ingest_spiaggia.py` (prima metà: import, costanti, helper, extract)
- Test: `tests/test_ingest_spiaggia.py` (aggiungi test)

- [ ] **Step 1: Scrivi i test (falliscono)**

Aggiungi in fondo a `tests/test_ingest_spiaggia.py`:

```python
from datetime import date as _date

from ingest.flussi.ingest_spiaggia import (
    extract_table,
    find_prefix,
    method_label,
    to_bool,
    to_float,
    to_int,
    to_str,
    unix_to_date,
    unix_to_ts,
)


def test_coercion_helpers():
    assert to_int(None) is None
    assert to_int("") is None
    assert to_int(5) == 5
    assert to_float("35.00") == 35.0
    assert to_float("-10.50") == -10.5
    assert to_float(None) is None
    assert to_float("") is None
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool(None) is False
    assert to_str("  x ") == "x"
    assert to_str("") is None
    assert to_str(None) is None


def test_unix_conversions():
    assert unix_to_date(1592524800) == _date(2020, 6, 19)
    assert unix_to_date(0) is None
    assert unix_to_date(None) is None
    assert unix_to_ts(0) is None
    assert unix_to_ts(1652133848).year == 2022


def test_method_label():
    assert method_label(None) == "sconosciuto"
    assert method_label(1) == "metodo_1"
    assert method_label(14) == "metodo_14"


def test_find_prefix_and_extract():
    dump = {
        "it-sa-84010-panorama-beach_reservations": {
            "columns": ["id", "spot_name", "amount"],
            "rows": [[1, "7", "35.00"], [2, "8", "40.00"]],
        }
    }
    prefix = find_prefix(dump)
    assert prefix == "it-sa-84010-panorama-beach_"
    recs = extract_table(dump, prefix, "reservations")
    assert recs == [
        {"id": 1, "spot_name": "7", "amount": "35.00"},
        {"id": 2, "spot_name": "8", "amount": "40.00"},
    ]
```

- [ ] **Step 2: Esegui, verifica fallimento**

Run: `pytest tests/test_ingest_spiaggia.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ingest.flussi.ingest_spiaggia'`

- [ ] **Step 3: Crea il parser (parte 1)**

Crea `ingest/flussi/ingest_spiaggia.py`:

```python
#!/usr/bin/env python3
"""Ingest dump JSON completo Spiagge.it → 3 tabelle canonical (fan-out 1→3).

Un dump = il DB intero di booking. Lifecycle SNAPSHOT full-replace: ogni dump
sostituisce integralmente le 3 tabelle. Il full-replace è ottenuto con
bq_write_validated(mode="snapshot", natural_key=["societa_id"]): siccome ogni
riga è societa_id='INTUR', il DELETE chirurgico del gate svuota la tabella prima
del re-insert.

È il parser_module della source SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT, invocato da
`hotelops promote` come:
    python -m ingest.flussi.ingest_spiaggia --file X.json --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_spiaggia --file <json> --raw-object-id <id>
    python -m ingest.flussi.ingest_spiaggia --file <json> --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.config import (
    F_SPIAGGIA_CASH_FLOWS,
    F_SPIAGGIA_RESERVATIONS,
    F_SPIAGGIA_SPOTS,
)
from core.schemas import (
    SpiaggiaCashFlowRow,
    SpiaggiaReservationRow,
    SpiaggiaSpotRow,
    make_hash,
    validate_batch,
)

log = logging.getLogger("ingest.spiaggia")

# Dimensioni fisse del vertical (vedi spec): la spiaggia è INTUR / LIDO.
SOCIETA = "INTUR"
BUSINESS_UNIT = "LIDO"
LOCATION = "LIDO"

# Legenda metodi pagamento Spiagge.it: IGNOTA. Riempire qui quando nota
# (es. {1: "contanti", 14: "POS"}) e ri-promuovere il dump. Finché vuota,
# method_label resta "metodo_<codice>".
METHOD_LABELS: dict[int, str] = {}


def to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_bool(v: Any) -> bool:
    """0/1/None → bool. None e falsy → False."""
    return bool(v) if v is not None else False


def to_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def unix_to_date(v: Any) -> Optional[date]:
    """Unix seconds → date UTC. 0/None/falsy → None (filtra epoch-junk 1970)."""
    n = to_int(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def unix_to_ts(v: Any) -> Optional[datetime]:
    """Unix seconds → datetime UTC. 0/None/falsy → None."""
    n = to_int(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def method_label(code: Optional[int]) -> str:
    if code is None:
        return "sconosciuto"
    return METHOD_LABELS.get(code, f"metodo_{code}")


def find_prefix(dump: dict) -> str:
    """Deduce il prefisso tabella dal dump (es. 'it-sa-84010-panorama-beach_').

    Cerca la chiave che termina in '_reservations'. Robusto a license_code
    diversi (altra spiaggia) senza hardcodare il nome.
    """
    suffix = "_reservations"
    for k in dump:
        if k.endswith(suffix):
            return k[: -len("reservations")]
    raise ValueError("dump senza tabella *_reservations: non è un dump Spiagge.it")


def extract_table(dump: dict, prefix: str, table: str) -> list[dict]:
    """Estrae una tabella {columns, rows} → list[dict] per nome colonna."""
    key = f"{prefix}{table}"
    block = dump.get(key)
    if block is None:
        raise KeyError(f"tabella mancante nel dump: {key}")
    cols = block["columns"]
    return [dict(zip(cols, row)) for row in block["rows"]]
```

- [ ] **Step 4: Esegui i test, verifica che passano**

Run: `pytest tests/test_ingest_spiaggia.py -v`
Expected: PASS (i test di Task 2 + i 4 nuovi).

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_spiaggia.py tests/test_ingest_spiaggia.py
git commit -m "feat(spiaggia): parser helpers di coercion + estrazione tabelle JSON

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Parser — build_rows per le 3 tabelle

**Files:**
- Modify: `ingest/flussi/ingest_spiaggia.py` (aggiungi le 3 funzioni build)
- Test: `tests/test_ingest_spiaggia.py`

- [ ] **Step 1: Scrivi i test (falliscono)**

Aggiungi in fondo a `tests/test_ingest_spiaggia.py`:

```python
from datetime import datetime as _dt
from datetime import timezone as _tz

from ingest.flussi.ingest_spiaggia import (
    build_cash_flow_rows,
    build_reservation_rows,
    build_spot_rows,
)

_NOW = _dt(2026, 6, 13, tzinfo=_tz.utc)


def test_build_reservation_rows():
    recs = [{
        "id": 4402425, "license_code": "it-sa-84010-panorama-beach",
        "spot_type": "umbrella", "spot_name": "7", "status": 1,
        "seasonal": 0, "deleted": 0, "online": 1, "hotel": "",
        "hotel_room": None, "start_date": 1592524800, "end_date": 1592524800,
        "beds": 2, "chairs": 0, "first_name": "Jessica", "last_name": "Neely",
        "email": "jess@example.com", "phone_area_code": None,
        "phone_number": "6128192966", "list_total": None, "paid_total": None,
        "gross_booking_value": 35, "discount": None, "channel": "",
        "invoice_number": None, "invoice_company": None,
        "utm_source": None, "utm_medium": None, "utm_campaign": None,
        "created_at": 1652133848, "updated_at": None,
    }]
    rows = build_reservation_rows(recs, "dump.json", "raw-1", _NOW)
    assert len(rows) == 1
    r = rows[0]
    assert r.id == 4402425
    assert r.societa_id == "INTUR"
    assert r.business_unit_id == "LIDO"
    assert r.oggetto_id == "7"          # spot_name
    assert r.online is True
    assert r.seasonal is False
    assert r.start_date.year == 2020
    assert r.phone == "6128192966"
    assert r.gross_booking_value == 35.0
    assert r.raw_object_id == "raw-1"


def test_build_cash_flow_rows_negative():
    recs = [{
        "id": 3055414, "reservation_id": 4402426, "method": None,
        "amount": "-35.00", "date": 1591786050, "receipt_id": None,
        "invoice_id": None, "deleted": 1, "created_at": 1652133848,
        "updated_at": None,
    }]
    rows = build_cash_flow_rows(recs, "dump.json", "raw-1", _NOW)
    c = rows[0]
    assert c.amount == -35.0
    assert c.method_label == "sconosciuto"
    assert c.deleted is True
    assert c.societa_id == "INTUR"


def test_build_spot_rows():
    recs = [{
        "id": 1394619, "uuid": "abc", "name": "7", "type": "umbrella",
        "sector": 0, "price_list_id": None, "pos_x": 617, "pos_y": 73,
        "element_type": "passerella",
    }]
    rows = build_spot_rows(recs, "dump.json", "raw-1", _NOW)
    s = rows[0]
    assert s.id == 1394619
    assert s.oggetto_id == "7"          # name
    assert s.type == "umbrella"
    assert s.business_unit_id == "LIDO"
```

- [ ] **Step 2: Esegui, verifica fallimento**

Run: `pytest tests/test_ingest_spiaggia.py -v`
Expected: FAIL con `ImportError: cannot import name 'build_reservation_rows'`

- [ ] **Step 3: Aggiungi le 3 build in `ingest/flussi/ingest_spiaggia.py`**

Dopo `extract_table` aggiungi:

```python
def _dims(oggetto_id: Optional[str]) -> dict:
    """Le 5 dimensioni del vertical (funzione_id sempre None per la spiaggia)."""
    return {
        "societa_id": SOCIETA,
        "business_unit_id": BUSINESS_UNIT,
        "location_id": LOCATION,
        "oggetto_id": oggetto_id,
        "funzione_id": None,
    }


def build_reservation_rows(
    recs: list[dict], file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[SpiaggiaReservationRow]:
    out: list[SpiaggiaReservationRow] = []
    for d in recs:
        spot_name = to_str(d.get("spot_name"))
        out.append(SpiaggiaReservationRow(
            **_dims(spot_name),
            id=int(d["id"]),
            license_code=to_str(d.get("license_code")),
            spot_type=to_str(d.get("spot_type")),
            spot_name=spot_name,
            status=to_int(d.get("status")),
            seasonal=to_bool(d.get("seasonal")),
            deleted=to_bool(d.get("deleted")),
            online=to_bool(d.get("online")),
            hotel=to_str(d.get("hotel")),
            hotel_room=to_str(d.get("hotel_room")),
            start_date=unix_to_date(d.get("start_date")),
            end_date=unix_to_date(d.get("end_date")),
            beds=to_int(d.get("beds")),
            chairs=to_int(d.get("chairs")),
            first_name=to_str(d.get("first_name")),
            last_name=to_str(d.get("last_name")),
            email=to_str(d.get("email")),
            phone=to_str(d.get("phone_number")),
            list_total=to_float(d.get("list_total")),
            paid_total=to_float(d.get("paid_total")),
            gross_booking_value=to_float(d.get("gross_booking_value")),
            discount=to_float(d.get("discount")),
            channel=to_str(d.get("channel")),
            invoice_number=to_str(d.get("invoice_number")),
            invoice_company=to_str(d.get("invoice_company")),
            utm_source=to_str(d.get("utm_source")),
            utm_medium=to_str(d.get("utm_medium")),
            utm_campaign=to_str(d.get("utm_campaign")),
            created_at=unix_to_ts(d.get("created_at")),
            updated_at=unix_to_ts(d.get("updated_at")),
            raw_object_id=raw_object_id,
            file_sorgente=file_name,
            hash_riga=make_hash("reservations", str(d["id"])),
            data_caricamento=now,
        ))
    return out


def build_cash_flow_rows(
    recs: list[dict], file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[SpiaggiaCashFlowRow]:
    out: list[SpiaggiaCashFlowRow] = []
    for d in recs:
        method = to_int(d.get("method"))
        out.append(SpiaggiaCashFlowRow(
            **_dims(None),
            id=int(d["id"]),
            reservation_id=to_int(d.get("reservation_id")),
            method=method,
            method_label=method_label(method),
            amount=to_float(d.get("amount")),
            date=unix_to_date(d.get("date")),
            receipt_id=to_int(d.get("receipt_id")),
            invoice_id=to_int(d.get("invoice_id")),
            deleted=to_bool(d.get("deleted")),
            created_at=unix_to_ts(d.get("created_at")),
            updated_at=unix_to_ts(d.get("updated_at")),
            raw_object_id=raw_object_id,
            file_sorgente=file_name,
            hash_riga=make_hash("cash_flows", str(d["id"])),
            data_caricamento=now,
        ))
    return out


def build_spot_rows(
    recs: list[dict], file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[SpiaggiaSpotRow]:
    out: list[SpiaggiaSpotRow] = []
    for d in recs:
        name = to_str(d.get("name"))
        out.append(SpiaggiaSpotRow(
            **_dims(name),
            id=int(d["id"]),
            uuid=to_str(d.get("uuid")),
            name=name,
            type=to_str(d.get("type")),
            sector=to_int(d.get("sector")),
            price_list_id=to_int(d.get("price_list_id")),
            pos_x=to_int(d.get("pos_x")),
            pos_y=to_int(d.get("pos_y")),
            element_type=to_str(d.get("element_type")),
            raw_object_id=raw_object_id,
            file_sorgente=file_name,
            hash_riga=make_hash("spots", str(d["id"])),
            data_caricamento=now,
        ))
    return out
```

- [ ] **Step 4: Esegui i test, verifica che passano**

Run: `pytest tests/test_ingest_spiaggia.py -v`
Expected: PASS (tutti).

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_spiaggia.py tests/test_ingest_spiaggia.py
git commit -m "feat(spiaggia): build_rows per reservations/cash_flows/spots

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Parser — orchestrazione ingest_file + main (full-replace)

**Files:**
- Modify: `ingest/flussi/ingest_spiaggia.py` (aggiungi `ingest_file` + `main`)
- Test: `tests/test_ingest_spiaggia.py` (dry-run su file temporaneo)

- [ ] **Step 1: Scrivi il test dry-run (fallisce)**

Aggiungi in fondo a `tests/test_ingest_spiaggia.py`:

```python
import json as _json

from ingest.flussi.ingest_spiaggia import ingest_file


def test_ingest_file_dry_run(tmp_path):
    dump = {
        "it-sa-84010-panorama-beach_reservations": {
            "columns": ["id", "spot_name", "start_date", "seasonal",
                        "deleted", "online", "gross_booking_value"],
            "rows": [[1, "7", 1592524800, 0, 0, 1, 35]],
        },
        "it-sa-84010-panorama-beach_cash_flows": {
            "columns": ["id", "reservation_id", "method", "amount", "date", "deleted"],
            "rows": [[10, 1, 1, "35.00", 1591786050, 0]],
        },
        "it-sa-84010-panorama-beach_spots": {
            "columns": ["id", "name", "type", "sector"],
            "rows": [[100, "7", "umbrella", 0]],
        },
    }
    f = tmp_path / "dump.json"
    f.write_text(_json.dumps(dump))
    counts = ingest_file(f, raw_object_id=None, dry_run=True)
    assert counts == {"reservations": 1, "cash_flows": 1, "spots": 1}
```

- [ ] **Step 2: Esegui, verifica fallimento**

Run: `pytest tests/test_ingest_spiaggia.py::test_ingest_file_dry_run -v`
Expected: FAIL con `ImportError: cannot import name 'ingest_file'`

- [ ] **Step 3: Aggiungi `ingest_file` + `main`**

In fondo a `ingest/flussi/ingest_spiaggia.py`:

```python
# (table_name, extract_table arg, builder, target table) per il fan-out 1→3.
_TABLES = [
    ("reservations", build_reservation_rows, F_SPIAGGIA_RESERVATIONS),
    ("cash_flows", build_cash_flow_rows, F_SPIAGGIA_CASH_FLOWS),
    ("spots", build_spot_rows, F_SPIAGGIA_SPOTS),
]


def ingest_file(
    path: Path, raw_object_id: Optional[str] = None, dry_run: bool = False
) -> dict[str, int]:
    """Parsa un dump JSON e fa full-replace SNAPSHOT delle 3 tabelle.

    Ritorna {table_name: n_righe}. Full-replace via natural_key=["societa_id"]:
    ogni riga è INTUR ⇒ il DELETE del gate svuota la tabella prima del re-insert.
    """
    with open(path, encoding="utf-8") as fh:
        dump = json.load(fh)
    prefix = find_prefix(dump)
    now = datetime.now(timezone.utc)

    counts: dict[str, int] = {}
    for table_name, builder, target in _TABLES:
        recs = extract_table(dump, prefix, table_name)
        rows = builder(recs, path.name, raw_object_id, now)
        # validate_batch lavora su dict; i modelli sono già validati alla
        # costruzione, ma teniamo il check esplicito per uniformità.
        validate_batch(
            [r.model_dump() for r in rows],
            type(rows[0]) if rows else SpiaggiaReservationRow,
            context=f"spiaggia {table_name} {path.name}",
        ) if rows else None
        counts[table_name] = len(rows)

        if dry_run:
            log.info("[DRY-RUN] %s → %s : %d righe", table_name, target, len(rows))
            continue

        from core.bq.write import bq_write_validated

        bq_write_validated(
            target,
            rows,
            mode="snapshot",
            natural_key=["societa_id"],
        )
        log.info("OK %s → %s : %d righe (full-replace)", table_name, target, len(rows))

    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest dump Spiagge.it → 3 tabelle canonical")
    ap.add_argument("--file", required=True, type=Path, help="dump JSON Spiagge.it")
    ap.add_argument(
        "--raw-object-id",
        default=None,
        help="FK a f_raw_objects — passato da `hotelops promote`",
    )
    ap.add_argument(
        "--societa",
        default=None,
        help="Ignorato — la spiaggia è sempre INTUR. Accettato da `hotelops promote`.",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    counts = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %s", counts)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Esegui il test, verifica che passa**

Run: `pytest tests/test_ingest_spiaggia.py -v`
Expected: PASS (tutti, incluso `test_ingest_file_dry_run`).

- [ ] **Step 5: Lint**

Run: `ruff check ingest/flussi/ingest_spiaggia.py core/schemas.py core/bq/load/create_spiaggia_tables.py`
Expected: nessun errore (o fixa quanto segnalato).

- [ ] **Step 6: Commit**

```bash
git add ingest/flussi/ingest_spiaggia.py tests/test_ingest_spiaggia.py
git commit -m "feat(spiaggia): ingest_file fan-out 1→3 full-replace + CLI main

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Source registry entry

**Files:**
- Modify: `core/source_registry.yaml`

- [ ] **Step 1: Aggiungi l'entry**

In `core/source_registry.yaml`, in coda alla sezione delle source (mantieni l'indentazione a 2 spazi delle altre entry, sotto la stessa chiave radice):

```yaml
  SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT:
    system: SPIAGGEIT
    dataset: SPIAGGIA
    dataset_label: "Dump completo prenotazioni Spiagge.it (Panorama Beach)"
    societa: INTUR
    business_unit: LIDO
    lifecycle: SNAPSHOT
    canonical_table: f_spiaggia_reservations
    parser_module: ingest.flussi.ingest_spiaggia
    natural_key: [societa_id]
    loop_targets: [cash_control]
    promotion_policy: MANUAL
    detector_category: spiaggia_dump
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "spiaggeit/spiaggia/INTUR"
```

- [ ] **Step 2: Verifica che il registry carica e l'invariante regge**

Run: `python -c "from core.lineage.source_resolver import load_registry; r=load_registry(); s=r['SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT']; print(s.system, s.societa, s.lifecycle, s.promotion_policy, s.loop_targets)"`
Expected: `SPIAGGEIT INTUR SNAPSHOT MANUAL ['cash_control']` (nessuna PolicyViolation: loop_targets non vuoto ⇒ MANUAL è coerente).

- [ ] **Step 3: Commit**

```bash
git add core/source_registry.yaml
git commit -m "feat(spiaggia): source SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT (MANUAL)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Viste BQ v_spiaggia_*

**Files:**
- Create: `core/bq/views/v_spiaggia_prenotazioni.sql`
- Create: `core/bq/views/v_spiaggia_cassa.sql`
- Create: `core/bq/views/v_spiaggia_occupazione.sql`
- Create: `core/bq/views/v_spiaggia_kpi.sql`

Ogni file è un `CREATE OR REPLACE VIEW` self-contained (il loader li ordina per dipendenza). Filtro junk: anno `start_date`/`date` in `[2018, 2030]` esclude record epoch 1970 e outlier.

- [ ] **Step 1: Crea `v_spiaggia_prenotazioni.sql`**

```sql
-- v_spiaggia_prenotazioni
-- Prenotazioni arricchite: join spots per settore, notti, flag online/hotel.
-- Esclude deleted e record con date fuori range plausibile (junk 1970/2010).
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_prenotazioni` AS
SELECT
  r.id,
  r.license_code,
  r.spot_type,
  r.spot_name,
  s.sector,
  s.type AS spot_kind,
  r.status,
  r.seasonal,
  r.online,
  (r.hotel IS NOT NULL AND r.hotel != '') AS hotel_linked,
  r.start_date,
  r.end_date,
  DATE_DIFF(r.end_date, r.start_date, DAY) AS notti,
  r.beds,
  r.chairs,
  r.first_name,
  r.last_name,
  r.email,
  r.phone,
  r.list_total,
  r.paid_total,
  r.gross_booking_value,
  r.discount,
  r.channel,
  r.utm_source,
  r.utm_medium,
  r.utm_campaign,
  EXTRACT(YEAR FROM r.start_date) AS anno,
  EXTRACT(MONTH FROM r.start_date) AS mese,
  r.raw_object_id
FROM `hotelops-suite.hotelops.f_spiaggia_reservations` r
LEFT JOIN `hotelops-suite.hotelops.f_spiaggia_spots` s
  ON r.spot_name = s.name
WHERE r.deleted = FALSE
  AND r.start_date IS NOT NULL
  AND EXTRACT(YEAR FROM r.start_date) BETWEEN 2018 AND 2030
```

- [ ] **Step 2: Crea `v_spiaggia_cassa.sql`**

```sql
-- v_spiaggia_cassa
-- Cassa per giorno × metodo (decodificato). Somma netta (storni col segno).
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_cassa` AS
SELECT
  date AS giorno,
  EXTRACT(YEAR FROM date) AS anno,
  EXTRACT(MONTH FROM date) AS mese,
  method,
  method_label,
  COUNT(*) AS n_movimenti,
  SUM(amount) AS importo_netto
FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows`
WHERE deleted = FALSE
  AND date IS NOT NULL
  AND EXTRACT(YEAR FROM date) BETWEEN 2018 AND 2030
GROUP BY giorno, anno, mese, method, method_label
```

- [ ] **Step 3: Crea `v_spiaggia_occupazione.sql`**

```sql
-- v_spiaggia_occupazione
-- Occupazione ombrelloni per giorno: esplode i range [start,end] × ombrelloni.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_occupazione` AS
WITH giorni AS (
  SELECT
    r.spot_name,
    g AS giorno
  FROM `hotelops-suite.hotelops.f_spiaggia_reservations` r,
  UNNEST(GENERATE_DATE_ARRAY(r.start_date, r.end_date)) AS g
  WHERE r.deleted = FALSE
    AND r.spot_type = 'umbrella'
    AND r.start_date IS NOT NULL
    AND r.end_date IS NOT NULL
    AND r.end_date >= r.start_date
    AND EXTRACT(YEAR FROM r.start_date) BETWEEN 2018 AND 2030
),
tot AS (
  SELECT COUNT(*) AS n_ombrelloni
  FROM `hotelops-suite.hotelops.f_spiaggia_spots`
  WHERE type = 'umbrella'
)
SELECT
  giorno,
  EXTRACT(YEAR FROM giorno) AS anno,
  EXTRACT(MONTH FROM giorno) AS mese,
  COUNT(DISTINCT spot_name) AS ombrelloni_occupati,
  (SELECT n_ombrelloni FROM tot) AS ombrelloni_totali,
  SAFE_DIVIDE(COUNT(DISTINCT spot_name), (SELECT n_ombrelloni FROM tot)) AS occupazione_pct
FROM giorni
GROUP BY giorno, anno, mese
```

- [ ] **Step 4: Crea `v_spiaggia_kpi.sql`**

```sql
-- v_spiaggia_kpi
-- KPI mensili: prenotazioni, ricavo, cassa, scontrino medio, quota online/hotel.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_kpi` AS
WITH pren AS (
  SELECT
    EXTRACT(YEAR FROM start_date) AS anno,
    EXTRACT(MONTH FROM start_date) AS mese,
    COUNT(*) AS n_prenotazioni,
    SUM(gross_booking_value) AS ricavo,
    COUNTIF(online) AS n_online,
    COUNTIF(hotel IS NOT NULL AND hotel != '') AS n_hotel
  FROM `hotelops-suite.hotelops.f_spiaggia_reservations`
  WHERE deleted = FALSE
    AND start_date IS NOT NULL
    AND EXTRACT(YEAR FROM start_date) BETWEEN 2018 AND 2030
  GROUP BY anno, mese
),
cassa AS (
  SELECT
    EXTRACT(YEAR FROM date) AS anno,
    EXTRACT(MONTH FROM date) AS mese,
    SUM(amount) AS incassato
  FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows`
  WHERE deleted = FALSE
    AND date IS NOT NULL
    AND EXTRACT(YEAR FROM date) BETWEEN 2018 AND 2030
  GROUP BY anno, mese
)
SELECT
  p.anno,
  p.mese,
  p.n_prenotazioni,
  p.ricavo,
  c.incassato,
  SAFE_DIVIDE(p.ricavo, p.n_prenotazioni) AS scontrino_medio,
  SAFE_DIVIDE(p.n_online, p.n_prenotazioni) AS quota_online,
  SAFE_DIVIDE(p.n_hotel, p.n_prenotazioni) AS quota_hotel
FROM pren p
LEFT JOIN cassa c USING (anno, mese)
ORDER BY p.anno, p.mese
```

- [ ] **Step 5: Verifica l'ordine di deploy (dry-run, no scrittura)**

Run: `hotelops deploy-views --dry-run`
Expected: le 4 viste `v_spiaggia_*` compaiono nell'ordine di deploy senza errori di parsing/dipendenza.

- [ ] **Step 6: Commit**

```bash
git add core/bq/views/v_spiaggia_prenotazioni.sql core/bq/views/v_spiaggia_cassa.sql core/bq/views/v_spiaggia_occupazione.sql core/bq/views/v_spiaggia_kpi.sql
git commit -m "feat(spiaggia): 4 viste v_spiaggia_* (prenotazioni/cassa/occupazione/kpi)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: App Streamlit Panorama Beach

**Files:**
- Create: `verticals/spiaggia/__init__.py`
- Create: `verticals/spiaggia/app.py`

Pattern read-only allineato a `verticals/condges/audit_consumi_dashboard.py`: `get_client().query(...).to_dataframe()` con `@st.cache_data(ttl=300)`. Richiede `db-dtypes` (dashboard extras).

- [ ] **Step 1: Crea il package marker**

Crea `verticals/spiaggia/__init__.py` (file vuoto):

```python
```

- [ ] **Step 2: Crea l'app**

Crea `verticals/spiaggia/app.py`:

```python
"""Streamlit — vertical Spiaggia (Panorama Beach), interna/direzione.

Ricerca prenotazioni + KPI cassa/occupazione. Read-only su viste v_spiaggia_*.

Run: streamlit run verticals/spiaggia/app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bq.client import get_client
from core.config import PROJECT, DATASET

st.set_page_config(page_title="Panorama Beach", page_icon="🏖️", layout="wide")

# --- Brand Panorama Beach (approssimazione CSS, non il Design System web) ---
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&family=Jost:wght@300;400;500&display=swap');
    html, body, [class*="css"] { font-family: 'Jost', sans-serif; }
    .stApp { background-color: #fbf9f5; }
    h1, h2, h3 { font-family: 'Cinzel', serif; color: #003764; }
    .pb-sub { font-family: 'Cormorant Garamond', serif; color: #57c1e8; font-size: 1.2rem; }
    [data-testid="stMetricValue"] { color: #003764; font-family: 'Cinzel', serif; }
    .stButton>button { background-color: #57c1e8; color: #003764; border: none; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _q(sql: str) -> pd.DataFrame:
    return get_client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_kpi() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_kpi` ORDER BY anno, mese")


@st.cache_data(ttl=300)
def load_prenotazioni() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_prenotazioni`")


@st.cache_data(ttl=300)
def load_cassa() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_cassa`")


@st.cache_data(ttl=300)
def load_occupazione() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_occupazione` ORDER BY giorno")


st.title("Panorama Beach")
st.markdown('<div class="pb-sub">Prenotazioni · Cassa · Occupazione</div>', unsafe_allow_html=True)

kpi = load_kpi()
anni = sorted(kpi["anno"].dropna().unique().tolist(), reverse=True) if not kpi.empty else []
anno_sel = st.sidebar.selectbox("Anno", anni, index=0) if anni else None

# --- Header KPI (anno selezionato) ---
if anno_sel is not None:
    k = kpi[kpi["anno"] == anno_sel]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Prenotazioni", int(k["n_prenotazioni"].sum()))
    c2.metric("Ricavo", f"€ {k['ricavo'].sum():,.0f}")
    c3.metric("Incassato", f"€ {k['incassato'].sum():,.0f}")
    quota_online = k["n_online"].sum() / k["n_prenotazioni"].sum() if "n_online" in k else None
    online_pct = (k["quota_online"] * k["n_prenotazioni"]).sum() / k["n_prenotazioni"].sum() if not k.empty else 0
    hotel_pct = (k["quota_hotel"] * k["n_prenotazioni"]).sum() / k["n_prenotazioni"].sum() if not k.empty else 0
    c4.metric("Online %", f"{online_pct*100:,.0f}%")
    c5.metric("Hotel-linked %", f"{hotel_pct*100:,.0f}%")

# --- Ricerca prenotazioni ---
st.header("Cerca prenotazioni")
pren = load_prenotazioni()
fc1, fc2, fc3 = st.columns(3)
q_cliente = fc1.text_input("Cliente / email / telefono")
q_ombrellone = fc2.text_input("Ombrellone (spot_name)")
q_anno = fc3.selectbox("Anno prenotazione", ["(tutti)"] + [str(a) for a in anni]) if anni else "(tutti)"

view = pren.copy()
if q_anno not in ("(tutti)", "") and "anno" in view:
    view = view[view["anno"] == int(q_anno)]
if q_ombrellone:
    view = view[view["spot_name"].fillna("").str.contains(q_ombrellone, case=False)]
if q_cliente:
    mask = (
        view["first_name"].fillna("").str.contains(q_cliente, case=False)
        | view["last_name"].fillna("").str.contains(q_cliente, case=False)
        | view["email"].fillna("").str.contains(q_cliente, case=False)
        | view["phone"].fillna("").str.contains(q_cliente, case=False)
    )
    view = view[mask]

st.caption(f"{len(view)} prenotazioni")
st.dataframe(
    view[[
        "id", "start_date", "end_date", "spot_name", "first_name", "last_name",
        "email", "phone", "beds", "chairs", "gross_booking_value", "channel",
        "online", "hotel_linked",
    ]],
    use_container_width=True,
    height=400,
)

# --- Grafici ---
st.header("Andamenti")
g1, g2 = st.columns(2)
occ = load_occupazione()
if not occ.empty and anno_sel is not None:
    occ_y = occ[occ["anno"] == anno_sel]
    g1.subheader("Occupazione ombrelloni")
    g1.line_chart(occ_y.set_index("giorno")["occupazione_pct"])
cassa = load_cassa()
if not cassa.empty and anno_sel is not None:
    cassa_y = cassa[cassa["anno"] == anno_sel]
    per_metodo = cassa_y.groupby("method_label")["importo_netto"].sum()
    g2.subheader("Cassa per metodo")
    g2.bar_chart(per_metodo)
```

- [ ] **Step 3: Verifica che importa senza errori di sintassi**

Run: `python -c "import ast; ast.parse(open('verticals/spiaggia/app.py').read()); print('OK sintassi')"`
Expected: `OK sintassi`

- [ ] **Step 4: Lint**

Run: `ruff check verticals/spiaggia/`
Expected: nessun errore (rimuovi eventuali variabili inutilizzate segnalate, es. `quota_online` se ruff la flagga — è ridondante con `online_pct`).

- [ ] **Step 5: Commit**

```bash
git add verticals/spiaggia/__init__.py verticals/spiaggia/app.py
git commit -m "feat(spiaggia): app Streamlit Panorama Beach (ricerca + KPI)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: End-to-end — crea tabelle, intake, promote, verifica

> **Richiede credenziali GCP** (`gcloud` come `stefano@panoramagroup.it`) e accesso al bucket `hotelops-raw`. Se l'ambiente non ha credenziali, dichiaralo e fermati qui: i Task 1–9 sono già verificabili offline.

**Files:** nessuno (esecuzione operativa).

- [ ] **Step 1: Crea le 3 tabelle**

Run: `python -m core.bq.load.create_spiaggia_tables`
Expected: `OK f_spiaggia_reservations creata/confermata` (×3).

- [ ] **Step 2: Deploy delle viste**

Run: `hotelops deploy-views`
Expected: deploy senza errori; le 4 viste `v_spiaggia_*` create. (Possono dare 0 righe finché non si promuove il dump — atteso.)

- [ ] **Step 3: Intake del dump (RAW → GCS + f_raw_objects)**

Run: `hotelops intake "/Users/stefanodellapietra/Downloads/Booking Settings Panorama Beach June 13 2026.json" --source-name SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT`
Expected: stampa `raw_object_id=<id>`, blob su `gs://hotelops-raw/spiaggeit/spiaggia/INTUR/...`. Annota l'`<id>`.

- [ ] **Step 4: Promote (MANUAL → full-replace delle 3 tabelle)**

Run: `hotelops promote --raw-object-id <id>`
Expected: il parser scrive le 3 tabelle, stato → PROMOTED, exit 0.

- [ ] **Step 5: Verifica §6 — FK coverage**

Run:
```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) tot, COUNTIF(raw_object_id IS NOT NULL) con_fk FROM `hotelops-suite.hotelops.f_spiaggia_reservations`'
```
Expected: `tot == con_fk`, `tot` ≈ 33.805.

- [ ] **Step 6: Verifica §6 — integrità FK cash_flows → reservations + quadratura cassa**

Run:
```bash
bq query --use_legacy_sql=false 'SELECT COUNTIF(r.id IS NULL) orfani FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows` c LEFT JOIN `hotelops-suite.hotelops.f_spiaggia_reservations` r ON c.reservation_id = r.id WHERE c.reservation_id IS NOT NULL'
bq query --use_legacy_sql=false 'SELECT ROUND(SUM(amount),0) somma FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows`'
```
Expected: `orfani` basso/zero (alcune cash_flows possono riferire reservation deleted — annotalo se >0); `somma` ≈ 532.904.

- [ ] **Step 7: Verifica §6 — stato lineage PROMOTED**

Run:
```bash
bq query --use_legacy_sql=false 'SELECT raw_object_id, current_state FROM `hotelops-suite.hotelops.v_raw_objects_current` WHERE raw_object_id = "<id>"'
```
Expected: `PROMOTED`.

- [ ] **Step 8: Verifica idempotenza full-replace (re-promote)**

Run: `hotelops promote --raw-object-id <id>` di nuovo, poi ri-conta:
```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `hotelops-suite.hotelops.f_spiaggia_reservations`'
```
Expected: stesso count del Step 5 (full-replace idempotente, nessun raddoppio).

- [ ] **Step 9: Smoke dell'app**

Run: `streamlit run verticals/spiaggia/app.py`
Expected: l'app apre, KPI popolati, la ricerca per cliente/ombrellone filtra, i grafici si disegnano. (Verifica visiva.)

---

## Self-Review (eseguito in fase di stesura)

**1. Spec coverage:**
- Source registry entry → Task 7 ✓
- Parser fan-out 1→3 full-replace → Task 4–6 ✓ (full-replace via natural_key=["societa_id"], documentato)
- 3 tabelle canonical + DDL → Task 3 ✓
- 5 dimensioni (INTUR/LIDO/LIDO/spot_name/null) → Task 5 `_dims()` ✓
- coercion amount str→float, unix→date, raw_object_id stamp → Task 4–5 ✓
- 4 viste v_spiaggia_* → Task 8 ✓
- app Streamlit Panorama Beach cercabile → Task 9 ✓
- routine intake→promote dedup → Task 10 ✓
- verifica §6 (FK, count, PROMOTED) → Task 10 ✓
- **Deviazione**: `d_spiaggia_metodi` (CSV/loader/DDL) sostituita da dict `METHOD_LABELS` in-parser (flaggata in testa al piano e nell'handoff). Decodifica metodi comunque coperta (Task 5 `method_label`).

**2. Placeholder scan:** nessun TBD/TODO nei passi; `METHOD_LABELS` vuoto è una scelta documentata (legenda ignota), non un placeholder.

**3. Type consistency:** nomi modelli `SpiaggiaReservationRow`/`SpiaggiaCashFlowRow`/`SpiaggiaSpotRow` coerenti tra schemas (Task 2), parser (Task 4–6), test. Costanti `F_SPIAGGIA_*` coerenti tra config (Task 1), DDL (Task 3), parser (Task 6). `natural_key=["societa_id"]` coerente tra registry (Task 7) e parser (Task 6). `build_reservation_rows/build_cash_flow_rows/build_spot_rows` coerenti tra test e implementazione.
