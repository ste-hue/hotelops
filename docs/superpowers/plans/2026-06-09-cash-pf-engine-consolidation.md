# Cash/PF Engine Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidare la scrittura cash/PF dietro un solo service (`cash_pf_service`) che passa per il gate I1 `bq_write_validated`, rendendo `app_cdg` (Streamlit) e `update_previsione` (CLI/NanoClaw) gusci sottili.

**Architecture:** `verticals/condges/services/cash_pf_service.py` riceve intent tipizzati, costruisce righe Pydantic (`BudgetMensileRow`/`PianoFinanziarioInputRow`) e scrive **solo** via `bq_write_validated(mode="snapshot", natural_key=…)`. Le surface costruiscono l'intent e delegano; nessuna scrive più SQL/`load_table_from_json`. `cdg_engine` (compute puro) e `pf_rotate` (render) restano invariati.

**Tech Stack:** Python 3.11+, Pydantic v2, `google-cloud-bigquery`, pytest, ruff. Branch: `feat/cash-pf-engine`.

**Spec:** `docs/superpowers/specs/2026-06-09-cash-pf-engine-consolidation-design.md` (Metà A; non-goals: memory tables, collasso viste, P0, refactor pf_rotate interni).

---

## File Structure

- Create `verticals/condges/services/__init__.py` — package marker.
- Create `verticals/condges/services/intents.py` — dataclass intent/result (nessuna logica BQ).
- Create `verticals/condges/services/cash_pf_service.py` — `save_budget`, `save_previsione`; unico chiamante del gate per cash/PF.
- Create `tests/test_cash_pf_service.py` — gate-usato, parità, validazione, regressione.
- Modify `verticals/condges/app_cdg.py` — `save_to_bq()` (≈458–504) delega al service.
- Modify `verticals/condges/update_previsione.py` — `update_previsione()` (63–187) delega il write al service.
- Modify `verticals/condges/pf_rotate/rotate.py` — docstring: etichetta render/export adapter.

**Verified primitives (do not re-derive):**
- Gate: `from core.bq.write import bq_write_validated` — `(table, rows: list[BaseModel], mode, natural_key)`; `mode="snapshot"` = DELETE+INSERT chirurgico per `natural_key`.
- Models: `from core.schemas import BudgetMensileRow, PianoFinanziarioInputRow` (`data_caricamento` è **required**, ISO string).
- Config: `from core.config import F_BUDGET_MENSILE, F_PIANO_FINANZIARIO_INPUT`.
- `BudgetMensileRow` campi: societa_id, anno, mese, codice_conto, descrizione?, tipo_costo?, categoria_ce?, business_unit_id?, importo, fonte, data_caricamento, raw_object_id?.
- `PianoFinanziarioInputRow` campi: hash_riga, societa_id, voce_id, anno, mese, importo?, fonte, note?, file_sorgente?, data_caricamento, raw_object_id?.

---

## Task 1: Scaffold services package + intents

**Files:**
- Create: `verticals/condges/services/__init__.py`
- Create: `verticals/condges/services/intents.py`
- Test: `tests/test_cash_pf_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cash_pf_service.py
from verticals.condges.services.intents import (
    BudgetRiga, SaveBudgetIntent, SavePrevisioneIntent, SaveResult,
)


def test_intents_construct():
    riga = BudgetRiga(
        mese=4, codice_conto="570913", descrizione="Utenze",
        tipo_costo="VARIABILE", categoria_ce="COSTI", business_unit_id="HOTEL",
        importo=22000.0,
    )
    b = SaveBudgetIntent(societa_id="ORTI", anno=2026, righe=[riga])
    assert b.fonte == "APP_BUDGET"
    assert b.righe[0].mese == 4

    p = SavePrevisioneIntent(
        societa_id="ORTI", voce_id="USCITE_UTENZE", mesi=[4, 5], importo=22000.0, anno=2026,
    )
    assert p.fonte == "NANOCLAW"

    r = SaveResult(table="t", rows_written=2, natural_key=["a"])
    assert r.rows_written == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cash_pf_service.py::test_intents_construct -v`
Expected: FAIL — `ModuleNotFoundError: verticals.condges.services`

- [ ] **Step 3: Create the package marker**

```python
# verticals/condges/services/__init__.py
"""Service layer condges: orchestrazione fetch→compute→write per le surface."""
```

- [ ] **Step 4: Create intents.py**

```python
# verticals/condges/services/intents.py
"""Intent/result tipizzati tra surface e service. Nessuna logica BQ qui."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetRiga:
    mese: int
    codice_conto: str
    importo: float
    descrizione: str | None = None
    tipo_costo: str | None = None
    categoria_ce: str | None = None
    business_unit_id: str | None = None


@dataclass(frozen=True)
class SaveBudgetIntent:
    societa_id: str
    anno: int
    righe: list[BudgetRiga]
    fonte: str = "APP_BUDGET"


@dataclass(frozen=True)
class SavePrevisioneIntent:
    societa_id: str
    voce_id: str
    mesi: list[int]
    importo: float
    anno: int
    fonte: str = "NANOCLAW"
    note: str | None = None


@dataclass(frozen=True)
class SaveResult:
    table: str
    rows_written: int
    natural_key: list[str] = field(default_factory=list)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cash_pf_service.py::test_intents_construct -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/services/__init__.py verticals/condges/services/intents.py tests/test_cash_pf_service.py
git commit -m "feat(condges): scaffold cash/PF service package + intents"
```

---

## Task 2: `cash_pf_service.save_budget` via gate

**Files:**
- Create: `verticals/condges/services/cash_pf_service.py`
- Test: `tests/test_cash_pf_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cash_pf_service.py  (append)
from unittest.mock import patch
from core.schemas import BudgetMensileRow
from verticals.condges.services import cash_pf_service
from verticals.condges.services.intents import BudgetRiga, SaveBudgetIntent


def test_save_budget_calls_gate_snapshot():
    intent = SaveBudgetIntent(
        societa_id="ORTI", anno=2026,
        righe=[
            BudgetRiga(mese=4, codice_conto="570913", descrizione="Utenze",
                       tipo_costo="VARIABILE", categoria_ce="COSTI",
                       business_unit_id="HOTEL", importo=22000.0),
            BudgetRiga(mese=5, codice_conto="570913", importo=21000.0),
        ],
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        result = cash_pf_service.save_budget(intent)

    gate.assert_called_once()
    args, kwargs = gate.call_args
    table, rows = args[0], args[1]
    assert table.endswith("f_budget_mensile")
    assert kwargs["mode"] == "snapshot"
    assert kwargs["natural_key"] == ["societa_id", "anno", "fonte"]
    assert all(isinstance(r, BudgetMensileRow) for r in rows)
    assert rows[0].fonte == "APP_BUDGET"
    assert rows[0].data_caricamento  # required field popolato
    assert result.rows_written == 2


def test_save_budget_rejects_bad_row():
    import pytest
    bad = SaveBudgetIntent(
        societa_id="ORTI", anno=2026,
        righe=[BudgetRiga(mese=13, codice_conto="570913", importo=1.0)],  # mese fuori range
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        with pytest.raises(Exception):
            cash_pf_service.save_budget(bad)
        gate.assert_not_called()  # fallisce alla validazione, prima del gate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cash_pf_service.py::test_save_budget_calls_gate_snapshot -v`
Expected: FAIL — `ModuleNotFoundError` / `cash_pf_service` non esiste

- [ ] **Step 3: Implement cash_pf_service.save_budget**

```python
# verticals/condges/services/cash_pf_service.py
"""Service cash/PF: unico writer canonical per budget e previsione (gate I1)."""

from __future__ import annotations

from datetime import datetime, timezone

from core.bq.write import bq_write_validated
from core.config import F_BUDGET_MENSILE
from core.schemas import BudgetMensileRow
from verticals.condges.services.intents import SaveBudgetIntent, SaveResult

_BUDGET_NATURAL_KEY = ["societa_id", "anno", "fonte"]


def save_budget(intent: SaveBudgetIntent) -> SaveResult:
    """DELETE+INSERT chirurgico di f_budget_mensile per (societa_id, anno, fonte)."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        BudgetMensileRow(
            societa_id=intent.societa_id,
            anno=intent.anno,
            mese=int(r.mese),
            codice_conto=r.codice_conto,
            descrizione=r.descrizione,
            tipo_costo=r.tipo_costo,
            categoria_ce=r.categoria_ce,
            business_unit_id=r.business_unit_id,
            importo=round(float(r.importo), 2),
            fonte=intent.fonte,
            data_caricamento=now,
        )
        for r in intent.righe
    ]
    bq_write_validated(
        str(F_BUDGET_MENSILE), rows, mode="snapshot", natural_key=_BUDGET_NATURAL_KEY
    )
    return SaveResult(str(F_BUDGET_MENSILE), len(rows), _BUDGET_NATURAL_KEY)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cash_pf_service.py -v -k save_budget`
Expected: PASS (both `test_save_budget_calls_gate_snapshot`, `test_save_budget_rejects_bad_row`)

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/services/cash_pf_service.py tests/test_cash_pf_service.py
git commit -m "feat(condges): cash_pf_service.save_budget via gate I1 (snapshot)"
```

---

## Task 3: `cash_pf_service.save_previsione` via gate

**Files:**
- Modify: `verticals/condges/services/cash_pf_service.py`
- Test: `tests/test_cash_pf_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cash_pf_service.py  (append)
from core.schemas import PianoFinanziarioInputRow
from verticals.condges.services.intents import SavePrevisioneIntent


def test_save_previsione_calls_gate_snapshot():
    intent = SavePrevisioneIntent(
        societa_id="ORTI", voce_id="USCITE_UTENZE", mesi=[4, 5, 6],
        importo=22000.0, anno=2026,
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        result = cash_pf_service.save_previsione(intent)

    args, kwargs = gate.call_args
    table, rows = args[0], args[1]
    assert table.endswith("f_piano_finanziario_input")
    assert kwargs["mode"] == "snapshot"
    assert kwargs["natural_key"] == ["societa_id", "voce_id", "anno", "mese", "fonte"]
    assert all(isinstance(r, PianoFinanziarioInputRow) for r in rows)
    assert {r.mese for r in rows} == {4, 5, 6}
    # hash deterministico e stabile per (societa, voce, anno, mese, fonte)
    assert rows[0].hash_riga and len(rows[0].hash_riga) == 32
    assert result.rows_written == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cash_pf_service.py::test_save_previsione_calls_gate_snapshot -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'save_previsione'`

- [ ] **Step 3: Implement save_previsione (append to cash_pf_service.py)**

```python
# verticals/condges/services/cash_pf_service.py  (append imports + function)
import hashlib

from core.config import F_PIANO_FINANZIARIO_INPUT
from core.schemas import PianoFinanziarioInputRow
from verticals.condges.services.intents import SavePrevisioneIntent

_PREVISIONE_NATURAL_KEY = ["societa_id", "voce_id", "anno", "mese", "fonte"]


def _previsione_hash(societa_id: str, voce_id: str, anno: int, mese: int, fonte: str) -> str:
    raw = f"{societa_id}|{voce_id}|{anno}|{mese}|{fonte}"
    return hashlib.md5(raw.encode()).hexdigest()


def save_previsione(intent: SavePrevisioneIntent) -> SaveResult:
    """DELETE+INSERT per (societa_id, voce_id, anno, mese, fonte)."""
    now = datetime.now(timezone.utc)
    rows = [
        PianoFinanziarioInputRow(
            hash_riga=_previsione_hash(
                intent.societa_id, intent.voce_id, intent.anno, mese, intent.fonte
            ),
            societa_id=intent.societa_id,
            voce_id=intent.voce_id,
            anno=intent.anno,
            mese=int(mese),
            importo=round(float(intent.importo), 2),
            fonte=intent.fonte,
            note=intent.note,
            file_sorgente=f"service:{now.strftime('%Y-%m-%d %H:%M')}",
            data_caricamento=now.isoformat(),
        )
        for mese in intent.mesi
    ]
    bq_write_validated(
        str(F_PIANO_FINANZIARIO_INPUT), rows, mode="snapshot",
        natural_key=_PREVISIONE_NATURAL_KEY,
    )
    return SaveResult(str(F_PIANO_FINANZIARIO_INPUT), len(rows), _PREVISIONE_NATURAL_KEY)
```

> Nota: l'hash replica `update_previsione._hash` (`societa|voce|anno|mese|fonte`, md5). Verifica in Task 5 che combaci.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cash_pf_service.py -v`
Expected: PASS (tutti)

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/services/cash_pf_service.py tests/test_cash_pf_service.py
git commit -m "feat(condges): cash_pf_service.save_previsione via gate I1 (snapshot)"
```

---

## Task 4: Migrare `app_cdg.save_to_bq` a delegare al service

**Files:**
- Modify: `verticals/condges/app_cdg.py` (`save_to_bq`, ≈458–504)
- Test: `tests/test_cash_pf_service.py`

- [ ] **Step 1: Write the failing regression test**

```python
# tests/test_cash_pf_service.py  (append)
import re
from pathlib import Path


def test_app_cdg_has_no_direct_canonical_write():
    src = Path("verticals/condges/app_cdg.py").read_text()
    assert "load_table_from_json" not in src, "app_cdg deve delegare al service"
    assert not re.search(r"DELETE\s+FROM", src, re.IGNORECASE), "no DELETE diretto in surface"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cash_pf_service.py::test_app_cdg_has_no_direct_canonical_write -v`
Expected: FAIL — `app_cdg` contiene ancora `load_table_from_json` e `DELETE FROM`

- [ ] **Step 3: Replace `save_to_bq` body (delegate)**

Sostituisci l'intera funzione `save_to_bq` (≈458–504) con:

```python
def save_to_bq(df: pd.DataFrame):
    """DELETE-INSERT budget fonte=APP_BUDGET — delega al service (gate I1)."""
    from verticals.condges.services import cash_pf_service
    from verticals.condges.services.intents import BudgetRiga, SaveBudgetIntent

    righe = [
        BudgetRiga(
            mese=int(r["mese"]),
            codice_conto=r["codice_conto"],
            descrizione=r["descrizione"],
            tipo_costo=r["tipo_costo"],
            categoria_ce=r["categoria_ce"],
            business_unit_id=r.get("business_unit_id"),
            importo=round(float(r["importo"]), 2),
        )
        for _, r in df.iterrows()
    ]
    return cash_pf_service.save_budget(
        SaveBudgetIntent(societa_id=SOCIETA, anno=ANNO, righe=righe)
    )
```

Rimuovi l'import locale `from google.cloud import bigquery` **dentro** la vecchia `save_to_bq` (non c'è più nel nuovo corpo). Se `bigquery` non è usato altrove in `app_cdg.py`, rimuovi anche l'import a livello modulo (verifica: `grep -n "bigquery" verticals/condges/app_cdg.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cash_pf_service.py -v`
Expected: PASS (incluso `test_app_cdg_has_no_direct_canonical_write`)

- [ ] **Step 5: Verify app_cdg still imports cleanly**

Run: `python -c "import ast; ast.parse(open('verticals/condges/app_cdg.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/app_cdg.py tests/test_cash_pf_service.py
git commit -m "refactor(condges): app_cdg.save_to_bq delega a cash_pf_service (no canonical write in surface)"
```

---

## Task 5: Ri-puntare `update_previsione` al service

**Files:**
- Modify: `verticals/condges/update_previsione.py` (`update_previsione`, 63–187)
- Test: `tests/test_cash_pf_service.py`

- [ ] **Step 1: Write the failing test (hash parity + delega)**

```python
# tests/test_cash_pf_service.py  (append)
def test_update_previsione_hash_matches_service():
    from verticals.condges import update_previsione as up
    from verticals.condges.services.cash_pf_service import _previsione_hash
    assert up._hash("ORTI", "USCITE_UTENZE", 2026, 4, "NANOCLAW") == \
        _previsione_hash("ORTI", "USCITE_UTENZE", 2026, 4, "NANOCLAW")
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_cash_pf_service.py::test_update_previsione_hash_matches_service -v`
Expected: PASS se `_hash` già usa `societa|voce|anno|mese|fonte` md5; se FAIL, allinea `_previsione_hash` a `up._hash` (copiare la formula esatta da `update_previsione._hash`). Non procedere finché non combaciano.

- [ ] **Step 3: Replace the write block in `update_previsione()`**

Sostituisci il blocco DELETE+INSERT (righe ≈145–187, da `# DELETE existing rows` fino a `job.result()`) con la delega al service, preservando return/dry-run/validazione voce a monte:

```python
    # Write via service (gate I1) — un solo writer per Streamlit/CLI/NanoClaw
    from verticals.condges.services import cash_pf_service
    from verticals.condges.services.intents import SavePrevisioneIntent

    result = cash_pf_service.save_previsione(
        SavePrevisioneIntent(
            societa_id=societa_id,
            voce_id=voce_id,
            mesi=mesi,
            importo=importo_mensile,
            anno=anno,
            fonte=fonte,
            note=note,
        )
    )
    rows_written = result.rows_written
```

Aggiorna il `return {...}` finale a usare `rows_written` (sostituendo eventuali riferimenti a `rows_deleted`/`new_rows`). Rimuovi gli import/righe ora orfani: `from google.cloud import bigquery` (se non più usato nella funzione), `validate_batch` se non più referenziato (`grep -n "validate_batch" verticals/condges/update_previsione.py`).

- [ ] **Step 4: Run the targeted + full condges tests**

Run: `pytest tests/test_cash_pf_service.py tests/test_cdg_engine.py -v`
Expected: PASS. `cdg_engine` invariato; nessuna regressione.

- [ ] **Step 5: Verify module parses + no orphan imports**

Run: `python -c "import ast; ast.parse(open('verticals/condges/update_previsione.py').read()); print('OK')" && ruff check verticals/condges/update_previsione.py`
Expected: `OK` e ruff senza errori (F401 unused import incluso).

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/update_previsione.py tests/test_cash_pf_service.py
git commit -m "refactor(condges): update_previsione delega a cash_pf_service (writer previsione unico)"
```

---

## Task 6: Etichettare `pf_rotate` come render/export adapter

**Files:**
- Modify: `verticals/condges/pf_rotate/rotate.py` (docstring modulo)

- [ ] **Step 1: Add the adapter note to the module docstring**

In cima a `verticals/condges/pf_rotate/rotate.py`, aggiungi/estendi il docstring di modulo:

```python
"""PF rotation — RENDER/EXPORT ADAPTER.

Non possiede stato: l'authority del cash/PF è BigQuery (vedi
docs/superpowers/specs/2026-06-09-cash-pf-engine-consolidation-design.md).
Questo modulo produce l'artefatto Excel post-rotate a partire dai dati BQ;
non è la fonte di verità della proiezione. Le scritture canonical passano
dal service (cash_pf_service → gate I1), mai da qui.
"""
```

(Se esiste già un docstring, prependi questa nota senza rimuovere il contenuto esistente.)

- [ ] **Step 2: Verify it still parses**

Run: `python -c "import ast; ast.parse(open('verticals/condges/pf_rotate/rotate.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/pf_rotate/rotate.py
git commit -m "docs(condges): pf_rotate etichettato render/export adapter (BQ authority)"
```

---

## Task 7: Green finale (lint + full suite)

**Files:** nessuno nuovo.

- [ ] **Step 1: Format + lint**

Run: `ruff format . && ruff check .`
Expected: nessun errore. Fix eventuali F401/E501 introdotti.

- [ ] **Step 2: Full test suite**

Run: `pytest -q`
Expected: tutti verdi (in particolare `test_cash_pf_service.py` e `test_cdg_engine.py`).

- [ ] **Step 3: Smoke import delle surface**

Run: `python -c "import ast; [ast.parse(open(f).read()) for f in ['verticals/condges/app_cdg.py','verticals/condges/update_previsione.py','verticals/condges/services/cash_pf_service.py']]; print('surfaces+service parse OK')"`
Expected: `surfaces+service parse OK`

- [ ] **Step 4: Commit (se ruff ha riformattato)**

```bash
git add -A
git commit -m "chore(condges): ruff format + green suite for cash/PF service slice" || echo "nothing to commit"
```

---

## Definition of Done

- `verticals/condges/services/cash_pf_service.py` è l'**unico** writer di `f_budget_mensile` e `f_piano_finanziario_input` nel cash/PF, sempre via `bq_write_validated`.
- `app_cdg.py` non contiene più `load_table_from_json`/`DELETE FROM` (test di regressione verde).
- Un solo writer previsione condiviso Streamlit/CLI/NanoClaw (hash parity verificata).
- `pf_rotate` etichettato render adapter; `cdg_engine` invariato.
- `pytest -q` e `ruff check .` verdi.

**Smoke manuale (post-merge, fuori dal piano automatico):** da Streamlit `app_cdg`, modifica budget → Salva → la riga compare in `f_budget_mensile` fonte=APP_BUDGET con lo stesso conteggio di prima e il log mostra il passaggio dal gate.

## Out of scope (Metà B — non in questo piano)

Nessuna memory table (`f_cash_projection_runs`, `f_decisioni`, evaluations); nessun collasso `v_previsione_cassa`+scadenzario → `v_cash_projection_current`; nessun P0 re-baseline; nessun refactor interni `pf_rotate`; consolidamento delle **letture** (le 6 query inline di `app_cdg`) rimandato a giro successivo.
