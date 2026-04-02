# Scadenzario → PF Excel Bridge — Design Spec

**Date:** 2026-04-02
**Status:** Approved
**Scope:** CLI command + Excel generator that maps supplier payment schedules to PF voci

## Purpose

Rosa maintains the Piano Finanziario Excel with ~80 supplier rows per voce (e.g., "Materie Prime-Consumo"), estimating amounts manually. The scadenzario fornitori (Esolver export, ingested into `f_partite_aperte_fornitori`) contains the actual committed payments with due dates. This tool bridges the two: it reads the scadenzario, maps each supplier to a PF voce via `d_fornitori`, and generates an annotated Excel that Rosa can use to update her PF with real numbers.

## Data Flow

```
f_partite_aperte_fornitori (BQ)  ──┐
   or                              ├──> JOIN d_fornitori (codice_fornitore → voce_id)
scadenzario.xlsx (fresh file)   ───┘           │
                                               ├──> group by voce_id × mese_scadenza
                                               │
Rosa's PF Excel (optional)      ───────────────┤
                                               │
                                               └──> Excel ponte (one sheet per voce)
```

## Data Sources

| Source | What | Join key |
|--------|------|----------|
| `f_partite_aperte_fornitori` | Open payables with due dates | codice_fornitore |
| `d_fornitori` | 64 ORTI suppliers mapped to voce_id | codice_fornitore |
| Rosa's PF Excel (optional) | Current forecasts per voce per month | voce label match |

### Matching: fornitori → voci PF

Join on `codice_fornitore` (integer FK). As of 2026-04-02: 64/64 suppliers in partite aperte have a match in d_fornitori. 100% coverage, no fuzzy matching needed.

If new suppliers appear without a d_fornitori entry, they go to a "DA VERIFICARE" sheet.

## CLI

```bash
hotelops scadenzario                              # from BQ, latest snapshot
hotelops scadenzario --file scadenze.xlsx         # from fresh Esolver export
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

1. `load_partite(bq_client, societa, file=None)` — load from BQ or parse fresh file
2. `map_to_voci(partite, fornitori_map)` — join codice_fornitore → voce_id, group by voce × month
3. `load_pf_forecasts(pf_path)` — parse Rosa's PF Excel for comparison (optional)
4. `generate_excel(voci_data, forecasts, output_path)` — write the Excel ponte

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
