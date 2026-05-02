# Doc Refresh Sprint — 2026-05-01

**Status:** ready
**Owner:** Stefano (approval) + Claude Code (execution)
**Tempo stimato totale:** ~3h end-to-end
**Working mode:** Plan-First. Per ogni step Claude Code propone il diff esatto → aspetta approvazione Stefano → esegue → passa al successivo. Niente scritto senza approvazione.

## Context

`CLAUDE.md` (v0.6.0, checkpoint 2026-04-30) e `README.md` sono drift-ati rispetto allo stato reale del repo. La frame attuale (digital twin / company OS, da `vault/IDENTITY.md` + meeting brief `docs/superpowers/specs/2026-04-30-meeting-brief-roadmap-architecture.md`) non è riflessa nei doc front-door. In più ci sono 4 capture pendenti dal session log dell'altra sessione (vocab fix, cutover decision, TODO markers, Epistemology promotion) che vanno chiuse insieme al refresh dei doc.

## Dipendenze

Step ordinati così che ognuno renda il successivo più pulito. Step 3-6 possono atterrare anche se Step 1-2 sono ritardati (con condizionali esplicite per riga).

---

## Step 1 — Vocabulary fix

**File:** `docs/architecture/AI_INSTRUCTIONS.md`
**Azione:** edit mirato, sezione "Personas / Vocabolario canonico" (creare se non esiste).
**Contenuto:**

- Gasparotto = file Master Excel di Roberto Romita (consulente CdG). **Non è una persona.**
- Rosa = persona reale (amministrazione, tesoreria) + il suo file scadenziario fornitori in Drive.
- Romita = la persona dietro il file "Gasparotto".

Sblocca vocab corretto in tutti i doc successivi. ~5 minuti.

## Step 2 — Data Engineering Rules

**Pre-step:** contenuto Rules doc da concordare in chat con Stefano prima del diff. MUST includere:

- Lineage columns (`pipeline_run_id`, `pipeline_name`) su ogni nuova fact table — schema contract, non opt-in
- `bq_write_validated` come unico gate di scrittura in BQ
- Naming canonico: `f_*` (facts), `d_*` (dimensions), `v_*` (views) — niente `stg_/mart_` finché non c'è layer di trasformazione separato
- Plan-first per pipelines finanziarie / fornitori / progetti / cashflow
- Prefer views over tables per logica derivata
- Assertions: uniqueness, not-null, allowed values, date validity

**File NEW:** `docs/architecture/DATA_ENGINEERING_RULES.md`
**File:** `CLAUDE.md`
**Azione:** aggiungere riga in reading list "For AI agents":

```
4. `docs/architecture/DATA_ENGINEERING_RULES.md` — pipeline standards e schema contract
```

## Step 3 — README.md rewrite

**File:** `README.md`
**Azione:** rewrite con draft concordato in chat (frame digital twin / company OS).
**Condizionale:** se Step 2 è atterrato, includere riga `DATA_ENGINEERING_RULES.md` nella reading list; altrimenti omettere.
**Acceptance:** menziona condges + reviews come verticali in produzione, vocab CASSA/COMPETENZA (no Gasparotto), pointer a INVARIANTS / AI_INSTRUCTIONS / LE_3_DIMENSIONI / CLAUDE.md.

## Step 4 — CLAUDE.md Project Overview + Architecture

**File:** `CLAUDE.md`
**Sezioni da rimpiazzare:**

- `## Project Overview` — paragrafo parallelo al README rewrite
- `## Architecture` — sostituire directory listing corrente con:
  1. Diagram ASCII Raw → Canonical → Semantic → Operational (quella prodotta dall'altra sessione, conserva I1/I5 inline e vocab Romita)
  2. Sottosezione "Module reference" con file listings aggiornati. Aggiungere:
     - `core/bq/write.py` (gate I1!), `core/bq/dedup.py`, `core/bq/manifest.py`, `core/bq/SCHEMA_CONTEXT.md`
     - `core/ontology.yaml` (a fianco di `registry.yaml`)
     - `condges/bq_data.py`, `cashflow.py`, `export_excel.py`, `materialize_reconciliation.py`, `parse_pf.py`, `tesoreria.py`, `Dockerfile`
     - `ingest/flussi/ingest_bilanci_annuali.py`, `ingest_consumi_economato_consolidato.py`, `ingest_pms_statistiche.py`, `ingest_scheda_190101.py`, `ingest_vendite_fb.py`

## Step 5 — CLAUDE.md sezioni mancanti

**File:** `CLAUDE.md`
**Aggiungere sezioni:**

- `## Documentation (docs/)` — architecture, adr, procedures, progetti, protocols, superpowers (specs + plans), vault-snippets
- `## Meta (meta/)` — reference (PDC files, INTUR_ORTI_relationship), skills (hotelops-ops, save-game)
- `## Slash commands (.claude/commands/)` — hotelops-tech-lead, session-context, vault-loop
- 1-liner su `STATUS.md` a root

## Step 6 — CLAUDE.md counts + tests refresh

**File:** `CLAUDE.md`
**Pre-step:** risolvere discrepanza views (directory tree mostra 19 file `.sql`; diagram dell'altra sessione dice 18). Verificare con `ls core/bq/views/*.sql | wc -l` e usare il numero verificato.
**Update:**

- "16 SQL view definitions" → numero verificato (probabilmente 19)
- "9 scripts" dimension loaders → 11 (incluso `create_progetti_tables`, `seed_progetti_step1`)
- Tests section: aggiungere `test_bq_write` (gate I1), `test_bq_dedup`, `test_accodamenti_parser`, `test_cashflow`, `test_parse_pf`, `test_progetti_schema`

## Step 7 — Cutover decision

**File NEW:** `vault/decisions/2026-05-01_HotelCube_Operating_Entity_Cutover.md`
**Contenuto:**

- **Decisione:** `OPERATIONS_CUTOVER_DATE = 2025-04-01`
- Pre-cutover → INTUR; post-cutover → ORTI
- **Sistemi impattati:**
  - `f_accodamenti` (bug retroattivo: hardcodes ORTI anche per 2024 — fix tecnico separato, parking lot)
  - `f_produzione_pms` (futuro, by construction nel design)
  - Viste downstream che attribuiscono ricavi storici a società
- **Riferimento spec:** `docs/superpowers/specs/2026-04-29-produzione-pms-ingest-design.md`

## Step 8 — TODO markers in codice

**File:** `ingest/banca/ingest.py`
**Azione:** aggiungere commento sui due punti dove c'è `client.load_table_from_dataframe`:

```python
# TODO Sprint 4: replace with bq_write_validated + filter_new_rows_by_hash
```

Capture pre-Sprint-4: il workflow attuale bypassa il gate I1, è debito noto. Il marker resta nel posto giusto fino al refactor.

## Step 9 — Agent Epistemology promotion

**Source:** `vault/architecture/Agent_Epistemology_Problem.md` (status: unresolved)
**Target:** `docs/architecture/AI_INSTRUCTIONS.md`, nuova sezione "Modi operativi"
**Contenuto:**

- 3 modi: Research Assistant (default) / Verified Responder (strict) / Tool Executor
- Criteri di selezione per modo
- Un esempio per modo. La "Gargano coast" hallucination è il caso paradigmatico per Verified Responder.

**Cleanup vault-side:** dopo merge, marcare il source come `status: promoted to AI_INSTRUCTIONS.md` e spostare in `vault/archive/`.

---

## Parking lot (non in questa scaletta)

- `concepts/INTERCOMPANY_SPIAGGIA.md` — BE* classes ambigue ORTI vs INTUR
- ADR Sprint 4 banche → gate I1 (parte quando Sprint 4 è schedulato)
- D2 Module Catalog (sessione pianificazione separata, scope diverso)
- Bug retroattivo `f_accodamenti` (hardcoded ORTI per 2024) — fix tecnico, non doc

---

## Note di esecuzione

- **Tempo per step:** Step 1, 8 sono <10 min ciascuno. Step 2, 9 richiedono content design in chat prima del diff (~30 min ciascuno). Step 3-6 sono il grosso del lavoro doc (~1.5h totali). Step 7 ~15 min.
- **Vault path:** Step 7 presume esista la cartella `vault/decisions/` nel vault Obsidian. Se il path canonico è diverso (es. `<vault>/HotelOps/decisions/`), adattare.
- **Conflict avoidance:** evitare di lanciare Step 4-6 su `CLAUDE.md` in parallelo — sono lo stesso file, eseguire in serie.
- **Verification post-merge:** dopo Step 6, lanciare `ruff check .` e `pytest --collect-only` per confermare niente è rotto. I doc non hanno test ma il refresh dei tests count va verificato contro l'output reale di pytest.
