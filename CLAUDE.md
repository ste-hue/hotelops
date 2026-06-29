# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last checkpoint:** 2026-06-19 | **Version:** 0.8.0

> **CLAUDE.md = concetti + puntatori, NON catalogo.** Qui stanno solo le cose che NON si rigenerano: architettura, invarianti, dominio (INTUR/ORTI), regole operative. Lo **schema completo** è BigQuery stesso (`bq show <table>` / `INFORMATION_SCHEMA` — la source of truth). Dettagli curati: skill `hotelops-data-analyst` + `core/bq/SCHEMA_CONTEXT.md`; `hotelops manifest` → `core/bq/manifest.yaml` (snapshot parziale, subset di tabelle). Il **diario operativo vivo** è `STATUS.md` (leggilo prima di pianificare).

> **2026-06-19 checkpoint:** **Cashflow vertical** nel hub (`verticals/condges/app_cashflow.py`, guscio su `pf-rotate` canonico: upload PF+scadenziario, saldi pre-fill da BQ, **mappatura fornitori in-UI persistente su BQ `d_fornitori`** via `load_fornitori_bq`/`upsert_fornitore_bq`, **esclusione per-rotation** (`extra_excluded`) vs permanente (`is_excluded`), **intercompany tracciato** non escluso). Write-path cash/PF budget/previsione dietro `cash_pf_service`+gate I1 (Metà A, PR #37 merged). **Governance (decision `vault/decisions/2026-06-19_Modello_Proiezione_Cassa`):** le proiezioni NON vanno nel pool `f_*` (= solo fatti/actuals); la memoria mese×mese delle proiezioni = i **file xlsx versionati**, non una fact table. **D1 refactor completato:** motore `write_pf` estratto in `pf_rotate/pf_writer.py`; `app_scadenzario.py` cancellato (UI sostituita da Cashflow). Thread aperti: deploy Cloud Run hub; control-discrepancy (conteggio CLI vs in-foglio + label-mese header stale). PR #38 (mapping BQ-backed) aperto.
>
> **2026-06-18 checkpoint:** **vertical #3 spiaggia** completo (banco INTUR/corrispettivi ↔ Moolty + alloggiati ORTI/PMS, vista `v_spiaggia_giornaliero`, Drive auto-sync via cron).

> **For AI agents**: ground truth = repo + BigQuery schema. Read in this order before non-trivial work:
> 1. `docs/architecture/INVARIANTS.md` — la costituzione (I1–I8, canonical per concept).
> 2. `docs/architecture/AI_INSTRUCTIONS.md` — layer model, canonical truth registry, operational loop, anti-goals.
> 3. `docs/architecture/LE_3_DIMENSIONI.md` — il concetto temporale più importante del sistema.
> 4. `CLAUDE.md` (this file) — concetti, comandi, regole di dominio.
>
> **Goal di lungo termine**: HotelOps è il **Company OS** — il sistema operativo decisionale delle vere operazioni del business. 3 layer: **Code** (`core/`, `ingest/`, `verticals/`) = come opera il twin; **BigQuery** = cosa osserva; **Vault** = meta-knowledge umano (non canonical per fatti tecnici, può essere stale — verifica sempre con repo + BQ + utente; asse **workstream** `workstreams/<NOME>.md` per rientrare su un fronte).

## Behavioral guidelines

**Vedi anche:** `~/.claude/CLAUDE.md` per "surface ambiguity" e "verify before claiming done".

### Simplicity first
Codice minimo che risolve il problema. Niente speculativo. Nessuna feature oltre a quello chiesto, nessuna astrazione per codice usato una volta, nessuna "flessibilità" non richiesta, nessun error handling per scenari impossibili. Se scrivi 200 righe e potevano essere 50, riscrivile. Test: "Un senior engineer direbbe che è overcomplicated?" Se sì, semplifica.

### Surgical changes
Tocca solo quello che devi. Non "migliorare" codice/commenti/formatting adiacenti, non refactor di cose non rotte, match dello stile esistente. Dead code non correlato: segnalalo, non cancellarlo. Rimuovi solo gli orfani che le TUE modifiche hanno reso unused. Ogni riga modificata deve essere riconducibile alla richiesta.

### Decisive action over exploration
Formula un'ipotesi in una frase prima di esplorare; esegui il minimo comando che la conferma/smentisce; dopo 3-4 Bash senza progressi, fermati e fai una domanda mirata. Pattern noto: Stefano interrompe con "niente" / "perché non usiamo l'app?" quando l'esplorazione si trascina.

### Check STATUS.md prima di pianificare
Prima di plan multi-step/cutover/migration o scope cross-cutting: leggi `STATUS.md` (decisioni recenti, thread aperti) + ADR/`docs/architecture/INVARIANTS.md`. Se trovi contraddizioni tra STATUS.md e il piano, **fermati e segnalale**.

## Project Overview

hotelops è la piattaforma dati finanziaria di Gruppo Panorama. Ingerisce banche, ERP (Esolver), PMS (HotelCube), budget manuali in BigQuery, e serve 3 vertical (condges, reviews, spiaggia). Il vertical #1 **condges** (Controllo di Gestione) ha due lenti: **Rosa (CASSA)** "quando il soldo entra/esce?" e **Gasparotto (COMPETENZA)** "quanto consumo/genero?". Ogni evento finanziario ha 3 dimensioni temporali: COMPETENZA, CASSA, IMPEGNO. BigQuery è la source of truth.

## Architecture

```
core/       <- world model: schemas, config, BQ views/dimensioni/loaders, lineage  (NON importa verticals)
ingest/     <- reality capture: file → GCS → BigQuery (lineage intake/promote)
verticals/  <- domain apps (consumano core/+ingest/): condges, reviews, spiaggia, hub
cli.py      <- `hotelops` CLI
```

**Layer chiave (concetti — il dettaglio file-per-file è nel codice):**
- `core/schemas.py` — Pydantic + `validate_batch()`. `core/bq/write.py::bq_write_validated` è **l'unico writer** (append/snapshot). **Ogni write BQ passa da qui** (gate I1/I9).
- `core/config.py` — table IDs (`F_*`/`D_*`/`V_*`), `PROJECT`/`DATASET`. ⚠️ **`V_PROGETTO_VOCI_STATO` = costante orfana**: la vista non esiste in BQ né ha SQL nel repo (era Task 9 del piano *Projects event-sourced Step 1*, mai landato — vedi STATUS "Projects event-sourced Step 1", deferred). Non è una vista deployabile (`core/bq/views/` non la contiene).
- `core/lineage/` — per-raw-object lineage: `SourceDefinition` (registry `core/source_registry.yaml`, **grammar 4-part** `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`), state machine (RAW_ONLY→…→PROMOTED), policy gate (invariante **`loop_targets==[] ⇔ RAW_ONLY`**). Tabelle `f_raw_objects`/`f_lineage_events`, bucket `gs://hotelops-raw` (Object Versioning).

**ingest/** — target model: `hotelops intake` (→ `f_raw_objects` con URI gs://) + `hotelops promote` (→ canonical via gate). Parser in `ingest/flussi/`.
- `ingest/drive_fetch.py` — pull da **Drive vivo** via service account (`drive-audit@`). **Drive è tornato come fonte VIVA** (via lineage, non rclone) per il registro corrispettivi spiaggia; cron `scripts/spiaggia-corrispettivi-daily.sh`. La vecchia nota "Drive non più popolato" vale solo per il path **legacy rclone** (`core/datahub_sync.py`, `ingest/classify.py`/`orchestrate.py` — Phase-5 cutover pendente).

**verticals/** (concetti):
- **#1 condges** — Controllo di Gestione: CE riclassificato, Budget vs Consuntivo, Tesoreria, indicatori, `hotelops pf-rotate` (rotation mensile Piano Finanziario, vedi §Financial Data). Streamlit `app_cdg.py`. **App Cashflow** (`app_cashflow.py`, montata nel hub) = guscio sul motore canonico `pf-rotate` per produrre il PF del mese successivo (mappatura fornitori→voce persistente su BQ). Write-path budget/previsione dietro `services/cash_pf_service.py` + gate I1. Motore `write_pf` in `pf_rotate/pf_writer.py` (D1 completato — `app_scadenzario.py` cancellato).
- **#2 reviews** — Guest reviews: Apify scrape → Claude NLP (Haiku) → `f_reviews` → alert email + dashboard.
- **#3 spiaggia** — stabilimento balneare (vedi §Vertical Spiaggia).
- **hub** (`verticals/hub/`) — app-store: front-door unico = `app.py` su Cloud Run (`hotelops-hub`), gated IAP. Registry-driven (1 riga = 1 app), accessi a 2 livelli (IAP edge + grant per-email in `roles.py`). I vertical si montano via `render()`. **Dettagli/deploy/accessi: `verticals/hub/README.md`.** (Vetrina Cloudflare ritirata 2026-06-20.)

## GCP
- **Project:** `hotelops-suite` · **Dataset:** `hotelops` · **Auth:** `gcloud` come `stefano@panoramagroup.it`
- **Cloud Run** `hotelops-hub` (viewer Streamlit, `Dockerfile` root): `gcloud run deploy hotelops-hub --source . --region=europe-west1`

## Commands (cheat-sheet — la superficie completa è `hotelops --help`)

```bash
pip install -e ".[dev]"

# condges
hotelops pf [--mese N] [--societa INTUR]   # Piano Finanziario
hotelops bva [--mese N]                     # Budget vs Consuntivo YTD
hotelops chiudi [--mese N] [--dry-run]      # Chiusura mese (previsione vs consuntivo + saldo)
hotelops saldo [--societa INTUR]            # Saldo banca + cash forward 12m
hotelops health                             # Freshness, gaps, alerts
hotelops previsione utenze 4-12 22000       # Update forecast
hotelops pf-rotate ...                      # Rotation mensile PF (vedi §Financial Data)

# lineage / ingest
hotelops intake <file> --source-name X      # Registra (RAW)
hotelops promote --raw-object-id Y          # Promuovi → canonical
hotelops lineage Y                          # Ispeziona identità + eventi
python -m ingest.drive_fetch --source-name X [--file-id ID]   # Pull da Drive vivo
hotelops deploy-views [--dry-run]           # Deploy viste da core/bq/views/
hotelops manifest [--table T]               # Snapshot catalogo BQ → core/bq/manifest.yaml (subset)

# reviews
hotelops reviews [--scrape] [--stats] [--alert] [--report]

# test / lint
pytest ; ruff check . ; ruff format .
```

## BigQuery (concetti — catalogo completo nel manifest)

> Schema completo: BigQuery stesso (`bq show <table>`). Dettagli curati: skill `hotelops-data-analyst` + `core/bq/SCHEMA_CONTEXT.md` + `core/bq/manifest.yaml` (snapshot parziale). Qui solo i concetti che non si rigenerano.

**Lifecycle:** **APPEND** (ogni file aggiunge righe; dedup via `hash_riga`/`filter_new_rows_by_hash` o MD5 content-hash all'intake) vs **SNAPSHOT** (l'ultimo file rimpiazza via DELETE-INSERT scoped al `natural_key`).

**Tabelle-ancora (semantica speciale da conoscere):**
- `f_saldi_banca_chiusura_mensile` — **anchor del loop `cash_control`**: se presente per (societa, data, banca) ha priorità su snapshot Esolver + movimenti in `hotelops chiudi`.
- `f_produzione_pms` — produzione giornaliera HotelCube per classe (**Daily Production Report granulare**, Imponibile, source `POWERBI_PRODUZIONE_ORTI_SNAPSHOT`). Classi spiaggia: `04BEALL` (ombrelloni alloggiati hotel), `10BEBAR` (~0). ⚠️ ≠ `f_ricavi_fb` (= **Produzione Netta MENSILE**, source `POWERBI_RICAVIFB`).
- `f_movimenti_contabili` + `f_fatture_righe` — prima nota + registro fatture: insieme quadrano col bilancino per classe (`v_ce_macro_mensile`).

**Data model:** ogni fact row porta **5 dimensioni** (`societa_id, business_unit_id, funzione_id, location_id, oggetto_id`) + le **3 dimensioni temporali** (COMPETENZA/CASSA/IMPEGNO).
- **Account codes:** d_piano_conti con punti (`57.09.13`), f_movimenti_contabili senza (`570913`) → join `REPLACE(codice_conto, '.', '')`.
- **Segni:** Views ENTRATE>0 / USCITE>0; Esolver ENTRATE = avere−dare; Banche `importo_netto`>0 = entrata.
- **`d_voci_piano_finanziario` = il SINGLE mapping layer** PF voci ↔ Esolver codici conto (28 voci, LIKE patterns); `d_mapping_piano_finanziario` = mapping sotto-voce più fine (220 righe).

**Budget sources** (ogni riga ha tag `fonte` — mai mischiare senza filtro): GASPAROTTO (full CE) > MAPPATURA (costi/BU) > INCIDENZA (payroll) → `f_budget_mensile`; PIANO_FINANZIARIO/SCADENZIARIO/BVA_2026/CLI/APP → `f_piano_finanziario_input`.

## Vertical Spiaggia

Stabilimento balneare (Lido, INTUR). **Ricavo TOTALE/giorno = banco INTUR + alloggiati ORTI** (additivo, no doppio conteggio):
- **Banco INTUR** = Registro Corrispettivi RT (spiaggia 22% + bar 10%), pescato dal **Drive vivo** (cron giornaliero) → `f_spiaggia_corrispettivi` (source `RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT`). Anno autorevole dal **filename** (l'header del template è stale).
- **Moolty** = cassa POS dell'intero banco walk-in (ombrelloni + bar) → `f_spiaggia_fb_ordini` (source `MOOLTY_FBSPIAGGIA_INTUR_APPEND`). È il **dettaglio operativo** del banco, NON un addendo: `scost_cassa = corrispettivo_totale − Moolty` (~2%, quadratura POS↔fiscale).
- **Alloggiati ORTI** = ospiti hotel che usano la spiaggia (conto camera, non al banco) → PMS `f_produzione_pms` classe `04BEALL`. **Spiagge.it** (`f_spiaggia_cash_flows`, prenotazioni online) è ⊆ alloggiati (2025 = 100% hotel-linked) → cross-check, NON si somma.
- Vista unificata **`v_spiaggia_giornaliero`**; app `verticals/spiaggia/app.py` (montata nel hub). Spec/plan: `docs/superpowers/{specs,plans}/2026-06-17-spiaggia-*`.

## Entities

### Societa (legal entities)
- **ORTI** — gestione operativa: vendite, acquisti, costi di Hotel, Residence, CVM. Paga fitto a INTUR (conto 6511).
- **INTUR** — proprietà e finanza (mutui, IVA, fatture). Possiede Hotel+Spiaggia+Immobili. Gestisce direttamente solo il Lido.

**Relazione critica**: ORTI non genera cash → non paga fitto → INTUR non paga mutui → rischio default. Il fitto ORTI→INTUR è intercompany e si cancella nel consolidato.

### Business Units
| business_unit_id | Nome | Note |
|---|---|---|
| `HOTEL` | Hotel Panorama | 4* a Maiori, stagionale apr-ott |
| `RESIDENCE` | Angelina Residence | Appartamenti, tutto l'anno |
| `CVM` | Casa Vacanze Maiori | Appartamenti vacanza, tutto l'anno |
| `LIDO` | Lido / Spiaggia | Concessione balneare, INTUR |
| `HQ` | Sede / Amministrazione | Funzioni centrali |

### Banks & Esolver mapping (Cc# → banca_id)
- **ORTI:** Cc1=INTESA, Cc2=MPS, Cc3=MPS_KROSS
- **INTUR:** Cc1=SELLA, Cc2=MPS, Cc3=INTESA, Cc4=BCP

## Financial Data / Cashflow

Regole per le rotation mensili del Piano Finanziario (`hotelops pf-rotate`).

**Layout-aware = obbligatorio.** Due layout del master "Piano Finanziario":
- **ORTI (`snapshot_kind="month-closed"`)**: la colonna del mese chiuso ospita saldi banche puntuali + saldo iniziale hardcoded.
- **INTUR (`snapshot_kind="fixed-snapshot"`)**: colonna C snapshot fisso (`C1="DATA RILEVAZ"`, `C2=<data>`, saldi in `C31:C33`); la colonna del mese chiuso resta vuota sui saldi.

`snapshot_kind` dedotto da `find_layout(wb)` (legge `pf["C1"]`). Step 1/2/5 branched per `snapshot_kind`.

**Mai azzerare formule.** Step 2 ("azzera mese chiuso") tocca solo `is_value_cell` (numero/stringa/formula-di-costanti). **Formule con riferimenti A1-style (`=Utenze!K3`, `=SUM(D5:D11)`, `=C37`) non vengono MAI sovrascritte** — protegge le cascate cross-sheet.

**File output nuovo, mai mutare l'input.** Naming `<societa>_PF_<YYYY-MM>_post-rotate_<ts>.xlsx`, dove `YYYY-MM` è il **primo mese aperto** (data_saldo + 1 mese). Se step 5 trova ERR → suffisso `_FAILED_CHECKS` (scritto comunque). Attesi smoke: ORTI 13/0/7, INTUR 12/0/8.

## Git Conventions

In aggiunta a `~/.claude/CLAUDE.md`:
- **Mai `git checkout main -- .`** su working tree dirty (usa `git stash` o path specifici).
- **Mai `git add .`/`git add -A`** con untracked non-cashflow — stagia per nome.
- **Commit logicamente atomici** ("feat(X): goal completo", non micro-step). Spec/plan committati separatamente.
- **Branch:** `verticals-v2` = laboratorio frozen, NON toccare. `feat/vetrina` = front-door Cloudflare. `main` = operativo.
- **Mai `pip install -e` da dentro un worktree** (rompe l'editable install: `ModuleNotFoundError: verticals`).

## Governance Rules
- Ogni fact row porta tutte le 5 dimensioni.
- No speculative modules — le pipeline nascono da flussi dati reali.
- Mai modificare `fatti/` a mano — solo pipeline.
- Tutti i budget hanno tag `fonte` — mai mischiare senza filtro esplicito.
- `d_voci_piano_finanziario` = unico mapping layer PF voci ↔ Esolver.

## NanoClaw Agent Integration
NanoClaw (WhatsApp agent) è un canale query + ingest: usa `ingest/classify.py` per classificare/instradare i file ricevuti. Config nel repo NanoClaw (`~/education/repos/AI_repos/nanoclaw/groups/hotelops/`).

## Tests & Dependencies
Python ≥3.11. `pytest` / `ruff check .` / `ruff format .`. I test sono in `tests/` (un file per dominio/pipeline).
Core: `pyyaml`, `openpyxl`, `pandas`, `google-cloud-bigquery`, `pydantic`.
Optional: `[reconcile]` (bank-reconcile), `[dashboard]` (streamlit+plotly+db-dtypes), `[drive]` (google-api-python-client). Dev: `[dev]` (pytest, ruff).
