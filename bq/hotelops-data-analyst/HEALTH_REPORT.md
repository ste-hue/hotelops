# HotelOps System Health Report

**Data**: 2026-03-19
**Scope**: Pipeline coverage, code consistency, data gaps

---

## Verdetto: 7/10 — Solido, ma con buchi prevedibili

Il sistema è **ben progettato architetturalmente** (4 layer, idempotenza, hash dedup, datahub governance). Ma l'esecuzione ha debiti tecnici tipici di un sistema cresciuto organicamente. Niente di allarmante — serve un consolidamento.

---

## 1. Pipeline Coverage Matrix

### ✅ Ingerito e funzionante in BQ

| Dato | Pipeline | Tabella BQ | Righe | Pattern | Status |
|------|----------|-----------|-------|---------|--------|
| Movimenti bancari (4 banche × 2 società) | `banca/ingest.py` | f_banche_movimenti | ~3,745 | hash dedup | ✅ Solido |
| Movimenti contabili Esolver | `amministrativa/ingest_movimenti_contabili.py` | f_movimenti_contabili | ~31,821 | hash dedup | ✅ Funziona |
| Bilancino (trial balance) | `amministrativa/ingest_bilancino.py` | f_bilancino | 110 | hash dedup | ✅ Basico |
| Accodamenti HotelCube | `banca/ingest_accodamenti.py` | f_accodamenti | 63 | hash dedup | ✅ Solo gen 2026 |
| Budget costi + personale | `amministrativa/ingest_budget_costi.py` | f_budget_mensile | 837 | DELETE-INSERT | ✅ 2026 |
| Piano finanziario input | `amministrativa/ingest_piano_finanziario_input.py` | f_piano_finanziario_input | 142 | hash dedup | ✅ Manuale |
| Voci piano finanziario | `amministrativa/ingest_voci_piano_finanziario.py` | d_voci_piano_finanziario | 29 | TRUNCATE | ✅ Dimensione |
| Piano dei conti | `amministrativa/ingest_piano_conti.py` | d_piano_conti | 2,103 | TRUNCATE | ✅ Dimensione |
| Budget costi fissi | (loaded manually) | d_budget_costi_fissi | 43 | — | ✅ Snapshot |
| Personale mensile | (loaded via budget pipeline) | d_personale_mensile | 78 | — | ✅ |
| Categorie conti | `amministrativa/ingest_mastrino.py` | d_categorie_conti | 167 | TRUNCATE | ✅ |
| Mastrino consolidato | `amministrativa/ingest_mastrino.py` | f_mastrino_consolidato | 901 | TRUNCATE | ⚠️ Snapshot non append |

### ❌ In ingresso ma NON ingerito (o pipeline incompleta)

| Dato | File in Drive | Pipeline | Gap |
|------|--------------|----------|-----|
| **Saldi bancari** | 4 file SALDI_BANCARI in TESORERIA_ingresso/ESOLVER | **Nessuna** | ❌ Saldi apertura mancanti — serve per riconciliazione |
| **Piano finanziario XLSX** | `ORTI - Piano Finanziario - 03_mar2026.xlsx` | `ingest_piano_finanziario_input.py` (solo CSV!) | ❌ Pipeline accetta solo CSV, file è XLSX |
| **f_ledger_movimenti** | (derivabile da f_movimenti_contabili) | `banca/ingest_mastrino.py` (CSV-only, no BQ) | ❌ Serve per riconciliazione ma NON esiste in BQ |
| **Consumi economato** | ~150 file 2024-2025 | `ingest_consumi_economato*.py` | ⚠️ Pipeline esiste, mai validata su BQ |
| **Coperti giornalieri** | (non verificato) | `ingest_coperti.py` | ⚠️ Pipeline esiste, stato ignoto |

### 🕳️ Dati che NON hanno nemmeno pipeline

| Dato | Perché serve | Priorità |
|------|-------------|----------|
| Saldi bancari apertura | Riconciliazione banca: saldo iniziale per quadrare | Alta |
| Ricavi XLSX (piano finanziario) | Budget ricavi per BVA da XLSX (non CSV) | Media |
| Voci mancanti (ORTI Angelina, Affitti, INTUR Hotel/CVM) | Completare il piano finanziario | Media |

---

## 2. Code Quality Matrix

| Aspetto | banca/ingest | movimenti_contabili | budget_costi | bilancino | piano_fin_input | consumi_eco |
|---------|:-----------:|:-------------------:|:------------:|:---------:|:---------------:|:-----------:|
| **validate_columns()** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **--dry-run** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **File logging** | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **data_ingresso/caricamento** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **hash dedup** | ✅ | ✅ | (DELETE) | ✅ | ✅ | ✅ |

**Problema principale**: solo `banca/ingest.py` usa `validate_columns()`. Tutte le pipeline amministrative saltano la validazione schema → se un export Esolver cambia formato, fail silenzioso.

---

## 3. Incoerenze da Sanare

### Naming inconsistency
- `data_ingresso` (banca/*) vs `data_caricamento` (amministrativa/*) — stesso concetto, nome diverso
- Due file `ingest_mastrino.py` (in banca/ e amministrativa/) — confuso
- `f_mastrino_consolidato` usa WRITE_TRUNCATE (è un fatto, non una dimensione)

### Codice conto format hell
- `f_movimenti_contabili.cod_conto` → senza punti
- `f_budget_mensile.codice_conto` → con punti
- `d_piano_conti.codice_conto` → senza punti
- `d_budget_costi_fissi.codice_conto` → con punti

Questo è il gotcha #1 del sistema. Ogni nuova tabella DEVE usare formato senza punti (INVARIANT 3), ma le vecchie non sono migrate.

### Views vs Tables
- `CLAUDE.md` documenta 7 tabelle BQ, ma ne esistono **almeno 13** (fact + dim)
- `CLAUDE.md` non menziona `f_budget_mensile`, `f_piano_finanziario_input`, `d_periodi_apertura`, `d_categorie_conti`, `f_consumi_economato`, `f_coperti_giornalieri`
- Le views (`v_*`) non sono tutte documentate

---

## 4. Architettura — Cosa funziona bene

- **Idempotenza**: hash_riga ovunque, safe to re-run ✅
- **Lineage**: `file_sorgente` + `riga_sorgente` su ogni riga ✅
- **4-layer separation**: Obsidian → Drive → Code → BQ — chiaro ✅
- **Rosetta Stone** (`d_voci_piano_finanziario`): mapping unico tra linguaggi ✅
- **Views materializzano logica**: v_piano_finanziario_mensile è il cuore analitico ✅
- **dry-run ovunque**: ogni pipeline supporta simulazione ✅

---

## 5. Piano di Azione (Priorità)

### P0 — Sblocca la riconciliazione
1. **Costruisci `f_ledger_movimenti` in BQ** — view o tabella materializzata da `f_movimenti_contabili WHERE cod_conto LIKE '190%'`
2. **Carica saldi bancari apertura** — serve il saldo iniziale per chiudere la riconciliazione

### P1 — Hardening (1 giornata di lavoro)
3. **Aggiungi `validate_columns()` a tutte le pipeline amministrative** — 10 minuti per pipeline, previene fail silenzioso
4. **Aggiungi file logging** alle pipeline console-only
5. **Aggiorna CLAUDE.md** con tutte le 13+ tabelle BQ (attualmente ne lista 7)

### P2 — Completamento copertura
6. **Pipeline saldi bancari** — nuovo ingestor per i 4 file SALDI_BANCARI in Drive
7. **Supporto XLSX per piano finanziario** — il pipeline attuale accetta solo CSV
8. **Completare voci mancanti** nel dizionario (Angelina ricavi, Affitti, INTUR Hotel/CVM)
9. **Validare consumi_economato su BQ** — pipeline esiste ma mai verificata end-to-end

### P3 — Consolidamento
10. **Standardizzare naming** (`data_ingresso` → `data_caricamento` per nuove tabelle)
11. **Rinominare `amministrativa/ingest_mastrino.py`** per evitare confusione con `banca/ingest_mastrino.py`
12. **Migrare codici conto con punti** → senza punti nei nuovi caricamenti

---

## Metriche Riassuntive

| Metrica | Valore |
|---------|--------|
| Pipeline totali | 14 |
| Pipeline con validate_columns | 3/14 (21%) |
| Pipeline con file logging | 4/14 (29%) |
| Pipeline con dry-run | 13/14 (93%) |
| Tabelle BQ documentate in CLAUDE.md | 7/13+ (54%) |
| Dati in ingresso senza pipeline | 3 categorie |
| Views in BQ | 5 (tutte funzionanti) |
