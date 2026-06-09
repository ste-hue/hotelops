# Cash/PF Engine Consolidation — design spec (Metà A)

**Date:** 2026-06-09 · **Status:** design (awaiting review) · **Slice:** cash/PF surface consolidation

## Scope

Consolidare la logica cash/PF (lettura proiezione + previsione + budget) dietro **un solo
service/engine**, così che le surface (Streamlit, CLI, skill) diventino gusci sottili che lo
chiamano. `pf_rotate` demoto a **render/export adapter**. **BQ resta authority.** Tutte le
scritture passano per **un solo write-path: il gate I1 `bq_write_validated`**.

**Esplicitamente fuori da questa slice (Metà B, next increment — NON requisito qui):**
nessuna memory table nuova; niente `f_cash_projection_runs` / `f_decisioni` / evaluations;
niente collasso di `v_previsione_cassa`+scadenzario in `v_cash_projection_current`; niente P0
re-baseline. Decisioni Metà B già speccate in `[[2026-06-03_cash_control_v1_kernel_loop_grill]]`
— citate come incremento successivo, non toccate.

Obiettivo: **dimostrare "1 processo fatto bene" sul cash/PF** senza trascinare il kernel.

---

## 1. Mappa attuale: componenti → letture / calcoli / scritture

Stato verificato 2026-06-09 (`verticals/condges/`, ~9.000 righe).

| Componente | Legge | Calcola | Scrive | Note |
|---|---|---|---|---|
| `cdg_engine.py` | — | ✅ CE cascade, indicatori, proiezione (3 fn pure) | — | **Già engine puro.** Consumato solo da `app_cdg`. |
| `app_cdg.py` (1281) | 6 query BQ inline (`bq.query(...).to_dataframe()`, righe 90–202) | via `cdg_engine` | ❌ **`save_to_bq()` 458–504**: `bq.query(DELETE… f-string)` + `load_table_from_json` raw → `f_budget_mensile` fonte=APP_BUDGET | **Violazione**: surface scrive canonical, no validazione, no lineage, schema a mano, SQL f-string. |
| `update_previsione.py` | `get_valid_voci` | — | `validate_batch` + `load_table_from_json` raw (DELETE-INSERT parametrico) → `f_piano_finanziario_input` | **Half-gated**: valida ma **non** usa `bq_write_validated`, no lineage. |
| `cli_commands.py` (965) | query proprie | versione propria | DELETE+INSERT a `f_chiusura_mensile` (cmd_chiudi, 609–640) | Reimplementa lettura/scrittura, non condivide con Streamlit. |
| `genera_excel.py` / `export_excel.py` | `f_piano_finanziario_input` | — | (genera xlsx) | Render. |
| `pf_rotate/` (step0–5, `rotate.py`) | PF xlsx + saldi BQ | rotazione layout-aware | **xlsx out** (`RotateResult`) | Excel-in/Excel-out. Già modulare. Da ri-etichettare adapter. |

**Diagnosi:** la stessa operazione (fetch → compute → write su cash/PF) è reimplementata in
`app_cdg`, `cli_commands`, `update_previsione`. Il compute è già centralizzato (`cdg_engine`);
**mancano un data-access condiviso e un write-path unico**. Tre writer scrivono
`f_piano_finanziario_input`/`f_budget_mensile` con tre meccanismi diversi, nessuno via gate I1.

**Primitivi già pronti da riusare (verificati):**
- Gate I1: `core/bq/write.py:83` `bq_write_validated(table, rows: list[BaseModel], mode, natural_key)`.
  `mode="snapshot"` = DELETE+INSERT chirurgico per `natural_key` (esattamente il pattern previsione/budget).
- Modelli Pydantic: `BudgetMensileRow`, `PianoFinanziarioInputRow` (`core/schemas.py:39,74`).
- Config: `cfg.F_BUDGET_MENSILE`, `cfg.F_PIANO_FINANZIARIO_INPUT`.
- Lineage: il gate legge `PipelineRun.get_current()` (`core/pipeline_run.py:107`).

---

## 2. Target architecture: Surface → Service/Engine → Kernel/BQ

```
SURFACES (sottili — solo UI/IO + intent, MAI scrittura canonical)
  CLI:        hotelops previsione | pf | bva | chiudi | saldo
  Streamlit:  verticals/condges/app_cdg.py
  Skill:      (futuro — stesso service)
        │  emette Intent (dataclass)
        ▼
SERVICE / ENGINE  →  verticals/condges/services/cash_pf_service.py  (NEW)
  - read:    helper di accesso dati (consolidano le query oggi sparse)
  - compute: delega a cdg_engine (puro, invariato)
  - write:   SEMPRE via core.bq.write.bq_write_validated  (gate I1)
  - render:  invoca pf_rotate.rotate() come adapter (produce xlsx, NON possiede stato)
        │
        ▼
KERNEL / BQ
  bq_write_validated (mode="snapshot", natural_key=…)  →  f_piano_finanziario_input
                                                          f_budget_mensile
```

**Regole del confine:**
- Una surface **legge, mostra, raccoglie intent**. Non scrive canonical, non costruisce SQL,
  non definisce schema. (allinea `INFRASTRUCTURE_VS_LOOPS`)
- Il service **non** importa Streamlit né `argparse`. Riceve Intent tipizzati, ritorna Result.
- L'unico modo di scrivere su BQ nel cash/PF è `bq_write_validated`. Zero `load_table_from_json`
  o `bq.query(DELETE/INSERT)` fuori dal gate.
- `cdg_engine` resta puro e invariato (è già la metà giusta).
- `pf_rotate` resta intatto internamente; cambia solo **chi lo chiama** (il service) e la sua
  etichetta (render/export, non owner di stato).

---

## 3. Primo modulo service da creare

`verticals/condges/services/cash_pf_service.py` — partendo dal **write-path** (è la duplicazione
peggiore: 3 writer, ed è dove vive la violazione I1).

Interfaccia v1 (intent → result, sincrona, niente magia):

```python
# verticals/condges/services/intents.py
@dataclass(frozen=True)
class SaveBudgetIntent:
    societa_id: str
    anno: int
    righe: list[BudgetRigaInput]   # campi minimi: mese, codice_conto, descrizione,
    fonte: str = "APP_BUDGET"      # tipo_costo, categoria_ce, business_unit_id, importo

@dataclass(frozen=True)
class SavePrevisioneIntent:
    societa_id: str
    voce_id: str
    mesi: list[int]
    importo: float
    anno: int
    fonte: str = "NANOCLAW"

@dataclass(frozen=True)
class SaveResult:
    table: str
    rows_written: int
    natural_key: list[str]
```

```python
# verticals/condges/services/cash_pf_service.py
def save_budget(intent: SaveBudgetIntent) -> SaveResult:
    rows = [BudgetMensileRow(...) for r in intent.righe]          # Pydantic
    bq_write_validated(
        cfg.F_BUDGET_MENSILE, rows,
        mode="snapshot",
        natural_key=["societa_id", "anno", "fonte"],             # = il DELETE attuale di app_cdg
    )
    return SaveResult(cfg.F_BUDGET_MENSILE, len(rows), [...])

def save_previsione(intent: SavePrevisioneIntent) -> SaveResult:
    rows = [PianoFinanziarioInputRow(...) for m in intent.mesi]
    bq_write_validated(
        cfg.F_PIANO_FINANZIARIO_INPUT, rows,
        mode="snapshot",
        natural_key=["societa_id", "voce_id", "anno", "mese", "fonte"],  # = update_previsione
    )
    return SaveResult(cfg.F_PIANO_FINANZIARIO_INPUT, len(rows), [...])
```

Il `natural_key` riproduce **esattamente** lo scope del DELETE attuale → parità comportamentale,
ma ora chirurgico, validato Pydantic, osservabile e con lineage (gate).

---

## 4. Prima surface da migrare

`app_cdg.py` → `save_to_bq()` (la **violazione viva**, righe 458–504).

- **Prima:** `bq.query(DELETE…f-string)` + `load_table_from_json` raw.
- **Dopo:** costruisce `SaveBudgetIntent` dal DataFrame e chiama `cash_pf_service.save_budget(intent)`.
  Rimuove import `bigquery`, lo schema a mano, la query DELETE. La funzione passa da ~46 righe a ~8.

Scelta del *perché questa per prima*: è dove la violazione I1 è conclamata, è un write (esercita il
nuovo write-path end-to-end), ed è piccola e isolata. La CLI `previsione` (che già delega a
`update_previsione`) si aggancia subito dopo ri-puntando `update_previsione.update_previsione()` a
`cash_pf_service.save_previsione()` — così **un solo writer** serve Streamlit + CLI + NanoClaw.

---

## 5. Test / golden path

`tests/test_cash_pf_service.py` (nuovo):

1. **Gate usato** (il cuore): `save_budget`/`save_previsione` chiamano `bq_write_validated` con
   (a) righe `BudgetMensileRow`/`PianoFinanziarioInputRow` validate, (b) `mode="snapshot"`,
   (c) `natural_key` atteso. Mock del gate; assert su args.
2. **Parità comportamentale**: dato un input DataFrame d'esempio, le righe prodotte dal service
   eguagliano (campo per campo) quelle che `app_cdg.save_to_bq` costruiva — nessun cambio di *cosa*
   si scrive, solo di *come*.
3. **Validazione fa il suo lavoro**: una riga con importo non numerico / campo mancante fa fallire
   il service alla costruzione del modello Pydantic (non arriva a BQ).
4. **Regressione anti-violazione**: `app_cdg.py` non contiene più `load_table_from_json` né
   `bq.query(` con `DELETE`/`INSERT` (grep test).

`cdg_engine` ha già `tests/test_cdg_engine.py` — invariato (non lo tocchiamo).

**Golden path manuale (smoke):** dall'app Streamlit, modifica budget → Salva → la riga compare in
`f_budget_mensile` fonte=APP_BUDGET con lo stesso conteggio di prima, e il log mostra il passaggio
dal gate. Nessuna scrittura fuori dal gate.

---

## 6. Rischi e non-goals

**Rischi:**
- **Lineage da surface = `unknown`.** Il gate legge `PipelineRun.get_current()`; Streamlit/CLI non
  sono pipeline run → il gate logga warning e scrive comunque (comportamento documentato). Accettabile
  in questa slice; opzionale aprire un `PipelineRun` leggero attorno alla chiamata service (non
  obbligatorio per Metà A).
- **Parità comportamentale.** Il `natural_key` deve replicare lo scope esatto del DELETE attuale,
  altrimenti over/under-delete. Mitigato dal test 2 + smoke.
- **Schema drift.** `BudgetMensileRow`/`PianoFinanziarioInputRow` devono combaciare con le colonne
  effettive delle tabelle. Mitigato: gli stessi modelli sono già usati altrove; il gate fallisce
  forte se driftano.
- **Doppio writer transitorio.** Finché non si migra anche `update_previsione`, esistono due path
  di scrittura previsione. Ordine task pensato per chiuderlo subito (task 4).

**Non-goals (espliciti):**
- Nessuna memory table (`f_cash_projection_runs`, `f_decisioni`, evaluations) — Metà B.
- Nessun collasso `v_previsione_cassa`+scadenzario → `v_cash_projection_current` — Metà B.
- Nessun P0 re-baseline di `f_movimenti_contabili`.
- Nessun refactor degli interni di `pf_rotate` (solo ricollocazione come adapter).
- Nessuna unificazione delle **letture** in questa slice oltre il minimo necessario al budget/previsione
  (le 6 query inline di `app_cdg` si consolidano in un secondo giro, dopo che il write-path è provato).
- Nessun cambio di UI/UX delle surface.

---

## 7. Task list (breve, eseguibile)

1. **Scaffold service**: `verticals/condges/services/__init__.py`, `intents.py` (3 dataclass),
   `cash_pf_service.py` con `save_budget` + `save_previsione` via `bq_write_validated`
   (mode="snapshot", natural_key come §3).
2. **Migra `app_cdg.save_to_bq`** → costruisce `SaveBudgetIntent` e delega al service; rimuovi
   DELETE f-string, `load_table_from_json`, schema a mano, import `bigquery`.
3. **Ri-punta `update_previsione.update_previsione()`** a `cash_pf_service.save_previsione()` → un
   solo writer per Streamlit + CLI + NanoClaw.
4. **Test** `tests/test_cash_pf_service.py` (gate-usato, parità, validazione, regressione anti-violazione).
5. **Etichetta `pf_rotate`** come render/export adapter (docstring modulo + nota: non possiede stato;
   l'authority è BQ). Nessun cambio logico.
6. **Verde**: `ruff check . && ruff format . && pytest` — focus sui nuovi test + `test_cdg_engine` intatto.
7. **Smoke manuale** Streamlit budget save → verifica riga in `f_budget_mensile` + log gate.

Definition of done della slice: la scrittura cash/PF passa **solo** dal gate I1; `app_cdg` non scrive
più canonical direttamente; un solo writer previsione; test verdi. Pattern provato → riusabile per le
letture, per le altre surface, e (Metà B) per la memory layer.

---

## Related

- Decisioni lockate riusate: `[[2026-06-03_cash_control_v1_kernel_loop_grill]]` (BQ=authority,
  pf_rotate=render), `[[concepts/INFRASTRUCTURE_VS_LOOPS]]` (Surface→Service→Kernel).
- Metà B (next increment): `v_cash_projection_current` + `f_cash_projection_runs` + `f_decisioni`.
- Gate: `core/bq/write.py` `bq_write_validated`. Engine puro: `verticals/condges/cdg_engine.py`.
- Decision di contesto ancora `proposed`: `[[2026-05-10_Kernel_Closure_Sequence]]` (questa slice ne è
  il primo passo concreto, scopato).
