---
type: design_spec
domain: ingest / lineage
status: draft (Phase 1 design, post-review v2)
last_updated: 2026-05-05
branch: refactor/ingest-lineage-gcs
related:
  - docs/architecture/INVARIANTS.md (I1 validation gate, I2 lifecycle, I5 deterministic classify)
  - docs/architecture/AI_INSTRUCTIONS.md (Layer Model, Canonical Truth Registry)
  - docs/architecture/DATA_ENGINEERING_RULES.md (§3 lineage contract, §4 validation contract)
  - docs/superpowers/specs/2026-04-28-bq-write-validated-design.md (gate I1)
  - docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md (precursor — superseded by this spec)
  - vault/decisions/2026-05-02_GCS_as_Raw_Layer.md (TBD — scope esteso a tutto il datahub)
---

# Ingest Lineage & GCS Refactor — Phase 1 Design

> **Scope di questa spec:** *solo Phase 1*. Phase 1 introduce moduli **additive-only** che modellano il lineage per-raw-object e separano detection da policy, **senza alterare il comportamento osservabile** delle pipeline esistenti né i test verdi. GCS come Raw Layer immutabile è il target architetturale di Phase 4 (vedi §11), questa spec mette le fondamenta.

## 1. Perché esiste questa spec

Oggi il flusso di ingest ha tre debiti accumulati:

1. **Concept conflation in `core/registry.yaml`**: un singolo file dichiara *come riconoscere* un file (signatures, formats), *dove finisce nel datahub* (`dest_folder`), *come si chiama la tabella canonica* (`bq_table`), *che pipeline lo processa* (`pipeline`), *che lifecycle ha* (APPEND/SNAPSHOT). Quattro concetti distinti in un posto solo. Conseguenza: aggiungere una nuova fonte ricicla copy-paste; cambiare la policy di un loop tocca anche le signatures.

2. **Lineage missing per-raw-object**: oggi il sistema sa *quante volte* una pipeline è girata (`f_pipeline_runs`) e *quali file sono stati droppati* (`ingresso/_audit/drops.jsonl`), ma **non** ha una vista canonica di *ogni singolo blob raw* con la sua storia (ricevuto → classificato → validato → promosso → in BQ). Quando una riga `f_*` puzza, non c'è path navigabile riga → write → run → raw object → file originale.

3. **Hard gate "no loop, no canonical" non esiste**: oggi ogni file riconosciuto da `classify` viene routed e (se `--ingest`) processato in BQ. Non c'è un check esplicito che dica "questa fonte non ha un loop dichiarato a valle, quindi entra in raw ma **non** promuove a canonical". Conseguenza: dati che non servono a nessuna decisione finiscono comunque in `f_*`, gonfiando lo store senza essere mai letti (anti-goal articolato il 2026-05-02).

Phase 1 risolve (1), (2), (3) con un **lineage layer aggiuntivo**, lasciando intatto il flusso di default.

## 2. Decisioni locked (input alla spec, riconciliate)

Riepilogate dal prompt e riconciliate con vincoli del repo (revisione v2):

| Decisione | Valore |
|---|---|
| `core/registry.yaml` | Detector registry **only** (technical recognition) |
| `core/source_registry.yaml` | Source meaning + policy (new SSOT) |
| `core/bq/manifest.py` | **Overridden** — il file esistente resta catalogo BQ; raw object lifecycle vive in `core/lineage/raw_manifest.py`. Vedi §3.4. |
| Boundaries `ingest/` | intake → classification → raw → promotion |
| Parser `ingest/banca` + `ingest/flussi` | **Unchanged in Phase 1** |
| Hard gate | No loop target ⇒ no canonical promotion (`RAW_ONLY`) |
| Source naming | `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>` — **strict 4 parts**, vedi §4.1.1 grammar |
| Manifest statuses | `RAW_ONLY → CLASSIFIED → PROMOTABLE → PROMOTED`, `REJECTED` side-state |
| Required events | `RAW_INGESTED`, `DETECTED`, `SOURCE_RESOLVED`, `VALIDATED_OK`, `VALIDATED_FAIL`, `PROMOTION_REQUESTED`, `PROMOTED`, `REJECTED`, `RECLASSIFIED` |

**Constraint operative aggiunte (post-confirmation Stefano)**:

- **Additive-only**: nuovi moduli accanto ai vecchi, niente delete/move
- **Adapters dai vecchi path verso i nuovi entrypoint** (vedi §6 backward compat)
- **Tutti i test esistenti restano verdi** (zero modifica a `tests/test_classify.py`, `tests/test_drop_audit.py`, etc.)
- **Phase 1 zero shadow mode**: nessun emit di lineage events dai vecchi path. Solo i nuovi entrypoint (`hotelops intake/promote`) scrivono nelle lineage tables. Shadow mode è un'opzione esplicita di Phase 2.

## 3. Target folder/module structure (additive-only)

### 3.1 Nuovi file

```
core/
├── source_registry.yaml          NEW   SSOT policy per source_name
└── lineage/                      NEW
    ├── __init__.py
    ├── schemas.py                NEW   Pydantic: SourceDefinition, RawObject, LineageEvent
    ├── source_resolver.py        NEW   load source_registry, map (detector_category, dims) → source_name
    ├── state_machine.py          NEW   transition rules + validation
    ├── raw_manifest.py           NEW   write/read f_raw_objects + f_lineage_events (append-only via gate)
    └── policy_gate.py            NEW   "no loop target ⇒ RAW_ONLY" enforcement

ingest/
├── intake.py                     NEW   entrypoint: file + source_metadata → raw blob + RAW_INGESTED event
└── promotion.py                  NEW   entrypoint: f_raw_objects (PROMOTABLE) → parser → bq_write_validated → PROMOTED

cli.py                            EDIT  add `hotelops intake` + `hotelops promote` + `hotelops lineage` subcommands (NEW commands, additive)
                                       cmd_drop, cmd_classifica unchanged

core/bq/load/
└── load_lineage_tables.py        NEW   creates f_raw_objects + f_lineage_events DDL + v_raw_objects_current view

core/bq/views/
└── v_raw_objects_current.sql     NEW   latest state per raw_object_id (joins identity + latest event)

docs/superpowers/specs/
└── 2026-05-05-ingest-lineage-gcs-design.md   THIS FILE
```

### 3.2 File esistenti — comportamento Phase 1

| File | Stato Phase 1 | Note |
|---|---|---|
| `core/registry.yaml` | **Unchanged** | Continua a contenere `dest_folder`/`bq_table`/`pipeline`. Phase 2 le sposta in `source_registry.yaml`; Phase 1 le lascia per non rompere `classify.py` + `orchestrate.py`. |
| `ingest/classify.py` | **Unchanged** | Tutti i symbol importati dai test restano. `cmd_drop` continua a chiamare `classify_batch` + `route_file` + `run_ingest` come oggi. |
| `ingest/orchestrate.py` | **Unchanged** | Continua con `PIPELINES` + `MULTI_PIPELINES`. Phase 2 considera unificazione con source_registry. |
| `ingest/banca/*`, `ingest/flussi/*` | **Unchanged** | Parser intatti. |
| `core/bq/manifest.py` | **Unchanged** | Resta catalogo metadata BQ. Vedi §3.4. |
| `core/bq/write.py` | **Unchanged** | Gate I1 invariato. Tutte le scritture lineage ci passano (append-only). |
| `core/pipeline_run.py` | **Unchanged** | `PipelineRun` invariato. `intake.py` e `promotion.py` lo wrappano. |

### 3.3 Tabelle BigQuery nuove

```
f_raw_objects             APPEND, write-once at intake (immutable identity table — vedi §4.2)
f_lineage_events          APPEND, immutable, una riga per transizione di stato
v_raw_objects_current     VIEW, joins f_raw_objects + latest f_lineage_events per raw_object_id
```

**Posizionamento**: stesso dataset `hotelops`. Naming `f_*` perché modellano *fatti osservazionali sul flusso di ingest*. Naming `v_*` per la view derivata.

### 3.4 Risoluzione collisione `core/bq/manifest.py` (Q1 chiusa)

La decisione locked nel prompt diceva "`core/bq/manifest.py` = runtime truth of each raw object lifecycle". Ma il file esiste già con scopo diverso (catalogo metadata tabelle BQ, usato da `hotelops manifest` + `tests/test_manifest.py`). Riscriverlo viola additive-only e rompe i test.

**Decisione finale (Q1 chiusa, conferma Stefano post-review v1)**: il "raw object lifecycle store" vive in **`core/lineage/raw_manifest.py`**. `core/bq/manifest.py` resta il catalogo BQ. Nessun rinominamento in Phase 1 né Phase 2.

Razionale: i due concetti (catalogo schema delle tabelle BQ vs lineage runtime delle raw objects) sono ortogonali. Tenerli in moduli separati con nomi distinti previene confusione futura. Rinominare `core/bq/manifest.py` → `core/bq/catalog.py` resta opzionale per cleanup estetico, ma fuori scope di questo refactor.

## 4. Data contracts

### 4.1 `core/source_registry.yaml` — schema

Nuovo SSOT che dichiara *cosa significa una fonte* e *che policy ha*. Una riga per `source_name`. Indipendente dai detector signatures.

#### 4.1.1 Naming grammar (strict, validated at boot)

```
source_name := <SYSTEM> "_" <DATASET> "_" <SOCIETA> "_" <LIFECYCLE>

<SYSTEM>    := [A-Z][A-Z0-9]*           # nessun underscore interno
<DATASET>   := [A-Z][A-Z0-9]*           # nessun underscore interno
<SOCIETA>   := "ORTI" | "INTUR" | "GROUP"   # GROUP per sorgenti cross-società
<LIFECYCLE> := "APPEND" | "SNAPSHOT"
```

**Esattamente 4 token** separati da `_`. Parser banale: `source_name.split("_")` deve produrre lista lunga 4. `source_resolver.py` valida questo formato all'import del registry e fallisce duro su violazioni.

**Conseguenze del vincolo**:
- BU (HOTEL/RESIDENCE/CVM/LIDO/HQ) **non entra** nel `source_name`. Vive nel campo `business_unit` del source definition (NULL se non bound) e/o nelle righe di `f_raw_objects` (per file dove BU si determina per-file dal contenuto).
- Dataset multi-token va condensato (es. `MOVIMENTI_CONTABILI` → `MOVIMENTI`; `PARTITE_FORNITORI` → `PARTITE`; `PIANO_FINANZIARIO` → `PF`). La label umana resta nel campo `dataset_label`.
- Se due sorgenti sono semanticamente distinte ma collassano sullo stesso 4-tuple, una delle due ha mappato male il proprio dataset — è un **errore di design**, non da risolvere allargando la grammatica.

**Q4 (BU nel nome) e Q5 (cross-società naming) chiuse qui**.

#### 4.1.2 YAML schema

```yaml
# core/source_registry.yaml
version: 1

sources:
  ESOLVER_BILANCINO_ORTI_SNAPSHOT:
    system: ESOLVER                  # source system (ERP/PMS/BANK/MANUAL)
    dataset: BILANCINO               # logical dataset (single token)
    dataset_label: "Bilancio di verifica"  # human-readable, free form
    societa: ORTI                    # ORTI | INTUR | GROUP
    business_unit: null              # null if not bound at source level
    lifecycle: SNAPSHOT              # APPEND | SNAPSHOT
    canonical_table: f_bilancino     # destination BQ table (FQN built via core.config)
    parser_module: ingest.flussi.ingest_bilancino   # python -m target
    parser_entrypoint: main          # function name (default: main)
    natural_key: [data_snapshot, societa_id, codice_conto]   # required if lifecycle=SNAPSHOT
    loop_targets:                    # downstream loops that consume this canonical
      - bank_ledger_reconciliation
      - monthly_close
    promotion_policy: AUTO           # AUTO | MANUAL | RAW_ONLY
    detector_category: bilancino     # ← link verso registry.yaml (oggi)
    raw_storage:
      backend: drive                 # drive | gcs (Phase 4 flips most to gcs)
      path_template: "ingresso/bilancino/{societa}"
    notes: |
      Bilancio di verifica Esolver, leaf nodes only. Snapshot sostituisce
      la versione precedente per data_snapshot+societa.

  ESOLVER_PARTITE_INTUR_SNAPSHOT:
    system: ESOLVER
    dataset: PARTITE
    dataset_label: "Partite aperte fornitori"
    societa: INTUR
    business_unit: null
    lifecycle: SNAPSHOT
    canonical_table: f_partite_aperte_fornitori
    parser_module: ingest.flussi.ingest_partite_aperte
    natural_key: [data_snapshot, societa_id]
    loop_targets: [cash_control, monthly_close]
    promotion_policy: AUTO
    detector_category: partite_fornitori
    raw_storage:
      backend: drive
      path_template: "ingresso/partite_fornitori/{societa}"

  HOTELCUBE_ACCODAMENTI_ORTI_APPEND:
    system: HOTELCUBE
    dataset: ACCODAMENTI
    dataset_label: "Accodamenti PMS (corrispettivi/fatture/movimenti)"
    societa: ORTI
    business_unit: null              # ← BU si determina per-file dal prefix H_/R_/C_, finisce in f_raw_objects.business_unit_id
    lifecycle: APPEND
    canonical_table: f_accodamenti
    parser_module: ingest.banca.ingest_accodamenti
    natural_key: null
    hash_basis: hash_riga            # APPEND-only: nome della colonna MD5
    loop_targets: [daily_reconciliation, cash_control]
    promotion_policy: AUTO
    detector_category: accodamenti
    raw_storage:
      backend: drive
      path_template: "accodamenti/ORTI"

  POWERBI_CRUSCOTTO_ORTI_APPEND:
    system: POWERBI
    dataset: CRUSCOTTO
    dataset_label: "Cruscotto produzione PMS (export Power BI)"
    societa: ORTI
    business_unit: null              # 3 file/giorno (HOTEL/CVM/RESIDENCE), BU per-file
    lifecycle: APPEND
    canonical_table: f_pms_statistiche
    parser_module: ingest.flussi.ingest_pms_statistiche
    loop_targets: []                 # ← nessun loop dichiarato
    promotion_policy: RAW_ONLY       # ← hard gate: niente promozione
    detector_category: pms_statistiche
    raw_storage:
      backend: drive
      path_template: "ingresso/pms_statistiche/{societa}/{business_unit}"
    notes: |
      Esempio del hard gate: questo source ha dati interessanti ma nessun
      loop downstream li consuma con verdetto. Resta in raw, non viene
      promosso. Quando un loop sarà dichiarato, flip promotion_policy=AUTO.
```

**Policy values**:

| `promotion_policy` | Significato |
|---|---|
| `AUTO` | Promozione automatica appena classificato + raw store ok |
| `MANUAL` | Promozione richiede `hotelops promote --raw-object-id X` esplicito |
| `RAW_ONLY` | **Hard gate**: solo raw, mai canonical. Tentativi di promotion → `REJECTED` con `reason=NO_LOOP_TARGET` |

**Invariant**: `loop_targets == [] ⇔ promotion_policy == RAW_ONLY`. `source_resolver.py` lo valida al boot e fallisce duro su qualsiasi inconsistenza.

### 4.2 `f_raw_objects` — identity table (write-once, immutable)

**Decisione Q2 chiusa: append-only, write-once at intake. Nessun UPDATE, nessun MERGE.**

Questo risolve il rischio I1 sui MERGE (issue High della review v1): ogni write a `f_raw_objects` passa da `bq_write_validated(mode="append")`, e la riga non viene mai più modificata. Lo stato corrente vive in `f_lineage_events` (append-only via gate) ed è esposto via `v_raw_objects_current`.

```python
# core/lineage/schemas.py
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

class RawObject(BaseModel):
    """Identity row per blob ricevuto. Write-once at intake, never mutated."""
    raw_object_id: str = Field(..., description="UUID generato all'intake")
    content_hash: str = Field(..., description="MD5 esadecimale del blob raw")
    raw_uri: str = Field(..., description="gs://... o file:///... — dove vive il blob")
    raw_backend: Literal["drive", "gcs", "local"]
    file_name_original: str
    file_name_canonical: Optional[str] = None
    bytes_size: int

    # Source metadata declared at intake time (best effort — può essere risolto post-hoc via RECLASSIFIED event)
    source_name: Optional[str] = Field(None, description="da source_registry; NULL finché non risolto")
    detector_category: Optional[str] = Field(None, description="output del detector tecnico")
    societa_id: Optional[str] = None
    business_unit_id: Optional[str] = None
    banca_id: Optional[str] = None

    # Audit (set once, never updated)
    intake_at: datetime
    intake_actor: str = Field(..., description="cli|nanoclaw|cron|test")

    # Required by DATA_ENGINEERING_RULES §3 (lineage contract)
    pipeline_run_id: str             # popolato dal gate
    pipeline_name: str               # popolato dal gate
    file_sorgente: Optional[str] = None
    ingestion_ts: datetime
```

**Note sul design**:
- **Nessun campo `status`** sulla riga. Lo stato corrente si calcola da `f_lineage_events`.
- **Nessun campo `canonical_run_id` o `promoted_at`** sulla riga. Quei dati vivono nei rispettivi events `PROMOTED`.
- I campi di source metadata (`source_name`, `detector_category`, dims) sono "best effort all'intake": se vuoti, sono risolvibili in seguito via `RECLASSIFIED` event (che porta a CLASSIFIED → PROMOTABLE).
- Idempotency: `intake.register()` deduplica per `content_hash`. Re-intake dello stesso hash ritorna l'esistente `raw_object_id` senza nuova riga né nuovo evento `RAW_INGESTED` (audit log conta il dedup hit, ma non scrive su BQ).

**BQ DDL**:

```sql
CREATE TABLE hotelops.f_raw_objects (
  raw_object_id        STRING NOT NULL,
  content_hash         STRING NOT NULL,
  raw_uri              STRING NOT NULL,
  raw_backend          STRING NOT NULL,
  file_name_original   STRING NOT NULL,
  file_name_canonical  STRING,
  bytes_size           INT64 NOT NULL,
  source_name          STRING,
  detector_category    STRING,
  societa_id           STRING,
  business_unit_id     STRING,
  banca_id             STRING,
  intake_at            TIMESTAMP NOT NULL,
  intake_actor         STRING NOT NULL,
  pipeline_run_id      STRING,
  pipeline_name        STRING,
  file_sorgente        STRING,
  ingestion_ts         TIMESTAMP NOT NULL
)
PARTITION BY DATE(intake_at)
CLUSTER BY content_hash, source_name;
```

(`pipeline_run_id` e `pipeline_name` sono NULLABLE in DDL ma REQUIRED in Pydantic — coerente con DATA_ENGINEERING_RULES §3.)

### 4.3 `f_lineage_events` — schema BQ + Pydantic

Una riga per *transizione di stato*. Append-only, immutabile, **unica fonte di verità per lo stato corrente**.

```python
# core/lineage/schemas.py (continua)
RawObjectStatus = Literal[
    "RAW_ONLY",
    "CLASSIFIED",
    "PROMOTABLE",
    "PROMOTED",
    "REJECTED",
]

LineageEventType = Literal[
    "RAW_INGESTED",         # blob ricevuto + persistito in raw store (transition: ∅ → RAW_ONLY)
    "DETECTED",             # detector ha matchato (no transition; payload: confidence)
    "SOURCE_RESOLVED",      # detector_category + dims → source_name (RAW_ONLY → CLASSIFIED → PROMOTABLE)
    "VALIDATED_OK",         # parser ha emesso righe + Pydantic ok (no transition; payload: row count)
    "VALIDATED_FAIL",       # parser o Pydantic ha fallito (PROMOTABLE → REJECTED)
    "PROMOTION_REQUESTED",  # promotion entrypoint chiamato (no transition)
    "PROMOTED",             # bq_write_validated OK (PROMOTABLE → PROMOTED)
    "REJECTED",             # qualsiasi rejection con reason (* → REJECTED)
    "RECLASSIFIED",         # source_name cambiato manualmente (REJECTED|CLASSIFIED → CLASSIFIED|RAW_ONLY)
]

RejectionReason = Literal[
    "NO_LOOP_TARGET",       # source ha promotion_policy=RAW_ONLY o loop_targets=[]
    "DETECT_FAIL",          # detector + manual override entrambi assenti
    "VALIDATE_FAIL",        # parser/Pydantic fallita
    "WRITE_FAIL",           # bq_write_validated raise
]

class LineageEvent(BaseModel):
    event_id: str
    raw_object_id: str
    event_type: LineageEventType
    event_at: datetime
    actor: str               # cli|cron|nanoclaw|test|gate
    pipeline_run_id: Optional[str] = None
    pipeline_name: Optional[str] = None
    from_status: Optional[RawObjectStatus] = None
    to_status: Optional[RawObjectStatus] = None
    payload_json: Optional[str] = Field(None, description="JSON: detector confidence, error msg, row counts, natural_key, ecc.")
    reason: Optional[RejectionReason] = None
```

```sql
CREATE TABLE hotelops.f_lineage_events (
  event_id          STRING NOT NULL,
  raw_object_id     STRING NOT NULL,
  event_type        STRING NOT NULL,
  event_at          TIMESTAMP NOT NULL,
  actor             STRING NOT NULL,
  pipeline_run_id   STRING,
  pipeline_name     STRING,
  from_status       STRING,
  to_status         STRING,
  payload_json      STRING,
  reason            STRING
)
PARTITION BY DATE(event_at)
CLUSTER BY raw_object_id, event_type;
```

**Tutti i write** a `f_lineage_events` passano da `bq_write_validated(mode="append")`. **I1 rispettato pienamente**, nessuna eccezione.

### 4.4 `v_raw_objects_current` — view di convenienza

Espone "stato corrente per raw object" senza richiedere window function al consumer.

```sql
-- core/bq/views/v_raw_objects_current.sql
CREATE OR REPLACE VIEW hotelops.v_raw_objects_current AS
WITH latest_event AS (
  SELECT
    raw_object_id,
    to_status AS current_status,
    event_at AS last_event_at,
    pipeline_run_id AS last_pipeline_run_id,
    reason AS last_rejection_reason,
    ROW_NUMBER() OVER (
      PARTITION BY raw_object_id
      ORDER BY event_at DESC, event_id DESC
    ) AS rn
  FROM hotelops.f_lineage_events
  WHERE to_status IS NOT NULL    -- only state-transition events
)
SELECT
  ro.*,
  COALESCE(le.current_status, 'RAW_ONLY') AS current_status,
  le.last_event_at,
  le.last_pipeline_run_id,
  le.last_rejection_reason
FROM hotelops.f_raw_objects ro
LEFT JOIN latest_event le
  ON le.raw_object_id = ro.raw_object_id
  AND le.rn = 1;
```

Questa view è la query surface per `hotelops lineage <id>`, dashboard, drift detection. Non scrive nulla: pura derivazione.

## 5. State machine + transition rules

### 5.1 Diagramma

```
                            ┌──────────────┐
                            │   (NEW FILE) │
                            └──────┬───────┘
                                   │ intake.py
                                   │ + RAW_INGESTED event (∅ → RAW_ONLY)
                                   ▼
                            ┌──────────────┐
                       ┌────│   RAW_ONLY   │────┐
                       │    └──────┬───────┘    │
                       │           │            │
   classify fails      │           │ classify OK│
   AND no manual       │           │ + DETECTED │
   source_name         │           │   event    │
                       │           │            │
                       │           │ source_resolver OK
                       │           │ + SOURCE_RESOLVED (RAW_ONLY → CLASSIFIED)
                       │           ▼            │
                       │    ┌──────────────┐    │
                       │    │  CLASSIFIED  │    │
                       │    └──────┬───────┘    │
                       │           │            │
                       │           │ policy_gate.enforce → ok
                       │           │ implicit transition CLASSIFIED → PROMOTABLE
                       │           │ (logged as part of SOURCE_RESOLVED payload)
                       │           ▼            │
                       │    ┌──────────────┐    │
                       │    │ PROMOTABLE   │    │
                       │    │   (AUTO)     │    │
                       │    │ or MANUAL    │    │
                       │    │   queued     │    │
                       │    └──────┬───────┘    │
                       │           │            │
                       │           │ promotion.py
                       │           │ + parser run + bq_write_validated
                       │           │ + VALIDATED_OK + PROMOTED (PROMOTABLE → PROMOTED)
                       │           ▼            │
                       │    ┌──────────────┐    │
                       │    │   PROMOTED   │    │ (terminal)
                       │    └──────────────┘    │
                       │                        │
                       │                        │
                       └─────► REJECTED ◄───────┘
                              (side state, terminal*)
                              + REJECTED event with reason ∈ {
                                  NO_LOOP_TARGET,
                                  DETECT_FAIL,
                                  VALIDATE_FAIL,
                                  WRITE_FAIL,
                              }

                              * RECLASSIFIED can move REJECTED → CLASSIFIED or RAW_ONLY
                                (operator manual action — emits new event chain)
```

### 5.2 Transition rules (formal)

| From | To | Trigger | Required precondition | Event(s) emitted |
|---|---|---|---|---|
| ∅ | RAW_ONLY | `intake.register(file, source_metadata)` | content_hash unique, raw_uri persisted | `RAW_INGESTED` (from_status=NULL, to_status=RAW_ONLY) |
| RAW_ONLY | CLASSIFIED | `source_resolver.resolve(detector_result, dims)` returns non-null | detector confidence ≥ threshold | `DETECTED` (no transition), `SOURCE_RESOLVED` (RAW_ONLY → CLASSIFIED) |
| RAW_ONLY | REJECTED | classify fails AND no manual override | exhaustive detector run | `REJECTED` with reason=`DETECT_FAIL` |
| CLASSIFIED | PROMOTABLE | `policy_gate.enforce_loop_target_gate(source)` passes | `promotion_policy in {AUTO, MANUAL}` | implicit (encoded in `SOURCE_RESOLVED.payload.next_status`) |
| CLASSIFIED | REJECTED | `policy_gate` raises (`promotion_policy == RAW_ONLY` OR `loop_targets == []`) | hard gate | `REJECTED` with reason=`NO_LOOP_TARGET` |
| PROMOTABLE | PROMOTED | `promotion.promote(raw_object_id)` calls parser + bq_write_validated successfully | inside `PipelineRun(...)` | `PROMOTION_REQUESTED`, `VALIDATED_OK`, `PROMOTED` |
| PROMOTABLE | REJECTED | parser raises OR Pydantic fails OR write fails | — | `VALIDATED_FAIL` then `REJECTED` (reason=`VALIDATE_FAIL` or `WRITE_FAIL`) |
| any non-PROMOTED | CLASSIFIED | `source_resolver.reclassify(raw_object_id, new_source_name)` (operator manual action) | new source_name valid in registry | `RECLASSIFIED` |
| any non-PROMOTED | RAW_ONLY | reset (operator) | explicit `--reset` flag | `RECLASSIFIED` (to_status=RAW_ONLY) |

**Terminal states**: `PROMOTED`, `REJECTED`. PROMOTED never transitions out without `--force`. REJECTED can be revived via RECLASSIFIED (creates new event chain, status moves back).

### 5.3 Why all writes respect I1

- `f_raw_objects`: write-once via `bq_write_validated(mode="append")` at intake. Mai modificata. Ogni riga ha `pipeline_run_id` + `pipeline_name` popolati dal gate via `PipelineRun.get_current()`.
- `f_lineage_events`: append-only via `bq_write_validated(mode="append")` ad ogni transizione. Stessa garanzia.
- `v_raw_objects_current`: pure VIEW, nessun side-effect.
- **Nessun MERGE, nessun UPDATE, nessun DELETE su queste due tabelle**. Punto.

Questo è strutturalmente più semplice della v1: il gate è già configurato per "append" mode e popola lineage automaticamente. Zero codice nuovo dentro `core/bq/write.py`.

### 5.4 Idempotency

- **Re-intake** dello stesso `content_hash`: `intake.register()` ritorna l'esistente `raw_object_id` (lookup via `WHERE content_hash = @h LIMIT 1` su `f_raw_objects`). Nessun nuovo evento `RAW_INGESTED`. Drop audit logs il dedup hit fuori-BQ.
- **Re-promotion** di un raw_object già PROMOTED: `promotion.promote()` ritorna no-op se `current_status=PROMOTED`. Force-promote richiede `--force` esplicito, che emette `RECLASSIFIED` (→ PROMOTABLE) seguito da nuova catena `PROMOTION_REQUESTED → PROMOTED`.
- **Re-classify** già CLASSIFIED con stesso source_name: no-op.

## 6. Backward compatibility — explicit map

Tutti i symbol pubblici esistenti restano importabili dai loro path attuali. Nessun test esistente cambia.

| Old surface | Phase 1 behavior |
|---|---|
| `from ingest.classify import classify, classify_batch, route_file, run_ingest` | Unchanged. Tests `test_classify.py` green. |
| `from ingest.classify import append_drop_audit, file_md5_hex, AUDIT_DROP_FILE` | Unchanged. Test `test_drop_audit.py` green. |
| `hotelops drop <file>` (cli.py:cmd_drop) | Unchanged. Continues `classify_batch → route_file → run_ingest → append_drop_audit`. |
| `hotelops classifica <file>` (cli.py:cmd_classifica) | Unchanged. |
| `hotelops ingest --pipeline X` → `python -m ingest.orchestrate --pipeline X` | Unchanged. |
| `python -m ingest.flussi.ingest_partite_aperte --file X --societa Y` | Unchanged (parser intatto). |
| `python -m ingest.banca.ingest_accodamenti --datahub D` | Unchanged. |
| `from core.bq.manifest import generate_manifest, TABLES` (BQ catalog) | Unchanged. Test `test_manifest.py` green. |

**New surfaces in Phase 1** (additive):

| New surface | Purpose |
|---|---|
| `from core.lineage.raw_manifest import register_raw_object, emit_event, latest_status` | API for intake.py + promotion.py |
| `from core.lineage.source_resolver import resolve_source, load_registry, validate_invariants` | Source name resolution |
| `from core.lineage.state_machine import can_transition, REJECTION_REASONS` | Transition validation (pure functions) |
| `from core.lineage.policy_gate import enforce_loop_target_gate, PolicyViolation` | Hard gate enforcement |
| `python -m ingest.intake --file X [--source-name Y \| --auto-classify]` | Phase-1 entrypoint to test the new path end-to-end |
| `python -m ingest.promotion [--raw-object-id Z \| --all-promotable]` | Manual or batch promotion |
| `hotelops intake <file>` (NEW subcommand) | CLI alias for `python -m ingest.intake` |
| `hotelops promote [--all-promotable \| --raw-object-id Z]` (NEW subcommand) | CLI for promotion |
| `hotelops lineage <raw_object_id>` (NEW subcommand) | Inspect raw object + event history |

**Adapter strategy (Phase 1, Q3 chiusa = NO shadow mode)**: la nuova flow non si attiva da sola sul flow vecchio. `cmd_drop`, `cmd_classifica`, `ingest.orchestrate` restano puri. Lineage events sono emessi **esclusivamente** dai nuovi entrypoint. Phase 2 introduce un opt-in `--lineage` flag (vedi §8).

## 7. Gate logic + failure modes

### 7.1 Hard gate "no loop, no canonical"

Implementato in `core/lineage/policy_gate.py`:

```python
class PolicyViolation(Exception):
    def __init__(self, reason: str, source_name: str, message: str):
        self.reason = reason
        self.source_name = source_name
        super().__init__(message)


def enforce_loop_target_gate(source_def: SourceDefinition) -> None:
    """Raise PolicyViolation if a source has no loop targets and would promote.

    Called by:
      - source_resolver at boot (validate registry consistency)
      - promotion.py before invoking parser
    """
    has_loops = bool(source_def.loop_targets)
    is_raw_only = source_def.promotion_policy == "RAW_ONLY"

    # Invariant: loop_targets == [] ⇔ promotion_policy == RAW_ONLY
    if has_loops and is_raw_only:
        raise PolicyViolation(
            reason="NO_LOOP_TARGET",
            source_name=source_def.source_name,
            message=(
                f"{source_def.source_name}: promotion_policy=RAW_ONLY "
                f"contraddice loop_targets={source_def.loop_targets}. "
                f"Decidi: o flip policy=AUTO/MANUAL, o azzera loop_targets."
            ),
        )
    if not has_loops and not is_raw_only:
        raise PolicyViolation(
            reason="NO_LOOP_TARGET",
            source_name=source_def.source_name,
            message=(
                f"{source_def.source_name}: loop_targets=[] ma "
                f"promotion_policy={source_def.promotion_policy}. "
                f"Hard gate: dichiara almeno un loop o flip policy=RAW_ONLY."
            ),
        )

    # Fail-closed at promotion time: never promote a RAW_ONLY source
    if is_raw_only:
        raise PolicyViolation(
            reason="NO_LOOP_TARGET",
            source_name=source_def.source_name,
            message=(
                f"{source_def.source_name} è RAW_ONLY: promotion non consentita."
            ),
        )
```

Boot-time: `source_resolver.load_registry()` chiama `enforce_loop_target_gate()` per ogni source con un wrapper che cattura solo i casi di **inconsistenza** (le due righe di `if has_loops and is_raw_only` / `if not has_loops and not is_raw_only`). Una source legittimamente RAW_ONLY (loop_targets=[], policy=RAW_ONLY) non fa fallire il boot.

Promotion-time: `promotion.promote()` chiama lo stesso gate **senza filter** — qualsiasi raise (incluso il caso RAW_ONLY legittimo) emette `REJECTED` con `reason=NO_LOOP_TARGET`.

### 7.2 Failure modes summary

| Failure | Detected by | Resulting status | reason | Recovery |
|---|---|---|---|---|
| File extension/content unknown | `classify.classify()` returns category=unknown | RAW_ONLY (stays) | (no rejection — operator can RECLASSIFY manually) | manual classification or new detector |
| Detector matched but source_resolver returns null | `source_resolver.resolve()` | REJECTED | `DETECT_FAIL` | add source_name to source_registry, RECLASSIFY |
| `loop_targets == []` and policy not RAW_ONLY | `enforce_loop_target_gate()` at boot | (system refuses to start) | — | fix source_registry |
| Promotion attempted on RAW_ONLY source | `enforce_loop_target_gate()` at promotion | REJECTED | `NO_LOOP_TARGET` | declare loop, flip policy=AUTO, RECLASSIFY |
| Parser raises / Pydantic fails | `promotion.promote()` catches | REJECTED | `VALIDATE_FAIL` | fix parser or input data, manual `--retry` |
| `bq_write_validated` raises `BigQueryInsertError` | gate inside promotion | REJECTED | `WRITE_FAIL` | inspect BQ logs, manual retry |
| Idempotent re-intake (same content_hash) | `intake.register()` | (existing raw_object_id returned, no new event) | — | (no recovery needed) |
| Promotion of already PROMOTED | `promotion.promote()` | (no-op, returns existing canonical_run_id from latest PROMOTED event) | — | `--force` to re-promote (snapshot) |

### 7.3 What happens to existing `cmd_drop` failures

Unchanged. `cmd_drop` still appends to `ingresso/_audit/drops.jsonl` with status `OK | UNKNOWN | DRY_RUN | FAIL_ROUTE | FAIL_INGEST`. The new lineage tables are populated only by new entrypoints. Two trails coexist in Phase 1 (Q3 chiusa = no shadow); Phase 3 unifies after Phase 2 shadow validates parity.

## 8. Migration plan — incremental, testable, rollback-ready

### Phase 1 — Foundations (this branch, ~4-6 days)

**Goal**: nuovi moduli + tabelle + tests. Zero behavior change in old paths.

- Create new files (§3.1)
- Create BQ tables `f_raw_objects`, `f_lineage_events` + view `v_raw_objects_current` via DDL loader
- Seed `core/source_registry.yaml` con le 10 categorie detector esistenti, ognuna validata contro la grammar 4-token
- Boot-time validation: `loop_targets == [] ⇔ RAW_ONLY` enforced
- Tests:
  - `tests/test_lineage_schemas.py` — Pydantic round-trip + naming grammar
  - `tests/test_source_resolver.py` — naming format, registry validation, lookup
  - `tests/test_state_machine.py` — every transition + every rejection
  - `tests/test_policy_gate.py` — hard gate enforcement (boot + promotion-time)
  - `tests/test_raw_manifest.py` — register, emit_event, latest_status (via view query mock), dedup
  - `tests/test_intake.py` — register, dedup by content_hash, RAW_INGESTED event
  - `tests/test_promotion.py` — happy path, RAW_ONLY rejection, validation failure, write failure
- New CLI subcommands `hotelops intake`, `hotelops promote`, `hotelops lineage`
- **Verification**: full `pytest` green (existing 33 test files + ~7 new). Conteggio test pre-refactor invariato.
- **Rollback**: revert the branch. No production tables modified in old flow.

### Phase 2 — Shadow mode (opt-in, ~3 days)

**Goal**: dual-emit lineage events from `cmd_drop` without changing canonical write path.

- Add `--lineage` flag to `cmd_drop` (default: off)
- When `--lineage` is set: `cmd_drop` calls `intake.register()` after `route_file` (raw blob = routed datahub file's content_hash)
- Continues to call `run_ingest` as today
- Lineage events emitted **best-effort** (failure to write to lineage tables non blocca il flow vecchio; warning loggato)
- **Verification**: comparing `f_raw_objects` rows vs `drops.jsonl` rows over a 1-week shadow run (parity script)
- **Rollback**: drop the flag. No table truncation needed.

### Phase 3 — Cutover (~3 days)

**Goal**: `hotelops drop` becomes a thin wrapper around `intake + promote`.

- `cmd_drop` defaults to `--lineage`
- `cmd_drop` delegates: `intake → promotion(auto)` for sources with `promotion_policy=AUTO`
- Old code in `classify.run_ingest` becomes deprecated path (kept for `cmd_classifica` and orchestrate)
- `drops.jsonl` continues to be written for human eyeball; lineage tables become the SSOT
- **Verification**: ingest a known file, check `f_*` row count + `f_lineage_events` chain == expected
- **Rollback**: feature flag or git revert. `f_raw_objects` retains history.

### Phase 4 — GCS as Raw Layer (separate spec)

**Goal**: replace `raw_backend=drive` with `raw_backend=gcs` for all sources.

- New module `core/lineage/gcs_raw_store.py` with Object Versioning + Autoclass terminal=ARCHIVE
- `intake.py` writes blob to `gs://hotelops-raw/...` instead of routing to Drive
- `source_registry.raw_storage.backend` flips to `gcs` per-source as loops migrate
- ADR `vault/decisions/2026-05-02_GCS_as_Raw_Layer.md` (TBD) is the prerequisite
- **Out of scope of this spec** — referenced for context.

### Rollback safety per phase

| Phase | What lives in BQ | What lives on disk | Rollback action |
|---|---|---|---|
| 1 | new tables + view (sparsely populated by tests + manual entrypoints) | new modules | revert branch |
| 2 | new tables populated in parallel via shadow flag | dual-write | drop `--lineage` flag |
| 3 | new tables = SSOT | unified | requires data migration to roll back to phase 2 |
| 4 | GCS bucket holds raw blobs | — | revert raw_backend in source_registry |

**Phase 3 is the irreversible one**. Phases 1+2 are zero-risk.

## 9. Phased implementation outline (no code, just shape)

**Phase 1 (this spec) — task summary**:

| # | Task | Files | TDD checkpoint |
|---|---|---|---|
| 1 | Pydantic schemas | `core/lineage/schemas.py` + test | round-trip + enum coverage + naming grammar regex |
| 2 | Source registry yaml + loader | `core/source_registry.yaml`, `core/lineage/source_resolver.py` + test | naming format, invariants, lookup, GROUP societa |
| 3 | State machine | `core/lineage/state_machine.py` + test | every transition + every rejection (pure functions) |
| 4 | Policy gate | `core/lineage/policy_gate.py` + test | hard gate firing (boot inconsistency + promotion RAW_ONLY) |
| 5 | BQ DDL loader + view | `core/bq/load/load_lineage_tables.py`, `core/bq/views/v_raw_objects_current.sql` | dry-run create, idempotent |
| 6 | Raw manifest store | `core/lineage/raw_manifest.py` + test | register (via gate), emit_event (via gate), latest_status (via view), dedup |
| 7 | Intake entrypoint | `ingest/intake.py` + test | end-to-end: file → raw_object + RAW_INGESTED event |
| 8 | Promotion entrypoint | `ingest/promotion.py` + test | happy path + 4 rejection paths |
| 9 | CLI subcommands | `cli.py` (additive only) | `hotelops intake/promote/lineage --help` smoke tests + wiring |
| 10 | Documentation update | `CLAUDE.md` (add §Lineage), `docs/architecture/DATA_ENGINEERING_RULES.md` (link this spec) | docstring/import sanity |

Plan TDD dettagliato (un file per task, step-by-step) → da generare via skill `writing-plans` quando Stefano dà OK alla spec.

**Phase 2 + 3 + 4** → spec separate quando arriva il momento.

## 10. Relationship to prior spec `2026-04-02-manifest-shadow-os-design.md`

Quel spec è in parking lot per "manifest/shadow OS" (vedi STATUS.md "Decisioni aperte"). Nel commit di Phase 1, aggiungere nota in cima a `2026-04-02-manifest-shadow-os-design.md`:

> **SUPERSEDED by `2026-05-05-ingest-lineage-gcs-design.md`** — il modello dati è stato semplificato (append-only via gate), il name "manifest" è stato disambiguato (catalog vs lineage), e il scope è ora chiaramente Phase-driven.

## 11. Anti-goals (Phase 1)

Cose che esplicitamente **non** facciamo in Phase 1:

- ❌ Modificare `core/registry.yaml` (resta il registry detector + dest_folder + bq_table + pipeline come oggi)
- ❌ Modificare `ingest/classify.py` (zero diff)
- ❌ Modificare `ingest/orchestrate.py` (zero diff)
- ❌ Modificare i parser in `ingest/banca/` o `ingest/flussi/`
- ❌ Cambiare il default behavior di `hotelops drop` o `hotelops classifica`
- ❌ Touch GCS (rimandato a Phase 4)
- ❌ Rinominare `core/bq/manifest.py` (Q1 chiusa = stay put)
- ❌ Inventare entità nuove nel vault `ontology/` (questa spec è puramente tecnica)
- ❌ Backfill di `f_raw_objects` con dati storici da `drops.jsonl` (parking lot, valutare in Phase 3)
- ❌ Shadow mode in `cmd_drop` (Q3 chiusa = no Phase 1, opt-in in Phase 2)
- ❌ MERGE/UPDATE/DELETE su `f_raw_objects` o `f_lineage_events` (append-only, I1 strict)

## 12. Decisioni (chiuse + ancora aperte)

### Chiuse in spec v2

| ID | Decision | Risoluzione |
|---|---|---|
| Q1 | Collisione `core/bq/manifest.py` | **Opzione A**: lineage in `core/lineage/raw_manifest.py`. `core/bq/manifest.py` resta catalogo BQ. Niente rename. |
| Q2 | `f_raw_objects` UPDATE-in-place vs append-only | **Append-only, write-once at intake**. Status corrente derivato da `f_lineage_events` via `v_raw_objects_current`. Risolve I1 sui MERGE. |
| Q3 | Phase 2 shadow mode su `cmd_drop`? | **NO in Phase 1**. Lineage events solo dai nuovi entrypoint. Shadow mode è un'opt-in di Phase 2 (best-effort emit). |
| Q4 | Naming `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>` ammette 5° token per BU? | **NO**. Strict 4 parts. BU vive in field separato. Source resolver fail-closed sul formato. |
| Q5 | Naming per cross-società? | **`SOCIETA=GROUP`** quando una source non è bound a ORTI/INTUR. |

### Ancora aperte (richiedono OK Stefano prima del relevant phase)

| ID | Decision | Default | Quando va chiusa |
|---|---|---|---|
| Q6 | Le 3 pipeline esistenti che già usano `bq_write_validated` (scheda, partite, coperti) come si interfacciano con la promotion in Phase 3? Wrapper trasparente o ricodifica via `promotion.py`? | TBD (Phase 3 design) | prima di Phase 3 task list |
| Q7 | Naming canonico per "fonti di prima parte" tipo `Master_Completo_*.xlsx` (Romita/Gasparotto): `system=ESOLVER` (perché i dati nascono lì) o `system=ROMITA` (perché il file lo cura lui)? | `ESOLVER` (la fonte primaria è l'ERP) | prima di Phase 1 task 2 (seed registry) |

## 13. Verification criteria (definition of done — Phase 1)

- [ ] Tutti i test esistenti verdi: `pytest` exit 0, **conteggio test pre-refactor invariato** (33 file → 33+7 nuovi)
- [ ] Nuovi test verdi: ~30 test cases sui nuovi moduli, copertura ≥ 90% del nuovo codice
- [ ] `core/source_registry.yaml` boot-validation:
  - [ ] import del modulo `source_resolver` con un registry "broken" (es. `loop_targets=[]` + `promotion_policy=AUTO`) deve fallire con `PolicyViolation`
  - [ ] import con un `source_name` che non rispetta la grammar 4-token deve fallire con `InvalidSourceName`
- [ ] `f_raw_objects` + `f_lineage_events` create on BQ produzione (dry-run prima, real second), DDL idempotente
- [ ] `v_raw_objects_current` create + spot-query funziona (vuota o con righe di test)
- [ ] `hotelops intake <file>` end-to-end: scrive raw_object row + RAW_INGESTED event tramite gate, ritorna `raw_object_id`
- [ ] `hotelops promote --raw-object-id X` end-to-end (su un source pilot AUTO): scrive su `f_*` + emette `PROMOTED` event, status finale visibile in `v_raw_objects_current`
- [ ] `hotelops promote --raw-object-id X` su source RAW_ONLY (es. `POWERBI_CRUSCOTTO_ORTI_APPEND`) → `REJECTED` + reason=`NO_LOOP_TARGET`, no canonical write
- [ ] `hotelops lineage <raw_object_id>` mostra: raw_object identity + tutti gli eventi ordinati per timestamp + current status
- [ ] `cmd_drop` esistente: stesso comportamento, stessi audit log su `drops.jsonl` (zero regression — `tests/test_drop_audit.py` invariato e verde)
- [ ] CLAUDE.md aggiornato con sezione Lineage (3-4 righe)
- [ ] DATA_ENGINEERING_RULES.md link a questa spec aggiunto in §10
- [ ] `2026-04-02-manifest-shadow-os-design.md` ha il banner SUPERSEDED

## 14. Out of scope of Phase 1 (parking lot)

- GCS object versioning + autoclass per il raw layer
- Migrazione delle 10 detector categories esistenti dentro `source_registry.yaml` come SSOT (Phase 1 le seed-a, Phase 2 fa lo switch)
- Unificazione `ingest.orchestrate.PIPELINES` con `source_registry.parser_module` (Phase 2)
- Backfill di `f_raw_objects` da `drops.jsonl` storico
- View `v_lineage_health` con drift detection (freshness, stuck-in-CLASSIFIED, ecc.)
- ADR formale `vault/decisions/2026-05-05_Lineage_Layer.md` (post-merge Phase 1)
- Wrapper di compatibilità per le 3 pipeline `bq_write_validated`-native (Q6 → Phase 3)

---

## Appendice A — naming examples (post-grammar fix)

Tutti i nomi rispettano la grammar 4-token: `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`, ogni token `[A-Z][A-Z0-9]*`.

| File reale | source_name | societa (field) | business_unit (row) | lifecycle |
|---|---|---|---|---|
| `Master_Completo_ORTI_20260430.xlsx` | `ESOLVER_BUDGET_ORTI_SNAPSHOT` | ORTI | (n/a) | SNAPSHOT |
| `ORTI_LISTAMOVCONT.XLS` | `ESOLVER_MOVIMENTI_ORTI_APPEND` | ORTI | (n/a) | APPEND |
| `INTUR_MPS_20260420.xlsx` | `MPS_BANCA_INTUR_APPEND` | INTUR | (n/a) | APPEND |
| `INTUR_PARTITE_FORNITORI_20260415.xlsx` | `ESOLVER_PARTITE_INTUR_SNAPSHOT` | INTUR | (n/a) | SNAPSHOT |
| `H_HotelOps_Corrispettivi.txt` | `HOTELCUBE_ACCODAMENTI_ORTI_APPEND` | ORTI | HOTEL (per-file) | APPEND |
| `R_HotelOps_Corrispettivi.txt` | `HOTELCUBE_ACCODAMENTI_ORTI_APPEND` (stesso source!) | ORTI | RESIDENCE (per-file) | APPEND |
| `Cruscotto_HOTEL_2026-04-15.pdf` | `POWERBI_CRUSCOTTO_ORTI_APPEND` (RAW_ONLY) | ORTI | HOTEL (per-file) | APPEND |
| `MASTER_GASPAROTTO_20260430.xlsx` | `ESOLVER_BUDGET_GROUP_SNAPSHOT` (se cross-società) | GROUP | (n/a) | SNAPSHOT |

Nota: file dello stesso source con BU diverse condividono il `source_name`. La distinzione vive in `f_raw_objects.business_unit_id` (popolato dal detector) e si propaga al canonical write via parser. Q7 (chi è "system" per i Master di Romita) resta aperta — il default `ESOLVER` riflette la fonte primaria dei dati, non l'autore del foglio.

## Appendice B — files touched in Phase 1

```
A   core/source_registry.yaml
A   core/lineage/__init__.py
A   core/lineage/schemas.py
A   core/lineage/source_resolver.py
A   core/lineage/state_machine.py
A   core/lineage/raw_manifest.py
A   core/lineage/policy_gate.py
A   core/bq/load/load_lineage_tables.py
A   core/bq/views/v_raw_objects_current.sql
A   ingest/intake.py
A   ingest/promotion.py
A   tests/test_lineage_schemas.py
A   tests/test_source_resolver.py
A   tests/test_state_machine.py
A   tests/test_policy_gate.py
A   tests/test_raw_manifest.py
A   tests/test_intake.py
A   tests/test_promotion.py
M   cli.py                                                       (additive: 3 new subparsers + handlers)
M   CLAUDE.md                                                    (additive: §Lineage, ~10 lines)
M   docs/architecture/DATA_ENGINEERING_RULES.md                  (additive: §10 link to this spec)
M   STATUS.md                                                    (additive: in-corso entry for Phase 1)
M   docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md   (banner SUPERSEDED)
A   docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md   (this file)
```

Total: **18 new files, 5 modified files. Zero deleted, zero moved.**
