---
name: hotelops-threads
description: Use when Stefano wants to evaluate, open, resume, or close work threads on hotelops — triggers on "valuta i thread aperti", "cosa vale la pena", "cosa porto avanti", "triage", "apri un worktree per X", "apri un fronte", "riprendi il fronte X", "chiudi questo thread", "pota i worktree", "a che punto sono i fronti", or whenever a request implies creating/managing a git worktree or deciding which open thread to pursue. NOT for codebase health/refactoring (→ hotelops-tech-lead) or file ingestion (→ hotelops-ingest).
---

# HotelOps Threads — triage e lifecycle worktree

## Perché esiste

I thread vivono in tre posti: `STATUS.md` (orizzontale), hub `workstreams/*.md` nel vault
(verticale per fronte), worktree git (forma fisica). Senza disciplina succedono due cose,
entrambe successe davvero:

1. **Fronti sovrapposti**: due sessioni hanno quasi aperto due app F&B parallele, perché
   "nessun branch con quel nome" era stato scambiato per "nessun conflitto".
2. **Verdetti persi**: un triage detto in chat e mai scritto → lo stesso thread viene
   rivalutato da zero la sessione dopo.

Due invarianti, non negoziabili:

> **Nessun verdetto vive solo in chat.** KILL/PARK/HANDOFF si scrivono in STATUS.md/hub
> **nello stesso turno**, anche se Stefano non sceglie nulla, anche se "ho poco tempo".
>
> **Nessun worktree senza conflict check per FRONTE.** La collisione di nome non basta:
> devi sapere COSA copre ogni worktree attivo prima di aprirne uno.

Confine: salute codebase/refactor → `hotelops-tech-lead`. Ingest file → `hotelops-ingest`.
Se durante il triage emerge debito di codice, rimanda a tech-lead — non assorbirlo qui.

## Il loop (5 fasi)

### 1. Inventario — TUTTE e tre le fonti, sempre

1. `STATUS.md`: "In corso", "Decisioni aperte", "Prossimi passi".
2. Vault: `workstreams/_INDEX.md` + ogni hub (`type: workstream_hub`) — blocco curato
   ("Dove sono / Prossimo passo / Thread aperti"). **"STATUS è fresco" NON esonera dagli
   hub**: l'hub ha la profondità (keystone, hazard, drift flag) che STATUS comprime in
   una riga.
3. `git worktree list` + per ogni worktree: branch, ahead/behind vs main, ultimo commit,
   e **che fronte copre** — deducilo da branch name + `git diff main...<branch> --stat` +
   hub. Se non deducibile, chiedi. Un worktree È un thread aperto in forma fisica.

Normalizza: `{id, fonte, stato fisico, descrizione 1 riga, dipendenze}`. Segnala drift
tra le tre fonti (es. STATUS dice "da mergiare" ma il branch è già in main).

### 2. Triage — rubrica goal-alignment

Per ogni thread, 4 assi, giudizio qualitativo motivato (niente score numerici finti):

| Asse | Domanda |
|---|---|
| Allineamento | Serve al Company OS / alla spina corrente (oggi `cash_control`)? |
| Potere sbloccante | Quanti altri thread sblocca? (keystone > foglia) |
| Effort vs payoff | Stima onesta; lavoro-codice vs azione-manuale |
| Rischio staleness | Il costo del parcheggio cresce? (drift BQ↔codice, hazard, branch che divergono) |

Verdetti:
- **PURSUE** — apri/continua worktree. Indica il top-1/top-2; **sceglie Stefano**.
- **PARK** — motivo + **condizione di risveglio** esplicita ("quando X").
- **KILL** — motivo (superato da / obsoleto perché).
- **HANDOFF** — azione manuale di Stefano (5-min, email, click): niente worktree, riga
  esplicita con l'azione.

### 3. Conflict check — obbligatorio prima di OGNI worktree

Anche se Stefano dice "fai veloce". Anche se l'inventario è di 10 minuti fa (rifai
`git worktree list` fresco).

**Sovrapposizione = stesso fronte workstream, O stessi file/moduli target, O stessa
tabella/vista BQ di destinazione.** Il nome del branch è irrilevante:
`feat/fb-audit-dashboard` e `feat/fb-looker-close` non collidono per nome ma possono
coprire lo stesso fronte F&B.

Procedura:
1. `git worktree list` fresco → mappa fronte→worktree per ciascuno (diff + hub).
2. Il deliverable richiesto **esiste già in main o in un branch?** Cercalo (`ls`, grep,
   STATUS, hub) PRIMA di pensare al worktree. Se esiste → STOP, verdetto HANDOFF o
   "già fatto", niente worktree.
3. Il thread scelto si sovrappone a un worktree attivo? → **STOP: rifiutati di aprirne
   un secondo.** Proponi invece: riprendi / finisci / pota quello esistente.
4. In dubbio se due fronti si sovrappongono → chiedi a Stefano. Non aprire.

Lo STOP è uno stop vero: non presentare "comunque i comandi che userei" per il worktree
nuovo. Presentare i comandi = invitare a eseguirli.

### 4. Esecuzione

- Convenzione: `git worktree add .worktrees/<thread-id> -b feat/<thread-id> main`.
  **NON usare** `EnterWorktree` / `.claude/worktrees/` — è il pattern legacy da potare,
  non da imitare.
- Prima riga di lavoro: definition of done esplicita — "questo thread è chiuso quando
  <X osservabile>" (dal "Prossimo passo" dell'hub o da STATUS).
- Dentro il worktree valgono le skill esistenti (brainstorming/writing-plans se manca la
  spec, TDD, verification-before-completion). Questa skill orchestra, non le duplica.
- Ci si ferma a: test verdi + criterio verificato + branch pushato → si presenta a
  Stefano per il merge. **Mai merge autonomo su main.**

### 5. Chiusura — il verdetto si scrive, sempre

- **KILL/PARK** → subito, stesso turno, senza aspettare conferma: riga in STATUS.md
  (strikethrough o marker con motivo + data — **mai cancellare righe**) e checkbox
  aggiornata nell'hub se il thread appartiene a un fronte (legenda ✅/⛔ esistente).
  Se Stefano poi ribalta il verdetto, si ri-marca: il record resta.
  Eccezione anti-duplicato: se il verdetto è GIÀ registrato accuratamente in STATUS/hub
  (verificato leggendo la riga, non presunto), non duplicare — aggiorna con data solo
  se la registrazione esistente è incompleta o stale.
- **PURSUE completato** (post-merge approvato): STATUS "Completato di recente" + blocco
  curato dell'hub + `git worktree remove` + branch cleanup. Chain-call a
  `session-reflect`/`vault-loop` se la sessione è stata sostanziosa.
- **HANDOFF** → riga in STATUS.md con l'azione manuale esplicita.

## Razionalizzazioni note (dal baseline test — non ripeterle)

| Scusa | Realtà |
|---|---|
| "STATUS è di oggi, il vault non serve" | L'hub ha keystone/hazard/drift che STATUS non ha. Leggi entrambi. |
| "Nessun branch con quel nome ⇒ nessun conflitto" | Il conflitto è di FRONTE, non di nome. Mappa cosa copre ogni worktree. |
| "Scrivo i verdetti quando Stefano conferma" | I verdetti del triage si scrivono nello stesso turno. La conferma cambia il verdetto, non il fatto che si scriva. |
| "Ho poco tempo, rispondo in chat" | Un triage non scritto è un triage da rifare. 2 minuti di Edit valgono la sessione dopo. |
| "Ti lascio comunque i comandi per il worktree" | Dopo uno STOP non si consegnano i comandi. Si propone il worktree esistente. |
| "EnterWorktree è più comodo" | `.claude/worktrees/` è legacy da potare. `.worktrees/<id>` + `feat/<id>`. |

## Red flags — fermati e rileggi la skill

- Stai per creare un worktree e non hai ancora fatto `git worktree list` in QUESTO turno.
- Stai dando verdetti e non hai aperto nessun file del vault.
- Stai per chiudere il turno con verdetti solo in chat.
- Stai per scrivere `git worktree add` dentro `.claude/worktrees/`.
- Hai trovato il deliverable già esistente e stai comunque proponendo il worktree.
