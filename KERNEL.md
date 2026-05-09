# KERNEL — verticals-v2 branch

**Status:** `verticals-v2` rebirth, 2026-05-09. See `.cursor/plans/platform-canonical-boundary_bd5044c3.plan.md` for the full plan.

## Cosa sopravvive (non si tocca)

### Lineage layer (Phase 1-4)

- `core/lineage/__init__.py`
- `core/lineage/schemas.py`
- `core/lineage/source_resolver.py`
- `core/lineage/state_machine.py`
- `core/lineage/policy_gate.py`
- `core/lineage/raw_manifest.py`
- `core/lineage/raw_storage.py`

### Write gate I1

- `core/bq/write.py` (bq_write_validated — Pydantic + serializzazione probe + lineage automatica)
- `core/bq/client.py` (singleton get_client)
- `core/bq/dedup.py` (filter_new_rows_by_hash)
- `core/contracts.py` (SchemaViolationError, validate_columns)
- `core/pipeline_run.py` (PipelineRun ContextVar)

### Dimensioni canoniche

- `core/bq/dimensioni/*.csv` — ground truth umano del dominio
- `core/bq/load/*.py` — loader per ogni CSV (8+ scripts)

### Schemas Pydantic kernel-only

In `core/schemas.py` SOPRAVVIVONO solo i model che corrispondono a fact/dim del kernel o di reviews:

- `BancaMovimentoRow` — kernel banca
- `MovimentoContabileRow` — kernel ERP
- `SaldoBancaSnapshotRow`, `SaldoBancaChiusuraMensileRow` — kernel banca
- `PartitaApertaFornitoreRow` — kernel fornitori
- `PmsStatisticheRow` — kernel PMS
- `CopertoGiornalieroRow` — kernel coperti
- `VenditaFbRow` — kernel vendite
- `ReviewRow`, `ApifyRunRow` — reviews vertical
- `PipelineRunRow` — telemetry kernel
- `AnagraficaFornitoreRow` — dim
- `MappingPianoFinanziarioRow`, `CoefficienteStagionalitaRow` — dim
- `BudgetMensileRow`, `PianoFinanziarioInputRow`, `RicaviStoriciRow`, `CoefficienteConsumoRow` — TBD per-vertical (decidere durante CONDGES/ECONOMATO design)

ELIMINATI:
- `ChiusuraMensileRow` (schema orfano, tabella NOT FOUND in BQ — se serve, ricreato con CONDGES)
- Schemas di domain models progetto (se non parte del kernel kernel) — TBD

### BQ tables sopravvissute (canonical kept)

Restano le canonical che il kernel popola direttamente:

- `f_raw_objects` (lineage)
- `f_lineage_events` (lineage)
- `f_pipeline_runs` (telemetry)

Tutte le altre fact tables sono **ridichiarate dai verticali** (anche se l'ALTER TABLE non viene eseguito immediatamente — DDL drop avviene in Phase E nuke prep).

### Views BQ kernel

- `v_raw_objects_current`
- `v_raw_promotion_status`

Tutte le altre view (21 totali) → eliminate o ridisegnate per-vertical.

### CLI kernel

- `hotelops intake`
- `hotelops promote`
- `hotelops lineage`

Tutti gli altri comandi (pf, bva, chiudi, saldo, health, voci, previsione, manifest, classifica, accodamenti, reviews, app) → ridichiarati dai verticali.

### Reviews vertical (preserved as-is)

**Non si tocca.** Funziona, ha audience, lascia stare.

- `reviews/*` (tutti i 10 file)
- `f_reviews`, `f_apify_runs` (BQ tables)
- Source Apify (registrazione lineage in Phase 2 reviews, fuori scope verticals-v2)

### Migrations storiche

- `core/bq/migrations/*` — già applicate, regression-tested

### Tests kernel

Sopravvivono i test che coprono il kernel:

- `tests/test_lineage_*.py`, `tests/test_state_machine.py`, `tests/test_policy_gate.py`, `tests/test_source_*.py`, `tests/test_intake*.py`, `tests/test_promote*.py`, `tests/test_promotion.py`, `tests/test_raw_*.py`, `tests/test_v_raw_promotion_status.py`, `tests/test_load_lineage_tables.py`
- `tests/test_bq_write.py`, `tests/test_bq_dedup.py`, `tests/test_contracts.py`
- `tests/test_pipeline_run.py`
- `tests/test_schemas.py` (filtrato sui model kernel)
- `tests/test_reviews_*.py` (tutti)
- `tests/test_classify.py` (parzialmente — la parte detector signature kernel sopravvive)
- `tests/conftest.py`

ELIMINATI o RIVISTI (vertical re-design):
- `tests/test_drop_*.py` → cancellati post Phase 5 cutover
- `tests/test_ingest_*.py` (movimenti, gasparotto, vendite_fb, banca_single_file, accodamenti_parser) → riscritti durante design vertical corrispondente
- `tests/test_cdg_engine.py`, `tests/test_cashflow.py`, `tests/test_parse_pf.py`, `tests/test_scadenzario.py`, `tests/test_cassa_giornaliera.py`, `tests/test_budget_orti_xlsx.py` → riscritti durante CONDGES design
- `tests/test_progetti_schema.py` → fuori scope verticals-v2
- `tests/test_health_checks.py` → kernel kernel? TBD
- `tests/test_manifest.py` → riscritto se manifest sopravvive
- `tests/test_materialize.py` → riscritto se materialize sopravvive
- `tests/test_stagionalita.py` → kernel kernel? TBD
- `tests/test_drop_audit.py`, `tests/test_drop_shadow.py` → cancellati con Phase 5 cutover
- `tests/test_saldi_banca_chiusura.py` → riscritto con CONDGES
- `tests/test_migration_add_gcs_generation.py` → kernel (regression migration), kept

---

## Cosa muore (rimosso a step successivi)

### Codice operativo (ridichiarato dai verticali)

- `condges/*` — 21 file → ricostruito in 1 vertical CONDGES coerente
- `ingest/banca/ingest.py`, `ingest/banca/ingest_accodamenti.py`, `ingest/banca/fetch_drive.py` → ridichiarati per CONDGES + ROOM DIVISION
- `ingest/flussi/*.py` — 8 pipeline → ridichiarati nei verticali corrispondenti
- `ingest/orchestrate.py` → riscritto come domain-aware orchestrator
- `ingest/classify.py` → kept partially (detector signatures sopravvivono nel kernel; routing path-of-old va ridisegnato)

### Source registry duplicato

- `core/registry.yaml` (file detector + pipeline mapping) → **merge in `core/source_registry.yaml`** (1 sola verità per source policy + lineage + detector)

### View BQ legacy

19 view su 21 vanno eliminate. Sopravvivono solo `v_raw_objects_current`, `v_raw_promotion_status`.

Le view contract-grade dei vecchi verticali (`v_budget_canonical`, `v_piano_finanziario_*`, `v_economato_*`, `v_food_cost_*`) **sono ground truth del dominio** ma vengono **ridisegnate per-vertical**, non importate as-is.

### Apps frammentate

- `condges/app_cdg.py`, `condges/app_scadenzario.py`, `condges/app_accodamenti.py` → 1 sola Streamlit multi-page CONDGES.

### CLI legacy

- `cmd_drop`, shadow path → cancellati con Phase 5 cutover.

### Documentazione superata

- `CLAUDE.md` → riscritto durante CONDGES Phase A (le sezioni current sono accurate per main, non per verticals-v2).
- `STATUS.md` → riusato, ma "in corso" e "completato di recente" vanno azzerati al cutover.
- `README.md` → riscritto sopra l'architettura nuova (oggi vuoto, attende verticals-v2 stable).

---

## Regola operativa

1. **Qualunque commit su `verticals-v2` che rimuove file deve citare questo `KERNEL.md`** nel commit message (es. `refactor(condges): remove legacy condges/ folder per KERNEL.md`).
2. **Modifiche al kernel sono `kernel(...)` scope** e richiedono giustificazione esplicita nel commit body.
3. **Reviews vertical è zona protetta**: zero diff vs main su `reviews/*`.
4. Quando un vertical viene completato, aggiornare la sezione corrispondente di questo file con: data, lista file aggiunti, lista canonical owned, audience.
