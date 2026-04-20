# Projects MVP — CapEx & Cantiere Control as CONDGES Extension

**Date:** 2026-04-20
**Status:** Draft (awaiting user review)
**Author:** Stefano + Claude (brainstorming session)
**Scope:** Introdurre il **Progetto** come dimensione di primo livello del controllo di gestione, estendendo CONDGES (non creando un nuovo vertical). MVP popolato con `HPAN25PIANO1` (Camere Primo Piano) su schema multi-progetto da day 1.

---

## 1. Direzione (candidato I9)

> **Il Progetto è una dimensione obbligatoria del controllo di gestione.**
> Sub-principio: *"se aspetti che il budget diventi preciso, è troppo tardi"* — la struttura dati esiste prima che i numeri siano stabili; man mano che arrivano documenti (preventivi → contratti → fatture), i numeri si raffinano, ma la forma non cambia.

Non è ancora un invariant applicato retroattivamente a tutti i fatti finanziari (I9 futuro). In MVP il tagging `progetto_id` vive **solo** nelle nuove tabelle (`f_progetto_*`). Le fact table canoniche esistenti (`f_movimenti_contabili`, `f_partite_aperte_fornitori`, `f_banche_movimenti`) **non vengono modificate**: il link progetto↔fattura passa tramite `f_progetto_invoice_link` (thin join), non via colonna aggiunta.

Quando I9 maturerà (dopo validazione MVP), si valuterà l'aggiunta di `progetto_id` nullable alle fact canoniche con default `"CORRENTE"` (gestione ordinaria non-CapEx).

### Posizionamento

Non è un vertical a sé: è **un terzo zoom del CdG Gasparotto-unificato**.

| Zoom | Domanda | Oggi | Dopo |
|---|---|---|---|
| Aziendale | "Come va ORTI 2026?" | ✅ `v_budget_vs_consuntivo`, `v_piano_finanziario_mensile` | invariato |
| Mensile | "Questo mese ho rispettato il budget?" | ✅ `hotelops chiudi`, `v_budget_canonical` | invariato |
| **Progetto** | "HPAN25PIANO1 sta sforando? Quanto devo pagare a STE questo mese?" | ❌ | ✅ questo MVP |

---

## 2. Scope & Audience

### 2.1 Audience

Singolo utente: **Stefano Della Pietra Jr** (owner platform).
Non Antonio (GM, non gestisce cantiere). Non Rosa (tesoreria operativa, non progetti).
Non serve multi-utente né permessi → rispettato **I7** (audience umana esplicita).

### 2.2 MVP scope

- Schema multi-progetto generico da day 1 (`d_progetti` + FK `progetto_id` ovunque).
- Popolato inizialmente con UN progetto reale: **HPAN25PIANO1 — Camere Primo Piano**.
  - ~€350K budget
  - 10 camere, impiantistica + arredi + finiture
  - Fornitori già noti: STE, SANTELIA, Dierre, Studio Ninni, Atelier Hospitality, Geberit, Frattini, Rocky, Comoda
  - Team: Amalia Pisacane (DL), Antonio Russo (GM), Marco Pignocchi + Filippo Faggioli (Hospitality Project), Anna Capone (Studio Ninni), Savio Marigliano (architetto)
  - Contratti firmati 27/02/2026 (STE, SANTELIA, ordine Dierre n.864)
- Drop + classifica + estrazione LLM documenti.
- UI Streamlit con 4+1 schermate.
- Integrazione con canonical sources esistenti (no duplicazione).

### 2.3 Out of MVP (future roadmap — vedi §8)

- Ricorrenti come "progetti permanenti" (stagione Hotel, gestione corrente).
- `v_previsione_cassa` derivata dai commitment dei progetti.
- Integrazione dentro `app_cdg.py` (MVP usa app separata).
- `progetto_id` obbligatorio su tutti i fatti (I9 pieno).

### 2.4 Success criteria

Su HPAN25PIANO1, Stefano deve poter rispondere in <30 secondi:

1. **Quanto ho impegnato vs budget a oggi?** (view `v_progetto_overview`)
2. **Quali documenti arrivano questo mese e quanto fanno in cassa?** (view `v_progetto_timeline`)
3. **Per la commessa arredi, quali preventivi ho e quale ho scelto?** (UI confronti)
4. **Quale fattura è entrata ma non ho ancora collegato a una commessa?** (UI inbox fatture orfane)

---

## 3. Data model

### 3.1 Entità (4)

```
Project (1) ──── (N) Commitment ──── (N) Document
                        │
                        └──── (N) InvoiceLink ──── (1) f_partite_aperte_fornitori
```

- **Project** — il progetto (HPAN25PIANO1). Long-lived, raro che cambi.
- **Commitment** — singolo impegno all'interno del progetto (es. "Impiantistica elettrica STE", "Arredi camere Atelier"). Ha un budget, uno stato lifecycle, un fornitore (o NULL se ancora non scelto).
- **Document** — polimorfico: preventivo | contratto | ordine | SAL | altro. Appeso al Commitment (o al Project se pre-commit). Storage: Drive + metadata BQ.
- **InvoiceLink** — tabella *thin* che collega una riga di `f_partite_aperte_fornitori` a un Commitment. Zero duplicazione dell'invoice (rispetta **I8**).

### 3.2 State machine Commitment

```
PREVENTIVO → CONTRATTO_FIRMATO → IN_CORSO → CHIUSO
                                    │
                                    └──→ ANNULLATO
```

Transizioni sono fatti audit (APPEND). Nessun UPDATE in BQ.

### 3.3 Schema Pydantic (`core/schemas.py` additions)

```python
class Project(BaseModel):
    progetto_id: str                          # HPAN25PIANO1
    nome: str                                 # "Camere Primo Piano - Hotel Panorama"
    societa_id: Literal["ORTI", "INTUR"]
    business_unit_id: str                     # HOTEL
    struttura: str                            # "Hotel Panorama"
    data_inizio: date
    data_fine_prevista: date | None
    budget_totale_eur: Decimal
    stato: Literal["PIANIFICATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    owner: str                                # "Stefano Della Pietra Jr"
    direzione_lavori: str | None              # "Amalia Pisacane"

class Commitment(BaseModel):
    commitment_id: str                        # UUID
    progetto_id: str                          # FK Project
    descrizione: str                          # "Impiantistica elettrica camere 121-130"
    categoria: Literal["IMPIANTI", "ARREDI", "FINITURE", "CONSULENZE", "ALTRO"]
    fornitore_id: str | None                  # FK d_anagrafica_fornitori (nullable)
    fornitore_denorm: str                     # "STE srl" — sempre presente, gestisce candidate
    importo_impegnato_eur: Decimal
    stato: Literal["PREVENTIVO", "CONTRATTO_FIRMATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    data_stato: datetime
    note: str | None

class Document(BaseModel):
    document_id: str                          # UUID
    owner_type: Literal["PROJECT", "COMMITMENT"]
    owner_id: str                             # progetto_id OR commitment_id
    tipo: Literal["PREVENTIVO", "CONTRATTO", "ORDINE", "SAL", "ALTRO"]
    fornitore_denorm: str | None
    numero_documento: str | None              # "864" (Dierre)
    data_documento: date | None
    importo_eur: Decimal | None
    drive_path: str                           # "investimenti2026/HPAN25PIANO1/..."
    file_hash_md5: str                        # dedup
    estratto_confidence: float                # 0.0-1.0 (LLM quality)
    estratto_reviewed: bool                   # True = umano ha validato
    note: str | None

class DocumentoStato(BaseModel):
    # APPEND audit log per stato di scelta (usato solo per tipo=PREVENTIVO)
    stato_id: str                             # UUID
    document_id: str                          # FK Document
    stato_scelta: Literal["NEUTRO", "SELEZIONATO", "SCARTATO"]
    data_stato: datetime
    note: str | None

class InvoiceLink(BaseModel):
    link_id: str                              # UUID
    commitment_id: str                        # FK Commitment
    partite_row_hash: str                     # hash riga f_partite_aperte_fornitori (UNIQUE)
    note: str | None
    # PK: link_id. Unique constraint on partite_row_hash (1 fattura → max 1 commitment).
```

### 3.4 Schema BigQuery

Sei tabelle nuove:

| Tabella | Lifecycle | Note |
|---|---|---|
| `d_progetti` | SNAPSHOT per `progetto_id` | Dimensione (bassa mutability) |
| `f_progetto_commitments` | APPEND audit log | Ogni transizione è una riga; latest-state via view |
| `f_progetto_documenti` | APPEND | Dedup su `file_hash_md5`. Immutabili (metadata di un file che esiste). |
| `f_progetto_documento_stato` | APPEND audit log | Storico `stato_scelta` per PREVENTIVO (NEUTRO/SELEZIONATO/SCARTATO); latest via view |
| `f_progetto_invoice_link` | SNAPSHOT per `link_id` | Può essere rivisto (riattacco fattura a commitment diverso se errore) |
| `f_progetto_extractions` | APPEND | Audit LLM: `document_id`, `model`, `raw_output`, `parsed_fields`, `ts_extraction` — mai sovrascritto |

Quattro view:

| View | Scopo |
|---|---|
| `v_progetto_commitments_current` | Latest state per `commitment_id` (row-selection centralizzata → **I8**) |
| `v_progetto_documenti_current` | Latest `stato_scelta` per `document_id` (row-selection in view → **I8**) |
| `v_progetto_overview` | Per progetto: budget vs impegnato vs fatturato vs pagato |
| `v_progetto_timeline` | Eventi ordinati: firma contratto, arrivo fattura, pagamento, SAL |

**FK su canonicals esistenti** (nessuna duplicazione):
- `fornitore_id` → `d_anagrafica_fornitori` (nullable per gestire candidate)
- `partite_row_hash` → hash riga `f_partite_aperte_fornitori` (la fattura vive lì, non duplicata)

### 3.5 Adattamenti HotelOps-specifici (3)

1. **`fornitore_id` FK nullable + `fornitore_denorm` sempre presente.** Permette di ingestire documenti da fornitori non ancora anagrafati in Esolver, mantenendo tracciabilità. Promozione candidate → `d_anagrafica_fornitori` via `entity_protocol_v1` (CLI comando dedicato).
2. **No tabella Invoice.** La fattura vive già in `f_partite_aperte_fornitori` (canonical IMPEGNO). `f_progetto_invoice_link` è una tabella *thin* che collega — zero duplicazione (**I8**, Canonical Truth Registry).
3. **Commitment come APPEND audit.** State transitions = nuove righe, non UPDATE. Lifecycle corrente via `v_progetto_commitments_current` con ROW_NUMBER OVER (PARTITION BY commitment_id ORDER BY data_stato DESC) — row-selection in view canonica (**I8**).

---

## 4. Ingestion flows

### 4.1 Flow A — Drop documento con pre-estrazione LLM

```
1. UI "Inbox drop zone" (Streamlit): drag PDF/Excel
2. Salvataggio temporaneo + computo MD5
3. Chiamata Claude Haiku con prompt strutturato:
   → JSON schema {tipo, fornitore, numero_doc, data_doc, importo, descrizione}
   → + confidence score per field
4. UI mostra fields pre-compilati + highlight bassa confidence
5. Stefano review/edit
6. Submit:
   - scrive riga in f_progetto_documenti (estratto_reviewed=True)
   - logga tutto il round-trip in f_progetto_extractions (audit)
   - copia file su Drive in investimenti2026/<progetto>/<commitment_short>/
```

**I5 compatibility note.** L'invariant I5 (classify deterministico) si applica al classify pipeline `ingest/classify.py` che routa file dal datahub alle pipeline BQ. Qui siamo in un'altra lane: **estrazione entità da documento già classificato come "project document"**, con *human in the loop* obbligatorio (`estratto_reviewed`). Non è un bypass I5.

**Fornitore matching.** Dopo estrazione, fuzzy match (Levenshtein) contro `d_anagrafica_fornitori.ragione_sociale`:
- Score ≥ 0.9 → auto-link `fornitore_id`
- Score 0.7-0.9 → suggest + asking conferma
- Score < 0.7 → marca come candidate (fornitore_id=NULL, fornitore_denorm=estratto)

### 4.2 Flow B — Fattura orfana → link a commitment

Una fattura arriva via pipeline standard (`ingest_partite_aperte.py`) in `f_partite_aperte_fornitori`.
L'app progetti ha una tab "Inbox fatture orfane": tutte le righe di `f_partite_aperte_fornitori` per cui **non esiste** un `InvoiceLink`.

Stefano seleziona la fattura, UI suggerisce commitment plausibili (stesso fornitore_id, importo vicino), Stefano conferma → insert in `f_progetto_invoice_link`.

Nessuna duplicazione: la fattura rimane UNA in `f_partite_aperte_fornitori`.

### 4.3 Flow C — Reconcile fornitore candidate → anagrafica

CLI:
```
hotelops progetti fornitori candidate       # lista fornitori candidate in commitment/documenti
hotelops progetti fornitori promote <denorm> --anagrafica-id <id>
```

Promozione segue **entity_protocol_v1** (candidate → approved → active). Scrittura:
1. Append riga in `ontology/suppliers/` nel vault (**I3**, SSOT)
2. Sync verso `d_anagrafica_fornitori` via loader esistente (include `alias` array per match futuri)
3. Riconciliazione in downstream:
   - **Commitments** (APPEND audit): per ogni commitment con `fornitore_denorm` che matcha, scrivi nuova riga APPEND con `fornitore_id` popolato (state machine = `IN_CORSO` invariato, è un'update di identità non di stato)
   - **Documenti** (APPEND immutabili): nessuna scrittura. `fornitore_denorm` resta; resolution verso `fornitore_id` avviene via JOIN on-demand a `d_anagrafica_fornitori.alias` nelle view consumer

### 4.4 Storage Drive

Struttura già esistente: `investimenti2026/` (vedi `ontology/projects/CamerePrimoPiano.md`).

MVP convention:
```
investimenti2026/
└── HPAN25PIANO1/
    ├── preventivi/
    ├── contratti/
    ├── ordini/
    ├── SAL/
    └── altro/
```

Accesso via `core.datahub_sync` (rclone wrapper già centralizzato).

---

## 5. UI — Streamlit app

**Nuova app:** `condges/app_projects.py` (avviabile con `streamlit run condges/app_projects.py`).

Non integrata in `app_cdg.py` (MVP). Integrazione in H2 quando il pattern è validato.

### 5.1 Schermata 1 — Lista Progetti

Tabella tutti i progetti in `d_progetti` con stato, budget, impegnato, fatturato, % avanzamento.
Click su riga → Vista Progetto.

### 5.2 Schermata 2 — Inbox (docs + fatture orfane)

Due tab:
- **Drop documento** (Flow A): drag & drop + LLM pre-extract + review.
- **Fatture orfane** (Flow B): lista `f_partite_aperte_fornitori` senza `InvoiceLink`.

### 5.3 Schermata 3 — Vista Progetto (tab)

Sub-tabs:
- **Overview** — KPI + grafico budget/impegnato/fatturato/pagato nel tempo.
- **Commesse** — tabella `v_progetto_commitments_current` con stato corrente, filtri per categoria/stato.
- **Documenti** — tutti i Document del progetto, filtri per tipo/fornitore.
- **Timeline** — `v_progetto_timeline` eventi cronologici.
- **Fatture** — fatture linkate via `InvoiceLink`.

### 5.4 Schermata 4 — Confronti preventivi

Per un Commitment in stato PREVENTIVO con ≥2 preventivi:
- Side-by-side di tutti i preventivi (importo, fornitore, data, note).
- Bottone **"Scegli"** per ciascuno. Submit → una transazione scrive:
  1. Nuova riga in `f_progetto_commitments` (stato → `CONTRATTO_FIRMATO`, `fornitore_id` preso dal Document vincitore)
  2. Nuova riga in `f_progetto_documento_stato` (`stato_scelta=SELEZIONATO`) per il Document vincitore
  3. Nuova riga in `f_progetto_documento_stato` (`stato_scelta=SCARTATO`) per ciascun altro Document dello stesso Commitment
- Tutte APPEND, idempotenti (rerun = nuove righe con `data_stato` più recente, view risolve).

**Non** è un algoritmo di scoring/ranking automatico. È una vista di confronto per decisione umana.

### 5.5 Schermata +1 — Admin fornitori candidate

Lista fornitori candidate (`fornitore_id=NULL`, `fornitore_denorm=<nome>`). Bottone "Promuovi" apre flow entity_protocol_v1 (Flow C).

---

## 6. Testing

Test posture: TDD dove possibile, coverage target **90%** su moduli nuovi.

### 6.1 Unit tests

- `tests/test_projects_models.py` — Pydantic validation (Project, Commitment, Document, InvoiceLink): enum, nullability, edge cases.
- `tests/test_projects_extract.py` — LLM extraction: mock Claude Haiku response, parsing JSON, confidence scoring, fuzzy supplier matching (Levenshtein boundaries 0.7/0.9).
- `tests/test_projects_state_machine.py` — state transitions valide/invalide (es. non si può andare da `CHIUSO` a `IN_CORSO`).

### 6.2 Integration tests

- `tests/test_projects_bq.py` — con marker `bq` (fixture `bq_client` esistente):
  - Insert commitment → verify `v_progetto_commitments_current` returns latest.
  - Insert InvoiceLink → verify join con `f_partite_aperte_fornitori`.
  - Overview view: budget vs impegnato vs fatturato matematicamente consistenti.

### 6.3 E2E smoke

`tests/test_projects_smoke.py`:
- Carica dati fixture di HPAN25PIANO1 (3 commitments, 5 documenti).
- Drop preventivo PDF sintetico → verifica end-to-end extraction → append in BQ.
- Invoca view → verifica numeri aggregati match atteso.

### 6.4 Non-goal

- Test coverage di `app_projects.py` UI components (Streamlit testing è costoso, basso ROI per MVP single-user).

---

## 7. Anti-goals (out of scope MVP, esplicito)

| Fuori scope | Perché |
|---|---|
| **Multi-utente / permessi** | Single user Stefano. Entra se emerge audience (I7). |
| **Pagamenti automatici** | Decisione paga/non-paga resta umana. Sistema informa, non esegue. |
| **Bank reconciliation automatica** | `f_banche_movimenti` ↔ `InvoiceLink` è H2. MVP: pagamento = manuale flag. |
| **LLM in `ingest/classify.py`** | I5: classify pipeline resta deterministico. LLM solo in-app con human review. |
| **Tagging retroattivo `progetto_id` su tabelle esistenti** | I9 pieno è H2. MVP: nullable, solo nuovi fatti. |
| **Algoritmi di scoring/ranking preventivi** | Decisione umana. UI è comparativa, non decisionale. |
| **Refactor di `app_cdg.py`** | App separata `app_projects.py` in MVP. Integrazione H2. |
| **Mobile / responsive** | Streamlit desktop. |
| **Scrittura verso Esolver** | Esolver resta sola input. Nessun round-trip. |
| **Gestione centri di costo interni Esolver** | Già gestiti da `d_categorie_conti`. Progetto è una dimensione parallela, non sostitutiva. |
| **Workflow approvazioni multi-step** | Single user. Approvazione = "Stefano ha reviewato". |

---

## 8. Open questions / H2 roadmap

1. **Ricorrenti come progetti.** La "gestione corrente" (stagione Hotel, costi fissi ORTI) dovrebbe essere un progetto permanente (`HPAN_STAGIONE_2026`)? Potenzialmente sì — rende I9 universale. Decidere dopo 1-2 mesi di MVP.
2. **`v_previsione_cassa` derivata dai progetti.** Oggi leggi da `f_piano_finanziario_input` + `f_partite_aperte_fornitori`. Se tutti i commitment hanno scadenze previste, la view cash forward potrebbe derivare da lì. Grosso valore ma richiede copertura I9 piena.
3. **Integrazione `app_cdg.py`.** Quando il pattern projects è validato, la vista Project diventa una tab di `app_cdg.py` (terzo zoom). MVP separato per non rompere `app_cdg.py` in fase instabile.
4. **Candidato invariant I9 formalizzato.** Dopo 2-3 mesi di MVP operativo, con dati reali, decidere se promuovere in `INVARIANTS.md` con decision stub `vault/decisions/YYYY-MM-DD_I9_Progetto_Dimensione.md`.
5. **Drive bidirezionale.** Oggi read-only via rclone. Per l'upload di documenti dall'app Streamlit serve Drive API write (OAuth già esistente per Gmail). Decidere MVP: upload diretto, o salvataggio locale + sync manuale?

---

## 9. Related

- `vault/INVARIANTS.md` — I1–I8 (MVP rispetta tutti; I9 candidato non applicato retroattivamente)
- `vault/AI_INSTRUCTIONS.md` — Canonical Truth Registry (no duplicazione `f_partite_aperte_fornitori`)
- `vault/entity_protocol_v1.md` — promozione fornitori candidate
- `vault/ontology/projects/CamerePrimoPiano.md` — dati di seed MVP
- `vault/verticals/CONDGES.md` — vertical in cui si integra
- `core/schemas.py` — nuovi modelli Pydantic
- `core/bq/views/` — quattro nuove view SQL
- `condges/app_projects.py` — nuova app Streamlit
- `condges/projects/` — modulo Python (models, extract, cli_commands)

---

## 10. Implementation (post-plan)

*Da popolare con commit hashes durante implementazione. Decision record separato in `vault/decisions/2026-04-20_Projects_MVP.md`.*

- Branch: `projects-mvp-hpan25piano1`
- Target: tutti i test verdi + HPAN25PIANO1 popolato + 4 success criteria §2.4 verificati manualmente.
