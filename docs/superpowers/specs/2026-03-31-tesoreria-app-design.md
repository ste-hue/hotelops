# Tesoreria App — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Scope:** Streamlit app for cash flow projection and treasury management

## Purpose

Predict cashflow. Project bank balances forward for the full season. See danger zones early.

Rosa opens the app on the 1st of each month, enters the bank balance as of the last day of the previous month, loads her Piano Finanziario Excel, and immediately sees where cash goes negative. She downloads a clean Excel for the meeting and closes the app. The power lives in the app, not in the Excel.

## Architecture

```
Rosa's PF Excel ──parse──> previsioni per voce × mese
                                    │
BQ f_movimenti_contabili ──────────>│
BQ f_budget_mensile ───────────────>├──> tabella unificata
BQ d_voci_piano_finanziario ───────>│    28 voci × 12 mesi
BQ d_mapping_piano_finanziario ────>│    (previsione | budget | consuntivo)
BQ d_categorie_conti ──────────────>│
                                    │
Saldo banca manuale (sidebar) ─────┘──> proiezione cashflow

                                    └──> Excel output (buttabile)
```

**No writes to BQ. No persistent state.** Each session starts fresh from the uploaded file + BQ facts.

## Data Sources (all read-only from BQ)

| Source | What | Grain |
|--------|------|-------|
| `f_movimenti_contabili` | Esolver actuals (consuntivo) | codice_conto × date |
| `f_budget_mensile` | Approved budget 2026 | codice_conto × mese |
| `d_voci_piano_finanziario` | 28 PF voci (11 entrate, 17 uscite) with ord, sezione, categoria | voce_id |
| `d_mapping_piano_finanziario` | 220 rows: sotto_voce → codice_conto per societa | voce_id × societa |
| `d_categorie_conti` | 167 rows: codice_conto → tipo_costo, categoria_ce | codice_conto |

### Mapping chain

PF voce (Rosa's Excel) → `d_voci_piano_finanziario.voce_label` (fuzzy match) → `d_mapping_piano_finanziario.cod_conto_pattern` → `f_movimenti_contabili` (LIKE join) → consuntivo per voce.

Same chain for budget: `d_mapping_piano_finanziario.cod_conto_pattern` → `f_budget_mensile` → budget per voce.

## File: `condges/tesoreria.py`

Single Streamlit file. No new modules needed.

## User Interface

### Sidebar

- **Societa selector**: ORTI / INTUR (auto-detected from uploaded PF Excel, cell A2)
- **Anno**: default 2026
- **Data saldo banca**: date picker, defaults to last day of previous month
- **Saldo per banca**: numeric inputs
  - ORTI: MPS + Intesa (+ MPS_KROSS if present)
  - INTUR: Sella + MPS + Intesa + BCP
  - Totale computed automatically
- **Upload PF Excel**: Rosa's Piano Finanziario file (required)
- **Upload scadenzario fornitori**: `interrogazionesituazionesinteticascadenze.XLSX` format (optional)
- **Download Excel** button

### Main View (single page, no tabs — scroll flow)

#### 1. Header (top)

Big number: current bank balance with traffic light.
- Green: > €50k
- Yellow: €0–50k
- Red: < €0

#### 2. Cashflow Projection (the core)

Table:

| | Apr | Mag | Giu | Lug | Ago | Set | Ott | Nov | Dic |
|---|---|---|---|---|---|---|---|---|---|
| Saldo iniziale | 134.647 | ... | ... | ... | ... | ... | ... | ... | ... |
| + Entrate (PF Rosa) | 186.620 | ... | ... | ... | ... | ... | ... | ... | ... |
| - Uscite (PF Rosa) | -210.875 | ... | ... | ... | ... | ... | ... | ... | ... |
| - Fornitori scad. | -xxx | ... | ... | ... | ... | ... | ... | ... | ... |
| **= Saldo fine mese** | **110.392** | ... | ... | **-274.568** | ... | ... | ... | ... | ... |

Red cells where balance goes negative. This is the early warning.

Chart: bar chart (entrate green, uscite red) + cumulative balance line + red zone below zero.

#### 3. Voci PF Detail Table

28 rows × months. For each cell, three values:

**Closed months (Gen-Mar):**
| Voce | Gen prev | Gen budget | Gen cons | Delta prev | Delta budget |
|------|----------|------------|----------|------------|--------------|

- Delta prev = consuntivo - previsione Rosa (how accurate was Rosa)
- Delta budget = consuntivo - budget (how accurate was the budget)
- Color: green = better than expected, red = worse

**Future months (Apr-Dic):**
| Voce | Apr prev | Apr budget | Delta |
|------|----------|------------|-------|

- Delta = previsione Rosa - budget (where Rosa disagrees with budget)

#### 4. Drill-down per voce (expander)

Click any voce row to expand and see underlying Esolver accounts:

| Codice | Descrizione | Cat. CE | Tipo | Budget 2026 | Cons. 2025 | Cons. 2026 YTD |
|--------|-------------|---------|------|-------------|------------|----------------|
| 57.09.13.01 | Energia elettrica | F | FISSO | 11.392/mese | 8.200 | 3.515 |
| 57.09.19 | Gas | F | FISSO | 2.275/mese | 1.800 | 1.109 |

## PF Excel Parser

### Input format (Rosa's PF Excel)

Structure from `ORTI - Piano Finanziario - 03_mar2026.xlsx`:

- Sheet: "Piano Finanziario"
- Cell A2: societa ("ORTI" or "INTUR")
- Cell B2: data ultimo saldo (datetime)
- Row 2 cols C-N: month headers (GENNAIO...DICEMBRE)
- Rows 5-10: ENTRATE voci (label in col A, amounts in cols C-N)
- Rows 14-25: USCITE voci (label in col A, amounts in cols C-N)
- Row 32-33: Saldo per banca (label in A, amount in B)

### Voce matching

Match Excel label → `d_voci_piano_finanziario.voce_label` using:
1. Exact match (case-insensitive, stripped)
2. Fuzzy match (for typos like "Finaziamenti" vs "Finanziamenti")
3. Hardcoded fallback map for the known 28 voci

Warning in app if any voce doesn't match.

## Scadenzario Fornitori Parser

### Input format

File: `interrogazionesituazionesinteticascadenze.XLSX`

Columns: fornitore name, totale, scaduto, then monthly buckets (the month columns vary by file date — parser reads headers dynamically).

### Usage in app

Fornitori amounts are added to PF uscite in the cashflow projection, giving a more precise picture of upcoming payments vs Rosa's aggregate forecasts.

Shown in a separate section below the PF detail: top suppliers by amount, total per month.

## Excel Output

Single XLSX download, three sheets:

### Sheet 1: "Proiezione Cashflow"

The cashflow projection table + chart data. Clean formatting:
- Black font throughout, bold for totals and section headers
- Light grey header background
- Green pale for entrate rows, orange pale for uscite rows
- Red background on cells where saldo goes negative
- No yellow highlights anywhere

### Sheet 2: "Dettaglio Voci"

28 voci × 12 months. Three columns per month: previsione Rosa, budget, consuntivo.
Codici Esolver column showing mapped account codes per voce.

### Sheet 3: "Fornitori" (only if scadenzario uploaded)

Supplier payment schedule by month. Top suppliers highlighted.

## What This App Does NOT Do

- No writes to BigQuery
- No persistent state between sessions
- No inline editing of forecasts (Rosa edits her Excel, re-uploads)
- No INTUR-specific logic beyond societa selection (same 28 voci structure)
- No authentication (local Streamlit, runs on Stefano's machine)

## Success Criteria

1. Rosa opens app, uploads PF Excel, enters bank balance → sees cashflow projection in under 10 seconds
2. Red zones clearly visible where cash goes negative (June is the known danger: semestral MPS mortgage + ORTI→INTUR rent)
3. Drill-down shows Esolver detail behind each PF voce
4. Excel output is clean and printable, no yellow highlights
5. Budget vs consuntivo delta visible for closed months (Gen-Mar)
