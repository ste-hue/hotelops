---
type: data_engineering_rules
status: active
last_updated: 2026-05-01
applies_to: hotelops platform
prereq_reading: INVARIANTS.md, AI_INSTRUCTIONS.md
---

# HotelOps — Data Engineering Rules

> Workflow contract per il lavoro di data engineering su HotelOps. Questo file
> **non duplica** `INVARIANTS.md` o `AI_INSTRUCTIONS.md` — costruisce sopra di loro
> con le regole operative concrete su naming, schema, contratti di scrittura, e
> workflow di review.

## Scope di applicazione

Le regole valgono **prospettivamente**:

- ✅ ogni nuova tabella, view, pipeline, e ogni riga scritta tramite il gate
  `bq_write_validated` da oggi in poi.
- ❌ tabelle legacy che esistono con il loro schema attuale **non** sono soggette a
  forced migration. Continuano a vivere come sono finché non c'è una migration
  deliberata — un task esplicito (spec o plan), allineato al gate, con
  verification count pre/post.

L'effetto è che il sistema si auto-tipizza nel tempo: nuove fact table nascono già
allineate al contratto; le legacy si convertono gradualmente quando ci sono ragioni
operative per farlo (Sprint 4 banche è il primo caso schedulato).

## §1. Architecture layers (reference)

Layer model `Raw → Canonical → Semantic → Operational` definito in `INVARIANTS.md`
e elaborato in `AI_INSTRUCTIONS.md` §"Layer Model". Non duplicato qui. Le regole
sotto si applicano principalmente alla transizione `Raw → Canonical` (ingest +
validation gate) e alla forma del Canonical layer.

## §2. Naming conventions

| prefisso | uso | esempio |
|---|---|---|
| `f_` | Fact tables (Canonical) | `f_banche_movimenti`, `f_vendite_fb` |
| `d_` | Dimension tables (Canonical) | `d_voci_piano_finanziario`, `d_fornitori` |
| `v_` | Views (Semantic) | `v_budget_canonical`, `v_food_cost_mensile` |

Prefissi **non adottati** oggi: `stg_` (staging), `mart_` (data mart). HotelOps
non ha un layer di trasformazione separato (Dataform / dbt-style); il Semantic
layer (`v_*`) è autoritativo per le lenti di business. L'introduzione di un
transformation layer è decisione architetturale separata (parking lot), non
variazione di queste regole.

Tabelle, view e file sorgente seguono `snake_case` italiano per i concetti di
dominio (`partite_aperte_fornitori`, `coperti_giornalieri`) — coerente col
vocabolario business in vault `ontology/`.

## §3. New fact table — required columns

Ogni nuova fact table (`f_*`) include queste colonne come **schema contract**.
Forzato dal gate I1 a livello Pydantic; permissivo a livello BigQuery DDL per
permettere retrofit naturale (vedi §"Lineage" sotto per il razionale del NULL
semantico).

### Spatial dimensions (5)

```
societa_id          STRING   REQUIRED   ⊆ {ORTI, INTUR}    (I3)
business_unit_id    STRING   NULLABLE   debito esplicito se non derivabile
funzione_id         STRING   NULLABLE   idem
location_id         STRING   NULLABLE   idem
oggetto_id          STRING   NULLABLE   idem
```

`societa_id` è REQUIRED perché ogni fatto appartiene a una società del gruppo. Le
altre 4 sono NULLABLE accettabilmente se non ancora derivabili al momento
dell'ingest — il debito viene tracciato in `STATUS.md` con il nome della future
dimension table di mapping (es. `d_classi_produzione TBD`).

### Lifecycle identity

```
APPEND:
  hash_riga         STRING   REQUIRED   MD5 deterministico, dedup primary

SNAPSHOT:
  natural_key set   STRING   REQUIRED   declared in bq_write_validated(natural_key=[...])
                                        (es. ['data_snapshot', 'societa_id'])
```

### Lineage (gate I1 output contract)

```
pipeline_run_id     STRING   NULLABLE in BQ schema, REQUIRED in Pydantic
pipeline_name       STRING   NULLABLE in BQ schema, REQUIRED in Pydantic
```

**Enforcement**: il Pydantic schema delle nuove fact table ha i due campi `str`
(non Optional). Il gate li popola dal ContextVar `PipelineRun.get_current()`. Se
chiamato fuori da un `with PipelineRun(...)` il gate logga warning, **genera un
UUID standalone** per `pipeline_run_id`, e popola
`pipeline_name='unknown_pipeline'`. Pydantic resta strict (no None).

Tre stati distinguibili a livello dati:

- `pipeline_run_id IS NULL AND pipeline_name IS NULL` → write **pre-gate** (legacy,
  scritto direttamente con `bigquery.Client` prima del refactor)
- `pipeline_run_id IS NOT NULL AND pipeline_name = 'unknown_pipeline'` → write via
  gate ma **fuori da PipelineRun** (debt auditable: è uscito dal validation path
  ma senza wrapping per la lineage)
- `pipeline_run_id IN (SELECT run_id FROM f_pipeline_runs) AND pipeline_name = 'ingest_*'`
  → write **canonico** via gate + PipelineRun wrapping

CI lint (Sprint 5, deadline 2026-05-31) bloccherà nuovi import diretti di
`bigquery.Client` fuori da `core/bq/`, riducendo nel tempo lo stato (1) per nuove
pipeline. Pipeline legacy migrano Sprint per Sprint (vedi
`docs/superpowers/specs/2026-04-28-bq-write-validated-design.md` §Migration plan).

### Audit

```
ingestion_ts        TIMESTAMP REQUIRED   canonical, ISO timezone-aware
file_sorgente       STRING   NULLABLE   NULL valido per source non-file (trigger,
                                        computed, API future)
```

`data_ingresso DATE` (presente in alcune fact table legacy) è deprecated. Non c'è
migration forzata: le tabelle legacy lo conservano fino a un refactor deliberato.
Le nuove tabelle usano `ingestion_ts TIMESTAMP`.

### Source preservation (derived financial values)

Quando una pipeline calcola un valore finanziario **derivato** da una fonte
upstream (importo riconciliato, somma di rate, valore convertito), la riga
risultante deve preservare la traccia:

```
importo_originale, data_originale, societa_originale,
business_unit_originale, file_sorgente_originale
```

…o un sottoinsieme appropriato. Principio: ogni numero deve essere riconducibile
alla sua fonte upstream tramite colonne dello stesso row, senza richiedere join
cross-table per la traccia di base.

## §4. Validation contract (I1)

Ogni write a BigQuery passa attraverso `core/bq/write.py::bq_write_validated`.
Il gate fa Pydantic validation, `json.dumps` probe per-row (boundary check), batch
load (no streaming buffer), e popola lineage. Spec autoritativa:
`docs/superpowers/specs/2026-04-28-bq-write-validated-design.md`.

**Eccezioni esistenti (debito noto, non tolerated come permanenti)**:

- `ingest/banca/ingest.py` (5 banche: MPS, MPS_KROSS, SELLA, INTESA, BCP) — in
  attesa di Sprint 4. Marker TODO nei punti di bypass.
- `--replace` mode di `ingest_coperti.py` — WRITE_TRUNCATE intenzionalmente fuori
  dallo scope del gate; documentato nella spec.

Nessuna nuova eccezione senza ADR esplicito in `docs/adr/`.

## §5. Lifecycle contract (I2)

Ogni fact table dichiara **APPEND** o **SNAPSHOT** al design. La scelta è
semantica:

- **APPEND** = fatti immutabili (movimenti, vendite, consumi). Dedup via
  `hash_riga` MD5. Helper: `core/bq/dedup.py::filter_new_rows_by_hash`.
- **SNAPSHOT** = stati a una data, sostituiscono la versione precedente (partite
  aperte, bilancino, budget). DELETE chirurgico per `natural_key`, poi INSERT.
  Il gate gestisce la transazione.

Cambio di lifecycle = migration esplicita + revisione downstream. Non al volo.

## §6. Semantic discipline

- **Don't merge entities without explicit stable IDs**. `societa_id`, `banca_id`,
  `voce_id` sono i punti di ancoraggio. Mai uniformare due entità per
  similitudine di nome.
- **Don't invent columns silently**. Ogni colonna BQ ha un campo Pydantic
  corrispondente in `core/schemas.py`. Aggiunte richiedono update Pydantic + spec
  se la colonna porta significato nuovo.
- **Don't infer business meaning silently**. Se un campo (es. `segmento_cliente`)
  ha codici opachi non documentati, il consumer non inventa decoder — chiede
  glossario o flagga il TBD nel vault `concepts/`.
- **Prefer views (`v_*`) over materialized tables** per logica derivata. Si
  materializza solo se c'è ragione operativa (latency, costo query ricorrente,
  consumer Looker con dataset specifico).

## §7. Assertions

A livello **Pydantic** (preferito, è dove vivono gli invariants):

- **Uniqueness** su chiavi: `hash_riga` per APPEND, `natural_key` set per
  SNAPSHOT — verificato dal gate via dedup helper o DELETE chirurgico.
- **Not-null** su chiavi e dimensioni REQUIRED: enforced dallo schema.
- **Allowed values**: `Literal[...]` per enums
  (`SocietaId = Literal["ORTI", "INTUR"]`,
  `tipo_evento = Literal["PREVENTIVO", "IMPEGNO", ...]`).
- **Date validity**: `model_validator` per range checks
  (es. `data_produzione` vs `OPERATIONS_CUTOVER_DATE`).

A livello **BigQuery** (sanity, non enforcement):

- `hotelops health` esegue spot-check su row counts, freshness, schema drift via
  `INFORMATION_SCHEMA`. È un drift detector, non un gate.

## §8. Workflow contract — Plan-First

Per cambiamenti a pipelines del dominio
**financial / supplier / project / cashflow**:

1. **Spec** — design in chat o `docs/superpowers/specs/YYYY-MM-DD-*.md`
2. **Plan** — TDD plan via skill `writing-plans` o checklist equivalente, con
   step verificabili
3. **Wait** — approvazione esplicita dell'owner (oggi: Stefano) prima di toccare
   file
4. **Execute** — task per task, evidence-based, ogni step verificabile pre/post

Conversazione architetturale resta in chat (no file touch). Modifiche di codice
passano dal gate workflow.

### Eccezioni (no plan needed)

- Typo, comment edits, README tweaks
- Operational fixes che non cambiano schema o pipeline shape (es. conversione
  formati .numbers → .csv prima di un ingest)
- Diagnostica read-only (BQ query, file inspect)
- Vault concept files non-ontology e non-decisions (es. fix puntuali a glossari)

### Cosa **non** è eccezione (richiede plan)

- Aggiunta di colonna a fact table esistente (anche se "solo nullable")
- Modifica della logica di parsing in un parser esistente
- Cambio del set `natural_key` di una SNAPSHOT
- Aggiornamento di view canonical (es. `v_budget_canonical`)

## §9. Anti-goals

- ❌ No bypass di `bq_write_validated` "per comodità" — eccezioni richiedono ADR
- ❌ No prefissi `stg_/mart_` finché non esiste un transformation layer separato
- ❌ No aggiunta silent di colonne (ogni colonna ha un Pydantic field)
- ❌ No inferenza di `societa_id` dal filename quando il contenuto disambigua
- ❌ No backfill di legacy data per colonne nuove a meno di un task migration
  esplicito

## §10. Related

- `docs/architecture/INVARIANTS.md` — costituzione (I1-I8)
- `docs/architecture/AI_INSTRUCTIONS.md` — operating manual per agenti AI
- `docs/architecture/LE_3_DIMENSIONI.md` — modello temporale CASSA / COMPETENZA / IMPEGNO
- `docs/superpowers/specs/2026-04-28-bq-write-validated-design.md` — gate I1 spec autoritativa
- `core/bq/write.py` — implementazione gate
- `core/bq/dedup.py` — dedup helper APPEND
- `core/pipeline_run.py` — PipelineRun ContextVar (lineage source)
- `STATUS.md` (root) — session memory, debiti aperti, prossimi passi
- `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md` — lineage layer Phase 1 design (raw object lifecycle, source_registry, hard gate)
