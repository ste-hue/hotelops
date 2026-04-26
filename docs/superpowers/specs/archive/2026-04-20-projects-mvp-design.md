# Projects MVP — 4° vertical (project subledger + forward-flow a CONDGES)

**Date:** 2026-04-20 (reframed 2026-04-21)
**Status:** ⚠️ **ARCHIVED 2026-04-26** — superseded by `docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md`. Pivot da 8 entità normalizzate a 3 tabelle event-sourced (`d_progetti`, `f_progetto_voci`, `f_progetto_eventi`). Logica forward-flow + 4 viste manageriali validate, riusate nel nuovo design. Mantenuto come riferimento storico.
**Author:** Stefano + Claude
**Seed data:** `docs/progetti/HPAN25PIANO1-walkthrough.md`

**Scope:** Introdurre **`progetti/`** come **quarto vertical** HotelOps, project subledger (analogo SAP PS) separato dal general ledger operativo (CONDGES). Il vertical gestisce il ciclo impegno → documento → fattura → pagamento per i progetti capex/cantiere; emette forward-flow verso `f_piano_finanziario_input` con fonte=`PROGETTI`. MVP popolato su `HPAN25PIANO1` (Camere Primo Piano Hotel Panorama).

---

## 1. Direzione

### 1.1 I9 (candidato, riformulato)

> **Il Progetto è una dimensione obbligatoria del controllo di gestione; il ciclo impegno–fattura–pagamento vive in un subledger dedicato con forward-flow verso CONDGES.**

Non è tagging retroattivo delle fact canoniche. È **subledger separato** con contratti di interoperabilità espliciti:

| Direzione | Meccanismo | Rispetto I3 (Canonical Truth Registry) |
|---|---|---|
| **Projects → CONDGES** | `PaymentSchedule` delle Commitments attive → righe `f_piano_finanziario_input` con fonte=`PROGETTI` | Aggiunge righe su canonical SoT cashflow; non duplica `f_piano_finanziario_input` |
| **CONDGES → Projects** | `f_movimenti_contabili` (fatture) → thin join `f_progetto_invoice_link(commitment_id, movimento_row_hash)` | La fattura resta in `f_movimenti_contabili`; il subledger la linka, non la copia |

Retroattività sulle fact canoniche (I9 "pieno" = colonna `progetto_id` ovunque) è **H2**, non MVP.

### 1.2 I10 — ritirato come invariant

La regola capex/opex → società pagante (capex su immobili → società proprietaria; opex operativi → società operativa) è **business rule gruppo-specifica** di Panorama, non invariant platform-wide.

Documentazione: `vault/ontology/business-rules/capex-opex-allocation.md` (nuovo file in capture alla fine MVP).

Enforcement: **soft** nel vertical `progetti/` — UI Streamlit propone default in base a tipo spesa, warn se override manuale, non blocca il salvataggio.

### 1.3 Posizionamento

Quarto vertical peer a CONDGES / REVIEWS / ECONOMATO. **Non** è un terzo zoom interno a CONDGES.

| Vertical | Audience | Domanda | Confini SoT |
|---|---|---|---|
| CONDGES | Rosa, Gasparotto | "Come va il mese? Cashflow? BvA?" | `f_movimenti_contabili`, `f_banche_movimenti`, `f_piano_finanziario_input`, `v_budget_canonical` |
| REVIEWS | Antonio | "Come ci vedono gli ospiti?" | `f_reviews`, `f_apify_runs` |
| ECONOMATO | (Mario, future) | "Quanto consumiamo?" | `f_consumi_economato`, `f_coperti_giornalieri` |
| **Projects** | Stefano Jr + PM | "HPAN25PIANO1 sta sforando? Quanto pago questo mese per cantiere?" | `d_progetti`, `f_progetto_*` (7 tabelle), emette a `f_piano_finanziario_input` fonte=`PROGETTI` |

---

## 2. Scope & Audience

### 2.1 Audience

- **Primaria:** Stefano Della Pietra Jr (owner, decisore capex).
- **Secondaria H2:** project manager esterni (Hospitality Project, ecc.) con accesso view-only.
- Non Antonio (non gestisce cantiere). Non Rosa (tesoreria, vede solo forward-flow attraverso CONDGES). Non serve multi-utente **in MVP**.

### 2.2 MVP scope

- Schema multi-progetto generico da day 1 (`d_progetti` + FK `progetto_id` ovunque nel vertical).
- Popolato inizialmente con **UN** progetto: `HPAN25PIANO1 — Camere Primo Piano` (cap 1.2M, seed da walkthrough con ~28 item).
- Entity model: 7 entità (Project, ScopePackage, Document, Commitment, PaymentSchedule, InvoiceLink, Extraction audit).
- Ingestion: drop documento + estrazione LLM + classify + fuzzy match fornitore.
- Forward-flow: solver che proietta Commitment+PaymentSchedule → `f_piano_finanziario_input` fonte=`PROGETTI`.
- UI: 4 view Streamlit (Register / Documents / Budget evolution / Payment planning).
- CLI: `hotelops progetti <subcommand>`.

### 2.3 Out of MVP (H2 roadmap)

- Ricorrenti come progetti permanenti (`HPAN_STAGIONE_2026`).
- `v_previsione_cassa` derivata dai Commitments progetti (richiede I9 pieno).
- Integrazione UI dentro `app_cdg.py` (MVP usa app separata).
- `progetto_id` obbligatorio su `f_movimenti_contabili` e `f_banche_movimenti`.
- Pagamenti automatici (decisione paga/non-paga resta umana).
- Multi-utente / permessi granulari.

### 2.4 Success criteria

Su HPAN25PIANO1, Stefano deve poter:

1. **Register view** — vedere in <10 sec budget vs impegnato vs fatturato vs pagato, per progetto e per ScopePackage, con semaforo overrun.
2. **Documents view** — drop PDF preventivo/fattura → estrazione LLM + review → append BQ + copia Drive in <60 sec.
3. **Budget evolution view** — timeline cronologica: da stima orfana → preventivo → contratto → fattura, con tracking delta.
4. **Payment planning view** — tabella cashflow mensile per (società_pagante × mese), con scenari di ritardo/anticipo rate.
5. **Forward-flow verificabile** — Rosa/Gasparotto vedono le rate Commitments di `HPAN25PIANO1` in `f_piano_finanziario_input` fonte=`PROGETTI`, voce `INVESTIMENTI_CAPEX` (per INTUR capex) o `CONSULENZE` (per ORTI PM fee).

---

## 3. Data model

### 3.1 Entità (7)

```
Project (1)
  │
  ├── (N) ScopePackage ── (N:M) f_progetto_scope_commitment_link ── (M) Commitment (N:1) [societa_pagante, fornitore]
  │         │                                                           │
  │         └── (N) Document ← ───── from_document_id (opzionale) ──────┘
  │                                                                     │
  │                                                                     ├── (N) PaymentSchedule
  │                                                                     │
  │                                                                     └── (N) InvoiceLink ── (1) f_movimenti_contabili
  │
  └── forward-flow a f_piano_finanziario_input fonte=PROGETTI
```

- **Project** — `d_progetti` row. Long-lived. Budget cap societa-agnostico.
- **ScopePackage** — WBS node, budget-bearing, può esistere senza vendor. Stati: `IDENTIFICATO → PREVENTIVATO → IMPEGNATO → CHIUSO`.
- **Document** — Preventivo / Contratto / Ordine / Fattura / SAL / Altro. Fisicamente su Drive, metadata in BQ. FK `scope_package_id`. Per preventivi: `stato_preventivo`.
- **Commitment** — obbligazione formale verso UN vendor da parte di UNA società pagante. Stati: `FIRMATO → IN_CORSO → CHIUSO (+ ANNULLATO)`. `importo_impegnato_eur` fisso alla firma.
- **PaymentSchedule** — rate del Commitment: `(data_prevista, importo, voce_pf_target, descrizione)`. Alimenta forward-flow.
- **InvoiceLink** — thin join Commitment ↔ `f_movimenti_contabili` (fatture fornitori già ingerite).
- **Extraction audit** — `f_progetto_extractions` log LLM (request, response, parsed, confidence, reviewed_by).

### 3.2 State machines

**Commitment:** `FIRMATO → IN_CORSO → CHIUSO`; `ANNULLATO` da qualsiasi stato non-CHIUSO.
Drop `PREVENTIVO` come stato Commitment: un preventivo non firmato è un `Document(tipo=PREVENTIVO)` attaccato a ScopePackage, senza Commitment.

**ScopePackage:** `IDENTIFICATO (solo stima) → PREVENTIVATO (≥1 Document) → IMPEGNATO (≥1 Commitment linkato) → CHIUSO (tutti i Commitment linkati chiusi)`.

**Document(tipo=Preventivo):** `stato_preventivo ∈ {RICEVUTO, ACCETTATO, RIFIUTATO, SCADUTO}`.

Tutte le transizioni sono APPEND audit (no UPDATE). Latest state via view `v_*_current` con `ROW_NUMBER() OVER (PARTITION BY <id> ORDER BY data_stato DESC)`.

### 3.3 Schema Pydantic (`core/schemas.py` additions)

```python
class Project(BaseModel):
    progetto_id: str                          # HPAN25PIANO1
    nome: str                                 # "Camere Primo Piano - Hotel Panorama"
    societa_beneficiaria_id: Literal["ORTI", "INTUR"]  # proprietario asset finale
    business_unit_id: str                     # HOTEL
    struttura: str                            # "Hotel Panorama"
    data_inizio: date
    data_fine_prevista: date | None
    budget_cap_eur: Decimal                   # 1_200_000 per HPAN25PIANO1
    stato: Literal["PIANIFICATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    owner: str                                # "Stefano Della Pietra Jr"
    direzione_lavori: str | None              # "Amalia Pisacane"

class ScopePackage(BaseModel):
    scope_id: str                             # UUID
    progetto_id: str                          # FK Project
    codice: str                               # "SP-IMPIANTI-ELETTRICO"
    descrizione: str                          # "Impiantistica elettrica camere 121-130"
    categoria: Literal["OPERE_MURARIE", "IMPIANTI", "ARREDI", "FINITURE",
                       "PORTE", "CONSULENZE", "PROGETTAZIONE", "PM", "ALTRO"]
    importo_stimato_eur: Decimal              # stima manuale, può essere sovrascritta da Document/Commitment linkati
    stato: Literal["IDENTIFICATO", "PREVENTIVATO", "IMPEGNATO", "CHIUSO"]
    data_stato: datetime
    note: str | None

class Document(BaseModel):
    document_id: str                          # UUID
    scope_package_id: str                     # FK ScopePackage
    tipo: Literal["PREVENTIVO", "CONTRATTO", "ORDINE", "FATTURA", "SAL", "ALTRO"]
    fornitore_id: str | None                  # FK d_anagrafica_fornitori (nullable, candidate)
    fornitore_denorm: str                     # sempre presente
    numero_documento: str | None              # "864" (Dierre)
    data_documento: date | None
    importo_eur: Decimal | None
    stato_preventivo: Literal["RICEVUTO", "ACCETTATO", "RIFIUTATO", "SCADUTO"] | None
    drive_path: str                           # "investimenti2026/HPAN25PIANO1/..."
    file_hash_md5: str                        # dedup
    estratto_confidence: float                # 0.0-1.0 (LLM quality)
    estratto_reviewed: bool                   # True = umano ha validato
    note: str | None

class Commitment(BaseModel):
    commitment_id: str                        # UUID
    progetto_id: str                          # FK Project (denorm per query)
    descrizione: str                          # "Contratto STE impiantistica elettrica"
    fornitore_id: str | None                  # FK d_anagrafica_fornitori
    fornitore_denorm: str
    societa_pagante_id: Literal["ORTI", "INTUR"]  # BINDING, obbligatorio
    tipo_spesa: Literal["CAPEX", "OPEX"]      # guida forward-flow voce PF
    importo_impegnato_eur: Decimal            # fisso alla firma, immutabile
    stato: Literal["FIRMATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    data_stato: datetime
    from_document_id: str | None              # Preventivo che è diventato Commitment
    voce_pf_target: str                       # default: INVESTIMENTI_CAPEX se CAPEX, lookup se OPEX
    note: str | None

class ScopeCommitmentLink(BaseModel):
    link_id: str                              # UUID
    scope_package_id: str                     # FK ScopePackage
    commitment_id: str                        # FK Commitment
    quota_importo_eur: Decimal                # quota del Commitment su questo Scope (per N:M bundled)

class PaymentSchedule(BaseModel):
    rate_id: str                              # UUID
    commitment_id: str                        # FK Commitment
    seq: int                                  # 1, 2, 3... rata
    data_prevista: date
    importo_eur: Decimal
    descrizione: str                          # "Acconto 30% alla firma"
    stato: Literal["PIANIFICATA", "EMESSA", "PAGATA", "ANNULLATA"]
    data_stato: datetime
    # PK: rate_id

class InvoiceLink(BaseModel):
    link_id: str                              # UUID
    commitment_id: str                        # FK Commitment
    movimento_row_hash: str                   # hash riga f_movimenti_contabili (UNIQUE)
    payment_schedule_rate_id: str | None      # opzionale: quale rata sta coprendo
    note: str | None

class DocumentExtraction(BaseModel):
    extraction_id: str                        # UUID
    document_id: str                          # FK Document
    model: str                                # "claude-haiku-4-5-20251001"
    raw_output: str                           # JSON stringified
    parsed_fields: dict                       # deserialized
    confidence_per_field: dict                # {"importo": 0.95, "data": 0.72, ...}
    ts_extraction: datetime
    reviewed_by: str | None
    ts_reviewed: datetime | None
```

### 3.4 Schema BigQuery

**8 tabelle nuove** (prefisso `f_progetto_` + `d_progetti`):

| Tabella | Lifecycle | Note |
|---|---|---|
| `d_progetti` | SNAPSHOT per `progetto_id` | Dimensione low-mutability |
| `f_progetto_scopes` | APPEND audit log | Ogni transizione stato = riga; latest via view |
| `f_progetto_commitments` | APPEND audit log | Ogni transizione = riga; `importo_impegnato_eur` immutabile |
| `f_progetto_scope_commitment_link` | SNAPSHOT per `link_id` | N:M link + `quota_importo_eur` |
| `f_progetto_documenti` | APPEND immutabili | Dedup su `file_hash_md5` |
| `f_progetto_payment_schedules` | APPEND audit log | Ogni modifica rata = riga; latest via view |
| `f_progetto_invoice_link` | SNAPSHOT per `link_id` | Può essere rivisto (riattacco fattura a commitment diverso) |
| `f_progetto_extractions` | APPEND immutabile | Audit LLM round-trip |

**6 view nuove** (in `core/bq/views/`):

| View | Scopo |
|---|---|
| `v_progetto_scopes_current` | Latest state per `scope_id` |
| `v_progetto_commitments_current` | Latest state per `commitment_id` |
| `v_progetto_payment_schedules_current` | Latest state per `rate_id` |
| `v_commitment_status` | Per commitment: `importo_impegnato`, `importo_fatturato_cum` (da InvoiceLink+f_movimenti_contabili), `delta_overrun_eur`, `residuo_eur`, `stato_overrun` (`OK`/`WARN >5%`/`ALERT >10%`) |
| `v_progetto_overview` | Per progetto: budget cap, SUM scope stime, SUM commitments, SUM fatturato, SUM pagato, % avanzamento, semaforo overrun |
| `v_progetto_timeline` | Eventi cronologici per progetto: scope creato → preventivo → commitment firmato → fattura → pagamento |

**FK su canonicals esistenti:**
- `fornitore_id` → `d_anagrafica_fornitori` (nullable per candidate)
- `movimento_row_hash` → hash riga `f_movimenti_contabili` (la fattura vive lì, non duplicata)

**Modifiche ai canonicals (minime):**
- `d_voci_piano_finanziario`: aggiunta voce `INVESTIMENTI_CAPEX` (vedi §1.1 decisione user).
- `f_piano_finanziario_input`: nuovo valore ammesso `fonte=PROGETTI` (oltre ai 6 esistenti).
- `d_anagrafica_fornitori`: aggiunta colonna `stato_censimento` (`DA_CENSIRE` / `CENSITO` / `ATTIVO`), default `CENSITO` per righe esistenti.

---

## 4. Ingestion flows

### 4.1 Flow A — Drop documento con pre-estrazione LLM

```
1. UI Documents: drag PDF/Excel
2. Salvataggio temporaneo + computo MD5
3. Check dedup su f_progetto_documenti.file_hash_md5
4. Claude Haiku (claude-haiku-4-5-20251001) con prompt strutturato:
   → JSON {tipo, fornitore_ragione_sociale, numero_doc, data_doc, importo, descrizione, scope_hint}
   → + confidence_per_field
5. Fuzzy match fornitore (rapidfuzz) contro d_anagrafica_fornitori.ragione_sociale:
   - score ≥ 0.9 → auto-link fornitore_id
   - score 0.7–0.9 → suggest, chiede conferma umana
   - score < 0.7 → candidate (fornitore_id=NULL, stato_censimento=DA_CENSIRE)
6. UI mostra fields pre-compilati, highlight bassa confidence, suggested scope_package_id
7. Stefano review/edit/conferma
8. Submit in transazione:
   - insert f_progetto_documenti (estratto_reviewed=True)
   - insert f_progetto_extractions (audit round-trip completo)
   - rclone put file → investimenti2026/<progetto>/<scope>/<tipo>/
   - se tipo=Preventivo e nessun Commitment esiste → stato ScopePackage passa a PREVENTIVATO (append f_progetto_scopes)
```

**I5 compatibility:** l'invariant classify deterministico vale per `ingest/classify.py` datahub pipeline. Qui è **estrazione** (extraction), non classify. Human in the loop obbligatorio (`estratto_reviewed=True` prima di considerare validi i campi per downstream).

### 4.2 Flow B — Fattura orfana → link a Commitment

Una fattura arriva via pipeline standard (`ingest_movimenti_contabili.py`) in `f_movimenti_contabili`. Il vertical progetti mostra "Inbox fatture orfane": righe `f_movimenti_contabili` per cui **non esiste** InvoiceLink.

Stefano seleziona fattura, UI suggerisce Commitment plausibili (match `fornitore_id`, importo ± 5%, data ≥ data_firma Commitment), Stefano conferma → insert `f_progetto_invoice_link`.

**Nessuna duplicazione:** la fattura resta UNA in `f_movimenti_contabili`.

### 4.3 Flow C — Reconcile fornitore candidate → anagrafica

CLI:
```bash
hotelops progetti fornitori candidate        # lista fornitori con stato_censimento=DA_CENSIRE
hotelops progetti fornitori promote <denorm> --anagrafica-id <id>
```

Promozione segue `entity_protocol_v1` (candidate → approved → active):
1. Append riga in `vault/ontology/suppliers/<slug>.md` (I3 SSOT ontologia).
2. Sync a `d_anagrafica_fornitori` via loader esistente (include `alias` array, `stato_censimento=CENSITO`).
3. Riconciliazione downstream (APPEND audit):
   - Commitments con `fornitore_denorm` match → nuova riga APPEND con `fornitore_id` popolato.
   - Documenti (APPEND immutabili): nessuna scrittura retroattiva. `fornitore_denorm` resta; join on-demand via `d_anagrafica_fornitori.alias`.

### 4.4 Flow D — Forward-flow Commitment → f_piano_finanziario_input (NUOVO)

Scheduler CLI o trigger post-commitment-change:
```bash
hotelops progetti forward-flow --progetto HPAN25PIANO1 --dry-run
hotelops progetti forward-flow --progetto HPAN25PIANO1        # applica
```

Algoritmo:
```
per ciascun Commitment con stato ∈ (FIRMATO, IN_CORSO):
  per ciascuna PaymentSchedule rata con stato=PIANIFICATA:
    mese = date_trunc(rata.data_prevista, MONTH)
    societa = commitment.societa_pagante_id
    if commitment.tipo_spesa == CAPEX:
        voce = 'INVESTIMENTI_CAPEX'
    else:  # OPEX (es. Hospitality Project PM fee ORTI)
        voce = lookup_opex_voce(commitment.fornitore_id, scope_package.categoria)
    importo = rata.importo_eur
    chiave = (societa, voce, mese, fonte='PROGETTI', progetto_id)
    emit row in f_piano_finanziario_input
```

**Idempotenza:** Before emit, DELETE `f_piano_finanziario_input` WHERE `fonte='PROGETTI'` AND `progetto_id=<p>`, poi INSERT. Il campo `progetto_id` serve come SNAPSHOT key (SNAPSHOT pattern come altri lifecycle SNAPSHOT del platform). Richiede aggiunta colonna `progetto_id` nullable su `f_piano_finanziario_input` (righe con `fonte=PROGETTI` valorizzate, altre fonti NULL).

**Coord con Session 1 (Gasparotto Cash-Flow):** la nuova voce `INVESTIMENTI_CAPEX` va aggiunta in `core/bq/dimensioni/d_voci_piano_finanziario.csv` prima di qualunque scrittura. Se Session 1 ristruttura `d_voci_piano_finanziario`, il forward-flow resta valido — cambia solo il literal `voce='INVESTIMENTI_CAPEX'` in config.

**Lookup opex voce (OPEX commitments):**
- Default mapping in config: `{PM: 'CONSULENZE', CONSULENZE: 'CONSULENZE', PROGETTAZIONE: 'CONSULENZE'}`.
- Fallback: `CONSULENZE` (voce esistente in `d_voci_piano_finanziario`).
- Override manuale per Commitment via campo `voce_pf_target`.

### 4.5 Storage Drive

Struttura già esistente: `investimenti2026/` (vedi `vault/ontology/projects/CamerePrimoPiano.md`).

MVP convention:
```
investimenti2026/
└── HPAN25PIANO1/
    ├── preventivi/
    ├── contratti/
    ├── ordini/
    ├── fatture/
    ├── SAL/
    └── altro/
```

Accesso via `core.datahub_sync` (rclone wrapper già centralizzato). Upload via rclone put; bidirezionale (read esistente + write per drop documenti).

---

## 5. UI — Streamlit app

**Nuova app:** `progetti/app_projects.py` (avvio: `streamlit run progetti/app_projects.py`).

Non integrata in `app_cdg.py` (MVP). Integrazione è H2.

### 5.1 View 1 — Register (Registro dinamico impegni)

Selettore progetto → tabella unificata:

| ScopePackage | Categoria | Stato | Fornitore | Importo | Fonte | Δ overrun |
|---|---|---|---|---:|---|---:|
| (per ogni scope del progetto) |

Colonne:
- **Stato**: ScopePackage state (IDENTIFICATO/PREVENTIVATO/IMPEGNATO/CHIUSO).
- **Fornitore**: vendor del Commitment linkato, o "—" se orfano.
- **Importo**: cascade `COALESCE(commitment.importo_impegnato, max(preventivo.importo), scope.importo_stimato)`.
- **Fonte**: badge `STIMA | PREVENTIVO | COMMITTED | FATTURATO`.
- **Δ overrun**: da `v_commitment_status.delta_overrun_eur` se applicabile, semaforo colorato.

KPI in header: cap, speso, committed, stimato, **buffer residuo con semaforo**.

### 5.2 View 2 — Documents (Drop + aggregazione)

Due sub-tab:
- **Drop documento** (Flow A): drag & drop + LLM pre-extract + review + submit.
- **Fatture orfane** (Flow B): lista `f_movimenti_contabili` senza InvoiceLink, con suggest Commitment (match fornitore + importo).

Filtri: per progetto, per scope, per fornitore, per tipo, per data range.

Lista documenti: tipo, fornitore, data, importo, stato_preventivo (se PREVENTIVO), confidence, reviewed, link Drive.

### 5.3 View 3 — Budget evolution (Timeline budget)

Per progetto selezionato, linea temporale:
- Snapshot budget iniziale (cap).
- Ogni **evento** che modifica budget proiettato: nuovo scope stimato, preventivo ricevuto, commitment firmato, fattura (overrun/underrun).
- Grafico stacked: Stima / Preventivo / Committed / Fatturato / Pagato nel tempo.
- Tabella eventi: data, scope, tipo evento, delta, importo proiettato post-evento.

Rollup: `v_progetto_timeline`.

### 5.4 View 4 — Payment planning (Piano pagamenti)

Tabella cashflow mensile da PaymentSchedule:

| Mese | ORTI capex | ORTI opex | INTUR capex | INTUR opex | Totale |
|---|---:|---:|---:|---:|---:|

Sub-tab scenari:
- **Baseline**: rate alle date previste.
- **Ritardo 30gg**: shift rate `PIANIFICATA` di +30gg.
- **Anticipo 15gg**: shift rate `PIANIFICATA` di −15gg.

Button "Esporta forward-flow" → invoca `hotelops progetti forward-flow` e riporta diff (quali righe cambiano in `f_piano_finanziario_input`).

### 5.5 Schermata admin (extra)

Admin fornitori candidate: `stato_censimento=DA_CENSIRE`. Bottone "Promuovi" → Flow C.

---

## 6. Testing

**Posture:** TDD dove possibile, coverage target 90% su moduli nuovi.

### 6.1 Unit

- `tests/test_projects_models.py` — Pydantic validation: enum, nullability, edge cases su 7 entità + ScopeCommitmentLink.
- `tests/test_projects_extract.py` — LLM extraction: mock Claude Haiku, JSON parsing, confidence, fuzzy supplier matching (rapidfuzz boundaries 0.7/0.9).
- `tests/test_projects_state_machines.py` — transizioni valide/invalide per Commitment, ScopePackage, Document.stato_preventivo.
- `tests/test_projects_forward_flow.py` — solver logic: capex→INTUR voce INVESTIMENTI_CAPEX; opex→ORTI voce CONSULENZE; idempotenza DELETE+INSERT; edge rate stato ≠ PIANIFICATA.
- `tests/test_projects_budget_cascade.py` — budget view: COALESCE impegnato/preventivo/stimato; scope orfano; overrun Commitment.

### 6.2 Integration (BQ)

Marker `bq` (fixture `bq_client` esistente in `tests/conftest.py`):

- `tests/test_projects_bq.py`:
  - Insert Commitment → `v_progetto_commitments_current` returns latest.
  - Insert InvoiceLink → join con `f_movimenti_contabili` popola `v_commitment_status.importo_fatturato_cum_eur`.
  - Overview view: budget vs impegnato vs fatturato matematicamente consistenti.
  - T1 invariant: no duplicazione `f_piano_finanziario_input` per `(fonte=PROGETTI, progetto_id, societa, voce, mese)`.

### 6.3 E2E smoke

`tests/test_projects_smoke.py`:
- Seed fixture HPAN25PIANO1 (4 scope, 2 commitment, 3 documenti, 4 rate).
- Drop preventivo PDF sintetico → estrazione → append BQ.
- Invoca forward-flow → verifica 4 righe in `f_piano_finanziario_input` fonte=PROGETTI.
- Invoca view → numeri aggregati match atteso.

### 6.4 Non-goal test

Streamlit UI components non hanno test automatici (basso ROI single-user MVP).

---

## 7. Anti-goals (esplicito out of MVP)

| Fuori scope | Perché |
|---|---|
| Multi-utente / permessi | Single user. Entra se emerge audience (I7). |
| Pagamenti automatici | Decisione umana. Sistema informa, non esegue. |
| Bank reconciliation automatica | `f_banche_movimenti` ↔ InvoiceLink è H2. Pagamento = flag manuale. |
| LLM in `ingest/classify.py` | I5 invariant. LLM solo in-app con human review. |
| Tagging retroattivo `progetto_id` su fact canoniche | H2. MVP: forward-flow via `f_piano_finanziario_input`. |
| Algoritmo scoring/ranking preventivi | Decisione umana. UI comparativa, non decisionale. |
| Refactor `app_cdg.py` | App separata in MVP. Integrazione H2. |
| Scrittura verso Esolver | Esolver resta sola input. No round-trip. |
| Gestione centri di costo Esolver | Già in `d_categorie_conti`. Progetto è dimensione parallela. |
| Workflow approvazioni multi-step | Single user. Approvazione = "Stefano ha reviewato". |
| I10 come invariant platform | Ritirato → business rule vertical in `vault/ontology/business-rules/`. |

---

## 8. Open questions / H2 roadmap

1. **Ricorrenti come progetti permanenti** — `HPAN_STAGIONE_2026`? Decidere dopo 1-2 mesi MVP.
2. **`v_previsione_cassa` derivata dai Commitments** — richiede I9 pieno su fact canoniche.
3. **Integrazione `app_cdg.py`** — vista Project come tab quando pattern validato.
4. **I9 promozione a invariant** — dopo 2-3 mesi MVP operativo, decision stub in `vault/decisions/`.
5. **Drive bidirezionale** — oggi rclone read+write via shell. Valutare switch a Drive API OAuth quando serve atomicità upload.
6. **Retroattività per fatture ante-MVP** — serve CLI `hotelops progetti retro-link` per linkare fatture HPAN25PIANO1 già presenti in `f_movimenti_contabili` pre-MVP a Commitments nuovi? In MVP: manual via UI orfane.

---

## 9. Coord con Session 1 (Gasparotto Cash-Flow)

Punto di contatto: **`d_voci_piano_finanziario`** + **`f_piano_finanziario_input.fonte` enum**.

Questo MVP:
- Aggiunge voce `INVESTIMENTI_CAPEX` in `core/bq/dimensioni/d_voci_piano_finanziario.csv`.
- Aggiunge `progetto_id` nullable su `f_piano_finanziario_input`.
- Aggiunge valore `PROGETTI` al dominio `fonte`.

Se Session 1 ristruttura `d_voci_piano_finanziario` (es. nuova tassonomia o struttura multi-level), serve merge coordinato. Fino a quel momento, MVP procede in parallelo senza conflitti di schema (colonne nuove, valori enum nuovi, no breaking change).

---

## 10. Related

- `docs/progetti/HPAN25PIANO1-walkthrough.md` — seed data + rotture validate
- `vault/INVARIANTS.md` — I1–I8 (MVP rispetta; I9 candidato forward-flow non retroattivo)
- `vault/AI_INSTRUCTIONS.md` — Canonical Truth Registry
- `vault/entity_protocol_v1.md` — promozione fornitori candidate
- `vault/ontology/projects/CamerePrimoPiano.md` — ontologia progetto (da aggiornare in capture)
- `core/schemas.py` — nuovi modelli Pydantic
- `core/bq/views/` — 6 nuove view SQL
- `core/bq/dimensioni/d_voci_piano_finanziario.csv` — aggiunta `INVESTIMENTI_CAPEX`
- `progetti/` — nuovo package Python (models, extract, forward_flow, cli_commands, app_projects.py)
- `vault/ontology/business-rules/capex-opex-allocation.md` — nuovo file (capture post-MVP)
- `vault/decisions/2026-04-21_Projects_Vertical.md` — decision stub (capture fine-MVP)

---

## 11. Implementation (post-plan)

- Branch: `projects-mvp-hpan25piano1`
- Plan TDD: `docs/superpowers/plans/2026-04-20-projects-mvp.md`
- Target: tutti i test verdi + HPAN25PIANO1 seed caricato + 5 success criteria §2.4 verificati manualmente + forward-flow row in `f_piano_finanziario_input` fonte=PROGETTI visibile a Rosa/Gasparotto.

*Sezione Implementation popolata con commit hashes durante l'esecuzione.*
