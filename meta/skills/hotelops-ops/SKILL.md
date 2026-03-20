---
name: hotelops-ops
description: |
  Full operations skill for the hotelops financial data platform (Gruppo Panorama). Use this skill whenever the user mentions hotelops, piano finanziario, budget vs consuntivo, saldo banca, tesoreria, bank reconciliation, Esolver, BigQuery hotel data, Rosa, Gasparotto, ORTI, INTUR, or any hotel financial operations. Also trigger when the user asks about monthly close procedures, cash flow projections, updating budget forecasts, ingesting bank data, or generating financial Excel reports. This skill covers the entire system: CLI commands, pipeline orchestration, BigQuery queries, Excel generation, and the monthly financial routine.
---

# hotelops Operations

You are operating the hotelops financial data platform for Gruppo Panorama — a hotel group in Maiori (Amalfi Coast) with two legal entities (ORTI and INTUR) and five business units (Hotel, Residence, CVM, Lido, HQ).

The platform ingests raw files from banks, ERP (Esolver), and PMS (HotelCube) into BigQuery, then provides CLI tools, Excel reports, and WhatsApp queries for treasury management and budget control.

## The Three Temporal Dimensions

Every financial event has three timestamps. Understanding which dimension you're looking at is **the** key concept of the entire system.

| Dimension | Question | Who cares | Source in hotelops | Status |
|-----------|----------|-----------|-------------------|--------|
| **COMPETENZA** (economic) | "Quando ho consumato/generato?" | Gasparotto (CE, budget) | `f_movimenti_contabili` → `v_budget_vs_consuntivo` | ✅ Operativo |
| **CASSA** (cash flow) | "Quando il soldo entra/esce dal conto?" | Rosa (tesoreria, PF) | `f_banche_movimenti` + `f_piano_finanziario_input` → `v_piano_finanziario_mensile` | ✅ Operativo |
| **IMPEGNO** (commitment/due date) | "Quando devo pagare? Quando mi devono pagare?" | Entrambi (previsione uscite certe) | `f_partite_aperte_fornitori` → `v_previsione_cassa` | ✅ **ORTI live** (INTUR + clienti pending) |

**Example:** A hotel buys food supplies. Invoice dated March (competenza = March). Food consumed in April. Payment due in June at 60 days (impegno = June). Cash leaves in June (cassa = June).

All three dimensions are now covered for ORTI. `f_partite_aperte_fornitori` snapshots the Esolver "Situazione Partite Fornitori" export each month — showing exactly which invoices are open, their due dates, and amounts. `v_previsione_cassa` integrates this as a reference column alongside PF estimates, giving Rosa a real cash projection anchored to her actual Feb 28 bank balance (€134,647).

**Still missing:** f_partite_aperte_clienti (receivables) and f_affidamenti (credit lines). INTUR snapshot not yet loaded.

## Two Audiences, Two Views

**Rosa (Amministrazione — Tesoreria)** thinks in *cassa* (cash flow). She needs to know: how much cash do we have, what's coming in, what's going out, and will we drown?
- Primary view: `v_piano_finanziario_mensile` — 28 voci × 12 mesi, budget vs consuntivo
- Cash projection: `v_previsione_cassa` — rolling 12 mesi con ancora reale e scadenzario
- Primary tool: `hotelops pf`, `hotelops saldo`, `hotelops chiudi`
- Excel: `python -m actions.genera_piano_finanziario`
- **Monthly input**: carica scadenzario Esolver → `ingest_partite_aperte.py` + aggiorna saldo banca → `f_saldi_banca_snapshot`

**Gasparotto (Consulente — Controllo di Gestione)** thinks in *competenza* (CE accounting). He needs: budget vs actual per account code, where are we overspending, what's the break-even?
- Primary view: `v_budget_vs_consuntivo` — per codice conto × mese, with status flags
- Primary tool: `hotelops bva`
- **Future need:** seasonality-adjusted budget (not flat 1/12), operational KPIs (cost per room, per cover)

Both use the same underlying data but through different lenses. The bridge between them is account codes: `d_voci_piano_finanziario` maps 28 PF cash voci → Esolver account codes via LIKE patterns.

## The Two Entities: INTUR and ORTI

These are "communicating vessels" — if one fails, both fail.

**ORTI** is the operating company. All hotel revenue, costs, staff, and operations flow through ORTI. ORTI pays rent to INTUR (€732K/year, 6 installments of €122K, account 65.11).

**INTUR** is the holding company. Owns the hotel building, beach concession, and real estate. Receives rent from ORTI, pays mortgages and property taxes. Also operates the beach (Lido) directly.

**ORTI is also a shareholder in INTUR** (€3M capital increase), creating a dual role: tenant who wants low rent AND shareholder who wants INTUR strong.

The critical chain: ORTI revenue → ORTI pays rent → INTUR pays mortgages. If ORTI underperforms, INTUR defaults. The intercompany rent (USCITE_CANONE_PASSIVO ↔ ENTRATE_AFFITTI_INTUR) cancels in a consolidated view.

For detailed relationship mapping, read `meta/reference/INTUR_ORTI_relationship.md`.

## CLI Commands

The `hotelops` CLI is the primary interface. Install with `pip install -e .` from the repo root.

| Command | What it does |
|---------|-------------|
| `hotelops pf` | Piano Finanziario: budget vs consuntivo per voce PF, per mese. Add `--societa INTUR` or `--mese 4`. |
| `hotelops bva` | Budget vs Consuntivo: per codice conto, top N by delta. Add `--mese 3` for single month. |
| `hotelops chiudi` | Monthly close: compares last month's forecast vs actual, shows bank balance, projects forward 3 months, saves snapshot to BQ. Add `--dry-run` to preview without saving. |
| `hotelops saldo` | Bank balance (real, from snapshots) + 12-month forward cash projection with danger flags. |
| `hotelops health` | Health check: data freshness per source, row counts, gap detection. |
| `hotelops previsione <voce> <mesi> <importo>` | Write/update budget forecast. Supports Italian names: `hotelops previsione utenze aprile-dicembre 28000` |
| `hotelops voci` | List all 28 PF voci with their mappings. |

## Pipeline Orchestration

Update all data sources with one command:

```bash
python -m pipelines.orchestrate              # Full sync + ingest
python -m pipelines.orchestrate --only banca  # Just bank data
python -m pipelines.orchestrate --dry-run     # Parse without writing to BQ
```

The orchestrator syncs from Google Drive (datahub), classifies files, calls the right parser, and logs everything to a manifest.

## Monthly Routine

This is the repeatable cycle Stefano follows each month.

### Days 1-5: Update Data
```bash
python -m pipelines.orchestrate    # Sync everything
hotelops health                    # Check freshness
```

### Day 5: Close Previous Month
```bash
hotelops chiudi                    # ORTI: forecast vs actual + bank balance + save snapshot
hotelops chiudi --societa INTUR    # Same for INTUR
```
Look at every voce where the delta is large. Why did utilities cost €28K instead of €22K? Adjust future months.

### Session with Rosa (monthly)
```bash
python -m actions.genera_piano_finanziario --output ~/Desktop/PF_2026.xlsx
```
Work through the Excel voce by voce. She checks Esolver for open payables, you update:
```bash
hotelops previsione "materie prime" aprile 80000
hotelops previsione utenze 4-12 28000
hotelops saldo    # Cash projection: will we drown?
```

### Session with Gasparotto (quarterly)
```bash
hotelops bva              # Top 30 variances
hotelops bva --mese 3     # Single month detail
```

## BigQuery Data Model

Project: `hotelops-suite`, Dataset: `hotelops`.

### Key Tables

**Fact tables (transactional — append-only with MD5 dedup):**
- `f_banche_movimenti` — bank transactions (MPS, Sella, Intesa × ORTI/INTUR)
- `f_movimenti_contabili` — full Esolver journal (~32K rows, account codes without dots: 570913)
- `f_budget_mensile` — monthly budget by account code (3 sources: GASPAROTTO, MAPPATURA, INCIDENZA)
- `f_piano_finanziario_input` — cash flow forecasts (28 voci × 12 months, multiple fonti)

**Snapshot tables (point-in-time — delete-insert):**
- `f_saldi_banca_snapshot` ✅ **LIVE** — real bank balances (anchor). ORTI: MPS €67,724 + INTESA €66,922 al 28/02/2026 = €134,647. Used by `v_previsione_cassa`.
- `f_partite_aperte_fornitori` ✅ **LIVE** — open supplier payables from Esolver snapshot. ORTI 2026-03-20: 176 fatture, €573K (of which €446K intercompany). Load monthly with `ingest_partite_aperte.py`.
- `f_chiusura_mensile` — monthly close snapshots for tracking forecast accuracy

**Dimension tables:**
- `d_voci_piano_finanziario` — 28 voci mapping PF structure → Esolver account codes via LIKE patterns
- `d_piano_conti` — chart of accounts (160 codes, dotted format: 57.09.13)
- `d_categorie_conti` — account classification (167 mappings)

### Critical Conventions

**Account code formats:** d_piano_conti uses dots (57.09.13), f_movimenti_contabili uses NO dots (570913). Always join with `REPLACE(codice_conto, '.', '')`.

**Sign conventions:**
- In views: ENTRATE positive = money coming in, USCITE positive = money going out
- In Esolver raw data: ENTRATE = imp_avere - imp_dare, USCITE = imp_dare - imp_avere
- In bank data: importo_netto positive = inflow, negative = outflow

**Budget fonte tags:** Every budget row has a `fonte` field. Never mix fonti without explicit filter. Sources: GASPAROTTO (CE full), MAPPATURA (per BU), INCIDENZA (payroll), PIANO_FINANZIARIO (from XLSX), CLI (manual updates).

### Useful Query Patterns

**Piano Finanziario for a specific month:**
```sql
SELECT voce_id, voce_label, sezione, mese,
  ROUND(importo_consuntivo) AS actual,
  ROUND(importo_budget) AS budget,
  ROUND(scostamento) AS delta
FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
WHERE anno = 2026 AND societa_id = 'ORTI' AND mese = 3
ORDER BY ord
```

**Budget vs Consuntivo top variances:**
```sql
SELECT codice_conto_display, descrizione, mese,
  ROUND(budget) AS budget, ROUND(consuntivo) AS actual, ROUND(delta) AS delta, status
FROM `hotelops-suite.hotelops.v_budget_vs_consuntivo`
WHERE societa_id = 'ORTI' AND anno = 2026
ORDER BY ABS(delta) DESC LIMIT 20
```

**Bank balance at a specific date:**
```sql
SELECT banca_id, ROUND(SUM(importo_netto)) AS saldo
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI' AND data_operazione <= '2026-02-28'
GROUP BY banca_id
```
Note: this is the cumulative sum fallback. The CLI uses anchor-based calculation from f_saldi_banca_snapshot for accurate balances.

**Unmapped account codes (coverage check):**
```sql
SELECT u.cod_conto, ROUND(SUM(imp_dare - imp_avere)) AS netto
FROM hotelops.f_movimenti_contabili u
LEFT JOIN hotelops.d_voci_piano_finanziario v
  ON v.fonte = 'ESOLVER'
  AND u.cod_conto LIKE CONCAT(v.cod_conto_pattern, '%')
WHERE EXTRACT(YEAR FROM u.data_registrazione) = 2026 AND v.voce_id IS NULL
GROUP BY u.cod_conto
HAVING ABS(SUM(imp_dare - imp_avere)) > 100
ORDER BY ABS(netto) DESC
```

## Known Issues (as of March 2026)

Keep these in mind when interpreting data:

- **Saldo banca ORTI** shows −€3.26M because there's no opening balance in f_banche_movimenti. The anchor-based system (f_saldi_banca_snapshot) fixes this once bank files are synced. If saldo shows "⚠ stima cumsum", the snapshots haven't been loaded yet.
- **USCITE_MUTUI has duplicate sources** — both SCADENZIARIO and PIANO_FINANZIARIO contribute to the budget, inflating it by ~€129K. Needs a decision on which source to keep.
- **USCITE_SALARI** show very low actuals in Jan/Feb (€5.5K vs €170K budget) because payroll postings in Esolver accounts 67.01.01.xx are done at month-end and may lag.
- **USCITE_VARIE_EXT** has negative budget (−€29K/month) due to a mapping issue in the Gasparotto source.
- **Budget is flat 1/12** — the Gasparotto budget divides annual amounts equally across months. Hotels are seasonal (revenue concentrated May-September). Seasonality adjustment pending.

## Business Units

| ID | Name | Entity | Seasonality |
|----|------|--------|-------------|
| HOTEL | Hotel Panorama | ORTI | Apr-Oct |
| RESIDENCE | Angelina Residence | ORTI | Year-round |
| CVM | Casa Vacanze Maiori | ORTI | Year-round |
| LIDO | Spiaggia/Lido | INTUR | May-Sep |
| HQ | Sede/Amministrazione | Both | Year-round |

## Banks

| ID | Bank | Notes |
|----|------|-------|
| MPS | Monte dei Paschi di Siena | Main account |
| MPS_KROSS | MPS conto Kross | Separate account |
| SELLA | Banca Sella | |
| INTESA | Intesa Sanpaolo | |

## Governance Rules

- Every pipeline reads from `ingresso/` and appends to `fatti/` (and BigQuery)
- Every fact row carries 5 dimensions: societa_id, business_unit_id, funzione_id, location_id, oggetto_id
- No speculative modules — pipelines are born from real data flows
- Never modify `fatti/` manually — pipelines only
- All budget data carries a `fonte` tag — never mix fonti without explicit filter
- d_voci_piano_finanziario is the single mapping layer between PF voci and Esolver account codes
