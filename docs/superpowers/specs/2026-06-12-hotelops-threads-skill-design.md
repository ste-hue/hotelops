# Spec — Skill `hotelops-threads` (triage thread + lifecycle worktree)

**Data:** 2026-06-12 · **Stato:** spec approvata a voce in sessione, skill da implementare in sessione fresca · **Owner:** Stefano

## Problema

I thread aperti vivono sparsi tra `STATUS.md` (vista orizzontale), gli hub workstream del vault
(`workstreams/*.md`, vista verticale per fronte) e i worktree git fisici. Oggi:

- nessun processo valuta sistematicamente se un thread **vale la pena** (pursue/park/kill);
- i worktree si accumulano senza lifecycle (4 attivi oggi, di cui `worktree-fb-looker` morto allo
  stesso commit di main e `worktree-app-store` di scopo ignoto);
- due sessioni parallele hanno quasi aperto **due fronti sovrapposti** (due app F&B) perché nessuno
  step obbligava a controllare cosa coprono i worktree esistenti;
- i verdetti "non vale la pena" non vengono mai scritti da nessuna parte → lo stesso thread viene
  rivalutato da zero ogni volta.

## Decisione di confine: skill nuova, NON estensione di `hotelops-tech-lead`

Valutato (vincolo di design #1). Verdetto: **skill nuova**, confine esplicito:

| | `hotelops-tech-lead` | `hotelops-threads` (questa) |
|---|---|---|
| Oggetto | salute della **codebase** (drift doc↔code, debito tecnico, refactor) | **thread di lavoro** da STATUS+vault e loro lifecycle |
| Output | report/audit + priorità refactor | verdetti PURSUE/PARK/KILL + worktree aperti/completati/mergiati/potati |
| Trigger | "how's the codebase", "tech debt", "audit" | "valuta i thread aperti", "cosa porto a casa", "apri un worktree per X", "chiudi questo fronte" |

Motivi per non estendere: tech-lead è già lunga e report-oriented; questa skill è un **loop
operativo con side-effect** (crea worktree, scrive verdetti, merge) — mescolare i due trigger
inquinerebbe entrambi. Le due skill si referenziano a vicenda: se durante il triage emerge debito
di codebase, `hotelops-threads` rimanda a tech-lead, e viceversa.

## Decisioni prese in sessione (Q&A)

1. **Fonti:** `STATUS.md` + hub vault `workstreams/*.md`, cross-referenziati; il triage segnala
   drift tra i due. I worktree git esistenti **sono thread** (forma fisica) e entrano
   nell'inventario.
2. **Autonomia:** triage → Stefano sceglie → la skill esegue. Si ferma a "verificato + pronto al
   merge"; il merge lo approva Stefano. Mai fully-autonomous fino a main.
3. **Rubrica:** goal-alignment a 4 assi (sotto).
4. **Worktree audit:** sì — il verdetto su un worktree esistente può essere "finiscilo",
   "mergialo", "potalo".

## Il loop (5 fasi)

### Fase 1 — Inventario

1. Leggi `STATUS.md`: sezioni "In corso", "Decisioni aperte", "Prossimi passi".
2. Leggi `workstreams/_INDEX.md` + ogni hub (`type: workstream_hub`): blocco curato
   ("Dove sono", "Prossimo passo", "Thread aperti").
3. `git worktree list` + per ogni worktree: branch, ahead/behind vs main, ultima attività,
   **che fronte copre** (deduci da branch name + diff + hub; se non deducibile → chiedi).
4. Normalizza in una lista unica di thread: `{id, fonte (STATUS/hub/worktree), stato fisico,
   descrizione 1 riga, dipendenze note}`.
5. Segnala drift STATUS↔hub↔worktree (es. hub dice "branch non pushato" ma branch è mergiato).

### Fase 2 — Triage (rubrica goal-alignment)

Per ogni thread, 4 assi (score qualitativo, non numerico-finto):

- **Allineamento** col goal Company OS e con la spina dorsale corrente (oggi: `cash_control`).
  Fonte: `docs/architecture/AI_INSTRUCTIONS.md`, INVARIANTS, STATUS.md.
- **Potere sbloccante** — quanti altri thread sblocca (es. keystone `f_produzione_pms`).
- **Effort vs payoff** — stima onesta; "5 min manuali di Stefano" è una categoria a parte
  (verdetto = HANDOFF, non worktree).
- **Rischio staleness** — il costo del thread parcheggiato cresce? (drift BQ↔codice, hazard
  attivi tipo P0-3, branch che divergono da main).

Verdetto per thread: **PURSUE** (apri/continua worktree) · **PARK** (motivo + condizione di
risveglio) · **KILL** (motivo) · **HANDOFF** (azione manuale di Stefano, niente worktree).
Output: tabella ordinata + raccomandazione top-1/top-2. **Stefano sceglie.**

### Fase 3 — Conflict check (obbligatorio, pre-worktree) [vincolo #3]

Prima di creare QUALSIASI worktree:

1. `git worktree list` fresco (non fidarsi dell'inventario di fase 1 se è passato tempo).
2. Mappa fronte→worktree per ogni worktree attivo.
3. **Se il thread scelto si sovrappone a un worktree esistente → STOP**: la skill si rifiuta di
   aprirne un secondo e propone invece di riprendere/finire/potare quello esistente.
   Caso reale da prevenire: due sessioni che aprono due app F&B parallele.
4. Sovrapposizione = stesso fronte workstream, stessi file/moduli target, o stessa tabella/vista
   BQ di destinazione. In dubbio → chiedi a Stefano, non aprire.

### Fase 4 — Esecuzione

1. Worktree standard: `.worktrees/<thread-id>` con branch `feat/<thread-id>` (convenzione già in
   uso: `cash-pf-engine`, `fb-looker-close`). I due legacy sotto `.claude/worktrees/` vanno
   migrati o potati, non imitati.
2. Dentro il worktree si applicano le skill esistenti: brainstorming/writing-plans se il thread
   non ha spec, TDD, verification-before-completion. `hotelops-threads` NON le reimplementa —
   orchestrazione, non duplicazione.
3. Definition of done del thread = il "Prossimo passo" dell'hub o il criterio in STATUS.md,
   reso esplicito PRIMA di iniziare (1 riga: "questo thread è chiuso quando X osservabile").
4. Si ferma a: test verdi + criterio verificato + branch pushato → presenta a Stefano per merge.

### Fase 5 — Chiusura del loop [vincolo #2: la skill CHIUDE i thread]

Ogni verdetto e ogni esito **viene scritto**, record-only decision-memory:

- **KILL/PARK** → riga in `STATUS.md` (sezione "Decisioni aperte" o thread strikethrough con
  motivo + data) e, se il thread appartiene a un hub, checkbox aggiornata nell'hub con
  legenda esistente (✅/⛔ + motivo). Mai cancellare la riga: si marca, con motivazione.
- **PURSUE completato** → dopo il merge approvato: aggiorna STATUS.md ("Completato di recente"),
  aggiorna il blocco curato dell'hub, `git worktree remove` + branch cleanup, e chain-call a
  `session-reflect`/`vault-loop` per la cattura se la sessione è stata sostanziosa.
- **HANDOFF** → riga in STATUS.md con l'azione manuale esplicita.

Invariante della skill: **nessun verdetto vive solo in chat.** Se il triage è stato fatto ma
Stefano non sceglie nulla, almeno i KILL/PARK vanno comunque scritti.

## Collocazione e deploy [vincolo #4]

- Source of truth: `meta/skills/hotelops-threads/SKILL.md` (versionata nel repo, come
  `hotelops-ingest`).
- Deploy: copia in `~/.claude/skills/hotelops-threads/SKILL.md`.
- Description/trigger della skill: "valuta i thread aperti", "cosa vale la pena", "triage
  worktree", "apri un fronte", "chiudi questo thread", "worktree per X", "cosa porto avanti".
  Esplicito anti-trigger: salute codebase → `hotelops-tech-lead`; ingest file → `hotelops-ingest`.

## Anti-goals

- NON fa audit di codice (→ tech-lead).
- NON merge autonomo su main, mai.
- NON crea workstream hub nuovi nel vault (quello è il pattern del sistema workstream, lo
  propone e basta).
- NON tiene stato proprio (niente file di registry nuovo): lo stato vive in STATUS.md, hub
  vault e git — la skill li legge e li aggiorna, non li duplica.
- Niente score numerici finti nella rubrica: giudizio qualitativo motivato.

## Test di accettazione (per la sessione di implementazione)

1. Run di triage a freddo su questo repo → inventario che include i 4 worktree reali e i thread
   STATUS, con verdetto motivato per ciascuno; i due worktree legacy `.claude/worktrees/*`
   ricevono verdetto esplicito (atteso: prune o migra).
2. Scelto un thread sovrapposto a un worktree esistente → la skill rifiuta e propone il
   worktree esistente (conflict check funziona).
3. Verdetto KILL su un thread → STATUS.md aggiornato con motivo e data, niente righe cancellate.
4. Thread completato end-to-end → branch mergiato da Stefano, worktree rimosso, STATUS+hub
   aggiornati nello stesso turno.

## Open per la sessione di implementazione

- Nome definitivo (`hotelops-threads` proposto; alternativa `thread-triage`).
- Se il conflict check debba anche guardare i branch remoti non-worktree (es. `feat/cashflow`
  vivo senza worktree locale).
- Quanto del triage delegare a subagent Explore (inventario fase 1 parallelizzabile).
