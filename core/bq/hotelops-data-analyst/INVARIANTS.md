# HotelOps System Invariants

Universal rules for any Claude session operating within the HotelOps ecosystem.
Import this file in CLAUDE.md or attach as context to enforce consistency across all sessions.

---

## System Architecture

```
Obsidian Vault (Knowledge)     hotelops repo (ETL Code)     Google Drive (Staging)     BigQuery (Warehouse)
──────────────────────────     ─────────────────────────     ──────────────────────     ────────────────────
ontology/                      pipelines/                   ingresso/                  hotelops-suite.hotelops
  companies/                     amministrativa/              banca/                     f_* (fact tables)
  banks/                         banca/                       amministrativa/            d_* (dimension tables)
  loans/                       bq/                            economato/                 v_* (views)
  financial/                     dimensioni/                  pms/
  departments/                   views/                     dimensioni/
  advisors/                    scripts/                     fatti/
  people/                                                   meta/
  projects/
```

**Flow**: Manual exports → Drive `ingresso/` (staging) → ETL pipeline → BigQuery (warehouse) → Views → Analysis

---

## INVARIANT 1: Idempotent Ingestion

Every pipeline MUST be idempotent. Running it twice with the same input produces the same result.

### Patterns (use one per table):

| Pattern | When to Use | How It Works |
|---------|-------------|--------------|
| **HASH DEDUP** | Append-only fact tables | `hash_riga = MD5(natural_key)`. Pipeline does `WRITE_APPEND` filtering out hashes already in BQ. |
| **DELETE-INSERT** | Snapshot/periodic tables | `DELETE WHERE anno = X AND fonte = Y`, then `INSERT`. Entire slice replaced. |
| **WRITE_TRUNCATE** | Small dimension tables | Full replace of entire table from CSV source of truth. |

### Rules:
- Every fact table (`f_*`) MUST have a `hash_riga` column (MD5 of its natural key)
- Natural key components MUST be documented in table header comments
- Never use `WRITE_TRUNCATE` on fact tables — data is immutable
- Never use `WRITE_APPEND` without hash dedup — duplicates corrupt everything
- Always include `data_ingresso` or `data_caricamento` timestamp for audit trail

---

## INVARIANT 2: 5-Dimension Classification

Every fact SHOULD be classifiable along 5 axes. Not all are required for every table, but the ontology is always the same:

| Dimension | Column Name | Values | Required? |
|-----------|-------------|--------|-----------|
| **Società** | `societa_id` | ORTI, INTUR | **YES — always** |
| **Business Unit** | `business_unit_id` | HOTEL, RESIDENCE, CVM, LIDO, HQ | When applicable |
| **Funzione** | Implicit via `cod_conto` or `voce_id` | Piano dei conti hierarchy | Via join |
| **Location** | `location_id` | Maiori, etc. | When applicable |
| **Oggetto** | `oggetto_id` | Transaction-specific | When applicable |

### Rules:
- `societa_id` is NEVER nullable and NEVER optional
- Queries MUST filter by `societa_id` unless explicitly doing consolidated group analysis
- New tables MUST include `societa_id` as first business column after hash

---

## INVARIANT 3: Account Code Normalization

Account codes (`codice_conto` / `cod_conto`) exist in TWO formats across the system:

| Format | Example | Where Used |
|--------|---------|------------|
| **Without dots** | `570913` | `f_movimenti_contabili.cod_conto`, `d_piano_conti.codice_conto`, `d_voci_piano_finanziario.cod_conto_pattern` |
| **With dots** | `57.09.13` | `f_budget_mensile.codice_conto`, Esolver raw exports, `d_budget_costi_fissi.codice_conto` |

### Rules:
- Internal BQ storage for NEW tables: **always without dots** (6-8 digit string)
- When joining across formats: `REPLACE(codice_conto, '.', '')` to normalize
- `d_voci_piano_finanziario` patterns are always without dots — match via `LIKE CONCAT(pattern, '%')`
- Never assume format — always check which table you're reading from

---

## INVARIANT 4: Sign Convention

| Context | Positive Means | Negative Means |
|---------|---------------|----------------|
| `f_movimenti_contabili.imp_dare` | Debit amount | Never negative |
| `f_movimenti_contabili.imp_avere` | Credit amount | Never negative |
| `f_banche_movimenti.importo_netto` | Cash inflow | Cash outflow |
| `f_banche_movimenti.importo_credito` | Inflow amount | Never negative |
| `f_banche_movimenti.importo_debito` | Outflow amount | Never negative |
| Views: ENTRATE amounts | Cash received | — |
| Views: USCITE amounts | Cash spent | — |

### Rules:
- For P&L from Esolver: ENTRATE = `imp_avere - imp_dare`, USCITE = `imp_dare - imp_avere`
- For cashflow from bank: use `importo_netto` directly (already signed)
- Views normalize this — prefer views over raw computation when possible
- NEVER mix Esolver and bank data for the same transaction without dedup logic

---

## INVARIANT 5: File Naming in Drive Staging

Files landing in `ingresso/` MUST follow this naming convention:

```
YYYY-MM-DD__TIPO__SORGENTE__DETTAGLIO.ext
```

Examples:
- `2026-03-15__MOVBANCA__MPS__ORTI.csv`
- `2026-03-01__LISTAMOVCONT__ESOLVER__ORTI.xls`
- `2026-01-01__BUDGET__MAPPATURA__v2.xlsx`

### Rules:
- Date is the export date (when file was generated), not the period it covers
- `TIPO` identifies what kind of data (MOVBANCA, LISTAMOVCONT, BUDGET, BILANCINO, etc.)
- `SORGENTE` identifies the system (MPS, ESOLVER, SELLA, INTESA, MAPPATURA)
- `DETTAGLIO` is free-form but should include società when relevant
- Pipelines record `file_sorgente` in every row they ingest for full traceability

---

## INVARIANT 6: Terminology Mapping

There are THREE "languages" in the system that describe the same financial reality:

| Layer | Source | Example | Authority |
|-------|--------|---------|-----------|
| **Colloquial** | Scadenziari, meetings | "utenze", "stipendi" | Human understanding |
| **Gestionale** | Budget Gasparotto | "Costi produttivi", "Costi amministrativi" | `d_budget_costi_fissi`, `d_categorie_conti` |
| **Contabile** | Esolver piano dei conti | `570913` = "En. Elettrica sede" | `d_piano_conti` |

### The Rosetta Stone: `d_voci_piano_finanziario`

This table is the SINGLE SOURCE OF TRUTH for mapping between languages:
- `voce_id` + `voce_label` = the canonical name
- `cod_conto_pattern` = maps to Esolver account codes
- `banca_tipo_pat` = maps to bank transaction types
- `categoria` = maps to gestionale categories
- `tipo_costo` = maps to cost type (F/V/P/X)

### Rules:
- When user says something colloquial ("quanto spendiamo in utenze?"), translate to the appropriate `voce_id` first
- When creating new analysis, always ground it in `d_voci_piano_finanziario` mappings
- If a voce doesn't exist for a concept, propose adding it to the dictionary — don't create ad-hoc mappings
- Never create parallel mapping systems — extend the existing one

---

## INVARIANT 7: Intercompany Discipline

ORTI and INTUR have real financial flows between them (rent, capital movements). These must be handled carefully:

### Rules:
- **P&L analysis**: Exclude intercompany (ORTI rent to INTUR inflates both sides)
- **Cashflow analysis**: Exclude intercompany unless tracking actual cash timing
- **Consolidated view**: Intercompany MUST net to zero — if they don't, investigate
- **Detection**: Check `rag_sociale` for counterparty name containing the other società
- **Rent**: ORTI pays INTUR €732K/year in 6 seasonal installments of €122K

---

## INVARIANT 8: No Double-Counting

The most dangerous analytical error in this system:

| Risk | Scenario | Prevention |
|------|----------|------------|
| **Parent + child accounts** | Summing group-level + detail-level conti | Only leaf accounts have movements in `f_movimenti_contabili` (safe by design) |
| **Esolver + Bank** | Same transaction in both `f_movimenti_contabili` AND `f_banche_movimenti` | These are different perspectives. Use ONE source per analysis, or use views that handle dedup. |
| **Budget overlap** | Multiple `cod_conto_pattern` matching same account | Check `d_voci_piano_finanziario` patterns don't overlap. Views handle this via priority. |
| **Manual + actual** | `f_piano_finanziario_input` for period that also has consuntivo | `v_piano_finanziario_mensile` uses `tipo_periodo` to separate. Don't sum both. |

---

## INVARIANT 9: Registration Lag Awareness

Esolver accounting entries can lag real transactions by days or weeks. This is a structural reality of the system.

### Rules:
- ALWAYS check `MAX(data_registrazione)` before interpreting recent months
- Use `f_banche_movimenti` for more current data (1-3 day lag vs weeks)
- Never say "costs are zero this month" without verifying data freshness
- `hotelops health` reports last available date per data source — use it
- When reporting, always note the data-as-of date

---

## INVARIANT 10: Schema Evolution Discipline

When adding new tables or columns to BigQuery:

### Rules:
- New fact tables: prefix with `f_`, include `hash_riga`, `societa_id`, `data_ingresso`/`data_caricamento`
- New dimension tables: prefix with `d_`, document in the skill's dimension reference
- New views: prefix with `v_`, document source tables and join logic
- Always update `SCHEMA_CONTEXT.md` when schema changes
- Always update `d_voci_piano_finanziario` if new financial categories are added
- Column types: use DATE (not STRING) for dates, FLOAT for amounts, STRING for codes
- String dates like "YYYY-MM" or "Gen"/"Feb" are tech debt — use proper DATE/INTEGER types in new tables

---

## Quick Reference: Table Prefixes

| Prefix | Type | Example | Mutability |
|--------|------|---------|------------|
| `f_` | Fact (transactional) | `f_movimenti_contabili` | Append-only (hash dedup) or delete-insert |
| `d_` | Dimension (lookup) | `d_piano_conti` | WRITE_TRUNCATE (full refresh) |
| `v_` | View (computed) | `v_piano_finanziario_mensile` | Derived — no direct writes |

---

## Session Context Checklist

When starting a new Claude session that touches HotelOps data:

1. ✅ Import this INVARIANTS.md
2. ✅ Import or reference SCHEMA_CONTEXT.md for table details
3. ✅ Know which società you're working with (ORTI or INTUR)
4. ✅ Check data freshness before drawing conclusions
5. ✅ Use `d_voci_piano_finanziario` as the canonical mapping layer
6. ✅ Normalize account codes (remove dots) before cross-table joins
7. ✅ Exclude intercompany unless explicitly analyzing it
