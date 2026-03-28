# Looker-Ready BQ Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create 5 Looker Studio-optimized BigQuery views for Controllo di Gestione and Economato.

**Architecture:** Each view is a standalone SQL file in `core/bq/views/`, deployed via `CREATE OR REPLACE VIEW`. Views are denormalized with human-readable labels baked in — Looker Studio connects directly, no JOINs needed. Config refs added to `core/config.py`.

**Tech Stack:** BigQuery SQL, Python (config.py only)

**Spec:** `docs/superpowers/specs/2026-03-28-looker-views-design.md`

---

### Task 1: Add config refs for the 5 new views

**Files:**
- Modify: `core/config.py:33-37` (append after existing view refs)

- [ ] **Step 1: Add the 5 new view constants to config.py**

Add after the existing `V_PREVISIONE_CASSA` line (line 36):

```python
V_PL_MOVIMENTI                 = _t("v_pl_movimenti")
V_CASHFLOW_MENSILE             = _t("v_cashflow_mensile")
V_INCASSI_PER_CANALE           = _t("v_incassi_per_canale")

# Looker Studio views
V_CONDGES_BUDGET_CONSUNTIVO    = _t("v_condges_budget_consuntivo")
V_CONDGES_PF_MENSILE           = _t("v_condges_pf_mensile")
V_CONDGES_CASHFLOW             = _t("v_condges_cashflow")
V_ECONOMATO_CONSUMI            = _t("v_economato_consumi")
V_ECONOMATO_PARETO             = _t("v_economato_pareto")
```

Note: also adding the 3 existing views that were missing from config.py (v_pl_movimenti, v_cashflow_mensile, v_incassi_per_canale).

- [ ] **Step 2: Verify config.py is valid Python**

Run: `python -c "from core.config import V_CONDGES_BUDGET_CONSUNTIVO, V_ECONOMATO_PARETO; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/config.py
git commit -m "feat: add config refs for 5 Looker views + 3 missing existing views"
```

---

### Task 2: Create `v_condges_budget_consuntivo`

**Files:**
- Create: `core/bq/views/v_condges_budget_consuntivo.sql`

- [ ] **Step 1: Write the SQL view**

Create `core/bq/views/v_condges_budget_consuntivo.sql`:

```sql
-- v_condges_budget_consuntivo: Budget vs Consuntivo per codice conto
--
-- Looker Studio view for Controllo di Gestione.
-- Every Esolver codice_conto carries two classification lenses:
--   voce_pf      = Rosa/Tesoreria lens (28 voci PF)
--   categoria_ce = Gasparotto/CdG lens (Ricavi, Costi Produttivi, etc.)
--
-- Grain: one row per (societa, anno, mese, codice_conto)
-- Sign convention:
--   IP (ricavi):      avere - dare  → positive = revenue
--   F/V/P/X (costi):  dare - avere  → positive = cost
--   Budget: always positive (importo from f_budget_mensile is pre-signed)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_condges_budget_consuntivo` AS

WITH

-- ── Month labels ────────────────────────────────────────────────────────────
mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

-- ── Tipo costo labels ───────────────────────────────────────────────────────
tipo_labels AS (
  SELECT code, label FROM UNNEST([
    STRUCT('F' AS code, 'Fisso' AS label),
    ('V', 'Variabile'),
    ('P', 'Personale'),
    ('IP', 'Ricavo'),
    ('X', 'Extra-EBITDA')
  ])
),

-- ── Budget per codice conto per mese ────────────────────────────────────────
budget AS (
  SELECT
    societa_id,
    anno,
    mese,
    codice_conto,
    descrizione_conto,
    SUM(importo) AS importo_budget
  FROM `hotelops-suite.hotelops.f_budget_mensile`
  GROUP BY 1, 2, 3, 4, 5
),

-- ── Consuntivo per codice conto per mese ────────────────────────────────────
-- cod_conto in f_movimenti_contabili is without dots (570913)
-- codice_conto in d_categorie_conti is with dots (57.09.13)
-- We normalize to dotted format for output
consuntivo AS (
  SELECT
    m.societa_id,
    m.anno,
    m.mese,
    c.codice_conto,
    c.categoria_ce AS _cat_ce,
    c.tipo_costo   AS _tipo,
    CASE
      WHEN c.tipo_costo = 'IP' THEN m.imp_avere - m.imp_dare
      ELSE m.imp_dare - m.imp_avere
    END AS importo_consuntivo
  FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
  JOIN `hotelops-suite.hotelops.d_categorie_conti` c
    ON REPLACE(c.codice_conto, '.', '') = m.cod_conto
),

consuntivo_agg AS (
  SELECT
    societa_id,
    anno,
    mese,
    codice_conto,
    SUM(importo_consuntivo) AS importo_consuntivo
  FROM consuntivo
  GROUP BY 1, 2, 3, 4
),

-- ── Full outer join budget + consuntivo ─────────────────────────────────────
combined AS (
  SELECT
    COALESCE(b.societa_id, ca.societa_id)       AS societa_id,
    COALESCE(b.anno, ca.anno)                   AS anno,
    COALESCE(b.mese, ca.mese)                   AS mese,
    COALESCE(b.codice_conto, ca.codice_conto)   AS codice_conto,
    b.descrizione_conto,
    COALESCE(b.importo_budget, 0)               AS importo_budget,
    COALESCE(ca.importo_consuntivo, 0)          AS importo_consuntivo
  FROM budget b
  FULL OUTER JOIN consuntivo_agg ca
    ON b.societa_id = ca.societa_id
    AND b.anno = ca.anno
    AND b.mese = ca.mese
    AND REPLACE(b.codice_conto, '.', '') = REPLACE(ca.codice_conto, '.', '')
),

-- ── Map voce PF via LIKE patterns (first match) ────────────────────────────
with_voce AS (
  SELECT
    co.*,
    (
      SELECT v.voce_label
      FROM `hotelops-suite.hotelops.d_voci_piano_finanziario` v
      WHERE v.fonte = 'ESOLVER'
        AND (
             REPLACE(co.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pattern, '%')
          OR (v.cod_conto_pat2 IS NOT NULL AND REPLACE(co.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat2, '%'))
          OR (v.cod_conto_pat3 IS NOT NULL AND REPLACE(co.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat3, '%'))
        )
        AND (v.societa_id IS NULL OR v.societa_id = co.societa_id)
      ORDER BY v.ord
      LIMIT 1
    ) AS voce_pf
  FROM combined co
)

-- ── Final output ────────────────────────────────────────────────────────────
SELECT
  wv.societa_id                                                         AS societa,
  wv.anno,
  wv.mese,
  DATE(wv.anno, wv.mese, 1)                                            AS data_mese,
  ml.mese_label,
  wv.codice_conto,
  COALESCE(wv.descrizione_conto, c.descrizione, wv.codice_conto)       AS descrizione_conto,
  COALESCE(c.categoria_ce, 'Non classificato')                         AS categoria_ce,
  COALESCE(c.tipo_costo, 'N/A')                                       AS tipo_costo,
  COALESCE(tl.label, 'Altro')                                         AS tipo_costo_label,
  wv.voce_pf,
  ROUND(wv.importo_budget, 2)                                         AS importo_budget,
  ROUND(wv.importo_consuntivo, 2)                                     AS importo_consuntivo,
  ROUND(wv.importo_consuntivo - wv.importo_budget, 2)                 AS scostamento,
  CASE
    WHEN wv.importo_budget = 0 THEN NULL
    ELSE ROUND((wv.importo_consuntivo - wv.importo_budget)
               / ABS(wv.importo_budget) * 100, 1)
  END                                                                   AS scostamento_pct
FROM with_voce wv
LEFT JOIN `hotelops-suite.hotelops.d_categorie_conti` c
  ON REPLACE(c.codice_conto, '.', '') = REPLACE(wv.codice_conto, '.', '')
LEFT JOIN mese_labels ml ON ml.mese = wv.mese
LEFT JOIN tipo_labels tl ON tl.code = c.tipo_costo
ORDER BY wv.societa_id, wv.anno, wv.mese, c.categoria_ce, wv.codice_conto
```

- [ ] **Step 2: Validate SQL syntax**

Run: `python -c "open('core/bq/views/v_condges_budget_consuntivo.sql').read(); print('SQL file reads OK')"`
Expected: `SQL file reads OK`

- [ ] **Step 3: Deploy to BigQuery**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_condges_budget_consuntivo.sql`
Expected: View created/replaced successfully

- [ ] **Step 4: Smoke test — verify data comes back**

Run: `bq query --use_legacy_sql=false "SELECT societa, anno, mese, mese_label, categoria_ce, tipo_costo_label, voce_pf, COUNT(*) as n, ROUND(SUM(importo_budget),0) as budget, ROUND(SUM(importo_consuntivo),0) as consuntivo FROM hotelops.v_condges_budget_consuntivo WHERE anno = 2026 AND mese <= 3 GROUP BY 1,2,3,4,5,6,7 ORDER BY 1,2,3,5 LIMIT 20"`

Expected: Rows with readable labels like `categoria_ce = "Costi Produttivi"`, `tipo_costo_label = "Fisso"`, `voce_pf = "Utenze"`, etc. Personale budget around ~120K for Q1 ORTI.

- [ ] **Step 5: Commit**

```bash
git add core/bq/views/v_condges_budget_consuntivo.sql
git commit -m "feat: add v_condges_budget_consuntivo — budget vs actuals with CE + PF labels"
```

---

### Task 3: Create `v_condges_pf_mensile`

**Files:**
- Create: `core/bq/views/v_condges_pf_mensile.sql`

- [ ] **Step 1: Write the SQL view**

Create `core/bq/views/v_condges_pf_mensile.sql`:

```sql
-- v_condges_pf_mensile: Piano Finanziario per Looker Studio
--
-- Wraps v_piano_finanziario_mensile with human-readable labels and DATE column.
-- Adds categoria_ce from d_voci_piano_finanziario for cross-lens filtering.
--
-- Grain: one row per (societa, voce_id, anno, mese)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_condges_pf_mensile` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
)

SELECT
  pf.societa_id                                   AS societa,
  pf.anno,
  pf.mese,
  DATE(pf.anno, pf.mese, 1)                       AS data_mese,
  ml.mese_label,
  pf.voce_id,
  pf.voce_label,
  pf.sezione,
  pf.categoria,
  COALESCE(v.categoria_ce, pf.categoria)           AS categoria_ce,
  pf.ord,
  pf.tipo_periodo,
  pf.importo_consuntivo,
  pf.importo_budget,
  pf.scostamento,
  pf.scostamento_pct
FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile` pf
LEFT JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
  ON v.voce_id = pf.voce_id
LEFT JOIN mese_labels ml ON ml.mese = pf.mese
ORDER BY pf.societa_id, pf.anno, pf.mese, pf.ord
```

- [ ] **Step 2: Deploy to BigQuery**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_condges_pf_mensile.sql`
Expected: View created/replaced successfully

- [ ] **Step 3: Smoke test**

Run: `bq query --use_legacy_sql=false "SELECT societa, mese_label, voce_label, sezione, categoria_ce, tipo_periodo, importo_consuntivo, importo_budget FROM hotelops.v_condges_pf_mensile WHERE anno = 2026 AND mese = 1 AND societa_id = 'ORTI' ORDER BY ord LIMIT 15"`

Expected: 28 voci per societa/mese with readable labels. Entrate Hotel, Salari e Stipendi, etc.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_condges_pf_mensile.sql
git commit -m "feat: add v_condges_pf_mensile — PF 28 voci for Looker Studio"
```

---

### Task 4: Create `v_condges_cashflow`

**Files:**
- Create: `core/bq/views/v_condges_cashflow.sql`

- [ ] **Step 1: Write the SQL view**

Create `core/bq/views/v_condges_cashflow.sql`:

```sql
-- v_condges_cashflow: Cashflow mensile + previsione cassa per Looker Studio
--
-- Combines historical actuals (v_cashflow_mensile) with forward projections
-- (v_previsione_cassa) into a single flat timeline.
--
-- Grain: one row per (societa, anno, mese)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_condges_cashflow` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

-- ── Actuals from bank movements ─────────────────────────────────────────────
actuals AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM mese)  AS anno,
    EXTRACT(MONTH FROM mese) AS mese,
    entrate,
    uscite,
    netto,
    netto_cumulativo         AS netto_cumulato,
    'CONSUNTIVO'             AS tipo_dato
  FROM `hotelops-suite.hotelops.v_cashflow_mensile`
),

-- ── Forward projections ─────────────────────────────────────────────────────
projections AS (
  SELECT
    societa_id,
    anno,
    mese,
    entrate,
    uscite_pf                AS uscite,
    netto_pf                 AS netto,
    saldo_proiettato         AS netto_cumulato,
    tipo_periodo             AS tipo_dato,
    stato_liquidita,
    saldo_ancora
  FROM `hotelops-suite.hotelops.v_previsione_cassa`
),

-- ── Combine: actuals for past, projections for current+future ───────────────
combined AS (
  SELECT
    societa_id,
    anno,
    mese,
    entrate,
    uscite,
    netto,
    netto_cumulato,
    tipo_dato,
    CAST(NULL AS STRING)  AS stato_liquidita,
    CAST(NULL AS FLOAT64) AS saldo_ancora
  FROM actuals
  WHERE DATE(anno, mese, 1) < DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)

  UNION ALL

  SELECT
    societa_id,
    anno,
    mese,
    entrate,
    uscite,
    netto,
    netto_cumulato,
    tipo_dato,
    stato_liquidita,
    saldo_ancora
  FROM projections
)

SELECT
  c.societa_id                                    AS societa,
  c.anno,
  c.mese,
  DATE(c.anno, c.mese, 1)                         AS data_mese,
  ml.mese_label,
  ROUND(c.entrate, 0)                             AS entrate,
  ROUND(c.uscite, 0)                              AS uscite,
  ROUND(c.netto, 0)                               AS netto,
  ROUND(c.netto_cumulato, 0)                      AS netto_cumulato,
  ROUND(c.saldo_ancora, 0)                        AS saldo_ancora,
  c.tipo_dato,
  COALESCE(c.stato_liquidita,
    CASE
      WHEN c.netto_cumulato < 0     THEN 'PERICOLO'
      WHEN c.netto_cumulato < 50000 THEN 'ATTENZIONE'
      ELSE 'OK'
    END
  )                                                AS stato_liquidita
FROM combined c
LEFT JOIN mese_labels ml ON ml.mese = c.mese
ORDER BY c.societa_id, c.anno, c.mese
```

- [ ] **Step 2: Deploy to BigQuery**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_condges_cashflow.sql`
Expected: View created/replaced successfully

- [ ] **Step 3: Smoke test**

Run: `bq query --use_legacy_sql=false "SELECT societa, data_mese, mese_label, entrate, uscite, netto, netto_cumulato, tipo_dato, stato_liquidita FROM hotelops.v_condges_cashflow WHERE societa_id = 'ORTI' ORDER BY anno, mese LIMIT 20"`

Expected: Mix of CONSUNTIVO (past) and BUDGET/CORRENTE (future) rows. stato_liquidita showing OK/ATTENZIONE/PERICOLO.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_condges_cashflow.sql
git commit -m "feat: add v_condges_cashflow — cashflow + projections for Looker Studio"
```

---

### Task 5: Create `v_economato_consumi`

**Files:**
- Create: `core/bq/views/v_economato_consumi.sql`

- [ ] **Step 1: Write the SQL view**

Create `core/bq/views/v_economato_consumi.sql`:

```sql
-- v_economato_consumi: Consumi storici per reparto/prodotto/mese per Looker Studio
--
-- Mario uses this to see historical consumption patterns, cost-per-unit trends,
-- and year-over-year comparisons to inform ordering decisions.
--
-- Denominators: coperti for F&B reparti (BRK, CUCINA, BAR, etc.),
--               will use coperti for all for now (f_coperti_giornalieri).
--
-- Grain: one row per (anno, mese, reparto_id, codice_prodotto)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_economato_consumi` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

-- ── Reparto labels ──────────────────────────────────────────────────────────
reparto_labels AS (
  SELECT code, label FROM UNNEST([
    STRUCT('BRK' AS code, 'Colazione' AS label),
    ('CUCINA', 'Cucina'),
    ('BAR', 'Bar'),
    ('HSK_HOTEL', 'Housekeeping Hotel'),
    ('HSK_AR', 'Housekeeping Residence'),
    ('HSK_CVM', 'Housekeeping CVM'),
    ('DIPEND', 'Mensa Dipendenti'),
    ('MAN', 'Manutenzione'),
    ('AMM', 'Amministrazione'),
    ('BANCHETT', 'Banchetti/Eventi'),
    ('SPIAGGIA', 'Spiaggia/Lido'),
    ('PISCINA', 'Piscina'),
    ('SPA', 'SPA'),
    ('LAVANDERIA', 'Lavanderia'),
    ('RECEPTION', 'Reception'),
    ('EVENTO', 'Evento')
  ])
),

-- ── Consumi aggregated ──────────────────────────────────────────────────────
consumi AS (
  SELECT
    anno,
    mese,
    societa_id,
    business_unit_id,
    funzione_id,
    reparto_id,
    codice_prodotto,
    descrizione,
    classe,
    categoria_prodotto,
    SUM(quantita)  AS quantita,
    SUM(importo)   AS importo
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
),

-- ── Coperti mensili (denominatore F&B) ──────────────────────────────────────
coperti_mensili AS (
  SELECT
    anno,
    mese,
    SUM(numero_coperti) AS coperti_totali
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  GROUP BY 1, 2
),

-- ── Year-over-year: same month previous year ────────────────────────────────
consumi_prev AS (
  SELECT
    anno + 1 AS anno_next,
    mese,
    reparto_id,
    codice_prodotto,
    SUM(importo) AS importo_anno_prec
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  GROUP BY 1, 2, 3, 4
)

SELECT
  co.societa_id                                             AS societa,
  co.anno,
  co.mese,
  DATE(co.anno, co.mese, 1)                                AS data_mese,
  ml.mese_label,
  co.reparto_id,
  COALESCE(rl.label, co.reparto_id)                        AS reparto_label,
  co.business_unit_id,
  co.funzione_id,
  co.codice_prodotto,
  co.descrizione,
  co.classe,
  co.categoria_prodotto,
  ROUND(co.quantita, 2)                                    AS quantita,
  ROUND(co.importo, 2)                                     AS importo,
  -- Denominatore
  cp.coperti_totali                                        AS denominatore,
  CASE
    WHEN co.funzione_id IN ('F&B') THEN 'COPERTO'
    WHEN co.reparto_id IN ('BRK','CUCINA','BAR','DIPEND','BANCHETT') THEN 'COPERTO'
    ELSE 'COPERTO'  -- default to coperti for now; HSK will use pernottamenti later
  END                                                       AS tipo_denominatore,
  -- Per-unit coefficients
  CASE WHEN COALESCE(cp.coperti_totali, 0) > 0
    THEN ROUND(co.quantita / cp.coperti_totali, 6)
    ELSE NULL
  END                                                       AS coeff_per_unita,
  CASE WHEN COALESCE(cp.coperti_totali, 0) > 0
    THEN ROUND(co.importo / cp.coperti_totali, 4)
    ELSE NULL
  END                                                       AS costo_per_unita,
  -- YoY comparison
  ROUND(prev.importo_anno_prec, 2)                         AS importo_anno_prec,
  ROUND(co.importo - COALESCE(prev.importo_anno_prec, 0), 2) AS delta_yoy,
  CASE WHEN COALESCE(prev.importo_anno_prec, 0) != 0
    THEN ROUND((co.importo - prev.importo_anno_prec)
               / ABS(prev.importo_anno_prec) * 100, 1)
    ELSE NULL
  END                                                       AS delta_yoy_pct
FROM consumi co
LEFT JOIN mese_labels ml ON ml.mese = co.mese
LEFT JOIN reparto_labels rl ON rl.code = co.reparto_id
LEFT JOIN coperti_mensili cp ON cp.anno = co.anno AND cp.mese = co.mese
LEFT JOIN consumi_prev prev
  ON prev.anno_next = co.anno
  AND prev.mese = co.mese
  AND prev.reparto_id = co.reparto_id
  AND prev.codice_prodotto = co.codice_prodotto
ORDER BY co.anno, co.mese, co.reparto_id, co.importo DESC
```

- [ ] **Step 2: Deploy to BigQuery**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_economato_consumi.sql`
Expected: View created/replaced successfully

- [ ] **Step 3: Smoke test**

Run: `bq query --use_legacy_sql=false "SELECT reparto_label, mese_label, COUNT(DISTINCT codice_prodotto) as n_prodotti, ROUND(SUM(importo),0) as totale, ROUND(AVG(costo_per_unita),2) as avg_costo_per_unita FROM hotelops.v_economato_consumi WHERE anno = 2025 GROUP BY 1,2 ORDER BY 1,2 LIMIT 20"`

Expected: Rows with readable reparto labels (Colazione, Cucina, etc.) and non-null costo_per_unita values.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_economato_consumi.sql
git commit -m "feat: add v_economato_consumi — consumption + YoY + coefficients for Looker"
```

---

### Task 6: Create `v_economato_pareto`

**Files:**
- Create: `core/bq/views/v_economato_pareto.sql`

- [ ] **Step 1: Write the SQL view**

Create `core/bq/views/v_economato_pareto.sql`:

```sql
-- v_economato_pareto: ABC analysis per referenza per Looker Studio
--
-- Mario uses this to identify the 20-30 products that drive most of the spend.
-- Pareto (80/20) analysis: fascia A = top 80% of spend, B = 80-95%, C = 95-100%.
--
-- Grain: one row per (anno, reparto_id, codice_prodotto) — annual aggregate

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_economato_pareto` AS

WITH

reparto_labels AS (
  SELECT code, label FROM UNNEST([
    STRUCT('BRK' AS code, 'Colazione' AS label),
    ('CUCINA', 'Cucina'),
    ('BAR', 'Bar'),
    ('HSK_HOTEL', 'Housekeeping Hotel'),
    ('HSK_AR', 'Housekeeping Residence'),
    ('HSK_CVM', 'Housekeeping CVM'),
    ('DIPEND', 'Mensa Dipendenti'),
    ('MAN', 'Manutenzione'),
    ('AMM', 'Amministrazione'),
    ('BANCHETT', 'Banchetti/Eventi'),
    ('SPIAGGIA', 'Spiaggia/Lido'),
    ('PISCINA', 'Piscina'),
    ('SPA', 'SPA'),
    ('LAVANDERIA', 'Lavanderia'),
    ('RECEPTION', 'Reception'),
    ('EVENTO', 'Evento')
  ])
),

-- ── Annual totals per product per reparto ───────────────────────────────────
annual AS (
  SELECT
    anno,
    societa_id,
    reparto_id,
    codice_prodotto,
    descrizione,
    classe,
    categoria_prodotto,
    SUM(quantita)  AS quantita_totale,
    SUM(importo)   AS importo_totale
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  GROUP BY 1, 2, 3, 4, 5, 6, 7
),

-- ── Percentage and ranking within (anno, reparto) ───────────────────────────
ranked AS (
  SELECT
    *,
    ROUND(importo_totale / SUM(importo_totale) OVER (
      PARTITION BY anno, reparto_id
    ) * 100, 3)                                              AS pct_su_totale,
    SUM(importo_totale) OVER (
      PARTITION BY anno, reparto_id
      ORDER BY importo_totale DESC
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) / SUM(importo_totale) OVER (
      PARTITION BY anno, reparto_id
    ) * 100                                                  AS pct_cumulativa,
    ROW_NUMBER() OVER (
      PARTITION BY anno, reparto_id
      ORDER BY importo_totale DESC
    )                                                        AS rank
  FROM annual
  WHERE importo_totale > 0
)

SELECT
  r.anno,
  r.societa_id                                    AS societa,
  r.reparto_id,
  COALESCE(rl.label, r.reparto_id)               AS reparto_label,
  r.codice_prodotto,
  r.descrizione,
  r.classe,
  r.categoria_prodotto,
  ROUND(r.importo_totale, 2)                     AS importo_totale,
  ROUND(r.quantita_totale, 2)                    AS quantita_totale,
  ROUND(r.pct_su_totale, 2)                      AS pct_su_totale,
  ROUND(r.pct_cumulativa, 2)                     AS pct_cumulativa,
  r.rank,
  CASE
    WHEN r.pct_cumulativa <= 80 THEN 'A'
    WHEN r.pct_cumulativa <= 95 THEN 'B'
    ELSE 'C'
  END                                             AS fascia_abc
FROM ranked r
LEFT JOIN reparto_labels rl ON rl.code = r.reparto_id
ORDER BY r.anno, r.reparto_id, r.rank
```

- [ ] **Step 2: Deploy to BigQuery**

Run: `bq query --use_legacy_sql=false < core/bq/views/v_economato_pareto.sql`
Expected: View created/replaced successfully

- [ ] **Step 3: Smoke test — verify Pareto makes sense**

Run: `bq query --use_legacy_sql=false "SELECT reparto_label, fascia_abc, COUNT(*) as n_prodotti, ROUND(SUM(importo_totale),0) as totale, ROUND(MAX(pct_cumulativa),1) as max_pct_cum FROM hotelops.v_economato_pareto WHERE anno = 2025 GROUP BY 1,2 ORDER BY 1,2 LIMIT 20"`

Expected: Fascia A should have few products but ~80% of spend. Fascia C should have many products but ~5% of spend.

- [ ] **Step 4: Verify top products are sensible**

Run: `bq query --use_legacy_sql=false "SELECT reparto_label, rank, descrizione, ROUND(importo_totale,0) as importo, pct_su_totale, fascia_abc FROM hotelops.v_economato_pareto WHERE anno = 2025 AND reparto_id = 'BRK' AND rank <= 10 ORDER BY rank"`

Expected: Top 10 BRK products by spend. Expect items like CAFFE IN GRANI at the top (consistent with the coefficients file).

- [ ] **Step 5: Commit**

```bash
git add core/bq/views/v_economato_pareto.sql
git commit -m "feat: add v_economato_pareto — ABC analysis for top referenze in Looker"
```

---

### Task 7: Final integration commit + CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md` (add new views to the views table)

- [ ] **Step 1: Update CLAUDE.md views table**

Add to the `### Views` table in CLAUDE.md:

```markdown
| `v_condges_budget_consuntivo` | Looker: Budget vs consuntivo per codice conto, dual CE/PF labels. `core/bq/views/` |
| `v_condges_pf_mensile` | Looker: Piano Finanziario 28 voci with labels + DATE. `core/bq/views/` |
| `v_condges_cashflow` | Looker: Cashflow actuals + 12m projection + semaphore. `core/bq/views/` |
| `v_economato_consumi` | Looker: Consumi per reparto/prodotto + YoY + coefficients. `core/bq/views/` |
| `v_economato_pareto` | Looker: ABC analysis top referenze per reparto. `core/bq/views/` |
```

- [ ] **Step 2: Run full test suite**

Run: `pytest`
Expected: All existing tests pass (new views are SQL-only, no Python tests needed).

- [ ] **Step 3: Run lint**

Run: `ruff check core/config.py`
Expected: No issues

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md core/config.py
git commit -m "docs: add 5 Looker views to CLAUDE.md views table"
```
