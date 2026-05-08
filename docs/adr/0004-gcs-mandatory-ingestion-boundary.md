---
date: 2026-05-07
status: accepted
supersedes: none
subsystem: ingest/lineage
owner: stefano
---

# ADR 0004 — GCS mandatory ingestion boundary

## Contesto

HotelOps ha introdotto il lineage per raw object (`f_raw_objects`, `f_lineage_events`) e ha avviato i primi pilot su GCS come raw layer. Nel frattempo sono emersi nuovi input operativi (accodamenti e semantic layer Power BI/HotelCube) che richiedono una regola chiara: separare in modo rigido provenienza raw e promozione canonical.

Il rischio senza decisione esplicita e' doppio:

- scritture canonical non tracciabili a un raw object verificabile;
- ingest "opportunistico" (dato disponibile -> ingest) senza discrimination need.

## Decisione

GCS diventa il boundary obbligatorio dell'ingest canonical.

Regola:

1. ogni write su fact table canoniche di business deve derivare da un raw object registrato in lineage;
2. il raw object deve avere `raw_uri` su `gs://...`;
3. se il target canonical non e' ancora deciso, la source resta `RAW_ONLY`.

La regola e' applicata con **enforcement progressivo per source**, non con big-bang:

- una source entra nel regime obbligatorio quando viene flippata a `raw_storage.backend: gcs`;
- le source non ancora migrate possono usare il percorso legacy temporaneo;
- i path GCS legacy gia' caricati restano validi (no riscrittura retroattiva).

## Implicazioni operative

- `intake -> promote` e' il percorso ufficiale di ingest.
- I parser esistenti restano funzioni interne richiamabili da `promote`, ma non sono l'entrypoint architetturale.
- Le nuove fonti discovery-first (es. semantic model Power BI) vanno in `RAW_ONLY` finche' non esiste un contratto canonical esplicito.
- Il backfill storico e l'eventuale rebuild canonical restano on-demand, guidati dai loop reali.

## Alternative scartate

- **Strict globale immediato**: troppo rischioso, romperebbe source non migrate.
- **Nessun boundary esplicito**: mantiene ambiguita' e riduce auditability.
- **Backfill totale subito**: alto costo con scarso valore se non legato a loop attivi.

## Conseguenze

Positive:

- provenienza verificabile end-to-end;
- migrazione controllata source-by-source;
- allineamento con policy `RAW_ONLY` per sorgenti non ancora modellate.

Trade-off:

- convivenza temporanea di path legacy e nuovo standard;
- necessita' di governance continua sul flip per-source.

## Done criteria iniziali

- [x] Regola formalizzata negli invariants (`I9`)
- [x] Source Power BI meta-layer registrate `RAW_ONLY` con intake lineage
- [ ] Enforcement tecnico per-source reso esplicito nel gate di write canonical
- [ ] Runbook migrazione per-source (pilot accodamenti come primo caso operativo)
