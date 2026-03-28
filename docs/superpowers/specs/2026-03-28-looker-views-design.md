# Looker-Ready BQ Views for Controllo di Gestione & Economato

**Date:** 2026-03-28
**Status:** Approved
**Scope:** 5 new BigQuery views optimized for Looker Studio drag-and-drop

## Context

The platform has 6 existing BQ views designed for Streamlit/code consumption. Looker Studio needs flatter, denormalized views with human-readable labels baked in so dashboards require zero JOINs.

Two naming prefixes keep things clear in BigQuery:
- `v_condges_*` — Controllo di Gestione (Rosa tesoreria + Gasparotto budget/CE)
- `v_economato_*` — Economato (Mario ordering decisions)

## Key Insight: Two Labels, One Esolver Code

Every Esolver `codice_conto` carries two classification lenses:

| Context | Label | Example for `57.09.13.01` | Source |
|---------|-------|---------------------------|--------|
| Tesoreria (Rosa) | voce PF | "Utenze" | d_voci_piano_finanziario.voce_label |
| Controllo di Gestione (Gasparotto) | categoria CE | "Costi Produttivi" | d_categorie_conti.categoria_ce / d_voci_piano_finanziario.categoria_ce |

Both labels are already mapped in BQ. No new dimension tables needed.

## Views

### 1. `v_condges_budget_consuntivo`

**Audience:** Gasparotto / CdG (also usable by Rosa via voce_pf filter)
**Purpose:** Budget vs consuntivo per codice conto, with both CE and PF labels for drill-down
**Grain:** One row per (societa, anno, mese, codice_conto)

| Column | Type | Source |
|--------|------|--------|
| societa | STRING | f_budget_mensile / f_movimenti_contabili |
| anno | INT | computed |
| mese | INT | computed |
| data_mese | DATE | first day of month, for Looker time axis |
| mese_label | STRING | "Gennaio"..."Dicembre" |
| codice_conto | STRING | dotted format (57.09.13) |
| descrizione_conto | STRING | f_budget_mensile.descrizione_conto |
| categoria_ce | STRING | d_categorie_conti — "Ricavi", "Costi Produttivi", "Costi Commerciali", "Costi Amministrativi", "Costi del Personale", "Oneri Tributari", "Oneri Finanziari" |
| tipo_costo | STRING | d_categorie_conti — F/V/P/IP/X |
| tipo_costo_label | STRING | "Fisso", "Variabile", "Personale", "Ricavo", "Extra-EBITDA" |
| voce_pf | STRING | d_voci_piano_finanziario.voce_label — "Utenze", "Salari", etc. (Rosa's lens) |
| importo_budget | FLOAT64 | from f_budget_mensile |
| importo_consuntivo | FLOAT64 | from f_movimenti_contabili (imp_dare - imp_avere for costs, imp_avere - imp_dare for revenues) |
| scostamento | FLOAT64 | consuntivo - budget |
| scostamento_pct | FLOAT64 | (consuntivo - budget) / NULLIF(budget, 0) |

**Join logic:**
- f_budget_mensile FULL OUTER JOIN f_movimenti_contabili on (societa, anno, mese, codice_conto)
- LEFT JOIN d_categorie_conti on codice_conto (REPLACE dots)
- LEFT JOIN d_voci_piano_finanziario via cod_conto_pattern LIKE

**Looker Studio usage:**
- Level 1: Bar chart by `categoria_ce` per month
- Level 2: Drill into `descrizione_conto` within a categoria
- Level 3: See `codice_conto` details
- Toggle lens: filter/group by `voce_pf` instead for Rosa's view

### 2. `v_condges_pf_mensile`

**Audience:** Rosa / Tesoreria
**Purpose:** Piano Finanziario 28 voci, budget vs consuntivo, rolling 18-month window
**Grain:** One row per (societa, voce_id, anno, mese)

| Column | Type | Source |
|--------|------|--------|
| societa | STRING | scaffold |
| anno | INT | scaffold |
| mese | INT | scaffold |
| data_mese | DATE | first day of month |
| mese_label | STRING | "Gennaio"..."Dicembre" |
| voce_id | STRING | d_voci_piano_finanziario |
| voce_label | STRING | "Entrate Hotel", "Salari e Stipendi", etc. |
| sezione | STRING | "ENTRATE" / "USCITE" |
| categoria | STRING | "Ricavi", "Personale", "Utenze", etc. |
| categoria_ce | STRING | "Ricavi", "Costi Produttivi", etc. |
| ord | INT | display ordering |
| importo_consuntivo | FLOAT64 | from v_piano_finanziario_consuntivo |
| importo_budget | FLOAT64 | from f_budget_mensile + f_piano_finanziario_input |
| scostamento | FLOAT64 | consuntivo - budget |
| scostamento_pct | FLOAT64 | computed |
| tipo_periodo | STRING | "CONSUNTIVO" (past) / "BUDGET" (current+future) |

**Implementation:** Wraps existing `v_piano_finanziario_mensile` adding labels and `data_mese` DATE column.

### 3. `v_condges_cashflow`

**Audience:** Rosa / CdG
**Purpose:** Monthly cashflow actuals + 12-month forward projection with liquidity semaphore
**Grain:** One row per (societa, anno, mese)

| Column | Type | Source |
|--------|------|--------|
| societa | STRING | |
| anno | INT | |
| mese | INT | |
| data_mese | DATE | first day of month |
| mese_label | STRING | "Gennaio"..."Dicembre" |
| entrate | FLOAT64 | bank inflows |
| uscite | FLOAT64 | bank outflows |
| netto | FLOAT64 | entrate - uscite |
| netto_cumulato | FLOAT64 | running sum |
| saldo_proiettato | FLOAT64 | from v_previsione_cassa |
| stato_liquidita | STRING | "OK" / "ATTENZIONE" / "PERICOLO" |
| tipo_dato | STRING | "CONSUNTIVO" (past months with bank data) / "PROIEZIONE" (future months) |

**Implementation:** Combines `v_cashflow_mensile` (actuals) with `v_previsione_cassa` (projections) into a single flat timeline.

### 4. `v_economato_consumi`

**Audience:** Mario / Economato
**Purpose:** Historical consumption by department/product/month with per-unit coefficients and YoY comparison
**Grain:** One row per (anno, mese, reparto_id, codice_prodotto)

| Column | Type | Source |
|--------|------|--------|
| anno | INT | f_consumi_economato |
| mese | INT | f_consumi_economato |
| data_mese | DATE | first day of month |
| mese_label | STRING | "Gennaio"..."Dicembre" |
| reparto_id | STRING | f_consumi_economato — BRK, CUCINA, HSK_HOTEL, etc. |
| reparto_label | STRING | mapped in view — "Colazione", "Cucina", "Housekeeping Hotel", etc. |
| business_unit_id | STRING | f_consumi_economato |
| funzione_id | STRING | f_consumi_economato — F&B, ROOMS, MAN, etc. |
| codice_prodotto | STRING | f_consumi_economato |
| descrizione | STRING | product description |
| classe | STRING | FOOD, BEVERAGE, VARIE |
| categoria_prodotto | STRING | PRODOTTI CAFFETTERIA, ORTAGGI, PESCE SURGELATO, etc. |
| quantita | FLOAT64 | aggregated |
| importo | FLOAT64 | aggregated |
| denominatore | FLOAT64 | coperti (F&B) or pernottamenti (HSK) from f_coperti_giornalieri / f_pms_statistiche |
| tipo_denominatore | STRING | "COPERTO" / "PERNOTTAMENTO" |
| coeff_per_unita | FLOAT64 | quantita / denominatore |
| costo_per_unita | FLOAT64 | importo / denominatore |
| importo_anno_prec | FLOAT64 | same product/reparto/month, previous year |
| delta_yoy | FLOAT64 | importo - importo_anno_prec |
| delta_yoy_pct | FLOAT64 | percentage change |

**Join logic:**
- f_consumi_economato aggregated by (anno, mese, reparto_id, codice_prodotto)
- LEFT JOIN f_coperti_giornalieri (aggregated monthly) for F&B denominators
- LEFT JOIN with self on (anno-1, mese, reparto_id, codice_prodotto) for YoY
- Reparto label mapping via CASE statement

**Looker Studio usage:**
- Filter by reparto, see consumption trends over time
- Compare months YoY: "marzo 2026 vs marzo 2025"
- Identify cost-per-coperto trends by department
- Share with department heads: "BRK costa €X per coperto questo mese"

### 5. `v_economato_pareto`

**Audience:** Mario / Economato
**Purpose:** ABC analysis — top referenze ranked by % impact on total spend. Answers "which 20-30 products eat the budget?"
**Grain:** One row per (anno, reparto_id, codice_prodotto) — annual aggregate

| Column | Type | Source |
|--------|------|--------|
| anno | INT | |
| reparto_id | STRING | |
| reparto_label | STRING | mapped in view |
| codice_prodotto | STRING | |
| descrizione | STRING | |
| classe | STRING | FOOD, BEVERAGE, VARIE |
| categoria_prodotto | STRING | |
| importo_totale | FLOAT64 | SUM(importo) for the year |
| quantita_totale | FLOAT64 | SUM(quantita) for the year |
| pct_su_totale | FLOAT64 | importo / SUM(importo) OVER (PARTITION BY anno, reparto_id) |
| pct_cumulativa | FLOAT64 | running SUM of pct_su_totale ordered by importo DESC |
| rank | INT | ROW_NUMBER ordered by importo DESC |
| fascia_abc | STRING | "A" (top 80%), "B" (80-95%), "C" (95-100%) |

**Looker Studio usage:**
- Pareto chart: bars = importo per product, line = pct_cumulativa
- Filter by reparto to see each department's top products
- Scorecards: "Top 20 referenze = X% del totale acquisti"
- Table filtered to fascia A = the products worth Mario's attention

## Dependencies

**Existing tables required (all already in BQ):**
- Fact: f_budget_mensile, f_movimenti_contabili, f_banche_movimenti, f_piano_finanziario_input, f_consumi_economato, f_coperti_giornalieri, f_saldi_banca_snapshot, f_partite_aperte_fornitori
- Dimension: d_voci_piano_finanziario, d_categorie_conti, d_mapping_piano_finanziario
- Views: v_piano_finanziario_mensile, v_piano_finanziario_consuntivo, v_previsione_cassa, v_cashflow_mensile

**No new dimension tables needed.** All label mappings exist.

## Deployment

- SQL files go in `core/bq/views/` following existing pattern
- Config refs added to `core/config.py` as `V_CONDGES_*` and `V_ECONOMATO_*`
- Existing `v_*` views remain untouched (Streamlit apps depend on them)

## Out of Scope

- Streamlit economato ordering app (magazzino snapshot + presenze previste + fabbisogno calculation) — separate project
- LookML model files — not needed for Looker Studio (connects directly to BQ views)
- Looker Studio dashboard creation — manual drag-and-drop after views are deployed
- Ingestion of coefficienti per pasto refined denominators — separate pipeline work
