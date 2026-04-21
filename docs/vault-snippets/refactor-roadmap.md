# HotelOps Refactor Roadmap

**Created:** 2026-04-21
**Source:** swarm audit di 4 agenti (state machines / ontology / data warehouse / UI).
**Purpose:** consolidare i findings in un piano prioritizzato per il refactor interactive da eseguire in una singola CC instance, partendo da stato committato post-S1-WI-1 e post-S2-spec.
**Leggi prima:** `active-workstreams.md` per context vocabolario + stato sessioni.

---

## TL;DR per la nuova instance

Cinque convergenze su cose che più agenti hanno flaggato indipendentemente — queste sono le fix a leva più alta:

1. **`fonte` è leaked ovunque** come string literal (78 occorrenze in 8+ file) con priority rank duplicato 3 volte con valori inconsistenti. **Centralize in `core/enums.py`**.
2. **SQL è embeddato nella UI** (12 blocchi inline in Streamlit, no data layer). **Estrai `condges/loaders.py`** prima di scrivere `progetti/app_projects.py` che duplicherebbe il pattern.
3. **Canonical migrations mancanti** bloccheranno Projects vertical al primo write (`USCITE_INVESTIMENTI_CAPEX` voce non esiste, `stato_censimento` colonna non esiste). **Pre-stage adesso**, 30 min.
4. **Stato machines dichiarati solo nello spec**, mai enforced. Momento perfetto per centralizarli **prima** che il codice Projects li spalmi in 5 file.
5. **Dead schemas** (`f_affidamenti`, `f_mastrino_consolidato`) + **viste ridondanti** (3 wrapper views). Cleanup ~2 ore, riduce superficie.

**Ordine di esecuzione raccomandato**: Fase 0 (blockers) → Fase 1 (cross-layer foundations) → Fase 2 (per-layer cleanup) → Fase 3 (preparazione Projects vertical).

---

## Findings per layer (consolidato)

### Layer 1 — State machines (⚠️ scattering critico)

| State machine | Dove sta | Come è enforced | Problema |
|---|---|---|---|
| `fonte` su `f_budget_mensile` | 8+ string literal in ingest/*, condges/*, SQL views | SQL CASE in views | No enum, 78 occorrenze ripetute |
| `fonte` su `f_piano_finanziario_input` | Literal in update_previsione.py, app_cdg.py, app_scadenzario.py | SQL priority rank in v_piano_finanziario_mensile:121-129 | Priority duplicata 3 volte con valori diversi |
| Lifecycle APPEND vs SNAPSHOT | Commenti sparsi + ingest/classify.py:65-66 | BigQuery WriteDisposition (implicito) | Readers cross-reference docstring per sapere idempotenza |
| `Commitment.stato` (pianificata) | Spec S2 §3.1 | Non ancora implementata | Solo documentazione, no enforcement code |
| `ScopePackage.stato` (pianificata) | Spec S2 §3.1 | Non ancora implementata | Stesse transizioni nel spec |
| `Document.stato_preventivo` (pianificata) | Spec S2 §3.1 | Non ancora implementata | Stessa |
| `stato_censimento` su `d_anagrafica_fornitori` | Spec S2 §3.3 | Non implementata, spec usa `stato_anagrafica` già esistente (drift) | Naming drift spec vs codice attuale |
| Cod_conto resolution chain | `ingest_gasparotto.py` (recente) | Funzione locale `_resolve_cod_conto_with_context` | Ottima ma non riutilizzabile da altri parser che avranno lo stesso problema |

**Leva più alta:** issue `fonte` priority triplice duplicata in `v_budget_vs_consuntivo.sql:19-30` vs `v_piano_finanziario_mensile.sql:121-129` vs `app_cdg.py:70-71` — 3 valori di priorità, con ordini parzialmente diversi.

### Layer 2 — Ontology / dimensioni

| Check | Esito | Dettaglio |
|---|---|---|
| Naming USCITE_*/ENTRATE_* | ✅ Enforced su 28/28 voci | Nessuna eccezione |
| `societa_id` enum | ✅ Clean | Solo ORTI/INTUR/NULL |
| FK integrity `voce_id` | ⚠️ 1 rischio critico | Spec S2 §3.2 usa `'CONSULENZE'` literal, vero `voce_id` è `USCITE_CONSULENZE` → forward-flow solver emetterebbe FK dangling |
| Voce `USCITE_INVESTIMENTI_CAPEX` | ❌ Mancante | Spec la referenzia (5+ punti), CSV vuoto → Projects forward-flow fallisce al primo write |
| Colonna `stato_censimento` | ❌ Mancante | Spec la aggiunge, codice attuale ha `stato_anagrafica` |
| TODO_* in `d_mapping_piano_finanziario.csv` | ⚠️ 9 righe | 6× `nome_esolver=TODO_*` MATERIE_PRIME ORTI, 2× INTUR, 1× commento `TODO: Stefano conferma` |
| Drift vault↔codice↔brief | ⚠️ 6 alert | Amalisa/Amalia, Capone TV, Dierre bucket, budget 350K→1.2M, 15 vendor non censiti, Atelier/Ninni overlap |
| Cod_conto_pattern TASSE | ⚠️ Sospetto | 63051 (admin) usato ma TASSE reali vivono in 71.xx |

**Leva più alta:** migrations pre-stage (30 min di lavoro sblocca tutto Projects).

### Layer 3 — Data warehouse / BQ

**DAG viste (tutto in `core/bq/views/`):**
```
Layer 2 (wrappers):
  v_budget → v_budget_canonical                    # MISSING in core/config.py!
  v_condges_cashflow → v_cashflow_mensile + v_previsione_cassa
  v_condges_pf_mensile → v_piano_finanziario_mensile   # thin wrapper (solo label)

Layer 1 (base analytical):
  v_budget_vs_consuntivo ← f_budget_mensile, f_movimenti_contabili, d_piano_conti
  v_piano_finanziario_mensile ← f_piano_finanziario_input + f_budget_mensile + v_piano_finanziario_consuntivo
  v_previsione_cassa ← f_saldi_banca_snapshot + v_piano_finanziario_consuntivo + f_piano_finanziario_input + f_partite_aperte_fornitori
  v_economato_pareto ← f_consumi_economato     # duplica v_economato_consumi granularity
  v_economato_costo_unitario ← f_coefficienti_consumo  # wrapper thin
  ... (9 altre)
```

**Dead/orphan candidates:**
- **`f_affidamenti`** — Pydantic schema, zero ingest, zero consumer. Stub pre-esistente o da ripulire.
- **`f_mastrino_consolidato`** — Schema in manifest, zero referenze SQL/Python. Deprecare o documentare deploy plan.
- **`v_budget_canonical`** — Fantasma: referenziato da `v_budget.sql` ma non in `core/config.py`. O in worktree separato o orfano.
- **`f_chiusura_mensile`** — Audit-only: ingest esiste, nessun consumer analitico. OK tenerlo ma flaggare come "observability only".
- **`v_economato_costo_unitario`** — Wrapper thin (+3 label columns) su `f_coefficienti_consumo`. Collassare al layer ingest.
- **`v_economato_pareto`** — Duplica grain di `v_economato_consumi`. Ranking può stare in Looker o come campo su base view.
- **`v_condges_pf_mensile`** — Wrapper label-only su `v_piano_finanziario_mensile`. Inlineable.

**God columns (rischio rename):**
- `codice_conto` — 5+ viste + 2 ingest → rinomina rompe LIKE pattern matching
- `voce_id` — 4+ viste + solver Projects → rinomina rompe tutto il financial reporting
- `data_operazione` / `data_registrazione` — 4+ viste con `EXTRACT(YEAR/MONTH)` hardcoded

### Layer 4 — UI / apps

**SQL-in-UI inventory: 12 blocchi inline**, zero modulo loader.
- `app_cdg.py`: 6 funzioni con SQL inline (load_budget_base, load_consuntivo_ytd, load_saldi_banca, load_consuntivo_ce, load_stagionalita, load_consuntivo_ce_detail)
- `reviews/app.py`: 1 in load_reviews()
- `cli_commands.py`: 5 in cmd_pf/cmd_health/ecc.
- `app_scadenzario.py`: 0 (solo openpyxl + CSV)

**Pattern duplicati (5 casi):**
1. Sign-flip CASE account ricavi vs costi → 3× verbatim in `app_cdg.py:92, 137, 175`
2. Sidebar societa/anno selector → in 3 app con lista hardcoded (no dim lookup)
3. DataFrame pivot→month columns → logica parallela in `app_cdg.py:218-231` e `app_scadenzario.py:200-320`
4. KPI cards layout → 3 app, colonne + metric labels hardcoded, no shared component
5. Cache decorator stack `@st.cache_resource` + `@st.cache_data(ttl=300)` → no cache invalidation strategy

**Session state:** usato solo in `app_scadenzario.py` (`excluded_suppliers`, `voce_assignments`), ad-hoc. `app_cdg.py` e `reviews/app.py` usano global vars. Projects MVP avrà bisogno di state per progetto_id/scope_id/LLM extraction session → rischio anarchia.

**Hardcoded leaks:** fonte list in `app_cdg.py:70`, sign-flip account ranges in 3 funzioni, BU list `["HOTEL","RESIDENCE","CVM","LIDO"]` in 2 app, column names in pivot config.

---

## Roadmap prioritizzato

### Fase 0 — Blockers (fai subito, <2 ore)

Queste tre sbloccano scrittura Projects vertical. Se lanci Projects senza queste, primo write esplode.

**0.1 — Add `USCITE_INVESTIMENTI_CAPEX` a `d_voci_piano_finanziario.csv`** (15 min)
```csv
USCITE_INVESTIMENTI_CAPEX,Investimenti Capex Cantieri,USCITE,Investimenti,,MANUALE,,,,,330,,Investimenti,X
```
Then load: `python -m core.bq.load.load_voci_piano_finanziario`.

**0.2 — Add `stato_censimento` column a `d_anagrafica_fornitori`** (30 min)
Schema migration + loader update. Default `CENSITO` per righe esistenti. Valori enum `DA_CENSIRE|CENSITO|ATTIVO`.

**0.3 — Fix literals in spec S2 prima di plan rewrite** (15 min)
Spec S2 `docs/superpowers/specs/2026-04-20-projects-mvp-design.md` §3.2 linee 320, 333-334 usano `'INVESTIMENTI_CAPEX'` e `'CONSULENZE'` come literal. Rename a `USCITE_INVESTIMENTI_CAPEX` e `USCITE_CONSULENZE`. Allineare anche OPEX_CATEGORY_MAP.

### Fase 1 — Cross-layer foundations (~1 giornata)

Queste foundations fanno convergere tutti i layer. Fai queste **prima** di toccare ogni altra cosa.

**1.1 — Create `core/enums.py` (2-4 ore)** 🎯 highest leverage

Centralizza:
```python
from enum import StrEnum

class Fonte(StrEnum):
    # f_budget_mensile
    STRUTTURALI = "STRUTTURALI"
    MAPPATURA = "MAPPATURA"
    PERSONALE = "PERSONALE"
    INCIDENZA = "INCIDENZA"
    GASPAROTTO = "GASPAROTTO"
    CONS2025_IP = "CONS2025_IP"
    CONS2025_F = "CONS2025_F"
    CONS2025_V = "CONS2025_V"
    CONS2025_X = "CONS2025_X"
    APP_BUDGET = "APP_BUDGET"
    # f_piano_finanziario_input
    PIANO_FINANZIARIO = "PIANO_FINANZIARIO"
    SCADENZIARIO = "SCADENZIARIO"
    BVA_2026 = "BVA_2026"
    CLI = "CLI"
    APP = "APP"
    NANOCLAW = "NANOCLAW"
    PROGETTI = "PROGETTI"    # new, Projects vertical

FONTE_PRIORITY_BUDGET = {
    Fonte.STRUTTURALI: 1,
    Fonte.MAPPATURA: 2,
    # ... single source of truth
}

FONTE_PRIORITY_PF = {
    Fonte.CLI: 1,
    Fonte.APP: 2,
    # ...
}

class Societa(StrEnum):
    ORTI = "ORTI"
    INTUR = "INTUR"

class LifecycleType(StrEnum):
    APPEND_MD5 = "APPEND_MD5"
    SNAPSHOT_DEL_INS = "SNAPSHOT_DEL_INS"
    APPEND_AUDIT = "APPEND_AUDIT"     # with ROW_NUMBER latest-state view

class CommitmentStato(StrEnum):    # Projects vertical
    FIRMATO = "FIRMATO"
    IN_CORSO = "IN_CORSO"
    CHIUSO = "CHIUSO"
    ANNULLATO = "ANNULLATO"

class ScopePackageStato(StrEnum):
    IDENTIFICATO = "IDENTIFICATO"
    PREVENTIVATO = "PREVENTIVATO"
    IMPEGNATO = "IMPEGNATO"
    CHIUSO = "CHIUSO"

class DocumentStatoPreventivo(StrEnum):
    RICEVUTO = "RICEVUTO"
    ACCETTATO = "ACCETTATO"
    RIFIUTATO = "RIFIUTATO"
    SCADUTO = "SCADUTO"

class StatoCensimento(StrEnum):
    DA_CENSIRE = "DA_CENSIRE"
    CENSITO = "CENSITO"
    ATTIVO = "ATTIVO"
```

Then replace:
- `core/schemas.py:41, 69, 189, 214, 308`: `fonte: Literal[...]` → `fonte: Fonte`
- `ingest/flussi/ingest_gasparotto.py:67`: `FONTE = "GASPAROTTO"` → `FONTE = Fonte.GASPAROTTO`
- `condges/update_previsione.py:45`: `DEFAULT_FONTE = "NANOCLAW"` → `DEFAULT_FONTE = Fonte.NANOCLAW`
- `condges/app_cdg.py:70-71`: hardcoded list → `[f.value for f in BUDGET_FONTI]`
- SQL views: generate CASE from `FONTE_PRIORITY_*` via codegen script (tolerable inelegance) or jinja2 templates

**1.2 — Create `core/bq/fonte_priority.sql` macro (2 ore)**

Single SQL CTE that `v_budget_vs_consuntivo.sql` and `v_piano_finanziario_mensile.sql` both include via template. Eliminates duplicated CASE with inconsistent order.

**1.3 — Extract `condges/loaders.py` con 6 funzioni (4-6 ore)** 🎯 secondhigh

Sposta da `app_cdg.py`:
```python
# condges/loaders.py
def load_budget_base(bq, societa: Societa, anno: int) -> pd.DataFrame:
    """Base budget query — senza Streamlit cache, testabile."""
    ...

def load_consuntivo_ytd(bq, societa: Societa, anno: int, mese: int) -> pd.DataFrame: ...
def load_saldi_banca(bq, societa: Societa) -> pd.DataFrame: ...
def load_consuntivo_ce(bq, societa: Societa, anno: int) -> pd.DataFrame: ...
def load_stagionalita(bq, bu: str | None) -> pd.DataFrame: ...
def load_consuntivo_ce_detail(bq, societa: Societa, anno: int, conto: str) -> pd.DataFrame: ...
```

`app_cdg.py` ora fa solo `@st.cache_data def cached_*(): return loaders.load_*(...)`. Rende i loader unit-testabili (in `tests/test_loaders.py`) senza Streamlit. Anche il piano Session 1 WI-2 Task 5 usa questo pattern per `cashflow_loader.py` — unifica in uno stesso `loaders.py`.

### Fase 2 — Per-layer cleanup (~2 giornate)

**2.1 — State machines: aggiungi guards transizione in Pydantic (3-4 ore)**

In `core/schemas.py` per `Commitment`:
```python
_ALLOWED_TRANSITIONS_COMMITMENT = {
    CommitmentStato.FIRMATO: {CommitmentStato.IN_CORSO, CommitmentStato.ANNULLATO},
    CommitmentStato.IN_CORSO: {CommitmentStato.CHIUSO, CommitmentStato.ANNULLATO},
    CommitmentStato.CHIUSO: set(),
    CommitmentStato.ANNULLATO: set(),
}

class Commitment(BaseModel):
    stato: CommitmentStato
    # ...
    @classmethod
    def validate_transition(cls, old: CommitmentStato, new: CommitmentStato) -> None:
        if new not in _ALLOWED_TRANSITIONS_COMMITMENT[old]:
            raise InvalidTransition(f"{old} → {new} not allowed")
```

Stesso pattern per `ScopePackageStato` e `DocumentStatoPreventivo`. Da fare PRIMA che Projects code venga scritto.

**2.2 — DW cleanup: rimuovi dead artifacts (2 ore)**

- Delete `core/schemas.py` stub per `f_affidamenti` se davvero non serve (o documenta piano concreto)
- Delete `core/schemas.py` stub per `f_mastrino_consolidato` idem
- Register `v_budget_canonical` in `core/config.py` o deprecare `v_budget`
- Collapse 3 wrapper views:
  - `v_economato_costo_unitario` → campi pushed a `f_coefficienti_consumo` o a `v_economato_consumi`
  - `v_economato_pareto` → Looker derived field
  - `v_condges_pf_mensile` → labels inline in `v_piano_finanziario_mensile`

**2.3 — Ontology: ripulisci TODO e drift (1 ora user + 30 min code)**

- Stefano risolve 9 righe TODO in `d_mapping_piano_finanziario.csv`
- Stefano disambigua Capone TV (ragione sociale) e Dierre bucket
- Code: add FK validation in `load_mapping_piano_finanziario.py` (error invece di silent skip)

**2.4 — UI: centralizza sign-flip + UI components (4 ore)**

- Nuovo `core/bq/views/v_consuntivo_ytd_sign_corrected.sql` con CASE unico. Replace 3 duplicate in `app_cdg.py`.
- Nuovo `condges/ui_components.py`:
  ```python
  def render_kpi_card(label, value, delta=None, fmt="€{:,.0f}"): ...
  def render_fonte_badge(fonte: Fonte) -> str: ...
  def render_societa_selector(key: str) -> Societa: ...
  def render_anno_selector(key: str, default: int = 2026) -> int: ...
  def render_month_selector(key: str, multi: bool = False) -> int | list[int]: ...
  def render_bu_selector(key: str) -> str: ...
  ```

### Fase 3 — Preparazione Projects vertical (~0.5 giornata prima di scrivere codice)

**3.1 — Define `core/state.py` con namespace Streamlit keys (1 ora)**

```python
# Progetti vertical namespace
PROGETTI_SELECTED_ID = "progetti:selected_id"
PROGETTI_SCOPE_FILTER = "progetti:scope_filter"
PROGETTI_EXTRACTION_DRAFT = "progetti:extraction_draft"
# Condges namespace (retrofit app_scadenzario)
SCADENZARIO_EXCLUDED = "condges:scad:excluded_suppliers"
SCADENZARIO_ASSIGNMENTS = "condges:scad:voce_assignments"
```

Convention: `{vertical}:{subnamespace}:{key}`.

**3.2 — Plan S2 needs update (1 ora)**

Plan S2 attuale non menziona fase 1 foundations. Aggiungi Task 0.5 "Depends on refactor roadmap Phase 0+1 complete" e riferimenti a `core/enums.py` invece di string literals.

Specifically in piano S2:
- Task 1-3 (Pydantic): import enums da `core/enums.py`, non ridefinire Literal
- Task 15 (fornitore fuzzy match): usa `StatoCensimento.DA_CENSIRE` / `CENSITO` / `ATTIVO` da enums
- Task 17 (forward-flow): import `Fonte.PROGETTI`, `Societa.INTUR`, `USCITE_INVESTIMENTI_CAPEX`
- Task 19-22 (Streamlit): import componenti da `condges/ui_components.py` + keys da `core/state.py`

---

## Post-refactor: cosa diventa facile

Dopo Fase 0+1+2:
- Aggiungere nuova `fonte` = 1 riga in enum. Appare in viste, UI, forward-flow automaticamente.
- Aggiungere nuova `voce` = 1 riga CSV + load. Nessun grep-and-replace.
- Aggiungere nuovo tab Streamlit condges = wrapper su loader + ui_components. 30 LOC invece di 300.
- Scrivere Projects vertical: ordine pulito (Pydantic con enums centralizzati, loader separato, UI riutilizzata, state namespaced).
- Test unitari: loader testabili senza Streamlit; state machines testabili senza BQ.

---

## Non-goals (esplicito)

Cose che potrebbero sembrare naturali ma restano fuori scope:

- Riscrivere `app_scadenzario.py` — è già funzionante e il suo parser Excel è idiosincratico. Toccare solo ui_components + state naming.
- Consolidare `cli.py` + `cli_commands.py` — già fatto a step durante WI recenti, OK così.
- Toccare `reviews/` — vertical separato, non entra in questo refactor.
- Toccare `ingest/banca/` parser bancari — funzionanti, test coverage buona, lasciali.
- Migrazione dati storici — solo schema/interfaccia changes, no retroactive rewrites di dati già in BQ.

---

## How to execute (per nuova CC instance)

1. **First-read:** questo file + `active-workstreams.md`.
2. **Execute Fase 0 first** — 3 blockers piccoli. Commit ogni atomic.
3. **Poi Fase 1 interactive** — Stefano prova, tu refactori, vedi breakages, fix. Iterativo.
4. **Fase 2 batch** — parallelizzabile (state machines + DW cleanup + UI indipendenti).
5. **Fase 3 come pre-req Projects plan rewrite**.

Attese realistiche: Fase 0 oggi (2 ore). Fase 1 in 1-2 sessioni. Fase 2 in 2-3 sessioni. Fase 3 in 1 sessione. **Totale: 4-6 sessioni interactive** prima di poter scrivere codice Projects vertical con foundations pulite.
