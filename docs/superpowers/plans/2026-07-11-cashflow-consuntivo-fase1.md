# Cashflow Consuntivo — Fase 1 (Livelli A+B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire i Livelli A (cash position per conto, quadratura sui saldi certificati) e B (cash flow consolidato per società, trasferimenti interni neutralizzati) del cashflow consuntivo, con superficie nel hub — v1 su giugno 2026.

**Architecture:** Livello A = vista BQ pura (`v_cash_position`: movimenti lordi per conto + anchor `f_saldi_banca_chiusura_mensile`). Livello B = modulo dati Python (pattern VERTICAL_VIEW_PATTERN: `_data.py` puro e testabile, zero import Streamlit) con matcher deterministico dei trasferimenti interni, montato come pagina hub via registry. Nessuna scrittura su BQ: tutto read-only su fatti esistenti.

**Tech Stack:** BigQuery (vista SQL via `hotelops deploy-views`), Python 3.11+, pytest (marker `@pytest.mark.bq` per i test live), Streamlit (solo nel modulo dashboard), hub registry.

**Spec:** `docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md` (Livelli A e B; C/C.2/D = piani successivi).

## Global Constraints

- **Read-only su BQ**: nessuna scrittura in tabelle `f_*`/`d_*`; l'unica DDL è `CREATE OR REPLACE VIEW` via `hotelops deploy-views`.
- **Livello A usa i LORDI per conto**: nessuna esclusione di partite di giro/trasferimenti (romperebbe la quadratura). Filtra SOLO le righe-junk (`descrizione IN ('Totale (€)','TOTALE')` o NULL) come fa `v_cashflow_mensile`.
- **Livello B neutralizza i trasferimenti SOLO al consolidato di società**; i trasferimenti sono mostrati in colonna dedicata, mai nascosti.
- **Naming honesty**: mai la parola "non registrato" in questa fase (arriva con C.2); lo scarto di quadratura si chiama `scarto`.
- Convenzione segni: `f_banche_movimenti.importo_netto > 0` = entrata.
- Anchor: `f_saldi_banca_chiusura_mensile(societa_id, data_riferimento DATE, banca_id, saldo_eur)`; il saldo del mese M è a `LAST_DAY(M)`.
- Pattern moduli: `cashflow_consuntivo_data.py` senza import Streamlit (testabile con pytest); `render()` nella pagina hub senza `st.set_page_config`.
- `ruff format` solo sui file toccati. Commit atomici a fine task.
- Test BQ live: `@pytest.mark.bq` + fixture `bq_client` (vedi `tests/test_budget_canonical.py:32` per lo stile).

---

### Task 1: Vista `v_cash_position` (Livello A)

**Files:**
- Create: `core/bq/views/v_cash_position.sql`
- Test: `tests/test_cash_position_view.py`

**Interfaces:**
- Consumes: `hotelops.f_banche_movimenti`, `hotelops.f_saldi_banca_chiusura_mensile` (esistenti).
- Produces: vista `hotelops-suite.hotelops.v_cash_position` con colonne
  `(mese DATE, societa_id STRING, banca_id STRING, saldo_iniziale_cert FLOAT64, accrediti FLOAT64, addebiti FLOAT64, netto FLOAT64, saldo_calcolato FLOAT64, saldo_finale_cert FLOAT64, scarto FLOAT64)` — Task 4 la legge così.

- [ ] **Step 1: Scrivere la vista**

```sql
-- View: hotelops.v_cash_position
-- Livello A del cashflow consuntivo (spec 2026-07-11-cashflow-consuntivo-design.md).
-- Quadratura per conto sui movimenti LORDI: saldo_iniziale_cert + netto = saldo_finale_cert.
-- NIENTE esclusione di giri/trasferimenti qui: si neutralizzano solo al Livello B (consolidato).
-- saldo_*_cert NULL = anchor mancante per quel mese (non un errore della vista).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_cash_position` AS

WITH mov AS (
  SELECT
    DATE_TRUNC(data_operazione, MONTH) AS mese,
    societa_id,
    banca_id,
    ROUND(SUM(CASE WHEN importo_netto > 0 THEN importo_netto ELSE 0 END), 2) AS accrediti,
    ROUND(SUM(CASE WHEN importo_netto < 0 THEN ABS(importo_netto) ELSE 0 END), 2) AS addebiti,
    ROUND(SUM(importo_netto), 2) AS netto
  FROM hotelops.f_banche_movimenti
  WHERE descrizione IS NOT NULL
    AND descrizione NOT IN ('Totale (€)', 'TOTALE')
  GROUP BY 1, 2, 3
),

anchor AS (
  SELECT
    DATE_TRUNC(data_riferimento, MONTH) AS mese,
    societa_id,
    banca_id,
    saldo_eur
  FROM hotelops.f_saldi_banca_chiusura_mensile
  WHERE data_riferimento = LAST_DAY(data_riferimento)
)

SELECT
  m.mese,
  m.societa_id,
  m.banca_id,
  a_prev.saldo_eur AS saldo_iniziale_cert,
  m.accrediti,
  m.addebiti,
  m.netto,
  ROUND(a_prev.saldo_eur + m.netto, 2) AS saldo_calcolato,
  a_fine.saldo_eur AS saldo_finale_cert,
  ROUND(a_prev.saldo_eur + m.netto - a_fine.saldo_eur, 2) AS scarto
FROM mov m
LEFT JOIN anchor a_prev
  ON a_prev.societa_id = m.societa_id
 AND a_prev.banca_id = m.banca_id
 AND a_prev.mese = DATE_SUB(m.mese, INTERVAL 1 MONTH)
LEFT JOIN anchor a_fine
  ON a_fine.societa_id = m.societa_id
 AND a_fine.banca_id = m.banca_id
 AND a_fine.mese = m.mese
```

- [ ] **Step 2: Scrivere i test (falliranno finché la vista non è deployata)**

```python
"""Test v_cash_position (Livello A cashflow consuntivo).

Query live su BigQuery: marcati @pytest.mark.bq (skippati in CI senza credenziali).
"""

import pytest


@pytest.mark.bq
def test_grain_unico(bq_client):
    """Una sola riga per (mese, societa_id, banca_id)."""
    sql = """
    SELECT mese, societa_id, banca_id, COUNT(*) n
    FROM `hotelops-suite.hotelops.v_cash_position`
    GROUP BY 1, 2, 3
    HAVING n > 1
    LIMIT 5
    """
    rows = list(bq_client.query(sql).result())
    assert rows == [], f"grain duplicato: {rows}"


@pytest.mark.bq
def test_scarto_coerente_con_formula(bq_client):
    """scarto = saldo_iniziale_cert + netto - saldo_finale_cert (dove gli anchor esistono)."""
    sql = """
    SELECT COUNT(*) n
    FROM `hotelops-suite.hotelops.v_cash_position`
    WHERE saldo_iniziale_cert IS NOT NULL AND saldo_finale_cert IS NOT NULL
      AND ABS(scarto - ROUND(saldo_iniziale_cert + netto - saldo_finale_cert, 2)) > 0.01
    """
    n = list(bq_client.query(sql).result())[0].n
    assert n == 0


@pytest.mark.bq
def test_giugno_orti_mps_presente_con_anchor(bq_client):
    """Il caso pilota (giugno 2026 ORTI/MPS) ha entrambi gli anchor e movimenti."""
    sql = """
    SELECT saldo_iniziale_cert, saldo_finale_cert, accrediti, addebiti
    FROM `hotelops-suite.hotelops.v_cash_position`
    WHERE mese = '2026-06-01' AND societa_id = 'ORTI' AND banca_id = 'MPS'
    """
    rows = list(bq_client.query(sql).result())
    assert len(rows) == 1
    r = rows[0]
    assert r.saldo_iniziale_cert == 469192.55
    assert r.saldo_finale_cert == 791654.10
    assert r.accrediti > 0 and r.addebiti > 0
```

- [ ] **Step 3: Verificare che i test falliscano (vista inesistente)**

Run: `python -m pytest tests/test_cash_position_view.py -v -m bq`
Expected: FAIL/ERROR con "Not found: Table/View ... v_cash_position"

- [ ] **Step 4: Deployare la vista**

Run: `hotelops deploy-views --dry-run` (verifica che `v_cash_position` compaia), poi `hotelops deploy-views`
Expected: `v_cash_position` deployata senza errori.

- [ ] **Step 5: Verificare che i test passino**

Run: `python -m pytest tests/test_cash_position_view.py -v -m bq`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add core/bq/views/v_cash_position.sql tests/test_cash_position_view.py
git commit -m "feat(condges): v_cash_position — Livello A cashflow consuntivo (quadratura lordi per conto su saldi certificati)"
```

---

### Task 2: Matcher trasferimenti interni (Livello B, funzione pura)

**Files:**
- Create: `verticals/condges/cashflow_consuntivo_data.py`
- Test: `tests/test_cashflow_consuntivo.py`

**Interfaces:**
- Consumes: niente dal resto del sistema (funzione pura su liste di dict).
- Produces: `detect_trasferimenti_interni(movimenti: list[dict], window_days: int = 3) -> list[dict]` — ritorna gli STESSI dict arricchiti di `transfer_status` (`"AUTO" | "CANDIDATE" | None`) e `transfer_group` (int | None, stesso id per le due gambe). Ogni movimento in input ha almeno: `id_movimento, banca_id, data_operazione (datetime.date), importo_netto (float), descrizione (str)`. Task 3 e Task 4 dipendono da questa firma.

Regole (dalla spec, deterministic-first):
1. Coppia **cross-banca**: stesso `abs(importo_netto)` (tolleranza 0.01), segni opposti, banche diverse, `|Δdata| <= window_days` → se la coppia è UNIVOCA (nessun altro candidato per nessuna delle due gambe) → entrambe `AUTO`, stesso `transfer_group`.
2. Coppia **stessa banca** con pattern causale (`GIROCONTO`, `ASS. CIRCOLAR`, `ASSEGNO CIRCOLARE`, `VERSAMENTO NS`, case-insensitive su `descrizione`): stesse condizioni di importo/finestra → `AUTO`.
3. Candidati **ambigui** (più di un pairing possibile): tutte le gambe coinvolte → `CANDIDATE`, `transfer_group=None`, MAI neutralizzate automaticamente.
4. Pairing greedy: tra i candidati univoci, accoppia prima le coppie con distanza data minore; ogni movimento appartiene ad al più un gruppo.

- [ ] **Step 1: Scrivere i test (falliscono: modulo inesistente)**

```python
"""Test Livello B — matcher trasferimenti interni e consolidato società."""

from datetime import date

from verticals.condges.cashflow_consuntivo_data import (
    consolidato_societa,
    detect_trasferimenti_interni,
)


def _mov(idx, banca, giorno, importo, descr="BONIFICO"):
    return {
        "id_movimento": f"m{idx}",
        "banca_id": banca,
        "data_operazione": date(2026, 6, giorno),
        "importo_netto": importo,
        "descrizione": descr,
    }


def test_coppia_cross_banca_univoca_e_auto():
    movs = [
        _mov(1, "INTESA", 10, -100_000.0, "Bon. a vostro favore"),
        _mov(2, "MPS", 11, +100_000.0, "Bonifico in entrata"),
        _mov(3, "MPS", 12, -500.0, "F24"),
    ]
    out = detect_trasferimenti_interni(movs)
    by_id = {m["id_movimento"]: m for m in out}
    assert by_id["m1"]["transfer_status"] == "AUTO"
    assert by_id["m2"]["transfer_status"] == "AUTO"
    assert by_id["m1"]["transfer_group"] == by_id["m2"]["transfer_group"]
    assert by_id["m3"]["transfer_status"] is None


def test_fuori_finestra_non_matcha():
    movs = [
        _mov(1, "INTESA", 1, -50_000.0),
        _mov(2, "MPS", 20, +50_000.0),
    ]
    out = detect_trasferimenti_interni(movs, window_days=3)
    assert all(m["transfer_status"] is None for m in out)


def test_ambiguo_diventa_candidate_mai_auto():
    movs = [
        _mov(1, "INTESA", 10, -10_000.0),
        _mov(2, "MPS", 10, +10_000.0),
        _mov(3, "SELLA", 11, +10_000.0),
    ]
    out = detect_trasferimenti_interni(movs)
    assert {m["transfer_status"] for m in out} == {"CANDIDATE"}
    assert all(m["transfer_group"] is None for m in out)


def test_stessa_banca_solo_con_pattern_causale():
    con_pattern = [
        _mov(1, "MPS", 5, -20_000.0, "Emissione ass. circolari"),
        _mov(2, "MPS", 7, +20_000.0, "Versamento ns. a/c"),
    ]
    out = detect_trasferimenti_interni(con_pattern)
    assert all(m["transfer_status"] == "AUTO" for m in out)

    senza_pattern = [
        _mov(1, "MPS", 5, -20_000.0, "Pagamento fornitore"),
        _mov(2, "MPS", 7, +20_000.0, "Incasso cliente"),
    ]
    out2 = detect_trasferimenti_interni(senza_pattern)
    assert all(m["transfer_status"] is None for m in out2)


def test_greedy_preferisce_distanza_minore():
    movs = [
        _mov(1, "INTESA", 10, -5_000.0),
        _mov(2, "MPS", 10, +5_000.0),
        _mov(3, "INTESA", 15, -5_000.0),
        _mov(4, "MPS", 16, +5_000.0),
    ]
    out = detect_trasferimenti_interni(movs, window_days=3)
    by_id = {m["id_movimento"]: m for m in out}
    assert by_id["m1"]["transfer_group"] == by_id["m2"]["transfer_group"]
    assert by_id["m3"]["transfer_group"] == by_id["m4"]["transfer_group"]
    assert by_id["m1"]["transfer_group"] != by_id["m3"]["transfer_group"]
```

(Nota: `consolidato_societa` è importato già qui ma testato nel Task 3 — l'import fallirà finché il Task 3 non definisce la funzione; per questo task definire anche uno stub `def consolidato_societa(...): raise NotImplementedError` così i test del Task 2 girano.)

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/test_cashflow_consuntivo.py -v -k trasferimenti or coppia or ambiguo or banca or greedy or finestra`
Expected: FAIL con "No module named 'verticals.condges.cashflow_consuntivo_data'"

- [ ] **Step 3: Implementazione minima**

```python
"""Livello B del cashflow consuntivo — dati puri, zero import Streamlit.

Spec: docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md.
I trasferimenti interni si neutralizzano SOLO al consolidato di società (Livello B);
il Livello A (v_cash_position) resta sui lordi per conto.
"""

from __future__ import annotations

import re
from datetime import date

_PATTERN_GIRO = re.compile(
    r"GIROCONTO|ASS\.? ?CIRCOLAR|ASSEGNO CIRCOLARE|VERSAMENTO NS", re.IGNORECASE
)


def detect_trasferimenti_interni(
    movimenti: list[dict], window_days: int = 3
) -> list[dict]:
    """Tagga i trasferimenti interni fra conti della stessa società.

    Ritorna gli stessi dict con transfer_status ('AUTO'|'CANDIDATE'|None)
    e transfer_group (int|None). Deterministic-first: solo coppie univoche
    diventano AUTO; ambiguità → CANDIDATE, mai neutralizzate.
    """
    out = [dict(m, transfer_status=None, transfer_group=None) for m in movimenti]

    def compatibile(a: dict, b: dict) -> bool:
        if abs(abs(a["importo_netto"]) - abs(b["importo_netto"])) > 0.01:
            return False
        if (a["importo_netto"] > 0) == (b["importo_netto"] > 0):
            return False
        if abs((a["data_operazione"] - b["data_operazione"]).days) > window_days:
            return False
        if a["banca_id"] == b["banca_id"]:
            # stessa banca: solo con pattern causale su almeno una gamba
            return bool(
                _PATTERN_GIRO.search(a["descrizione"] or "")
                or _PATTERN_GIRO.search(b["descrizione"] or "")
            )
        return True

    # candidati per ogni movimento
    candidates: dict[int, list[int]] = {i: [] for i in range(len(out))}
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if compatibile(out[i], out[j]):
                candidates[i].append(j)
                candidates[j].append(i)

    # coppie univoche → AUTO (greedy per distanza data crescente)
    pairs = []
    for i, cands in candidates.items():
        if len(cands) == 1 and len(candidates[cands[0]]) == 1 and i < cands[0]:
            dist = abs(
                (out[i]["data_operazione"] - out[cands[0]]["data_operazione"]).days
            )
            pairs.append((dist, i, cands[0]))

    group = 0
    for _, i, j in sorted(pairs):
        group += 1
        for k in (i, j):
            out[k]["transfer_status"] = "AUTO"
            out[k]["transfer_group"] = group

    # ambigui → CANDIDATE
    for i, cands in candidates.items():
        if out[i]["transfer_status"] is None and cands:
            out[i]["transfer_status"] = "CANDIDATE"

    return out


def consolidato_societa(movimenti_tagged: list[dict]) -> dict:
    raise NotImplementedError  # Task 3
```

- [ ] **Step 4: Verificare che i 5 test del matcher passino**

Run: `python -m pytest tests/test_cashflow_consuntivo.py -v`
Expected: 5 PASS (i test di `consolidato_societa` arrivano nel Task 3)

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/cashflow_consuntivo_data.py tests/test_cashflow_consuntivo.py
git commit -m "feat(condges): matcher deterministico trasferimenti interni (Livello B cashflow consuntivo)"
```

---

### Task 3: Consolidato società + fetch da BQ

**Files:**
- Modify: `verticals/condges/cashflow_consuntivo_data.py` (sostituire lo stub `consolidato_societa`, aggiungere `fetch_movimenti_mese`)
- Test: `tests/test_cashflow_consuntivo.py` (append)

**Interfaces:**
- Consumes: `detect_trasferimenti_interni` (Task 2).
- Produces:
  - `consolidato_societa(movimenti_tagged: list[dict]) -> dict` con chiavi
    `incassi_esterni, pagamenti_esterni, trasferimenti_interni, candidati_trasferimento, variazione_netta` (tutti float ≥ 0 tranne `variazione_netta` che è signed).
  - `fetch_movimenti_mese(societa_id: str, anno: int, mese: int) -> list[dict]` (query BQ su `f_banche_movimenti`, stesse chiavi richieste dal matcher). Task 4 usa entrambe.

- [ ] **Step 1: Test del consolidato (append al file test)**

```python
def test_consolidato_neutralizza_solo_auto_caso_zia():
    """Caso canonico: 2M in/out come giro → variazione netta = solo flussi esterni."""
    movs = [
        _mov(1, "MPS", 10, +2_000_000.0, "Versamento ns. a/c assegni circolari"),
        _mov(2, "MPS", 12, -2_000_000.0, "Emissione ass. circolari"),
        _mov(3, "MPS", 15, +40_000.0, "POS incassi"),
        _mov(4, "INTESA", 20, -100_000.0, "Pagamento fornitori"),
    ]
    tagged = detect_trasferimenti_interni(movs)
    cons = consolidato_societa(tagged)
    assert cons["trasferimenti_interni"] == 4_000_000.0  # lordo movimentato nei giri
    assert cons["incassi_esterni"] == 40_000.0
    assert cons["pagamenti_esterni"] == 100_000.0
    assert cons["variazione_netta"] == -60_000.0


def test_consolidato_candidate_resta_nei_flussi_esterni():
    """I CANDIDATE non vengono neutralizzati (naming honesty: solo AUTO esce dal consolidato)."""
    movs = [
        _mov(1, "INTESA", 10, -10_000.0),
        _mov(2, "MPS", 10, +10_000.0),
        _mov(3, "SELLA", 11, +10_000.0),
    ]
    tagged = detect_trasferimenti_interni(movs)
    cons = consolidato_societa(tagged)
    assert cons["trasferimenti_interni"] == 0.0
    assert cons["candidati_trasferimento"] == 30_000.0
    assert cons["incassi_esterni"] == 20_000.0
    assert cons["pagamenti_esterni"] == 10_000.0
```

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/test_cashflow_consuntivo.py -v -k consolidato`
Expected: FAIL con NotImplementedError

- [ ] **Step 3: Implementare**

Sostituire lo stub in `cashflow_consuntivo_data.py`:

```python
def consolidato_societa(movimenti_tagged: list[dict]) -> dict:
    """Livello B: flussi esterni con trasferimenti interni (AUTO) neutralizzati.

    I CANDIDATE restano nei flussi esterni ma sono quantificati a parte:
    verranno risolti dalla review queue (C.2), mai neutralizzati in silenzio.
    """
    incassi = pagamenti = trasferimenti = candidati = 0.0
    for m in movimenti_tagged:
        imp = m["importo_netto"]
        if m["transfer_status"] == "AUTO":
            trasferimenti += abs(imp)
            continue
        if m["transfer_status"] == "CANDIDATE":
            candidati += abs(imp)
        if imp > 0:
            incassi += imp
        else:
            pagamenti += abs(imp)
    return {
        "incassi_esterni": round(incassi, 2),
        "pagamenti_esterni": round(pagamenti, 2),
        "trasferimenti_interni": round(trasferimenti, 2),
        "candidati_trasferimento": round(candidati, 2),
        "variazione_netta": round(incassi - pagamenti, 2),
    }


def fetch_movimenti_mese(societa_id: str, anno: int, mese: int) -> list[dict]:
    """Movimenti banca del mese, nel formato atteso da detect_trasferimenti_interni."""
    from google.cloud import bigquery

    from core.config import PROJECT

    client = bigquery.Client(project=PROJECT)
    sql = f"""
    SELECT id_movimento, banca_id, data_operazione,
           CAST(importo_netto AS FLOAT64) AS importo_netto, descrizione
    FROM `{PROJECT}.hotelops.f_banche_movimenti`
    WHERE societa_id = @societa
      AND DATE_TRUNC(data_operazione, MONTH) = DATE(@anno, @mese, 1)
      AND descrizione IS NOT NULL
      AND descrizione NOT IN ('Totale (€)', 'TOTALE')
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa_id),
                bigquery.ScalarQueryParameter("anno", "INT64", anno),
                bigquery.ScalarQueryParameter("mese", "INT64", mese),
            ]
        ),
    )
    return [dict(r) for r in job.result()]
```

(Verificare che `core.config` esponga `PROJECT`; se il nome reale è diverso — es. `PROJECT_ID` — adeguare l'import, NON aggiungere costanti nuove.)

- [ ] **Step 4: Tutti i test del file passano**

Run: `python -m pytest tests/test_cashflow_consuntivo.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/cashflow_consuntivo_data.py tests/test_cashflow_consuntivo.py
git commit -m "feat(condges): consolidato società (Livello B) + fetch movimenti mese"
```

---

### Task 4: Pagina hub "Cassa consuntivo"

**Files:**
- Create: `verticals/hub/pages_/cassa_consuntivo.py`
- Modify: `verticals/hub/registry.py` (import + 1 riga HubApp, accanto alla riga `cashflow` esistente a `registry.py:47`)
- Test: `tests/test_cashflow_consuntivo.py` (append: smoke import)

**Interfaces:**
- Consumes: `v_cash_position` (Task 1), `fetch_movimenti_mese` + `detect_trasferimenti_interni` + `consolidato_societa` (Task 2-3).
- Produces: `cassa_consuntivo.render()` montata dal hub (pattern: come le altre pagine in `verticals/hub/pages_/`; NO `st.set_page_config` dentro `render`).

Nota di design (deviazione dichiarata dalla spec): la spec dice "tab nell'app Cashflow"; si monta invece come **pagina hub separata** (pattern registry "1 riga = 1 app") per non rifattorizzare `app_cashflow.render()`. Stessa superficie logica (categoria Finanza, sensitive), zero rischio sul flusso rotation.

- [ ] **Step 1: Smoke test (fallisce: modulo inesistente)**

```python
def test_pagina_hub_importabile_e_senza_page_config():
    """render() esiste e il modulo non chiama st.set_page_config (vincolo hub)."""
    import inspect

    from verticals.hub.pages_ import cassa_consuntivo

    assert callable(cassa_consuntivo.render)
    src = inspect.getsource(cassa_consuntivo)
    assert "set_page_config" not in src
```

- [ ] **Step 2: Verificare che fallisca**

Run: `python -m pytest tests/test_cashflow_consuntivo.py::test_pagina_hub_importabile_e_senza_page_config -v`
Expected: FAIL con ImportError

- [ ] **Step 3: Implementare la pagina**

```python
"""Pagina hub — Cassa consuntivo (Livelli A+B).

Spec: docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md.
Read-only: v_cash_position (Livello A) + consolidato società (Livello B).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from verticals.condges.cashflow_consuntivo_data import (
    consolidato_societa,
    detect_trasferimenti_interni,
    fetch_movimenti_mese,
)


@st.cache_data(ttl=600)
def _cash_position(societa: str) -> pd.DataFrame:
    from google.cloud import bigquery

    from core.config import PROJECT

    client = bigquery.Client(project=PROJECT)
    sql = f"""
    SELECT mese, banca_id, saldo_iniziale_cert, accrediti, addebiti, netto,
           saldo_calcolato, saldo_finale_cert, scarto
    FROM `{PROJECT}.hotelops.v_cash_position`
    WHERE societa_id = @societa
    ORDER BY mese DESC, banca_id
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa)
            ]
        ),
    )
    return job.to_dataframe()


@st.cache_data(ttl=600)
def _consolidato(societa: str, anno: int, mese: int) -> dict:
    movs = fetch_movimenti_mese(societa, anno, mese)
    return consolidato_societa(detect_trasferimenti_interni(movs))


def render() -> None:
    st.title("💰 Cassa consuntivo")
    st.caption(
        "Il vero cashflow: totali dalla banca, quadratura sui saldi certificati. "
        "Livello A = lordi per conto · Livello B = consolidato società, "
        "trasferimenti interni neutralizzati."
    )

    societa = st.radio("Società", ["ORTI", "INTUR"], horizontal=True)

    st.subheader("Livello A — Cash position per conto")
    df = _cash_position(societa)
    if df.empty:
        st.info("Nessun dato in v_cash_position per questa società.")
        return
    st.dataframe(
        df.style.map(
            lambda v: "background-color:#fdd"
            if isinstance(v, float) and abs(v) > 0.01
            else "",
            subset=["scarto"],
        ),
        use_container_width=True,
    )
    st.caption(
        "scarto ≠ 0 → export homebanking incompleto o saldo certificato da rivedere. "
        "Anchor NULL = saldo certificato mancante per quel mese."
    )

    st.subheader("Livello B — Consolidato società (mese)")
    mesi = sorted({(m.year, m.month) for m in df["mese"]}, reverse=True)
    anno, mese = mesi[0]
    scelta = st.selectbox(
        "Mese", mesi, format_func=lambda am: f"{am[0]}-{am[1]:02d}"
    )
    anno, mese = scelta
    cons = _consolidato(societa, anno, mese)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Incassi esterni", f"{cons['incassi_esterni']:,.2f} €")
    c2.metric("Pagamenti esterni", f"{cons['pagamenti_esterni']:,.2f} €")
    c3.metric("Trasferimenti interni", f"{cons['trasferimenti_interni']:,.2f} €")
    c4.metric("Variazione netta", f"{cons['variazione_netta']:,.2f} €")
    if cons["candidati_trasferimento"]:
        st.warning(
            f"Candidati trasferimento non confermati: "
            f"{cons['candidati_trasferimento']:,.2f} € — restano nei flussi esterni "
            "(review in arrivo con C.2)."
        )
```

Poi in `verticals/hub/registry.py`: aggiungere `cassa_consuntivo` all'import dei pages (`registry.py:13`) e la riga (accanto a quella `cashflow`, `registry.py:47`):

```python
    HubApp("cassa-consuntivo", "Cassa consuntivo", "💰", "Finanza", "page", cassa_consuntivo.render, "Il vero cashflow: banca vs certificati", sensitive=True),
```

(Adeguare la firma `HubApp(...)` a quella reale delle righe adiacenti — copiare la struttura della riga `cashflow` esistente.)

- [ ] **Step 4: Test verdi + suite intera**

Run: `python -m pytest tests/test_cashflow_consuntivo.py -v && python -m pytest -q`
Expected: tutti PASS (la suite era 957+ prima del piano)

- [ ] **Step 5: Smoke visivo locale**

Run: `streamlit run verticals/hub/app.py` → aprire la pagina "Cassa consuntivo" → ORTI: la tabella Livello A mostra giugno con scarti; Livello B mostra i 4 metric.
Expected: nessuna eccezione; MPS giugno ha entrambi gli anchor.

- [ ] **Step 6: Commit**

```bash
git add verticals/hub/pages_/cassa_consuntivo.py verticals/hub/registry.py tests/test_cashflow_consuntivo.py
git commit -m "feat(hub): pagina Cassa consuntivo — Livelli A+B su v_cash_position e consolidato società"
```

---

### Task 5: Verifica e2e su giugno 2026 ORTI + chiusura

**Files:**
- Nessun file nuovo di prodotto; aggiornare `STATUS.md` (riga esito) e il hub vault `workstreams/CDG.md` (checkbox Fase 1).

**Interfaces:**
- Consumes: tutto quanto sopra, su dati reali.

Numeri attesi (misurati 2026-07-11 — se i dati sono cambiati, documentare i nuovi):

- ORTI/MPS giugno: saldo 469.192,55 (31/05) → 791.654,10 (30/06); movimenti netti misurati +323.568,10 → **scarto atteso ≈ +1.106,55 — NON zero: va spiegato** (candidati: competenze/valuta di fine mese, movimento mancante nell'export). L'indagine è parte di questo task: guardare i movimenti a cavallo del 30/06 (`data_operazione` vs `data_valuta`).
- ORTI/INTESA giugno: **scarto atteso GRANDE e noto** — homebanking INTESA ORTI manca dal 05/06 (HANDOFF aperto in STATUS). La pagina deve MOSTRARLO (cella rossa), non nasconderlo: è il Livello A che fa il suo lavoro.
- ORTI/UNICREDIT: anchor 30/06 = 10.000,00 ma saldo iniziale NULL (nessun anchor 31/05) e probabilmente zero movimenti in BQ → riga con anchor mancante visibile.

- [ ] **Step 1: Eseguire la verifica**

Run: query `v_cash_position` per giugno ORTI (o dalla pagina hub) e annotare gli scarti reali per banca.

- [ ] **Step 2: Indagare lo scarto MPS (~1.1k)**

Run: confronto movimenti 28/06–02/07 su `data_operazione` vs `data_valuta`; se lo scarto è spiegato (es. competenze liquidate al 30/06 con valuta 01/07), annotare la spiegazione nella pagina/STATUS; se è un buco export → HANDOFF.
Expected: spiegazione scritta, non uno scarto ignorato.

- [ ] **Step 3: Aggiornare STATUS.md e vault**

- `STATUS.md`: riga sotto la sezione GC/CdG: "Cashflow consuntivo Fase 1 (A+B) live nel hub — scarti giugno ORTI: MPS <valore spiegato>, INTESA <gap export noto>".
- `workstreams/CDG.md`: spuntare la parte A+B del thread cashflow consuntivo, prossimo passo → Fase 2 (Livello C).

- [ ] **Step 4: Commit finale**

```bash
git add STATUS.md
git commit -m "docs(status): cashflow consuntivo Fase 1 (A+B) verificato su giugno ORTI"
```

---

## Fuori da questo piano (piani successivi)

- **Fase 2 — Livello C**: classificazione via prima nota (chiave `(societa, data_registrazione, gruppo_doc)`, bracci 1901xx → sorelle → `d_fornitori`/`d_voci_piano_finanziario`), colonna "differenza banca–contabilità".
- **Fase 3 — C.2**: matching deterministico banca↔prima nota (82% misurato) + `bank_reconcile` come suggeritore + review queue Rosa + decisioni persistenti.
- **Fase 4 — Livello D**: previsto vs reale (gated dalla copertura di C).
