---
type: invariants
domain: HotelOps
last_updated: 2026-05-07
canonical: repo (was vault HotelOps/INVARIANTS.md)
---

# HotelOps — Invariants & Purpose

> **Migrated from Obsidian vault on 2026-04-30.** Da questa data, la fonte canonica degli invarianti è questo file nel repo. La copia nel vault è archiviata in `_archive/migrated_to_repo/`. Aggiornamenti successivi vanno qui — il vault NON è più source of truth per fatti tecnici.

## Perché HotelOps esiste

Gruppo Panorama (ORTI + INTUR) ha dati finanziari e operativi frammentati tra ERP (Esolver), PMS (HotelCube), homebanking di 4 banche, Drive, WhatsApp, fogli Excel manuali. Nessuna vista unificata. Decisioni di tesoreria, budget e forecast vengono prese su dati ricostruiti a mano ogni volta.

HotelOps esiste per:

1. **Centralizzare** questi dati in un unico store canonico (BigQuery)
2. **Servire** audience di business specifiche con interfacce dedicate (Rosa tesoreria, Gasparotto budget, Antonio GM reputation, Mario economato)
3. **Automatizzare** i cicli che oggi sono manuali (classificazione file, riconciliazione, forecast cassa)

Non è un ERP, non è un BI tool generico. È una **piattaforma dati verticale** sul dominio specifico del gruppo. Il goal di lungo termine è essere un **digital twin** delle vere operazioni del business.

## Invariants

Le regole che **non devono essere violate**. Se un cambiamento le rompe, non è un refactor — è un cambio di sistema, e richiede una decisione esplicita (vedi `docs/adr/`).

### I1. Nessun write a BigQuery senza validation gate

Ogni riga che entra in BQ passa da `core.bq.write.bq_write_validated`, che applica:

- Validazione Pydantic stretta (`core/schemas.py`)
- Probe di serializzazione (`json.dumps` per-row, prima di qualunque side-effect su BQ)
- Lineage automatica via `core/pipeline_run.PipelineRun.get_current()` (ContextVar)
- Single observable log line per write

Nota: il boundary Raw/GCS è ora esplicitato in I9 (2026-05-07). I1 resta il
vincolo sul validation gate dei write.

Mai bypass, mai "solo stavolta". Violare questo invariant significa perdere la garanzia di consistenza dei fatti → tutto il motore a valle diventa inaffidabile.

Spec: `docs/superpowers/specs/2026-04-28-bq-write-validated-design.md`

### I2. Lifecycle per-tabella è legge

Ogni fact table è **APPEND** (immutable, dedup via md5 hash_riga) o **SNAPSHOT** (DELETE+INSERT chirurgico per natural_key). La scelta è semantica, non implementativa:

- **APPEND** = fatti che sono accaduti (movimenti bancari, consumi, vendite POS). Immutabili per natura. Helper: `core.bq.dedup.filter_new_rows_by_hash`.
- **SNAPSHOT** = stati a una data (partite aperte, bilancino, budget). Sostituiscono la versione precedente. Il gate fa DELETE chirurgico per natural_key.

Cambiare il lifecycle di una tabella = migration + revisione downstream. Non si fa al volo.

### I3. Dimensioni canoniche sono single source of truth

I nomi di società, banche, persone, conti, categorie esistono in **un posto solo** ontologicamente: il vault `HotelOps/ontology/` (meta-knowledge umano). I valori in `D_*` in BigQuery devono coincidere carattere per carattere.

Corollario: nessuno crea una nuova società/banca/categoria direttamente in codice o in un CSV senza prima allineare il vault.

### I4. Le 3 dimensioni temporali sono obbligatorie

Ogni fatto finanziario è classificato su **CASSA**, **COMPETENZA**, **IMPEGNO**. Queste non sono "campi opzionali" — sono la lente con cui Rosa e Gasparotto leggono il mondo. Una transazione senza le 3 dimensioni è incompleta, non "da arricchire dopo".

Vedi `docs/architecture/LE_3_DIMENSIONI.md`.

### I5. Classify è deterministico (eccetto reviews)

Il routing dei file dal datahub (`ingest/classify.py`) è **regolare**, non LLM-based. Stesso file → stesso routing, sempre. Il vertical `reviews/` è l'unica eccezione (classify via Claude API), e lo è per ragioni esplicite: il testo libero delle recensioni non è strutturalmente prevedibile.

Corollario: non introdurre LLM nel classify "per comodità". Se un file non è classificabile deterministicamente, il problema è il contratto di input, non il classifier.

### I6. Stagionalità è un fatto del dominio, non una complicazione

Gli hotel del gruppo sono stagionali (apr-ott aperti, nov-mar chiusura ridotta). Qualunque forecast, KPI, proiezione che ignora la curva stagionale produce numeri sbagliati in modo prevedibile. Il motore deve *incorporare* stagionalità, non trattarla come caso speciale.

Tabelle correlate: `d_coefficienti_stagionalita`, `d_periodi_apertura`.

### I7. Ogni vertical ha un'audience umana esplicita

Un vertical senza un nome proprio accanto (Rosa, Gasparotto, Antonio, Mario) non è un vertical — è infrastruttura in cerca di scopo. Il prodotto vive nella testa di queste persone, non nei dataset.

### I8. La logica di row-selection vive nella view canonica, non nei consumer

Quando più fonti di input si sovrappongono su stessa entità (stesso codice conto, stessa chiave), la risoluzione — *quale riga tengo, con che precedenza, quali altre sopprimo* — avviene in **un posto solo**: la view canonica dedicata. Le view a valle possono riformare, aggregare, pivotare, joinare — ma non possono ri-decidere quale riga vince.

Violare questo invariant significa spargere la stessa regola in N consumer con N implementazioni leggermente diverse, ri-creando sistematicamente il problema del doppio conteggio.

Primo caso concreto: `v_budget_canonical` come verità risolta del budget multi-fonte (`f_budget_mensile` ha 9 fonti sovrapposte).

ADR: `docs/adr/2026-04-17_Budget_Canonical_View.md` (da migrare dal vault).

### I9. GCS Raw Layer è il boundary obbligatorio dell'ingest (enforcement progressivo)

Nessun write su fact table canoniche di business è valido senza provenienza
tracciabile da Raw Object registrato (`raw_object_id`) con `raw_uri` su `gs://...`.

L'enforcement è **progressivo per source**:

- una source entra nel regime obbligatorio quando viene flippata a `raw_storage.backend: gcs`;
- finché non è flippata, può restare su percorso legacy temporaneo;
- i blob legacy già caricati con path precedente restano validi e non vanno riscritti retroattivamente.

Corollario operativo:

- ingest diretto a canonical senza passare da intake lineage è comportamento da deprecare;
- nuove sorgenti discovery-first vanno in `RAW_ONLY` finché non esiste un target canonical esplicito.

ADR: `docs/adr/0004-gcs-mandatory-ingestion-boundary.md`

## Quando aggiornare questo file

- Nasce un nuovo invariant → aggiungilo, spiega il *perché*
- Un invariant viene **consapevolmente** rilassato → ADR esplicito in `docs/adr/` + update qui
- Cambia lo scopo di HotelOps (nuovo gruppo, nuova audience strutturale) → rewrite della sezione "Perché esiste"

**Non aggiornare** questo file quando:

- Aggiungi una fact table (aggiorna `CLAUDE.md` BigQuery section)
- Aggiungi un detector (aggiorna `ingest/classify.py`)
- Cambi un comando CLI (aggiorna `CLAUDE.md` Commands section)
