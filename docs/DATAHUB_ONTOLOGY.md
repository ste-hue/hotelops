# HotelOPS — Ontologia Operativa

Ultimo aggiornamento: 2026-03-03

---

## Architettura a 4 livelli

```
┌─────────────────────────────────────────────────────────────────┐
│  AGENTE  (NanoClaw)                                             │
│  Container Linux con Claude Agent SDK                           │
│  Riceve eventi WhatsApp, gestisce entità, lancia pipeline       │
│  groups/hotelops/CLAUDE.md = istruzioni + schema DB             │
│  groups/hotelops/hotelops.db = SQLite (entità, eventi, audit)   │
└──────────┬──────────────────────────┬───────────────────────────┘
           │ monta read-write         │ monta read-only
           ▼                          ▼
┌──────────────────────┐   ┌──────────────────────────────────────┐
│  ONTOLOGIA (Obsidian) │   │  CODICE (hotelops repo)              │
│  Entità promosse ad   │   │  Pipeline ETL + Riconciliazione      │
│  "active" diventano   │   │  pipelines/banca/ingest.py           │
│  note Obsidian        │   │  pipelines/banca/ingest_mastrino.py  │
│                       │   │  actions/reconcile_banca.py          │
│  companies/           │   │  services/reconcile_api.py           │
│  people/              │   │  lib/contracts.py                    │
│  banks/               │   │  lib/datahub.py                     │
│  loans/               │   └──────────┬───────────────────────────┘
│  departments/         │              │ legge/scrive
│  advisors/            │              ▼
│  projects/            │   ┌──────────────────────────────────────┐
│  financial/           │   │  DATI (Google Drive datahub)          │
│  relationships/       │   │  Database a file — append-only        │
└───────────────────────┘   │  ingresso/ → fatti/ + dimensioni/     │
                            │  meta/ = log, run, decisioni          │
                            └──────────────────────────────────────┘
```

| Livello | Path | Ruolo |
|---------|------|-------|
| Agente | `nanoclaw/groups/hotelops/` | Riceve eventi, gestisce entità (10 tipi fissi), lancia pipeline |
| Ontologia | `Obsidian Vault/Work/HotelOps/` | Note strutturate per entità promosse ad active |
| Codice | `~/dev/Projects/hotelops/` | Pipeline Python (ingestion, riconciliazione, API) |
| Dati | `Google Drive/hotelops_datahub/` | File CSV immutabili (fatti, dimensioni, mapping, meta) |

---

## 1. Modello a 5 Dimensioni

Ogni riga in `fatti/*.csv` porta 5 etichette. Se non applicabile → `N_A`.

| # | Dimensione | Campo | Valori reali nel datahub |
|---|-----------|-------|--------------------------|
| 1 | **Legale** | `societa_id` | ORTI (Operativa), INTUR (Immobiliare) |
| 2 | **Business Unit** | `business_unit_id` | HOTEL, RESIDENCE, CVM, LIDO, HQ |
| 3 | **Funzione** | `funzione_id` | ROOMS, F&B, BEACH_OPS, FINANZA, LOGISTICA, AMM, MAN |
| 4 | **Location** | `location_id` | TERRAZZA, SALA_INT, CHIOSCO, ARENILE, CVM_APT, RES_APT, UFFICI, MAGAZZINO, N_A |
| 5 | **Oggetto** | `oggetto_id` | GENERICO (unico seed); pipeline genera CONTO_{societa}_{banca} |

**Nota**: `dim_oggetto.csv` ha solo il seed GENERICO. I valori reali (CONTO_INTUR_SELLA, CONTO_ORTI_MPS) sono generati dalle pipeline ma non ancora registrati nella dimensione. Da allineare.

---

## 2. Struttura Datahub (stato reale)

```
hotelops_datahub/                        Google Drive
├── RULES.md                             Governance (7 regole)
├── ingresso/
│   └── banca/
│       ├── banca_grezza/                Estratti conto Sella CSV, MPS Excel
│       └── mastrino_grezzo/             Mastrini ERP Excel
├── fatti/
│   ├── f_banche_movimenti.csv           3.623 righe — movimenti bancari
│   └── f_ledger_movimenti.csv           2.233 righe — registrazioni contabili
├── dimensioni/
│   ├── dim_societa.csv                  2 valori: ORTI, INTUR
│   ├── dim_business_unit.csv            5 valori: HOTEL, RESIDENCE, CVM, LIDO, HQ
│   ├── dim_funzione.csv                 7 valori: ROOMS, F&B, BEACH_OPS, FINANZA, LOGISTICA, AMM, MAN
│   ├── dim_location.csv                 9 valori: TERRAZZA...N_A
│   ├── dim_oggetto.csv                  1 valore: GENERICO (sparse — da popolare)
│   └── mappature/
│       └── dim_mapping_banca.csv        26 regole (INTUR_SELLA + MPS + DEFAULT)
├── indice_documenti/
│   └── grezzi/                          Documenti indicizzati (es. CondGes)
└── meta/
    ├── pipeline/
    │   ├── ingest_banca.py              Script legacy (deprecato — ora nel repo)
    │   ├── README_INGEST_BANCA.md       Documentazione legacy
    │   └── logs/                         6 log di ingestion
    ├── schemas/
    │   ├── ingest_banca.yaml            Schema YAML
    │   └── schema_banche.txt            Schema testuale
    ├── actions/
    │   └── reconcile_banca/
    │       ├── runs.csv                 Registro run (1 run: fba3e11cdd71)
    │       └── runs/fba3e11cdd71/       Ultimo run
    │           ├── metrics.json
    │           ├── matches_auto.csv
    │           ├── matches_review.csv
    │           └── no_match.csv
    └── laboratorio/                     File di lavoro/esplorazione
```

---

## 3. Agente (NanoClaw HotelOps)

Container Linux isolato, invocato da messaggi WhatsApp.

**Database**: `hotelops.db` (SQLite, WAL mode) con 10 tipi entità fissi:
Societa, Struttura, Reparto, Persona, Fornitore, Banca, Progetto, Contratto, Strumento_Finanziario, Consulente

**Macchina a stati**: candidate → approved → active → inactive (mai saltare)

**Trigger di promozione**: soldi (>5k EUR), obbligo, passività, ripetizione (≥2 eventi)

**Mount nel container**:

| Host | Container | Mode |
|------|-----------|------|
| `groups/hotelops/` | `/workspace/group` | rw |
| Obsidian `Work/HotelOps/` | `/workspace/extra/obsidian-hotelops` | rw |
| Google Drive `hotelops_datahub/` | `/workspace/extra/datahub` | rw |
| `~/dev/Projects/hotelops` | `/workspace/extra/hotelops-repo` | ro |

Quando un'entità diventa `active`, l'agente crea una nota Obsidian nella cartella appropriata.

---

## 4. Pipeline attive

### Banca — Ingestion

Legge estratti conto grezzi → appende a `f_banche_movimenti.csv`.

- **Sorgenti**: Sella (CSV), MPS (Excel)
- **Deduplicazione**: MD5(`societa|banca|data|importo_netto|descrizione`)
- **Lineage**: `file_sorgente` + `riga_sorgente` su ogni riga
- **Mapping**: 26 regole in `dim_mapping_banca.csv` (keyword → categoria normalizzata)
- **Contratti dati**: `validate_columns()` — fail-fast se mancano colonne

```bash
python -m pipelines.banca.ingest --datahub /path --all
```

### Mastrino — Ingestion

Legge mastrini ERP (Excel) → appende a `f_ledger_movimenti.csv`.

```bash
python -m pipelines.banca.ingest_mastrino --datahub /path --societa ORTI --banca MPS --all
```

### Riconciliazione Banca ↔ Contabilità

Abbina movimenti bancari con registrazioni contabili. Scoring cascata (data 0.8, testo 0.2).

- **Run ID deterministico**: SHA256(`societa|conto|from|to`)[:12]
- **Output**: matches_auto, matches_review, no_match + metrics.json
- **Registro**: append-only `runs.csv`

```bash
python -m actions.reconcile_banca --datahub /path --societa INTUR --conto SELLA --from 2025-01-01 --to 2025-01-31
```

### API W3C Reconciliation

Espone il ledger come target di riconciliazione per OpenRefine (W3C v0.2). Supporta decisioni umane persistite.

```bash
python -m services.reconcile_api --datahub /path --societa ORTI --banca MPS --port 8000
```

---

## 5. Convenzione nomi file

```
YYYY-MM-DD__FUNZIONE__SOCIETA_BANCA__DETTAGLIO.ext
```

Esempi reali:
```
2025-12-09__FINANZA__INTUR_SELLA__LISTA_MOVIMENTI_010125_091225.csv
2025_MPS_cc2_19-01-01_EC_saldo-85983-93.xlsx  ← mastrino (convenzione diversa)
```

---

## 6. Schema fatti

### f_banche_movimenti.csv (26 colonne)

```
id_movimento, societa_id, business_unit_id, funzione_id, location_id,
oggetto_id, banca_id, data_operazione, data_valuta, descrizione,
divisa, importo_debito, importo_credito, importo_netto,
categoria_raw, sottocategoria_raw, categoria_normalizzata,
sottocategoria_normalizzata, tipo_movimento, codice_identificativo_banca,
etichette, note, data_ingresso, file_sorgente, riga_sorgente, hash_riga
```

### f_ledger_movimenti.csv (21 colonne)

```
id_registrazione, societa_id, business_unit_id, funzione_id,
location_id, oggetto_id, banca_id, data_registrazione,
descrizione, importo, importo_dare, importo_avere, divisa,
riferimento_registrazione, documento, riferimenti_iva,
centro_imputazione, data_ingresso, file_sorgente, riga_sorgente, hash_riga
```

---

## 7. Meccanismi di qualità

| Meccanismo | Dove | Cosa fa |
|-----------|------|---------|
| **Data Contracts** | `lib/contracts.py` | Valida colonne obbligatorie prima dell'elaborazione |
| **Lineage** | Ogni riga in fatti/ | `file_sorgente` + `riga_sorgente` tracciano l'origine |
| **Deduplicazione** | Hash MD5 per riga | Impedisce duplicati su re-ingestion |
| **Run Lifecycle** | `metrics.json` | Stato running → completed/failed con timing e conteggi |
| **Run Registry** | `runs.csv` | Registro append-only di tutte le esecuzioni |
| **Decisioni umane** | `decisions.csv` | Confirm/reject per API di riconciliazione |
| **RULES.md** | Root datahub | 7 regole di governance immutabili |

---

## 8. Debito tecnico e lacune note

| Cosa | Dettaglio |
|------|-----------|
| `dim_oggetto.csv` sparse | Solo GENERICO; le pipeline generano CONTO_* ma non li registrano nella dimensione |
| `validate_columns` su fatti vuoti | Salta validazione se il file è vuoto |
| `runs.csv` single-writer | Nessun locking; problematico se più agenti scrivono in parallelo |
| `meta/pipeline/ingest_banca.py` | Script legacy nel datahub — il codice autoritativo è nel repo |
| Naming mastrini | Non segue la convenzione standard (manca `__`) |
| `business_unit_id` sempre HQ | Le pipeline bancarie non assegnano mai HOTEL/RESIDENCE/CVM |

---

## 9. Prossimi passi (non ancora costruiti)

| Pipeline | Sorgente | Fatto target | Priorità |
|----------|----------|-------------|----------|
| PMS | Produzione giornaliera | `f_ricavi_pms.csv` | Alta |
| POS | Terminali pagamento | `f_corrispettivi_pos.csv` | Media |
| Fornitori | Fatture | `f_costi_generali.csv` | Media |
| Payroll | Consulente lavoro (LUL) | `f_payroll.csv` | Media |
| Economato | Gestionale | `f_economato.csv` | Bassa |
| Mutui | Piani ammortamento | `f_mutui.csv` | Bassa |
| Spiaggia | Gestionale spiaggia | `f_spiaggia_occupancy.csv` | Bassa |

---

## 10. Regole per gli script

Ogni pipeline deve:

1. Leggere dimensioni da `dimensioni/`
2. Leggere mapping da `dimensioni/mappature/`
3. Validare schema con `validate_columns()` prima di elaborare
4. Garantire le 5 dimensioni su ogni riga di output
5. Tracciare lineage (`file_sorgente`, `riga_sorgente`)
6. Deduplicare via hash MD5
7. Scrivere in `fatti/` in modalità append-only
8. Scrivere metriche in `meta/` con lifecycle strutturato
9. Se una dimensione non è determinabile → `N_A`, mai lasciare vuoto
