# GCS as Raw Staging — Phase 4 Design

**Date:** 2026-05-05
**Branch:** `refactor/gcs-raw-staging` (to be created)
**Supersedes / extends:** `2026-05-05-ingest-lineage-gcs-design.md` (Phase 1)
**Related:** `docs/DATAHUB_ONTOLOGY.md` (target architecture)

---

## 1. Context

Phase 1 (`refactor/ingest-lineage-gcs`) shipped the lineage control plane on
BigQuery: `f_raw_objects`, `f_lineage_events`, `v_raw_objects_current`, state
machine, naming grammar, hard gate, intake/promote/lineage CLI, Phase 2 shadow
mode on `drop`. The implementation deliberately left blob storage on **local
disk** (`raw_uri = file:///...`), with `raw_backend` parameter wired but only
`"local"` exercised.

`docs/DATAHUB_ONTOLOGY.md` (committed `52fa51e`) declares **GCS as the Raw
layer**. There is currently a doc-vs-implementation drift: the doc says
`gs://hotelops-raw`, the code writes `file://`. This spec closes that gap.

### Why now

The loop-driven principle (vault, 2026-05-02) said *"no GCS refactor until a
loop demands it."* That principle correctly governs **scope of ingestion**
(which files we capture). It is the wrong governance for **staging
infrastructure** that the documentation already claims as fact. Closing the
drift earns:

- doc credibility (DATAHUB_ONTOLOGY stops lying)
- immutable raw history (Object Versioning) replacing fragile local files
- substrate for Phase 5 cutover (drop → intake+promote, GCS-native)

---

## 2. Scope

### In scope
1. GCS bucket `gs://hotelops-raw` provisioned (Object Versioning + Autoclass)
2. New module `core/lineage/raw_storage.py` with `RawStorageBackend` ABC and
   two implementations: `LocalBackend` (no-op, returns `file://` URI) and
   `GCSBackend` (uploads, returns `gs://` URI + generation)
3. `intake_file` selects backend via `source_def.raw_storage.backend`
4. Schema migration: add nullable `gcs_generation INT64` to `f_raw_objects`
5. `_invoke_parser` (promotion.py) supports `gs://` URIs by downloading to
   temp file before subprocess dispatch
6. Pilot one source flipped to `backend: gcs` (`ESOLVER_PARTITE_ORTI_SNAPSHOT`)
7. Smoke test: real intake of a partite_aperte file → GCS object exists +
   `f_raw_objects` row carries `gs://` URI + `gcs_generation` populated
8. `hotelops lineage` displays GCS URI + generation correctly

### Out of scope (explicit)
- Backfill of existing `file://` raw_objects to GCS
- Bulk flip of remaining 12 sources (only pilot here; bulk after validation)
- Replacement of Drive datahub for human workspace use
- Change to `cmd_drop` legacy flow (still local-file input)
- Resumable upload for files >5GB (none currently exceed)
- GCS lifecycle rules beyond Autoclass terminal=ARCHIVE
- IAM / service-account hardening (uses existing ADC stefano@panoramagroup.it)
- Phase 5 cutover (drop = intake+promote)

---

## 3. Decisions locked

### D1 — Bucket configuration
- **Name:** `hotelops-raw`
- **Project:** `hotelops-suite`
- **Location:** `EU` (multi-region, matches BQ dataset locality)
- **Storage class default:** `STANDARD` with **Autoclass enabled**, terminal
  class `ARCHIVE` (Stefano's 2026-05-02 decision)
- **Object Versioning:** **ON** (immutability requirement; non-current versions
  retained indefinitely until lifecycle rule explicitly deletes them — none
  in this scope)
- **Public access prevention:** `enforced`
- **Uniform bucket-level access:** `enforced` (no per-object ACLs)
- **Encryption:** Google-managed (default; CMEK out of scope)

### D2 — Object key structure (chosen: path-mirroring + filename)

**Format:** `<source_name>/<intake_yyyy>/<intake_mm>/<original_filename>`

Example: `ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/situazione_partite_2026-05-05.xlsx`

Rationale:
- **Human-readable** in GCS console — operators can browse like a folder tree
- **`source_name` prefix** = strong namespace, prevents cross-source collision
- **Year/month partition** = bounded directory size, keeps listing fast,
  matches BQ partitioning intuition
- **Original filename** preserved → downloaded copies are recognizable
- **Object Versioning handles dedup**: re-uploading the same key with
  different content creates a new generation; same content (same bytes) creates
  a generation but `register_raw_object` MD5 dedup short-circuits **before**
  upload (see §6 idempotency)

**Rejected alternatives:**
- `<sha256[:2]>/<sha256>/<filename>` (content-addressed): better dedup but
  unbrowsable. We already MD5-dedup at the BQ layer; GCS readability matters
  more than GCS-layer dedup.
- `<source.path_template>/<filename>` (mirror Drive paths): tempting for
  parity but couples GCS layout to Drive folder structure that may change.

### D3 — `raw_uri` format
- **Stored value:** `gs://hotelops-raw/<key>` (no fragment, no query string)
- **`gcs_generation`:** stored in **separate column** on `f_raw_objects`
- **Why separate column:** SQL filtering by generation, lineage queries by
  bucket/key, future migration to a different bucket with same keys
- A row's full identity = `(raw_uri, gcs_generation)`. Without generation,
  the URI alone is mutable (Object Versioning is by design).

### D4 — Backend selector is per-source
- `source_def.raw_storage.backend` already in YAML schema (`drive` today)
- Adding `gcs` as third value (alongside `drive`, `local`)
- `LocalBackend` handles both `local` and `drive` (both = "file is at this
  path on disk, register URI as `file://`")
- `GCSBackend` handles `gcs`
- Unknown backend → boot-time validation error in `load_registry`

### D5 — Schema change: nullable `gcs_generation INT64`
- **Migration:** ALTER TABLE ADD COLUMN (BQ-native, non-breaking, default NULL)
- Existing rows: NULL (not backfilled)
- New rows from `LocalBackend`: NULL
- New rows from `GCSBackend`: populated with the upload's generation

### D6 — Parser invocation supports `gs://`
- `_invoke_parser` in `ingest/promotion.py` currently raises
  `NotImplementedError` on non-`file://` schemes
- Replace with: detect scheme, if `gs://` download to NamedTemporaryFile via
  `GCSBackend.download_to_path(uri, generation, dest)`, pass local path to
  parser as today, cleanup temp file in `finally`
- Parsers themselves are **not modified** (they receive a local path as
  before). This preserves the additive-only contract from Phase 1.

### D7 — Auth via ADC (Application Default Credentials)
- `google-cloud-storage` SDK uses same ADC chain as existing
  `google-cloud-bigquery` client
- Stefano's `gcloud` already authenticated as `stefano@panoramagroup.it`
- IAM: account needs `Storage Object Admin` on `hotelops-raw` (manual grant)
- No service account / key file in this scope

### D8 — Idempotency contract
- **Before GCS upload:** `intake_file` computes MD5 of local file, calls
  `register_raw_object` which short-circuits on existing `content_hash`. If
  hit → no GCS upload, return existing `raw_object_id`
- **GCS-side idempotency:** if upload races (two concurrent intakes of new
  file), Object Versioning creates two generations. The first
  `register_raw_object` to commit wins (gets the `raw_object_id`); the second
  hits BQ dedup and returns the same id. The orphan generation in GCS is
  harmless (immutable history is the point).
- **No cleanup of orphan generations** in this scope

### D9 — Pilot source: `ESOLVER_PARTITE_ORTI_SNAPSHOT`
Why:
- Already exercised in Phase 2 shadow mode demo (proven path through `drop --lineage`)
- SNAPSHOT lifecycle = small, recurring, low-volume (low risk)
- Real production file available for smoke test
- If pilot succeeds → bulk flip in a separate PR (out of scope here)

---

## 4. Architecture

### Module layout

```
core/lineage/
  raw_storage.py          # NEW: ABC + LocalBackend + GCSBackend
  raw_manifest.py         # MODIFIED: register_raw_object accepts gcs_generation
  schemas.py              # MODIFIED: RawObject.gcs_generation: Optional[int]
  source_resolver.py      # MODIFIED: validate backend ∈ {drive, local, gcs}

ingest/
  intake.py               # MODIFIED: backend selection + upload before register
  promotion.py            # MODIFIED: _invoke_parser handles gs:// via download

core/bq/load/
  load_lineage_tables.py  # MODIFIED: DDL adds gcs_generation column
  migrate_add_gcs_generation.py  # NEW: one-shot migration script

scripts/
  provision_gcs_bucket.sh # NEW: idempotent bucket creation
```

### Sequence — intake with GCS backend

```
hotelops intake file.xlsx --source-name ESOLVER_PARTITE_ORTI_SNAPSHOT
  │
  ├─► intake_file()
  │     ├─► compute MD5
  │     ├─► resolve source_def from registry
  │     │     └─► source_def.raw_storage.backend == "gcs"
  │     ├─► [BQ] _lookup_existing_by_hash(md5)
  │     │     ├─► hit  → return existing raw_object_id (NO upload, NO event)
  │     │     └─► miss → continue
  │     ├─► backend = GCSBackend(bucket="hotelops-raw")
  │     ├─► key = backend.compute_key(source_name, intake_at, filename)
  │     │       = "ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/situazione_partite.xlsx"
  │     ├─► [GCS] backend.upload(local_path, key) → (gs_uri, generation)
  │     ├─► [BQ] register_raw_object(
  │     │         raw_uri=gs_uri,
  │     │         raw_backend="gcs",
  │     │         gcs_generation=generation,
  │     │         ...)
  │     └─► [BQ] emit_event(RAW_INGESTED, to_status=RAW_ONLY)
  │
  └─► IntakeResult(raw_object_id, content_hash, ...)
```

### Sequence — promote with GCS-stored raw

```
hotelops promote --raw-object-id raw-uuid
  │
  ├─► promote_raw_object()
  │     ├─► [BQ] _fetch_raw_object → row.raw_uri = "gs://hotelops-raw/..."
  │     ├─► hard gate check
  │     ├─► emit_event(PROMOTION_REQUESTED)
  │     ├─► _invoke_parser(parser_module, raw_uri, source_def)
  │     │     ├─► detect scheme = "gs"
  │     │     ├─► [GCS] backend.download_to_temp(raw_uri, generation) → /tmp/xyz
  │     │     ├─► subprocess [parser_module, --file, /tmp/xyz, --societa, ORTI]
  │     │     └─► finally: os.unlink(/tmp/xyz)
  │     ├─► emit_event(VALIDATED_OK + PROMOTED)  on success
  │     └─► emit_event(VALIDATED_FAIL + REJECTED) on parser failure
```

---

## 5. Schema changes

### `f_raw_objects` — ALTER TABLE

```sql
ALTER TABLE `hotelops-suite.hotelops.f_raw_objects`
ADD COLUMN gcs_generation INT64 OPTIONS(description="GCS object generation when raw_backend='gcs'; NULL otherwise");
```

- Non-breaking: nullable column, existing rows = NULL
- No write-path change for existing pipelines (column is additive on Pydantic model)
- View `v_raw_objects_current` does not reference this column → no recreate needed

### `RawObject` Pydantic model

```python
class RawObject(BaseModel):
    # ... existing fields ...
    gcs_generation: Optional[int] = None
```

### `core/source_registry.yaml`

```yaml
ESOLVER_PARTITE_ORTI_SNAPSHOT:
  # ... unchanged ...
  raw_storage:
    backend: gcs                              # was: drive
    path_template: "partite_fornitori/ORTI"   # retained for Drive-side workspace
    bucket: hotelops-raw                       # NEW (only for backend=gcs)
```

(Other 12 sources stay `backend: drive` until bulk-flip PR.)

---

## 6. Boundaries (what changes / what doesn't)

### Changes
- New module `core/lineage/raw_storage.py`
- `intake_file` adds upload step when backend=gcs
- `_invoke_parser` adds download step when uri starts with `gs://`
- `f_raw_objects` gets one new nullable column
- Source registry pilot entry switches backend
- New deps: `google-cloud-storage>=2.14`

### Does NOT change
- Parser modules (`ingest/flussi/*`, `ingest/banca/*`)
- `bq_write_validated` gate
- State machine / event types / naming grammar
- `cmd_drop` legacy flow
- `cmd_drop --lineage` Phase 2 shadow mode (still local; flips to GCS only
  through source_def backend selection, transparently)
- Existing 12 non-pilot sources (still `drive`)
- Existing `file://` raw_objects (no migration)
- CLI surface (`intake/promote/lineage` unchanged signatures)
- Tests for Phase 1 / Phase 2 (must remain green)

---

## 7. Migration / cutover plan

### Step 0 — Branch + bucket
- `git checkout -b refactor/gcs-raw-staging`
- Run `scripts/provision_gcs_bucket.sh` (idempotent gsutil/gcloud commands)
- Verify: `gsutil ls -L -b gs://hotelops-raw` shows Versioning: Enabled, Autoclass terminal=ARCHIVE

### Step 1-7 — TDD implementation
(Detailed in plan doc; not duplicated here.)

### Step 8 — Pilot smoke test
- Take a real `situazione_partite_*.xlsx` file
- `hotelops intake <file> --source-name ESOLVER_PARTITE_ORTI_SNAPSHOT --actor smoke_test`
- Verify:
  - `gsutil ls gs://hotelops-raw/ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/` shows the object
  - `bq query "SELECT raw_uri, raw_backend, gcs_generation FROM hotelops.f_raw_objects WHERE intake_actor='smoke_test'"` shows `gs://...` URI and non-null generation
  - `hotelops lineage <raw_object_id>` displays correctly
- Optional: `hotelops promote --raw-object-id <id>` → confirm parser ran from temp download

### Step 9 — PR + merge

### Out of scope (separate PR after validation)
- Bulk flip of remaining 12 sources to `backend: gcs`
- Backfill historical raw_objects to GCS
- Drive datahub deprecation

---

## 8. Acceptance criteria

A reviewer agrees the spec is satisfied iff:

1. ✅ `gs://hotelops-raw` exists with Versioning ON + Autoclass terminal=ARCHIVE
2. ✅ `f_raw_objects` has `gcs_generation INT64 NULLABLE` column
3. ✅ `core/lineage/raw_storage.py` defines `RawStorageBackend` ABC with two
   implementations, fully unit-tested (mock `google.cloud.storage.Client`)
4. ✅ `intake_file` invokes `GCSBackend.upload` only when source backend=gcs;
   `LocalBackend` path produces identical behavior to today (regression-safe)
5. ✅ `_invoke_parser` downloads `gs://` URIs to temp + cleans up; `file://`
   path unchanged
6. ✅ Source registry has `ESOLVER_PARTITE_ORTI_SNAPSHOT.raw_storage.backend
   = gcs`; `load_registry` accepts it; other 12 unchanged
7. ✅ All Phase 1+2 tests still pass (no regression)
8. ✅ Smoke test produces a real GCS object + a real BQ row referencing it
   with non-null generation
9. ✅ `DATAHUB_ONTOLOGY.md` updated: section §10 acknowledges Phase 4 lands
   GCS for the pilot source, with cutover for remaining sources tracked in
   STATUS.md

---

## 9. Open questions (need Stefano's call before writing the plan)

### Q1 — Object key format
Proposed: `<source_name>/<YYYY>/<MM>/<original_filename>` (D2).
**Alternative:** mirror Drive `path_template` exactly
(`partite_fornitori/ORTI/<filename>`).
**Recommendation:** stick with proposal (decoupled from Drive).
**Need answer:** confirm or override.

### Q2 — Pilot source
Proposed: `ESOLVER_PARTITE_ORTI_SNAPSHOT` (D9).
**Alternative:** any other source you'd prefer to flip first.
**Recommendation:** stick with proposal (already exercised in Phase 2).
**Need answer:** confirm or override.

### Q3 — Bucket lifecycle
Proposed: Autoclass terminal=ARCHIVE, no explicit deletion rule, no
non-current version expiration (versions retained forever).
**Alternative:** add lifecycle rule to delete non-current versions after N
days (saves storage if many uploads).
**Recommendation:** no expiration. Object Versioning's value is forensic
audit; stripping old versions defeats it. Storage cost negligible (Autoclass
sends to ARCHIVE).
**Need answer:** confirm or specify retention.

### Q4 — `intake_file` behavior when `--source-name` is omitted
Phase 1 behavior: register as RAW_ONLY without source binding, `raw_backend`
defaults to `"local"` (file:// URI).
Question: with GCS as substrate, should sourceless intakes also go to GCS?
**Proposal:** NO. Sourceless intake = exploratory / unclassified. Keep on
local until classified. Re-intake after `--source-name` is known.
**Alternative:** YES, upload to `gs://hotelops-raw/_unclassified/<sha256>/<filename>`.
**Recommendation:** stick with proposal (NO). Simpler, no orphan-key cleanup.
**Need answer:** confirm or override.

### Q5 — Failure mode: GCS upload succeeds, BQ write fails
Proposal: orphan GCS object remains. Retry of `intake_file` will MD5-dedup
hit only if BQ row exists → second upload happens, second generation created,
first orphan stays. In practice rare (BQ writes are reliable); if it
becomes a problem, add a sweep job.
**Alternative:** wrap upload+write in a sentinel marker (unnecessary
complexity Phase 4).
**Recommendation:** accept orphan risk in scope.
**Need answer:** confirm or escalate.

---

## 10. Effort estimate

| Step | Effort |
|---|---|
| Bucket provisioning script + actual creation | 30 min |
| `raw_storage.py` (ABC + LocalBackend + GCSBackend) + tests | 4 h |
| Schema migration (DDL + Pydantic + test) | 1.5 h |
| `intake_file` backend selector + tests | 2 h |
| `_invoke_parser` gs:// support + tests | 2 h |
| Source registry pilot flip + boot test | 30 min |
| Smoke test (real production file) | 1 h |
| Doc update (`DATAHUB_ONTOLOGY.md`, STATUS.md) | 30 min |
| **Total** | **~12 h** (1.5 working days) |

Matches initial estimate.
