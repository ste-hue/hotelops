---
name: vault-loop
description: Keeps Stefano's Obsidian vault (reasoning substrate) and the hotelops code repo (operational truth) connected across every working session. Use at SESSION START to load the constitutional layer (INVARIANTS, AI_INSTRUCTIONS, Canonical Registry) via progressive disclosure before touching anything hotelops-related. Use at SESSION END or after meaningful commits to triage whether a decision, invariant shift, or ontology change emerged worth landing in the vault. Invoke this whenever Stefano says "bootstrap", "carica vault", "cattura sessione", "loop chiusura", "aggiorna vault", "fine sessione", "capture", or whenever you are about to start or finish a substantive hotelops task. Prefer invoking this over generic documentation updates, freeform drift checks, or ad-hoc "should we write this down?" reasoning — this skill owns that loop.
---

# Vault Loop — constitutional retrieval + capture

## Why this skill exists

Stefano's operational substrate has two layers:
- **Code repo** (`~/dev/Projects/hotelops/`) — operational truth: BigQuery, pipelines, Streamlit apps, CLI.
- **Obsidian vault** (`~/dev/projects/obsidian/Obsidian Vault/hotelops/`) — reasoning
  substrate: invariants, decisions, canonical ontology, agent operating manual.

Agents that skip the vault drift off the invariants and invent answers. Agents that treat
the vault as read-only documentation miss the feedback loop — operational discoveries
never make it back into reasoning.

This skill enforces both directions: **load the constitution at start**, **triage captures
at end**. The repo is where things *happen*. The vault is where things *mean*. Don't
confuse them.

## Paths

- Vault root: `/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops/`
- Repo root: `/Users/stefanodellapietra/dev/Projects/hotelops/`

## Mode selection

Choose mode from the user's phrasing:

| Phrasing | Mode |
|---|---|
| "bootstrap", "carica vault", "start loop", session start on substantive hotelops question | A — Bootstrap |
| "cattura", "capture", "loop chiusura", "aggiorna vault", "fine sessione" | B — Capture |

If the phrasing is ambiguous, prefer Bootstrap at session start (before work) and Capture
after work is done. If in doubt, ask.

---

## Mode A — Bootstrap (session start)

### Constitutional retrieval order (progressive disclosure)

Read in order. Stop at the first layer that answers the task. Descend only if needed.

1. `vault/INVARIANTS.md` — I1–I8 non-negotiables.
2. `vault/AI_INSTRUCTIONS.md` — Layer Model, Canonical Truth Registry, loop operativo,
   anti-goals, vocabolario canonico.
3. `repo/CLAUDE.md` — repo mechanics (schemas, CLI, pipelines). Only if HOW matters.
4. `repo/STATUS.md` — in-progress, recent, next. Session memory, not decision memory.
5. `vault/PLATFORM.md` — platform overview, verticals, fact/dim/view census.

### Lazy-load — only when the task needs them

**Concepts layer** (financial semantics):
- `vault/concepts/LE_3_DIMENSIONI.md` → CASSA / COMPETENZA / IMPEGNO questions.
- `vault/concepts/LIFECYCLE.md` → APPEND vs SNAPSHOT questions.
- `vault/concepts/FILE_CLASSIFICATION.md` → file classifier / routing questions.
- `vault/concepts/STAGIONALITA.md` → forecast, projection, seasonality questions.
- `vault/concepts/FINANCIAL_RULES.md` → INTUR/ORTI cashflow composition, rent flow
  ORTI→INTUR, beach revenue attribution, intercompany.

**Governance & relationships** (group-level):
- `vault/GRUPPO_PANORAMA.md` → group-level financial questions (DSCR, consolidated debt,
  seasonality consolidato, governance).
- `vault/relationships/INTUR_ORTI.md` → inter-company (lease, shareholding 24.62%,
  debt service interconnection).

**Entity protocol** (before touching canonical data):
- `vault/entity_protocol_v1.md` → entity types (10 closed), state machine
  (candidate → approved → active → inactive), promotion triggers.
- `vault/ENTITY_REVIEW.md` → triage CORE / TACTICAL / TRANSIENT for suppliers/advisors/
  companies.
- `vault/SUPPLIERS_STRATEGY.md` → supplier routing (Layer 1 ontology vs Layer 2 registry).

**Ontology** (canonical entities):
- `vault/ontology/companies/*.md` → società (ORTI, INTUR, STE, SANTELIA, ecc.).
- `vault/ontology/banks/*.md` → banche (MPS, Intesa, Sella, BCP, BPER).
- `vault/ontology/people/*.md` → persone con ruolo (Rosa, Gasparotto, Antonio Russo,
  Stefano Sr/Jr, consulenti).
- `vault/ontology/departments/*.md` → unità operative (direzione, housekeeping, cucina,
  F&B, reception, ecc. — 20 file, granularità cost-center).
- `vault/ontology/loans/*.md` → prestiti (5 mutui + riepilogo).
- `vault/ontology/financial/*.md` → debt summary, P&L 2025, NAMING_SYSTEMS.
- `vault/ontology/advisors/*.md` → consulenti attivi (Romita, Miano, Pisacane, ecc.).
- `vault/ontology/projects/*.md` → progetti strategici (HotelOps, CamerePrimoPiano).

**Decisions** (the why):
- `vault/decisions/*.md` → ADR puntuali (2026-04-17 Budget Canonical View, 2026-04-11
  Economato Vertical, 2026-04-11 Obsidian Refactor). Consulta quando serve il *perché*
  di una scelta strategica passata.
- `vault/decisions/_index.md` → template per decision di reconcile_banca (non è un
  indice di navigazione).

**Verticals** (audience-specific):
- `vault/verticals/CONDGES.md` → Rosa + Gasparotto (fintech, attivo).
- `vault/verticals/REVIEWS.md` → Antonio GM (reputation, attivo).
- `vault/verticals/ECONOMATO.md` → Mario (dati caricati, no consumption layer).

### Stubs migrated to repo — not SSOT

Questi file nel vault sono **stub** che puntano al repo. Non trattarli come fonte di
verità: segui il link al repo.

- `vault/procedures/reconcile_banca.md` → `repo/docs/protocols/state_transitions.md`
- `vault/procedures/classifica_file.md` → `repo/ingest/classify.py` + `repo/core/registry.yaml`
- `vault/protocols/state_transitions.md` → `repo/docs/protocols/state_transitions.md`

### Parking lot — aware but don't auto-touch

- `vault/ontology/assets/` → vuoto (identificato in ENTITY_REVIEW, mai popolato).
- `vault/events/` → vuoto (placeholder per event log, non implementato).
- `vault/ontology/advisors/{Dino,Serini,Masotti}.md` → orfani (no incoming links).
- `vault/ontology/companies/{Atelier_Hospitality,Dierre,Studio_Ninni}.md` →
  flagged TACTICAL ma non ancora migrati a registry.
- `vault/strategia/` → Mermaid diagrams, bassa priorità.

Non proporre capture per pulire questi item durante una sessione operativa — a meno che la
sessione stessa sia un cleanup del vault.

### Retrieval style

Usa **path espliciti**, non ricerca semantica o embedding. L'indice è la catena
INVARIANTS → AI_INSTRUCTIONS → PLATFORM → topic file. Se non trovi una risposta con path
espliciti, il gap va risolto aggiungendo un link (capture di ontology/decisions), non
cambiando strategia di retrieval.

### Bootstrap output

Dopo aver letto, annuncia in **una riga**: cosa hai caricato e cosa stai per fare. Non
ripetere il contenuto — Stefano l'ha scritto lui. Esempio:

> Bootstrap: letti INVARIANTS + AI_INSTRUCTIONS + STATUS + FINANCIAL_RULES. Procedo su
> [task] con Canonical Registry + Layer Model in mente.

---

## Mode B — Capture (end of session / post-commit)

### The three triage questions

Default: **skip**. Proponi una capture solo se la sessione ha prodotto qualcosa che avrà
ancora senso tra 6 mesi.

#### Q1 — È emersa una decisione strategica?

Strategica = tocca la forma a lungo termine della piattaforma (architettura, scope,
audience) **e** non era ovvia dagli invariants attuali.

| Strategica | Non strategica |
|---|---|
| "v_budget_canonical è SSOT del budget multi-fonte" | "Rinominata variabile X" |
| "ECONOMATO resta dati-only finché Mario non ha dashboard" | "Fix typo" |
| "API HotelCube: client diretto da hotelops, non via Esolver" | "Aggiunta ruff rule" |
| "Revman diventa vertical #3" | "Refactor: estratto helper setup_logging" |

**Se yes** → proponi `vault/decisions/YYYY-MM-DD_<slug>.md`. Usa come template
`2026-04-17_Budget_Canonical_View.md`. Includi: contesto, decisione, conseguenze,
invariants correlati, **commit hash** se la decisione è già materializzata nel codice.

#### Q2 — È stato sfidato o confermato un invariant?

Un invariant (I1–I8) può essere:
- **Confermato** — la sessione ha colpito il suo bordo e l'invariant ha tenuto. Spesso
  non richiede capture; è un no-op. Proponi capture solo se la conferma è stata non
  ovvia (es. "pensavamo di rilassare I3 ma abbiamo scoperto perché non si può").
- **Sfidato** — qualcuno ha proposto di rilassarlo. Richiede decision esplicita paired con
  edit a INVARIANTS.md.
- **Nuovo** — è emersa una regola platform-wide non ancora catturata. Promuoverla a I9 (o
  amend di uno esistente) richiede decision stub.

Sfidare un invariant è grosso. Non silenziosamente. Mai un edit a INVARIANTS.md senza un
`vault/decisions/YYYY-MM-DD_<slug>.md` appaiato che spieghi il cambio.

#### Q3 — È cambiata un'entità canonica o l'ontologia?

Entità canoniche (per entity_protocol_v1): **Societa, Struttura, Reparto, Persona,
Fornitore, Banca, Progetto, Contratto, Strumento_Finanziario, Consulente**.

Il flusso corretto ha due passi:

**Q3a — Triage CORE / TACTICAL / TRANSIENT** (via ENTITY_REVIEW.md + SUPPLIERS_STRATEGY.md):

| Classe | Criterio | Destinazione |
|---|---|---|
| CORE | strategica, pluri-progetto, multi-anno, obbligazioni ricorrenti | `vault/ontology/<kind>/<name>.md` |
| TACTICAL | singolo progetto o fornitore ricorrente ma non strategico | single registry file (Layer 2) |
| TRANSIENT | una tantum, no obblighi residui | project-level / STATUS.md, **mai** vault |

**Q3b — State (solo se CORE)** via entity_protocol_v1.md:
candidate → approved → active → inactive. Ogni transizione richiede nota.

Corollario **I3 (vault è SSOT per ontologia)**: se la modifica è già stata applicata
direttamente in `core/bq/dimensioni/*.csv` o hardcoded in `CLAUDE.md` senza una nota
vault corrispondente → è **drift**. Proponi la scrittura vault **prima** del merge CSV,
e nota la violazione I3 nel proposal.

**Se yes** → proponi file appropriato (`ontology/<kind>/<name>.md` per CORE, o suppliers
registry per TACTICAL). Skippa TRANSIENT.

### If none apply → skip

> Capture: nothing to land. Session was operational-only.

Nessuna ceremony, nessun file. Non inventare lavoro.

### Proposal format

Per ogni "yes", emetti un blocco separato:

````
## Capture proposal — [decision | invariant | ontology]

**File:** <absolute path>
**Action:** create | edit
**Related commit(s):** <hash> <hash>  (o "none yet" se la decisione precede il codice)
**Related invariants:** I<n> (se applicabile)

**Content:**
```markdown
<stub markdown pronto da incollare>
```
````

Mai auto-write al vault. Stefano approva, poi si scrive.

---

## Traceability

Ogni capture dovrebbe riferirsi al commit (o ai commit) che l'ha generata. Questo chiude
il loop **decisione ↔ codice**:

- Decision file → sezione `## Implementation` con lista `commit: <hash>`.
- Commit message → opzionalmente cita `vault/decisions/<slug>` se esiste.
- Ontology file CORE → link al commit che l'ha materializzata in `D_*` o CSV.

Questo è il significato concreto di "structured retrieval": un agente che cerca "perché
v_budget_canonical?" trova la decision; dalla decision salta al commit; dal commit vede
il codice. Niente vector search, solo link espliciti bidirezionali.

---

## Anti-goals

- **Non leggere il vault intero ogni turno.** Progressive disclosure è il punto. Se carichi
  tutto, la skill diventa rumore di contesto.
- **Non riscrivere `INVARIANTS.md` senza decision stub appaiato.** Gli invariants sono
  costituzionali, ogni cambio lascia paper trail.
- **Non generare capture per lavoro meccanico** (refactor, lint, bug fix di superficie).
  STATUS.md copre quello.
- **Non confondere capture con `STATUS.md`.** STATUS = session memory breve termine,
  vault = decision/ontology memory lungo termine. Se non sai in quale va una nota,
  chiedi.
- **Non trattare gli stub come SSOT.** `procedures/reconcile_banca.md`,
  `procedures/classifica_file.md`, `protocols/state_transitions.md` puntano al repo.
- **Non usare vector search, semantic search, embeddings** per navigare il vault. Solo
  path espliciti.
- **Non inventare commit hash, date, importi, conteggi.** Se incerto, chiedi o verifica.
- **Non toccare il parking lot** (`ontology/assets/` vuoto, `events/` vuoto, advisor
  orfani) durante una sessione operativa. È cleanup dedicato, non capture di scoperta.

---

## Relationship to sibling skills

- **`session-context`** — gestisce `STATUS.md` (session memory a breve). Complementare:
  STATUS è "cosa ho fatto oggi", vault-loop è "cosa conterà tra 6 mesi".
- **`hotelops-tech-lead`** — audit architetturali. Se una capture propone una decisione
  con implicazioni strutturali, il tech-lead è il deep-dive successivo. vault-loop
  propone la scrittura; tech-lead ragiona sulle conseguenze.

---

## One-line compression

> Bootstrap: read INVARIANTS → AI_INSTRUCTIONS → STATUS → lazy-load by topic.
> Capture: triage decision / invariant / ontology (CORE-TACTICAL-TRANSIENT); propose
> stubs with commit traceability; skip if operational-only.
