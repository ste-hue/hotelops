---
name: hotelops-data-analyst
description: "HotelOps data analysis skill for querying BigQuery. Provides full context for the hotelops-suite project: entity definitions (ORTI / INTUR), metric calculations, account code conventions, and common query patterns. Use when analyzing HotelOps data for: (1) Budget vs Consuntivo variance analysis, (2) Cashflow and liquidity monitoring, (3) Costi per Business Unit, or any finance/accounting questions requiring hotelops-specific context."
---

# HotelOps Data Analysis

**Progetto BigQuery**: `hotelops-suite`
**Dataset**: `hotelops`
**Entità operative**: ORTI (hotel operations), INTUR (holding finanziaria)

## SQL Dialect: BigQuery

- **Table references**: Use backticks: \`hotelops-suite.hotelops.table_name\`
- **Safe division**: `SAFE_DIVIDE(a, b)` returns NULL instead of error
- **Date functions**:
  - `DATE_TRUNC(date_col, MONTH)`
  - `DATE_SUB(date_col, INTERVAL 1 DAY)`
  - `DATE_DIFF(end_date, start_date, DAY)`
- **Column exclusion**: `SELECT * EXCEPT(column_to_exclude)`
- **String matching**: `LIKE`, `REGEXP_CONTAINS(col, r'pattern')`
- **NULLs in aggregations**: Most functions ignore NULLs; use `IFNULL()` or `COALESCE()`

---

## Entity Disambiguation

### "Società" — ALWAYS separate

ORTI and INTUR are **always analyzed separately**. Every query MUST include a `WHERE societa_id = 'ORTI'` or `WHERE societa_id = 'INTUR'` filter. Never combine them unless explicitly requested for consolidated group totals.

| Società | Full Name | Role |
|---------|-----------|------|
| **ORTI** | ORTI SRL | Hotel operations (Hotel, Residence, CVM, Lido, HQ) |
| **INTUR** | INTUR SRL | Holding finanziaria / gestione immobiliare |

**Banche attive**:
- ORTI → MPS, MPS_KROSS
- INTUR → MPS, SELLA, INTESA

### "Conto" can mean:

- **Codice conto** (`cod_conto` / `codice_conto`): Account code from Esolver's piano dei conti. **WARNING**: Format varies by table — see Conventions section below.
- **Conto bancario**: Bank account — identified by `banca_id` + `societa_id` in `f_banche_movimenti`
- **Conto economico (CE)**: Income statement — `sezione = 'CE'` in `d_piano_conti`
- **Stato patrimoniale (SP)**: Balance sheet — `sezione = 'SP'` in `d_piano_conti`

### "Voce" means:

A **voce del piano finanziario** — a conceptual financial line item that maps across multiple source systems. Defined in `d_voci_piano_finanziario` and identified by `voce_id` (e.g., `ENTRATE_HOTEL`, `USCITE_SALARI`). A single voce can pull data from Esolver account codes, bank transaction types, or manual input.

---

## Business Terminology

| Colloquial Term | Actual Meaning | Maps To |
|-----------------|----------------|---------|
| "Utenze" | Electricity + Water + Gas + Telecom + Internet | Multiple `USCITE_UTENZE_*` voci in `d_voci_piano_finanziario` |
| "Costi fissi" | Fixed costs per BU (rent, insurance, etc.) | `tipo_costo = 'F'` in `f_budget_mensile` |
| "Costi variabili" | Variable costs (supplies, food) | `tipo_costo = 'V'` in `f_budget_mensile` |
| "Personale" | HR/labor costs by division | `tipo_costo = 'P'` + `d_personale_mensile` |
| "Scadenziario" | Informal payment schedule | `f_piano_finanziario_input` with `fonte = 'SCADENZIARIO'` |
| "Budget Gasparotto" | Consultant's budget categorization | `f_budget_mensile` + `d_budget_costi_fissi` |
| "Bilancino" | Bilancio di verifica (trial balance) | `f_bilancino` |
| "Mastrino" | Ledger detail by account | `f_movimenti_contabili` (prima nota); il mastrino banca Esolver arriva via `ingest_scheda_contabile` → `f_saldi_banca_snapshot` |
| "Accodamenti" | Bank-side entries in Esolver | `f_accodamenti` |
| "PNC" | Prima Nota Contabile | Reference in `rif_registrazione` |
| "Giroconti" | Internal accounting transfers | No real cash flow — exclude from cashflow analysis |
| "Partitario" | Sub-ledger (C/F/B/S) | `tipo_conto` in `d_piano_conti` |

### Business Units

| ID | Descrizione |
|----|-------------|
| HOTEL | Hotel ricettivo |
| RESIDENCE | Residence |
| CVM | Casa Vacanza / Mini appartamenti |
| LIDO | Spiaggia / Stabilimento balneare |
| HQ | Direzione / Amministrazione |

---

## Standard Filters

Always apply these filters unless explicitly told otherwise:

```sql
-- ALWAYS filter by società (never combine unless asked)
WHERE societa_id = 'ORTI'  -- or 'INTUR'

-- Exclude intercompany transfers from cashflow/P&L
  AND NOT (
    rag_sociale LIKE '%INTUR%'   -- when querying ORTI
    -- OR rag_sociale LIKE '%ORTI%'  -- when querying INTUR
  )

-- Exclude giroconti (partite di giro) from cash analysis
-- These are internal accounting transfers, not real cash flows
```

**When to override**:
- **Consolidated group view**: Include both società when asked for "totale gruppo"
- **Intercompany reconciliation**: Include intercompany transfers to check they net to zero

---

## Key Metrics

### Budget vs Consuntivo (Scostamento)
- **Definition**: Variance between budgeted and actual amounts per voce per month
- **Source**: `v_piano_finanziario_mensile`
- **Formula**: `scostamento = importo_consuntivo - importo_budget` and `scostamento_pct`
- **Time grain**: Monthly
- **Caveats**: `tipo_periodo` = CONSUNTIVO for past months, BUDGET for future months. View uses rolling 18-month window (-6m → +12m from today).

### Cashflow Netto Mensile
- **Definition**: Net cash in/out per month
- **Source**: `v_cashflow_mensile` or derived from `f_banche_movimenti`
- **Formula**: `SUM(importo_credito) - SUM(importo_debito)` or `SUM(importo_netto)`
- **Caveats**: `importo_netto` is already signed (positive = inflow, negative = outflow). Exclude intercompany.

### Costi per BU
- **Definition**: Cost breakdown by Business Unit
- **Source**: `f_budget_mensile` (budget) or `f_movimenti_contabili` + `cod_divisione` (actual)
- **Formula**: `SUM(importo)` grouped by `business_unit_id`
- **Caveats**: Budget uses BU split from `d_budget_costi_fissi`. Actuals depend on `cod_divisione` mapping.

### Incassi POS
- **Definition**: POS credit card receipts
- **Source**: `f_banche_movimenti`
- **Formula**: `SUM(importo_credito) WHERE tipo_movimento LIKE '%(09)%'`
- **Caveats**: tipo_movimento format includes code prefix like "(09)" for POS.

---

## Data Freshness

| Table | Update Method | Typical Lag | Check Query |
|-------|---------------|-------------|-------------|
| `f_movimenti_contabili` | Manual XLS upload | Days-weeks (registration delays!) | `SELECT MAX(data_registrazione)` |
| `f_banche_movimenti` | CSV from home banking | 1-3 days | `SELECT MAX(data_operazione)` |
| `f_budget_mensile` | Annual/periodic Excel | N/A (budget is static per year) | Check `data_caricamento` |
| `f_piano_finanziario_input` | Manual CSV | N/A (projections) | Check `data_caricamento` |
| `f_bilancino` | Periodic Esolver export | Weeks | Check `data_ingresso` |

**CRITICAL**: Registration delays mean `f_movimenti_contabili` can be weeks behind. Always check `MAX(data_registrazione)` before drawing conclusions about recent months.

To check all freshness at once:
```sql
SELECT 'movimenti' AS src, MAX(data_registrazione) AS latest
FROM `hotelops-suite.hotelops.f_movimenti_contabili`
UNION ALL
SELECT 'banche', MAX(data_operazione)
FROM `hotelops-suite.hotelops.f_banche_movimenti`
UNION ALL
SELECT 'bilancino', CAST(MAX(data_ingresso) AS DATE)
FROM `hotelops-suite.hotelops.f_bilancino`
```

---

## Knowledge Base Navigation

Use these reference files for detailed table documentation:

| Domain | Reference File | Use For |
|--------|----------------|---------|
| Contabilità (fact tables) | `references/tables/contabilita.md` | f_movimenti_contabili, f_bilancino, f_accodamenti |
| Banche (bank movements) | `references/tables/banche.md` | f_banche_movimenti, incassi, cashflow |
| Budget & Planning | `references/tables/budget.md` | f_budget_mensile, f_piano_finanziario_input |
| Dimensioni | `references/tables/dimensioni.md` | d_voci_piano_finanziario, d_piano_conti, d_budget_costi_fissi, etc. |
| Entities & Relationships | `references/entities.md` | Entity definitions, join keys, LIKE-pattern logic |
| Metrics | `references/metrics.md` | KPI calculations and formulas |

---

## Common Query Patterns

### Budget vs Consuntivo per Voce (ORTI, 2026)
```sql
SELECT
  mese, voce_id, voce_label,
  importo_consuntivo, importo_budget,
  scostamento, scostamento_pct
FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
WHERE anno = 2026
  AND societa_id = 'ORTI'
  AND (importo_consuntivo != 0 OR importo_budget != 0)
ORDER BY mese, ord;
```

### Movimenti bancari per tipo (ORTI, MPS)
```sql
SELECT
  data_operazione, tipo_movimento, descrizione,
  importo_credito, importo_debito, importo_netto
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI' AND banca_id = 'MPS'
ORDER BY data_operazione DESC;
```

### Costi consuntivo per conto (ORTI, anno corrente)
```sql
SELECT
  cod_conto,
  pc.descrizione AS desc_conto,
  SUM(imp_dare) AS tot_dare,
  SUM(imp_avere) AS tot_avere,
  SUM(imp_dare - imp_avere) AS saldo
FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
LEFT JOIN `hotelops-suite.hotelops.d_piano_conti` pc
  ON m.cod_conto = pc.codice_conto
WHERE m.societa_id = 'ORTI' AND m.anno = 2026
GROUP BY cod_conto, pc.descrizione
ORDER BY saldo DESC;
```

### Cashflow mensile per banca
```sql
SELECT
  FORMAT_DATE('%Y-%m', data_operazione) AS periodo,
  banca_id,
  SUM(importo_credito) AS entrate,
  SUM(importo_debito) AS uscite,
  SUM(importo_netto) AS netto
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI'
GROUP BY periodo, banca_id
ORDER BY periodo, banca_id;
```

---

## Troubleshooting

### Common Mistakes

1. **Codice conto dot format confusion**: `f_movimenti_contabili` uses codes **without dots** (`570913`), while `f_budget_mensile` uses **with dots** (`57.09.13`). Always normalize: `REPLACE(codice_conto, '.', '')` before cross-table joins.

2. **Double-counting macro vs detail**: Only leaf accounts (`cod_conto` in `f_movimenti_contabili`) have movements. Parent/group accounts in `d_piano_conti` do NOT appear in the fact table, so no risk there. But **do not** sum both `f_movimenti_contabili` (Esolver) and `f_banche_movimenti` (bank) for the same transaction — they are different perspectives.

3. **Sign convention confusion**:
   - `f_movimenti_contabili`: `imp_dare` and `imp_avere` are always positive. For ENTRATE: `imp_avere - imp_dare`. For USCITE: `imp_dare - imp_avere`.
   - `f_banche_movimenti`: `importo_netto` is already signed (positive = entrata).

4. **Overlapping terminology**: The "piano finanziario" (scadenziario/cash forecast) is NOT the "piano dei conti" (chart of accounts). The "budget Gasparotto" (consultant categories) uses different groupings than Esolver's codici conto. Use `d_voci_piano_finanziario` as the Rosetta Stone that maps across all three.

5. **Registration delays**: Esolver entries (`f_movimenti_contabili`) can lag weeks behind actual transactions. Bank data (`f_banche_movimenti`) is more current. Don't conclude "no costs this month" without checking data freshness.

6. **Intercompany inflation**: ORTI↔INTUR transfers appear as real movements in both entities. Filter them out for P&L and cashflow analysis unless doing intercompany reconciliation.

### Performance Tips
- Filter by `societa_id` and `anno` first to reduce scan (tables are not partitioned but these are the strongest filters)
- Prefer views (`v_piano_finanziario_mensile`, `v_cashflow_mensile`) over raw joins when possible
- Use `LIMIT` during exploration
