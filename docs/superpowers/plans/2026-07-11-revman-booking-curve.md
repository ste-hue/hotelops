# Revman Booking Curve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vista BQ `v_booking_curve` (booking pace normalizzato per capacità) + pagina hub "Revenue" read-only che mostra batteria / ADR marginale / ADR richiesto per mese.

**Architecture:** Tutta la logica numerica in una vista SQL (pattern delle 33 viste esistenti, deploy via `hotelops deploy-views`); la semantica del verdetto in una funzione pura Python dentro la pagina; la pagina Streamlit (`pages_/revenue.py` + 1 riga registry) è presentazione pura.

**Tech Stack:** BigQuery SQL (vista), Streamlit + plotly (pagina, extra `[dashboard]`), pytest (`@pytest.mark.bq` per gli invariant test live).

**Spec:** `docs/superpowers/specs/2026-07-11-revman-booking-curve-design.md` — leggila prima di iniziare.

## Global Constraints

- Worktree `.worktrees/revman`, branch `feat/revman`. **Mai `pip install -e` da dentro il worktree** (CLAUDE.md — rompe l'editable install). Lancia pytest dalla root del worktree: `python -m pytest`.
- Base di misura: **sempre imponibile**. Varianti `dim_tipologia` mai sommate; preferenza `VENDUTA > ASSEGNATA > NESSUNA`.
- I test `@pytest.mark.bq` interrogano BQ live (skip con `HOTELOPS_SKIP_BQ=1`). Se l'auth è scaduta: far lanciare a Stefano `gcloud auth login`.
- `gap_notti_target` = notti mancanti al volume LY riproporzionato (NON capacità residua reale); `adr_richiesto` = ADR necessario su quelle notti aggiuntive.
- Palette: reference instance dataviz — ruoli definiti in un punto solo di `revenue.py`, mai hex sparsi.
- Nessun write-path: la pagina è read-only (`sensitive=False`).
- Commit frequenti, messaggi `feat(revman): ...` / `test(revman): ...`.

---

### Task 1: Gate checks (assunzioni sui dati — STOP se falliscono)

**Files:** nessuno (solo query BQ). Il deliverable è il risultato dei due check, riportato nel commit message del Task 2.

**Interfaces:**
- Produces: conferma (o smentita) di 2 assunzioni della spec. **Se un check fallisce: STOP, riportare i numeri a Stefano, NON procedere ai task successivi.**

- [ ] **Step 1: Check variante-invarianza (foto 6/7, per BU × mese)**

```bash
bq query --use_legacy_sql=false --format=pretty '
WITH per_var AS (
  SELECT business_unit_id, dim_tipologia,
         DATE_TRUNC(DATE(data), MONTH) AS mese,
         SUM(camere) AS notti, ROUND(SUM(imponibile), 2) AS imponibile
  FROM `hotelops-suite.hotelops.f_prenotazioni_otb`
  WHERE DATE(snapshot_date) = "2026-07-06"
    AND dim_tipologia IN ("ASSEGNATA", "VENDUTA")
  GROUP BY 1, 2, 3
)
SELECT a.business_unit_id, a.mese,
       a.notti - v.notti AS diff_notti,
       ROUND(a.imponibile - v.imponibile, 2) AS diff_imponibile
FROM per_var a
JOIN per_var v USING (business_unit_id, mese)
WHERE a.dim_tipologia = "ASSEGNATA" AND v.dim_tipologia = "VENDUTA"
  AND (a.notti != v.notti OR ABS(a.imponibile - v.imponibile) > 1)'
```

Expected: **0 righe** (criterio spec: diff notti = 0, diff imponibile ≤ €1, per BU × mese — mai solo sul totale BU). Se escono righe → STOP e riportare a Stefano (l'assunzione "stessa foto su dimensioni diverse" cade e la selezione variante va ridisegnata).

- [ ] **Step 2: Check base di `revenue_room` (imponibile vs lordo)**

```bash
bq query --use_legacy_sql=false --format=pretty '
WITH stat AS (
  SELECT EXTRACT(MONTH FROM DATE(data)) AS mese, ROUND(SUM(revenue_room), 2) AS pms_stat
  FROM `hotelops-suite.hotelops.f_pms_statistiche`
  WHERE business_unit_id = "HOTEL" AND EXTRACT(YEAR FROM DATE(data)) = 2025
    AND EXTRACT(MONTH FROM DATE(data)) IN (5, 6)
  GROUP BY 1
), prod AS (
  SELECT EXTRACT(MONTH FROM DATE(data)) AS mese, ROUND(SUM(importo_imponibile), 2) AS prod_01room
  FROM `hotelops-suite.hotelops.f_produzione_pms`
  WHERE classe = "01ROOM" AND societa_id = "ORTI"
    AND EXTRACT(YEAR FROM DATE(data)) = 2025 AND EXTRACT(MONTH FROM DATE(data)) IN (5, 6)
  GROUP BY 1
)
SELECT mese, pms_stat, prod_01room,
       ROUND(SAFE_DIVIDE(pms_stat, prod_01room), 4) AS ratio
FROM stat JOIN prod USING (mese) ORDER BY mese'
```

Expected: `ratio` ≈ **1.0 (±2%)** su entrambi i mesi → `revenue_room` è imponibile, si usa come LY. Se ratio ≈ 1.10 (IVA camere) → è lordo → STOP: il LY va preso da `f_produzione_pms` classe 01ROOM (ma quella non ha le notti → riportare a Stefano prima di scegliere).

> **ESEGUITO 2026-07-11 — esito STOP, risolto.** Ratio 1,0906 (mag) / 1,0364 (giu): base terza. Decisione Stefano: LY € = `f_produzione_pms` 01ROOM (imponibile, per BU), LY notti = `f_pms_statistiche.camere_vendute`. Il SQL del Task 2 già riflette la decisione (CTE `room_revenue_monthly`). Gate 1 PASS (0 righe fuori tolleranza). Report: `.superpowers/sdd/task-1-report.md`.

---

### Task 2: Vista `v_booking_curve` + invariant test

**Files:**
- Create: `core/bq/views/v_booking_curve.sql`
- Create: `tests/test_booking_curve.py`
- Modify: `core/config.py` (dopo la riga `V_INCASSI_PER_CANALE`)

**Interfaces:**
- Consumes: esito Task 1 (entrambi i check passati).
- Produces: vista `hotelops-suite.hotelops.v_booking_curve` deployata; costante `V_BOOKING_CURVE` in `core.config`. Colonne (usate dal Task 3): `snapshot_date DATE, business_unit_id STRING, mese_soggiorno DATE, anno INT, mese INT, otb_notti, otb_imponibile, otb_adr, gg_tra_foto, pickup_notti, pickup_imponibile, pickup_notti_gg, pickup_eur_gg, adr_marginale, ly_notti, ly_imponibile, ly_adr, ly_giorni_con_capacita, ly_capacita_massima, cy_giorni_con_capacita_osservati, cy_capacita_massima, cap_ratio, target_imponibile, notti_attese, saturazione_pct, gap_target, gap_notti_target, adr_richiesto`.

- [ ] **Step 1: Scrivi i test invariant (falliranno: vista inesistente)**

Crea `tests/test_booking_curve.py`:

```python
"""Invariant + golden test per v_booking_curve.

Query BQ live (@pytest.mark.bq, skip con HOTELOPS_SKIP_BQ=1).
Golden = numeri validati a mano l'11/07 (vault BOOKING_PACE_E_BASI):
se la vista non li riproduce, è sbagliata lei.

Spec: docs/superpowers/specs/2026-07-11-revman-booking-curve-design.md
"""

from __future__ import annotations

import pytest

VIEW = "`hotelops-suite.hotelops.v_booking_curve`"


def _rows(bq_client, sql):
    return [dict(r) for r in bq_client.query(sql).result()]


@pytest.mark.bq
def test_grain_uniqueness(bq_client):
    """Una riga per (business_unit_id, mese_soggiorno, snapshot_date)."""
    rows = _rows(bq_client, f"""
        SELECT business_unit_id, mese_soggiorno, snapshot_date, COUNT(*) n
        FROM {VIEW}
        GROUP BY 1, 2, 3 HAVING n > 1 LIMIT 5
    """)
    assert not rows, f"grain violato: {rows[:2]}"


@pytest.mark.bq
def test_prima_foto_pickup_null(bq_client):
    """La foto più vecchia di ogni (BU, mese) non ha pickup né marginale."""
    rows = _rows(bq_client, f"""
        WITH prima AS (
          SELECT business_unit_id, mese_soggiorno, MIN(snapshot_date) s
          FROM {VIEW} GROUP BY 1, 2
        )
        SELECT v.* FROM {VIEW} v
        JOIN prima p ON v.business_unit_id = p.business_unit_id
          AND v.mese_soggiorno = p.mese_soggiorno AND v.snapshot_date = p.s
        WHERE v.pickup_notti IS NOT NULL OR v.adr_marginale IS NOT NULL
        LIMIT 5
    """)
    assert not rows, f"prima foto con pickup non NULL: {rows[:2]}"


@pytest.mark.bq
def test_marginale_null_su_pickup_non_positivo(bq_client):
    """adr_marginale mai calcolato su Δnotti <= 0 (niente marginali fantasma)."""
    rows = _rows(bq_client, f"""
        SELECT * FROM {VIEW}
        WHERE pickup_notti <= 0 AND adr_marginale IS NOT NULL LIMIT 5
    """)
    assert not rows, f"marginale su pickup <= 0: {rows[:2]}"


@pytest.mark.bq
def test_cap_ratio(bq_client):
    """cap_ratio misurato dai dati: HOTEL 86/76, RESIDENCE 1.0, CVM 1.0."""
    rows = _rows(bq_client, f"""
        SELECT business_unit_id, ANY_VALUE(cap_ratio) cap_ratio
        FROM {VIEW} WHERE cap_ratio IS NOT NULL GROUP BY 1
    """)
    ratio = {r["business_unit_id"]: r["cap_ratio"] for r in rows}
    assert abs(ratio["HOTEL"] - 86 / 76) < 0.001, ratio
    assert abs(ratio["RESIDENCE"] - 1.0) < 0.001, ratio
    assert abs(ratio["CVM"] - 1.0) < 0.001, ratio


@pytest.mark.bq
def test_golden_hotel_foto_11_07(bq_client):
    """Riproduce i numeri validati a mano l'11/07 (HOTEL, foto 2026-07-11)."""
    rows = _rows(bq_client, f"""
        SELECT mese, otb_adr, adr_marginale, saturazione_pct,
               adr_richiesto, gap_notti_target
        FROM {VIEW}
        WHERE business_unit_id = 'HOTEL' AND snapshot_date = '2026-07-11'
          AND mese IN (7, 10)
    """)
    per_mese = {r["mese"]: r for r in rows}
    lug, ott = per_mese[7], per_mese[10]
    # luglio: marginale ~476 vs media ~230, saturazione ~80,7%
    assert 400 <= lug["adr_marginale"] <= 550, lug
    assert 200 <= lug["otb_adr"] <= 260, lug
    assert 0.73 <= lug["saturazione_pct"] <= 0.88, lug
    # ottobre: marginale ~206 vs media ~213, richiesto ~175, gap notti ~736
    assert 180 <= ott["adr_marginale"] <= 235, ott
    assert 150 <= ott["adr_richiesto"] <= 200, ott
    assert 590 <= ott["gap_notti_target"] <= 880, ott
```

- [ ] **Step 2: Verifica che falliscano per il motivo giusto**

Run: `python -m pytest tests/test_booking_curve.py -v`
Expected: tutti FAIL/ERROR con `Not found: Table ... v_booking_curve` (NON per import error o sintassi).

- [ ] **Step 3: Aggiungi la costante in `core/config.py`**

Dopo la riga `V_INCASSI_PER_CANALE         = _t("v_incassi_per_canale")`:

```python
V_BOOKING_CURVE              = _t("v_booking_curve")
```

- [ ] **Step 4: Scrivi `core/bq/views/v_booking_curve.sql`**

```sql
-- v_booking_curve
-- Booking pace normalizzato per capacità (revman, issue #81).
-- Spec: docs/superpowers/specs/2026-07-11-revman-booking-curve-design.md
-- Grana: 1 riga = business_unit_id × mese_soggiorno × snapshot_date.
-- Base di misura: SEMPRE imponibile (vault BOOKING_PACE_E_BASI, basi omogenee).
-- Sequenza obbligatoria: selezione variante → aggregazione mensile → LAG
--   (mai window su righe alla granularità originaria).
-- Caveat:
--  * mesi già consumati: l'OTB include il consuntivo (la foto è "consumato +
--    futuro") — la curva ha senso pieno sui mesi >= mese della foto;
--  * aprile 2026 drogato dall'apertura anticipata (3/4 vs 16/4 2025): non si
--    aggiusta qui, si legge col benchmark giusto (concept §3);
--  * il benchmark LY assume calendario operativo comparabile: le colonne
--    diagnostiche ly_/cy_giorni_con_capacita e *_capacita_massima espongono
--    quando l'assunzione è debole (NON corrette in v1, solo esposte);
--  * gap_notti_target = notti mancanti al volume LY riproporzionato, NON la
--    capacità residua reale; adr_richiesto = ADR medio necessario su quelle
--    notti aggiuntive, non sulle camere fisicamente ancora disponibili.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_booking_curve` AS
WITH source_ranked AS (
  -- una foto può esistere in più varianti dim_tipologia (stessa foto
  -- aggregata su dimensioni diverse — MAI sommarle): rank di preferenza
  SELECT
    DATE(snapshot_date) AS snapshot_date,
    business_unit_id,
    DATE(data)          AS data_soggiorno,
    camere,
    imponibile,
    DENSE_RANK() OVER (
      PARTITION BY snapshot_date, business_unit_id
      ORDER BY CASE dim_tipologia
        WHEN 'VENDUTA' THEN 1 WHEN 'ASSEGNATA' THEN 2 ELSE 3 END
    ) AS variante_rank
  FROM `hotelops-suite.hotelops.f_prenotazioni_otb`
),
selected_variant AS (
  SELECT * FROM source_ranked WHERE variante_rank = 1
),
otb_monthly AS (
  SELECT
    snapshot_date,
    business_unit_id,
    DATE_TRUNC(data_soggiorno, MONTH) AS mese_soggiorno,
    SUM(camere)     AS otb_notti,
    SUM(imponibile) AS otb_imponibile
  FROM selected_variant
  GROUP BY 1, 2, 3
),
otb_with_pickup AS (
  SELECT
    *,
    LAG(snapshot_date)  OVER w AS foto_precedente,
    LAG(otb_notti)      OVER w AS notti_foto_prec,
    LAG(otb_imponibile) OVER w AS imponibile_foto_prec
  FROM otb_monthly
  WINDOW w AS (
    PARTITION BY business_unit_id, mese_soggiorno
    ORDER BY snapshot_date
  )
),
pms_monthly AS (
  -- notti + diagnostiche calendario per BU × anno × mese (fonte statistiche)
  SELECT
    business_unit_id,
    EXTRACT(YEAR FROM DATE(data))  AS anno,
    EXTRACT(MONTH FROM DATE(data)) AS mese,
    SUM(camere_vendute)            AS notti,
    COUNTIF(camere_totali > 0)     AS giorni_con_capacita,
    MAX(camere_totali)             AS capacita_massima
  FROM `hotelops-suite.hotelops.f_pms_statistiche`
  GROUP BY 1, 2, 3
),
room_revenue_monthly AS (
  -- ricavo camere imponibile per BU × anno × mese (decisione gate 2:
  -- 01ROOM di f_produzione_pms, NON revenue_room di f_pms_statistiche
  -- che è una base terza — ratio 1,09/1,04 vs 01ROOM)
  SELECT
    business_unit_id,
    EXTRACT(YEAR FROM DATE(data))  AS anno,
    EXTRACT(MONTH FROM DATE(data)) AS mese,
    SUM(importo_imponibile)        AS imponibile
  FROM `hotelops-suite.hotelops.f_produzione_pms`
  WHERE classe = '01ROOM'
  GROUP BY 1, 2, 3
),
ly_monthly AS (
  -- benchmark: l'anno N legge il PMS dell'anno N-1
  SELECT p.business_unit_id, p.anno + 1 AS anno_target, p.mese,
         p.notti AS ly_notti, r.imponibile AS ly_imponibile,
         p.giorni_con_capacita AS ly_giorni_con_capacita,
         p.capacita_massima AS ly_capacita_massima
  FROM pms_monthly p
  LEFT JOIN room_revenue_monthly r
    ON r.business_unit_id = p.business_unit_id
   AND r.anno = p.anno AND r.mese = p.mese
),
capacity_by_year AS (
  -- capacità osservata; esclusa l'anomalia RESIDENCE 2025 (giorni con 55)
  SELECT
    business_unit_id,
    EXTRACT(YEAR FROM DATE(data)) AS anno,
    MAX(camere_totali)            AS capacita
  FROM `hotelops-suite.hotelops.f_pms_statistiche`
  WHERE NOT (business_unit_id = 'RESIDENCE' AND camere_totali > 20)
  GROUP BY 1, 2
),
curve_metrics AS (
  SELECT
    o.snapshot_date,
    o.business_unit_id,
    o.mese_soggiorno,
    EXTRACT(YEAR FROM o.mese_soggiorno)  AS anno,
    EXTRACT(MONTH FROM o.mese_soggiorno) AS mese,
    -- 1. OTB (la foto)
    o.otb_notti,
    o.otb_imponibile,
    SAFE_DIVIDE(o.otb_imponibile, o.otb_notti) AS otb_adr,
    -- 2. pickup (foto vs foto precedente)
    DATE_DIFF(o.snapshot_date, o.foto_precedente, DAY) AS gg_tra_foto,
    o.otb_notti - o.notti_foto_prec           AS pickup_notti,
    o.otb_imponibile - o.imponibile_foto_prec AS pickup_imponibile,
    SAFE_DIVIDE(o.otb_notti - o.notti_foto_prec,
                DATE_DIFF(o.snapshot_date, o.foto_precedente, DAY)) AS pickup_notti_gg,
    SAFE_DIVIDE(o.otb_imponibile - o.imponibile_foto_prec,
                DATE_DIFF(o.snapshot_date, o.foto_precedente, DAY)) AS pickup_eur_gg,
    CASE
      WHEN o.notti_foto_prec IS NOT NULL
           AND (o.otb_notti - o.notti_foto_prec) > 0
      THEN (o.otb_imponibile - o.imponibile_foto_prec)
           / (o.otb_notti - o.notti_foto_prec)
    END AS adr_marginale,
    -- 3. LY, capacità, diagnostiche
    ly.ly_notti,
    ly.ly_imponibile,
    SAFE_DIVIDE(ly.ly_imponibile, ly.ly_notti) AS ly_adr,
    ly.ly_giorni_con_capacita,
    ly.ly_capacita_massima,
    cy.giorni_con_capacita AS cy_giorni_con_capacita_osservati,
    cy.capacita_massima    AS cy_capacita_massima,
    SAFE_DIVIDE(cap_cy.capacita, cap_ly.capacita) AS cap_ratio,
    ly.ly_imponibile * SAFE_DIVIDE(cap_cy.capacita, cap_ly.capacita) AS target_imponibile,
    ly.ly_notti      * SAFE_DIVIDE(cap_cy.capacita, cap_ly.capacita) AS notti_attese
  FROM otb_with_pickup o
  LEFT JOIN ly_monthly ly
    ON ly.business_unit_id = o.business_unit_id
   AND ly.anno_target = EXTRACT(YEAR FROM o.mese_soggiorno)
   AND ly.mese        = EXTRACT(MONTH FROM o.mese_soggiorno)
  LEFT JOIN pms_monthly cy
    ON cy.business_unit_id = o.business_unit_id
   AND cy.anno = EXTRACT(YEAR FROM o.mese_soggiorno)
   AND cy.mese = EXTRACT(MONTH FROM o.mese_soggiorno)
  LEFT JOIN capacity_by_year cap_cy
    ON cap_cy.business_unit_id = o.business_unit_id
   AND cap_cy.anno = EXTRACT(YEAR FROM o.mese_soggiorno)
  LEFT JOIN capacity_by_year cap_ly
    ON cap_ly.business_unit_id = o.business_unit_id
   AND cap_ly.anno = EXTRACT(YEAR FROM o.mese_soggiorno) - 1
)
SELECT
  *,
  SAFE_DIVIDE(otb_notti, notti_attese) AS saturazione_pct,
  target_imponibile - otb_imponibile   AS gap_target,
  notti_attese - otb_notti             AS gap_notti_target,
  CASE
    WHEN (notti_attese - otb_notti) > 0
    THEN (target_imponibile - otb_imponibile) / (notti_attese - otb_notti)
  END AS adr_richiesto
FROM curve_metrics
```

- [ ] **Step 5: Deploy della vista**

Run (dalla root del worktree): `python cli.py deploy-views --dry-run` poi `python cli.py deploy-views`
⚠️ NON usare il comando `hotelops`: l'editable install punta al repo main, che non ha il file nuovo — il deploy partirebbe senza `v_booking_curve`. `python cli.py` dal worktree importa i moduli del worktree.
Expected: `v_booking_curve` nell'ordine di deploy (dry-run), poi deploy senza errori SQL.

- [ ] **Step 6: Verifica che i test passino**

Run: `python -m pytest tests/test_booking_curve.py -v`
Expected: 5 PASS. Se `test_golden_hotel_foto_11_07` fallisce, NON allargare i range: indagare la formula (i golden sono numeri validati a mano — se la vista non li riproduce, è sbagliata lei).

- [ ] **Step 7: Commit**

```bash
git add core/bq/views/v_booking_curve.sql core/config.py tests/test_booking_curve.py
git commit -m "feat(revman): vista v_booking_curve — pace normalizzato per capacità

Gate Task 1 passati: variante-invarianza 6/7 (diff notti 0, imponibile <=1€
per BU×mese) e revenue_room=imponibile (ratio vs 01ROOM ~1.0).
[sostituire con i numeri reali dei check]"
```

---

### Task 3: Pagina hub "Revenue" + registry + verdetto puro

**Files:**
- Create: `verticals/hub/pages_/revenue.py`
- Create: `tests/test_hub_revenue.py`
- Modify: `verticals/hub/registry.py` (import + riga APPS nel gruppo Finanza)
- Modify: `tests/test_hub_registry.py` (i 2 test con elenchi id espliciti)

**Interfaces:**
- Consumes: vista `v_booking_curve` (colonne dal Task 2), `core.bq.client.get_client`, `core.config.PROJECT/DATASET`, pattern registry `HubApp`.
- Produces: `verticals.hub.pages_.revenue.render() -> None` (montata dal hub); `verticals.hub.pages_.revenue.verdetto(...) -> str` (funzione pura, firma sotto).

- [ ] **Step 1: Scrivi i test (falliranno: modulo inesistente)**

Crea `tests/test_hub_revenue.py`:

```python
"""Pagina Revenue — verdetto puro + contratto di montaggio."""

import inspect

from verticals.hub.pages_.revenue import verdetto


def _base(**kw):
    d = dict(mese_consumato=False, prima_foto=False, pickup_notti=10.0,
             gap_target=50_000.0, gap_notti_target=300.0,
             adr_marginale=250.0, adr_richiesto=150.0)
    d.update(kw)
    return d


def test_stati_preliminari_in_ordine():
    assert verdetto(**_base(mese_consumato=True)) == "CONSUNTIVO"
    assert verdetto(**_base(prima_foto=True)) == "DATI_INSUFFICIENTI"
    assert verdetto(**_base(pickup_notti=0.0)) == "DATI_INSUFFICIENTI"
    assert verdetto(**_base(pickup_notti=None)) == "DATI_INSUFFICIENTI"
    assert verdetto(**_base(gap_target=0.0)) == "TARGET_RAGGIUNTO"
    assert verdetto(**_base(gap_target=-1.0)) == "TARGET_RAGGIUNTO"
    assert verdetto(**_base(gap_notti_target=0.0)) == "TARGET_INCOERENTE"
    assert verdetto(**_base(adr_marginale=None)) == "NESSUN_CONFRONTO"
    assert verdetto(**_base(adr_richiesto=None)) == "NESSUN_CONFRONTO"


def test_tre_zone_calibrazione_11_07():
    # luglio 11/07: richiesto 218 vs marginale 476 -> 0.46 < 0.6
    assert verdetto(**_base(adr_richiesto=218.0, adr_marginale=476.0)) == "TARGET_SCONTATO"
    # ottobre 11/07: richiesto 175 vs marginale 206 -> 0.85, tra 0.6 e 1
    assert verdetto(**_base(adr_richiesto=175.0, adr_marginale=206.0)) == "SERVE_DOMANDA"
    # richiesto sopra il marginale
    assert verdetto(**_base(adr_richiesto=250.0, adr_marginale=206.0)) == "SERVE_REPRICING"


def test_render_montabile():
    from verticals.hub.pages_ import revenue

    assert callable(revenue.render)
    # contratto hub: render() non chiama set_page_config
    assert "set_page_config" not in inspect.getsource(revenue.render)


def test_registry_ha_revenue():
    from verticals.hub.registry import APPS, validate

    validate()
    app = {a.id: a for a in APPS}["revenue"]
    assert app.kind == "page" and app.group == "Finanza"
    assert app.sensitive is False
```

- [ ] **Step 2: Verifica che falliscano per il motivo giusto**

Run: `python -m pytest tests/test_hub_revenue.py -v`
Expected: ERROR `ModuleNotFoundError: ... revenue` (non altri errori).

- [ ] **Step 3: Scrivi `verticals/hub/pages_/revenue.py`**

```python
"""Pagina Revenue — booking curve & pace (read-only su v_booking_curve).

Spec: docs/superpowers/specs/2026-07-11-revman-booking-curve-design.md
Metodologia: vault concepts/BOOKING_PACE_E_BASI (batteria / ADR marginale /
ADR richiesto). NON è un motore di pricing: lente + loop umano settimanale.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bq.client import get_client
from core.config import DATASET, PROJECT

# ── palette (dataviz reference instance — ruoli, non hex sparsi) ─────────────
BLUE = "#2a78d6"        # slot-1: emphasis + riempimento meter
GRAY_CTX = "#c3c2b7"    # de-enfasi (linee contesto)
STATUS_COLOR = {        # status riservati, sempre con icona+etichetta
    "TARGET_SCONTATO": "#0ca30c",   # good
    "SERVE_DOMANDA": "#fab219",     # warning
    "SERVE_REPRICING": "#ec835a",   # serious
}
STATUS_LABEL = {
    "CONSUNTIVO": "· consuntivo",
    "DATI_INSUFFICIENTI": "— dati insufficienti",
    "TARGET_RAGGIUNTO": "✓ target raggiunto",
    "TARGET_INCOERENTE": "≠ target incoerente",
    "NESSUN_CONFRONTO": "— nessun confronto",
    "TARGET_SCONTATO": "✓ target scontato",
    "SERVE_DOMANDA": "⚠ serve domanda",
    "SERVE_REPRICING": "⛔ serve repricing",
}


def verdetto(*, mese_consumato: bool, prima_foto: bool,
             pickup_notti: float | None, gap_target: float | None,
             gap_notti_target: float | None, adr_marginale: float | None,
             adr_richiesto: float | None) -> str:
    """Semantica del verdetto (spec §vista) — pura, testabile senza BQ.

    Stati preliminari in quest'ordine, poi le 3 zone richiesto-vs-marginale.
    """
    if mese_consumato:
        return "CONSUNTIVO"
    if prima_foto or pickup_notti is None or pickup_notti <= 0:
        return "DATI_INSUFFICIENTI"
    if gap_target is not None and gap_target <= 0:
        return "TARGET_RAGGIUNTO"
    if gap_notti_target is not None and gap_notti_target <= 0:
        return "TARGET_INCOERENTE"
    if adr_marginale is None or adr_richiesto is None:
        return "NESSUN_CONFRONTO"
    if adr_richiesto < 0.6 * adr_marginale:
        return "TARGET_SCONTATO"
    if adr_richiesto > adr_marginale:
        return "SERVE_REPRICING"
    return "SERVE_DOMANDA"


def _f(v) -> float | None:
    """NaN/NA pandas -> None (il verdetto ragiona su Optional)."""
    return None if v is None or pd.isna(v) else float(v)


@st.cache_data(ttl=300)
def load_curve() -> pd.DataFrame:
    sql = (
        f"SELECT * FROM `{PROJECT}.{DATASET}.v_booking_curve` "
        "ORDER BY business_unit_id, mese_soggiorno, snapshot_date"
    )
    df = get_client().query(sql).to_dataframe()
    for c in ("snapshot_date", "mese_soggiorno"):
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


_MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug",
         "ago", "set", "ott", "nov", "dic"]


def _mese_label(d) -> str:
    return f"{_MESI[d.month - 1]} {d.year}"


def render() -> None:
    st.title("📈 Revenue")
    st.caption(
        "Booking curve & pace — fotografie OTB che si accumulano · "
        "batteria / ADR marginale / ADR richiesto (base imponibile)"
    )
    df = load_curve()
    if df.empty:
        st.info("Nessuna fotografia OTB in `f_prenotazioni_otb`.")
        return

    bus = sorted(df["business_unit_id"].unique())
    bu = st.selectbox("Business unit", bus,
                      index=bus.index("HOTEL") if "HOTEL" in bus else 0)
    d = df[df["business_unit_id"] == bu]

    # ── freshness (stat tile) ────────────────────────────────────────────
    ultima = d["snapshot_date"].max()
    gg_fa = (pd.Timestamp.today().date() - ultima).days
    n_foto = d["snapshot_date"].nunique()
    c1, c2 = st.columns(2)
    c1.metric("Ultima foto", ultima.strftime("%d/%m/%Y"), f"{gg_fa} giorni fa",
              delta_color="off")
    c2.metric("Fotografie", n_foto)
    if gg_fa > 10:
        st.warning(
            "Foto più recente di oltre 10 giorni — manca l'export settimanale "
            "\"Andamento Prenotazioni\" (rituale: export → intake → promote)."
        )

    # ── tabella batteria (ultima foto) ───────────────────────────────────
    last = d[d["snapshot_date"] == ultima].sort_values("mese_soggiorno").copy()
    prime_foto = d.groupby("mese_soggiorno")["snapshot_date"].min()

    def _row_verdetto(r) -> str:
        stato = verdetto(
            mese_consumato=r["mese_soggiorno"] < ultima.replace(day=1),
            prima_foto=prime_foto[r["mese_soggiorno"]] == r["snapshot_date"],
            pickup_notti=_f(r["pickup_notti"]),
            gap_target=_f(r["gap_target"]),
            gap_notti_target=_f(r["gap_notti_target"]),
            adr_marginale=_f(r["adr_marginale"]),
            adr_richiesto=_f(r["adr_richiesto"]),
        )
        return STATUS_LABEL[stato]

    show = pd.DataFrame({
        "Mese": last["mese_soggiorno"].map(_mese_label),
        "Batteria": last["saturazione_pct"].clip(upper=1.0),
        "Sat. %": (last["saturazione_pct"] * 100).round(1),
        "OTB notti": last["otb_notti"],
        "OTB €": last["otb_imponibile"].round(0),
        "Pickup €/gg": last["pickup_eur_gg"].round(0),
        "ADR medio": last["otb_adr"].round(0),
        "ADR marginale": last["adr_marginale"].round(0),
        "ADR richiesto": last["adr_richiesto"].round(0),
        "Gap € target": last["gap_target"].round(0),
        "Verdetto": last.apply(_row_verdetto, axis=1),
    })
    st.dataframe(
        show, hide_index=True, use_container_width=True,
        column_config={
            "Batteria": st.column_config.ProgressColumn(
                "Batteria", min_value=0.0, max_value=1.0, format=" ",
            ),
        },
    )
    st.caption(
        "gap_notti_target = notti mancanti al volume 2025 riproporzionato "
        "sulla capacità — non la capacità residua reale. ADR richiesto = "
        "ADR medio necessario su quelle notti aggiuntive."
    )

    # ── curva delle foto (emphasis: un mese in evidenza, il resto contesto) ─
    import plotly.graph_objects as go

    mesi = list(last["mese_soggiorno"])
    ott = [m for m in mesi if m.month == 10]
    sel = st.selectbox("Mese in evidenza", mesi,
                       index=mesi.index(ott[0]) if ott else 0,
                       format_func=_mese_label)
    fig = go.Figure()
    for m, grp in d.groupby("mese_soggiorno"):
        if m == sel:
            continue
        fig.add_trace(go.Scatter(
            x=grp["snapshot_date"], y=grp["saturazione_pct"] * 100,
            mode="lines", line=dict(color=GRAY_CTX, width=1),
            hovertemplate=_mese_label(m) + " · %{y:.1f}%<extra></extra>",
        ))
    sel_grp = d[d["mese_soggiorno"] == sel]
    fig.add_trace(go.Scatter(
        x=sel_grp["snapshot_date"], y=sel_grp["saturazione_pct"] * 100,
        mode="lines+markers+text", line=dict(color=BLUE, width=2),
        marker=dict(size=9),
        text=[""] * (len(sel_grp) - 1) + [_mese_label(sel)],
        textposition="middle right",
        hovertemplate=_mese_label(sel) + " · %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        showlegend=False, height=380,
        yaxis_title="saturazione %", xaxis_title=None,
        margin=dict(l=10, r=60, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)
```

- [ ] **Step 4: Riga registry**

In `verticals/hub/registry.py`, aggiorna l'import:

```python
from verticals.hub.pages_ import accodamenti, cashflow, fb, mutui, reviews, revenue, spiaggia
```

e aggiungi in `APPS`, gruppo Finanza, dopo la riga `mutui`:

```python
    HubApp("revenue", "Revenue", "📈", "Finanza", "page", revenue.render, "booking curve & pace"),
```

- [ ] **Step 5: Aggiorna i test del registry**

In `tests/test_hub_registry.py`:

`test_pages_solo_kind_page` — aggiungi `"revenue"` al set atteso:

```python
    assert {a.id for a in pages()} == {
        "cashflow", "accodamenti", "mutui", "fb", "spiaggia", "reviews",
        "revenue",
    }
```

`test_by_group_ordine_e_contenuto` — aggiungi l'assert:

```python
    assert "revenue" in {a.id for a in g["Finanza"]}
```

- [ ] **Step 6: Verifica che i test passino**

Run: `python -m pytest tests/test_hub_revenue.py tests/test_hub_registry.py tests/test_hub_mounts.py -v`
Expected: tutti PASS.

- [ ] **Step 7: Commit**

```bash
git add verticals/hub/pages_/revenue.py verticals/hub/registry.py \
        tests/test_hub_revenue.py tests/test_hub_registry.py
git commit -m "feat(revman): pagina hub Revenue — batteria, verdetto, curva foto"
```

---

### Task 4: Verifica finale

**Files:** nessun file nuovo (solo esecuzione e, se serve, fix).

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: branch `feat/revman` pushato, pronto per il merge (decide Stefano — MAI merge autonomo su main).

- [ ] **Step 1: Suite completa + lint**

Run: `python -m pytest -q && ruff check . && ruff format --check .`
Expected: 0 failed (i test `bq` girano — non impostare `HOTELOPS_SKIP_BQ`), ruff pulito. Se `ruff format --check` segnala i file nuovi, esegui `ruff format` sui soli file del branch e ricommitta.

- [ ] **Step 2: Smoke della pagina con dati reali**

Run: `streamlit run verticals/hub/app.py` (dal worktree; interrompere con Ctrl-C dopo il check)
Expected (verifica visiva, chiedere a Stefano se non si può aprire il browser): pagina "Revenue" in nav; HOTEL default; tabella con ~7 mesi; ottobre con verdetto "⚠ serve domanda"; luglio "✓ target scontato" o consuntivo a seconda del mese corrente; curva con 3 punti sul mese in evidenza; freshness senza warning (foto 11/07).

- [ ] **Step 3: Nota palette**

La palette usa la reference instance dataviz invariata (validata: worst adjacent CVD ΔE 24.2 light — `references/palette.md` della skill). Nessuna rivalidazione necessaria finché i valori restano questi; se in futuro cambiano hue o superficie, rilanciare `validate_palette.js`.

- [ ] **Step 4: Push del branch**

```bash
git push -u origin feat/revman
```

Expected: branch remoto creato. Presentare a Stefano per merge; aggiornare issue #81 (checkbox 2 e 3) con un commento riassuntivo dopo il merge.
