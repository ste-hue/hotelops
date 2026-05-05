# HotelOps — Datahub Ontology (GCS-first)

Ultimo aggiornamento: 2026-05-05

---

## Scopo

Questo documento definisce il modello operativo attuale del layer dati di HotelOps.

Principio base:
- **GCS** = dump ordinato, immutabile, tracciato del mondo reale (Raw layer)
- **BigQuery** = solo dati resi interrogabili da HotelOps (Canonical/Semantic layer)

HotelOps non deve ingerire tutto in BQ. Deve poter conservare tutto in Raw,
classificare progressivamente, e promuovere in Canonical solo cio che supera
regole esplicite.

---

## Architettura a 4 layer

```
Raw (GCS immutable)
  -> Manifest (BQ control plane)
  -> Canonical (BQ facts/dimensions, validated)
  -> Semantic/Operational (views, CLI, app, agent)
```

| Layer | Sistema | Ruolo |
|---|---|---|
| Raw | `gs://hotelops-raw` | Oggetti originali, versionati, append-only logico |
| Manifest | BigQuery (`f_raw_manifest`, `f_raw_events`) | Stato pipeline per file e decisioni di promozione |
| Canonical | BigQuery (`f_*`, `d_*`) | Dati validati, dedup, lifecycle APPEND/SNAPSHOT |
| Semantic/Operational | BigQuery `v_*`, CLI, Streamlit, agent | Lenti business e workflow umani |

---

## Regola d'oro

Flusso obbligatorio:

`dump raw -> manifesto -> classificazione -> validazione -> BigQuery`

Conseguenza pratica:
- un file puo restare **solo Raw** per settimane/mesi senza sporcare il Canonical
- ingest in BQ avviene solo quando esiste una regola utile per un loop reale

---

## 1) Raw layer (GCS)

### 1.1 Bucket

- Bucket target: `hotelops-raw`
- Richiesto: Object Versioning ON
- Lifecycle storage: Autoclass con terminal class archivio

### 1.2 Oggetti raw accettati

Esempi non esaustivi:
- export banca
- csv/xlsx PMS e Power BI
- file budget, partite aperte, bilancino, scheda
- allegati email fornitori
- pdf contratti/documenti amministrativi

### 1.3 Contract minimo metadata oggetto

Ogni oggetto Raw deve avere almeno:
- `source_system` (es. MPS, Sella, Esolver, HotelCube, Email)
- `source_channel` (Drive, WhatsApp, manual upload, mail)
- `received_at` (UTC)
- `sha256`
- `original_filename`
- `uploader` (utente o processo)

---

## 2) Manifest layer (control plane)

Manifesto in BigQuery (nome tabella definitivo da confermare; consigliato
`f_raw_manifest`). Una riga per oggetto raw versionato.

Campi minimi consigliati:
- `raw_object_id` (id interno stabile)
- `gcs_uri`
- `generation` (GCS object generation)
- `sha256`
- `size_bytes`
- `mime_type`
- `received_at`
- `source_system`
- `source_channel`
- `societa_hint` (nullable)
- `status`
- `classifier_rule_id` (nullable)
- `target_table` (nullable)
- `pipeline_name` (nullable)
- `pipeline_run_id` (nullable)

Stati consigliati:
- `RAW_ONLY`
- `CLASSIFIED`
- `VALIDATED`
- `INGESTED`
- `REJECTED`

---

## 3) Classificazione

La classificazione deve essere **deterministica** e basata su regole
(`ingest/classify.py`, `core/registry.yaml`).

Domande canoniche per ogni oggetto:
- Serve a un loop CASSA/COMPETENZA/IMPEGNO attivo?
- Schema riconosciuto?
- Lifecycle target `APPEND` o `SNAPSHOT`?
- Destinazione canonical (`f_*`/`d_*`) o resta Raw?

Se non classificabile o non utile ora:
- resta in `RAW_ONLY`
- non e un errore di sistema

---

## 4) Promozione a Canonical (BigQuery)

Un oggetto puo essere promosso a Canonical solo se:
1. classificato
2. parser disponibile
3. validation contract superato (Pydantic)
4. lifecycle applicato correttamente (APPEND/SNAPSHOT)
5. write effettuato via gate unico (`bq_write_validated`)

Canonical non e un dump: e una scelta esplicita del sistema.

---

## 5) Lineage end-to-end

Obiettivo: ogni numero Canonical deve essere spiegabile con origine e regole.

Minimo richiesto sulle righe canonical nuove (o a livello batch dove necessario):
- `pipeline_run_id`
- `pipeline_name`
- `source_gcs_uri` oppure `raw_object_id`
- `source_sha256`
- `ingestion_ts`

Frase audit attesa:
"questo valore in BQ viene da questo oggetto raw (GCS generation X),
acquisito in data Y, processato da pipeline Z, con regole R".

---

## 6) Relazione con Drive datahub

Drive resta workspace umano/editabile, non sorgente canonica immutabile.

Regola operativa:
- Drive puo essere punto di ingresso
- ma la provenienza ufficiale e il blob in GCS

In altre parole: si processa da deposito raw tracciato, non da cartelle umane.

---

## 7) 5 dimensioni (business contract)

Il modello a 5 dimensioni resta valido per i fatti canonical:
- `societa_id`
- `business_unit_id`
- `funzione_id`
- `location_id`
- `oggetto_id`

Se non derivabile in ingest:
- usare campo nullable dove consentito dallo schema
- tracciare il debito in STATUS/plan dedicato
- evitare scorciatoie che forzano valori non reali

---

## 8) Governance ingest

Ogni nuova pipeline deve:
1. leggere da Raw/Manifest (non da path ad hoc hardcoded)
2. dichiarare lifecycle (`APPEND` o `SNAPSHOT`)
3. validare schema prima del write
4. scrivere via gate unico BQ
5. aggiornare stato manifesto (`RAW_ONLY` -> ... -> `INGESTED`)
6. emettere metriche run (conteggi parse/valid/reject)

---

## 9) Anti-pattern da evitare

- scrivere in BQ direttamente da export locale senza passare Raw+Manifest
- derivare canonical da cartelle Drive non versionate
- ingestare tutto "perche c'e" senza discrimination need
- duplicare regole di classificazione o dedup in piu consumer
- perdere il legame tra record canonical e file origine

---

## 10) Stato di transizione (oggi 2026-05-05)

- Architettura target: GCS-first (decisa, in materializzazione)
- **Phase 4 landed**: `gs://hotelops-raw` operativo (Versioning ON +
  Autoclass→ARCHIVE), `core/lineage/raw_storage.py` con `LocalBackend` +
  `GCSBackend`, schema `f_raw_objects.gcs_generation` aggiunto, parser
  invocation supporta `gs://` via download-to-temp.
- **Pilot source attivo**: `MPS_BANCA_ORTI_APPEND` (`backend: gcs`,
  lifecycle APPEND con content_hash dedup — esercita il caso d'uso pieno
  di GCS+versioning).
- **Bulk flip pendente**: altre 12 sources restano `backend: drive` finché
  un PR dedicato le sposta in batch (separato da Phase 4 per limitare blast
  radius del pilot).
- **Backfill rows storiche**: NON eseguito — `f_raw_objects` esistenti
  restano `file://`. Backfill è opzionale e separato.
- Legacy datahub Drive: ancora workspace umano editabile; non sostituito.

I nuovi lavori che toccano lineage devono usare `intake_file` (che dispatcha
backend automaticamente via `source_def`). Non scrivere mai direttamente in
`f_raw_objects`.
