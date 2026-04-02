# Scadenzario → PF Excel Bridge — Design Spec

**Date:** 2026-04-02
**Status:** Approved
**Scope:** CLI command + Excel generator that maps supplier payment schedules to PF voci

## Purpose

Rosa maintains the Piano Finanziario Excel with ~80 supplier rows per voce (e.g., "Materie Prime-Consumo"), estimating amounts manually. The scadenzario fornitori (Esolver export, ingested into `f_partite_aperte_fornitori`) contains the actual committed payments with due dates. This tool bridges the two: it reads the scadenzario, maps each supplier to a PF voce via `d_fornitori`, and generates an annotated Excel that Rosa can use to update her PF with real numbers.

## Data Flow

```
situazionesinteticascadenze.xlsx ──┐
   (primary: pre-aggregated)       ├──> JOIN d_fornitori (codice_fornitore → voce_id)
   or                              │
f_partite_aperte_fornitori (BQ) ───┘           │
   (fallback: detail-level)                    ├──> group by voce_id × bucket
                                               │
Rosa's PF Excel (optional)      ───────────────┤
                                               │
                                               └──> Excel ponte (one sheet per voce)
```

## Input: Esolver "Situazione Sintetica Scadenze"

Primary input file: `situazionesinteticascadenze.xlsx` — Esolver export with one row per supplier, pre-aggregated into temporal buckets.

### File format (74 rows, 15 cols as of 2026-04-02)

| Column | Content |
|--------|---------|
| A | `"{codice} {nome_fornitore}"` — e.g., `"264 PANORAMA COMPANY S.R.L."` |
| B | Totale |
| C | Scaduto (fino a report date) |
| D | In scadenza ~+1 mese |
| E | In scadenza ~+2 mesi |
| F | In scadenza ~+3 mesi |
| G-J | Further monthly buckets |
| K | Di cui insoluti |
| L | Di cui anticipate |
| M | Di cui bloccate |
| N | Giorni medi di ritardo |
| O | Giorni medi di pagamento |

Row 1 is the header. Bucket date boundaries are in the header text (e.g., "Scadenze - In scadenza al 02/05/2026") — parser reads them dynamically.

### Parsing codice_fornitore

Extract integer prefix from column A: `int(cell.split()[0])`. Join to `d_fornitori` on `codice_fornitore`.

As of 2026-04-02: 74 suppliers in file, 64 in d_fornitori = 100% of those with partite aperte match. Some suppliers in the file may be new — those go to "DA VERIFICARE".

### Fallback: BQ

If no file provided, read from `f_partite_aperte_fornitori` (latest snapshot) and aggregate to same structure.

## Data Sources

| Source | What | Join key |
|--------|------|----------|
| `situazionesinteticascadenze.xlsx` | Pre-aggregated payables by supplier × time bucket | codice_fornitore (prefix) |
| `d_fornitori` | 64 ORTI suppliers mapped to voce_id | codice_fornitore |
| `f_partite_aperte_fornitori` (fallback) | Detail-level open payables | codice_fornitore |
| Rosa's PF Excel (optional) | Current forecasts per voce per month | voce label match |

## CLI

```bash
hotelops scadenzario --file sintetica.xlsx        # from fresh Esolver sintetica export (primary)
hotelops scadenzario                              # from BQ fallback, latest snapshot
hotelops scadenzario --pf ~/Downloads/04_APRILE_ORTI_2026.xlsx  # include Rosa's forecasts for gap analysis
hotelops scadenzario --output ~/Desktop/          # output directory (default: current dir)
hotelops scadenzario --societa INTUR              # INTUR (default: ORTI)
```

## Excel Output

Filename: `Scadenzario_PF_{societa}_{YYYY-MM-DD}.xlsx`

### Sheet 1: "Riepilogo"

All uscite voci in one table:

| Voce PF | Scaduto | Apr | Mag | Giu | Lug | Ago | Set | Ott | Nov | Dic | Totale |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Materie Prime | -72.962 | -12.062 | -392 | | | | | | | | -85.416 |
| Canone Passivo | -146.999 | | | -299.427 | | | | | | | -446.426 |
| Servizi Produzione | -16.132 | -1.772 | -13.359 | | | | | | | | -31.263 |
| Utenze | -141 | -14.174 | | | | | | | | | -14.315 |
| Consulenze | -6.119 | | | | | | | | | | -6.119 |
| Commissioni | -13 | | | | | | | | | | -13 |
| **Totale** | **-242.366** | **-28.008** | **-13.751** | **-299.427** | | | | | | | **-583.552** |

If Rosa's PF Excel is provided, add rows:
- **Rosa prevede**: her forecast for that voce/month
- **Gap (non fatturato)**: Rosa's forecast minus scadenzario amount (= purchases not yet invoiced)

### Sheets 2+: One per voce (e.g., "Materie Prime-Consumo")

| Fornitore | Cod. | Scaduto | Apr | Mag | Giu | ... | Totale |
|---|---|---|---|---|---|---|---|
| LE CROISSANT SRL | 123 | -14.277 | | | | | -14.277 |
| REIDOS S.R.L. | 456 | -14.640 | | | | | -14.640 |
| HOTELSERVICE S.R.L. | 789 | -8.022 | -4.512 | | | | -12.534 |
| ... | | | | | | | |
| **Totale scadenzario** | | **-72.962** | **-12.062** | **-392** | | | |
| **Rosa prevede** | | | **-117.460** | **-40.075** | **-95.000** | | |
| **Gap** | | | **-105.398** | **-39.683** | **-95.000** | | |

Formatting:
- Red background on "Scaduto" column (overdue payments)
- Bold totals
- Number format: #,##0 (no decimals, thousands separator)
- Only create sheets for voci that have partite (skip empty voci)

### Sheet "DA VERIFICARE" (only if unmapped suppliers exist)

| Fornitore | Cod. | Importo | Scadenza | Voce suggerita |
|---|---|---|---|---|
| (empty today — 100% coverage) | | | | |

## File: `condges/scadenzario_excel.py`

Single module, ~150 lines. Functions:

1. `parse_sintetica_scadenze(filepath)` — parse Esolver sintetica: extract codice from col A prefix, read bucket amounts, return list of dicts `{codice_fornitore, nome, totale, scaduto, buckets: {month: amount}}`
2. `load_from_bq(bq_client, societa)` — fallback: query f_partite_aperte_fornitori, aggregate to same structure
3. `load_fornitori_map(bq_client)` — read d_fornitori, return `{codice_fornitore: voce_id}`
4. `map_to_voci(partite, fornitori_map)` — join codice_fornitore → voce_id, group by voce × bucket
5. `load_pf_forecasts(pf_path)` — parse Rosa's PF Excel for comparison (optional)
6. `generate_excel(voci_data, forecasts, unmapped, output_path)` — write the Excel ponte

CLI integration: new `cmd_scadenzario` in `cli.py`.

## What This Does NOT Do

- No writes to BigQuery
- No modification of Rosa's PF Excel
- No prediction of future purchases (gap = "not yet invoiced", Rosa decides if reasonable)
- No partite aperte clienti (receivables) — only payables

## Success Criteria

1. `hotelops scadenzario` generates Excel in under 5 seconds
2. Every supplier in scadenzario maps to a PF voce (currently 100%)
3. Rosa can see per-voce, per-month breakdown with scaduto column
4. With `--pf` flag, gap analysis shows where forecasts exceed committed payments
5. Unmapped suppliers (if any) clearly flagged in DA VERIFICARE sheet
