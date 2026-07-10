# Budget & Planning Tables

Budget data from consultant spreadsheets, manual forecasts, and financial planning input.

---

## f_budget_mensile

**Location**: `hotelops-suite.hotelops.f_budget_mensile`
**Description**: Monthly budget by account code and BU. Combines fixed costs (Gasparotto mapping) and personnel costs.
**Primary Key**: societa_id + anno + mese + codice_conto + business_unit_id + fonte
**Row Count**: 837
**Year**: 2026
**Update**: DELETE-INSERT per anno + fonte (idempotent)
**Pipeline**: `ingest_budget_costi.py`

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `societa_id` | STRING REQUIRED | ORTI or INTUR | |
| `anno` | INTEGER REQUIRED | 2026 | |
| `mese` | INTEGER REQUIRED | 1-12 | |
| `codice_conto` | STRING REQUIRED | Account code **WITH dots** | `57.09.13` — normalize! |
| `descrizione` | STRING | Cost description | |
| `tipo_costo` | STRING | F=Fisso, V=Variabile, P=Personale, X=Oneri finanziari | |
| `categoria_ce` | STRING | P&L category | |
| `business_unit_id` | STRING | HOTEL, RESIDENCE, CVM, LIDO, HQ | |
| `importo` | FLOAT | Monthly amount (€) | Uniform 1/12 distribution |
| `fonte` | STRING | MAPPATURA or INCIDENZA | |
| `data_caricamento` | TIMESTAMP | Load timestamp | |

**Budget Totals (2026)**:
- ORTI: 1,543,295 €/year (Fixed 368K + Purchases 15K + Personnel 1,158K + Financial 1.2K)
- INTUR: 305,601 €/year (Fixed 238K + Personnel 68K)

**CRITICAL**: `codice_conto` uses **dots** (`57.09.13`). Must normalize with `REPLACE(codice_conto, '.', '')` before joining to `d_voci_piano_finanziario.cod_conto_pattern`.

---

## f_piano_finanziario_input

**Location**: `hotelops-suite.hotelops.f_piano_finanziario_input`
**Description**: Manual input for projected items (revenue budgets, loan schedules).
**Primary Key**: `hash_riga` = MD5(societa_id | voce_id | anno | mese | fonte)
**Row Count**: 142
**Period**: 2026-2027
**Update**: WRITE_APPEND with hash dedup

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `hash_riga` | STRING | Dedup key | |
| `societa_id` | STRING REQUIRED | ORTI or INTUR | |
| `voce_id` | STRING REQUIRED | FK → d_voci_piano_finanziario | Direct join |
| `anno` | INTEGER REQUIRED | Year | |
| `mese` | INTEGER REQUIRED | Month (1-12) | |
| `importo` | FLOAT | Amount (€) | |
| `fonte` | STRING | SCADENZIARIO, BVA_2026, etc. | |
| `note` | STRING | Free text | |
| `file_sorgente` | STRING | Source file | |
| `data_caricamento` | TIMESTAMP | Load timestamp | |

**Active Sources**:
- `SCADENZIARIO`: Loan installments ORTI + INTUR (voci: USCITE_MUTUI, USCITE_MUTUI_SEMESTRALE), years 2026-2027
- `BVA_2026`: Revenue budget 2026 (ENTRATE_HOTEL, ENTRATE_CVM, ENTRATE_SPIAGGIA_ORTI, ENTRATE_SPIAGGIA, ENTRATE_AFFITTI_INTUR)

**Unmapped voci** (to be added):
- ORTI: Ricavi Angelina (restaurant), Ricavi Affitti a terzi
- INTUR: Ricavi Hotel, Ricavi CVM

---

## Sample Queries

### Budget mensile per BU (ORTI 2026)
```sql
SELECT
  mese, business_unit_id, tipo_costo,
  SUM(importo) AS budget_mensile
FROM `hotelops-suite.hotelops.f_budget_mensile`
WHERE societa_id = 'ORTI' AND anno = 2026
GROUP BY mese, business_unit_id, tipo_costo
ORDER BY mese, business_unit_id;
```

### Piano finanziario input per fonte
```sql
SELECT
  voce_id, fonte, anno, mese, importo
FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
WHERE societa_id = 'ORTI'
ORDER BY anno, mese, voce_id;
```
