---
name: session-reflect
description: Use to capture or resume a heavy working session on hotelops — when wrapping up substantive work (architecture decisions, refactors, audits, design sessions, multi-step debugging) or when starting a session that follows a previous heavy one. Triggers on "wrap up", "salva sessione", "save session", "fine sessione", "chiudiamo", "salviamo", "wrap rapido", "quick wrap", "riprendiamo", "where were we", "dove eravamo", "what was I doing", "carica ultima sessione", or any first prompt after a >24h gap on hotelops/obsidian work. Make sure to use this whenever a session has produced multiple insights/decisions/open threads that would be lost in chat history, OR when the agent needs to pick up from a previous session without asking "where were we?". The point is to make the Obsidian vault a layer of persistence on the work happening in the repo, so any agent (human or AI) entering tomorrow knows exactly what was done, what remains, what to do next, and what to ask if stuck. This skill is complementary to `session-context` (which manages repo/STATUS.md mechanics) and SUBSUMES `vault-loop` Mode B (chain-call with opt-out prompt). session-reflect captures the FULL session narrative including tactical work, open threads, and stuck-resolution protocols. If the session was operational-only with no insights or threads, skip — not every chat needs a reflection.
---

> **Canonical source: questo file** (`.claude/commands/session-reflect.md` — la copia in `~/.claude/skills/` non esiste più; puntatore sanato 2026-07-11).
>
> **2026-07-11 — thread GC**: i thread vivi vivono nei **workstream hub** (`vault/workstreams/`), non nei session file. Ogni thread al wrap dichiara una destinazione; i session file nascono `closed`. Vedi §Mode B step 4 e [[reports/2026-07-11_thread_gc]].

# Session Reflect — vault as inter-session memory layer

## Why this skill exists

A heavy session on hotelops produces four kinds of output:

1. **Narrative** — what happened. Sometimes lives in `journal/` for breakthroughs, otherwise dies in chat history.
2. **Durable artifacts** — decisions, concepts, ontology that matter for 6+ months. Lives in `vault/decisions/`, `vault/concepts/`, `vault/ontology/` via `vault-loop` Mode B.
3. **Tactical state** — current work, in-flight tasks. Lives in `repo/STATUS.md` via `session-context`.
4. **Resumption protocol** — open threads, next moves, questions to ask if stuck.

#4 had no home before this skill. When you close a heavy session, the open threads die in chat. When a new agent opens tomorrow's session, they have to ask "where were we?" — and you have to reconstruct from memory.

session-reflect writes a single file per heavy session that captures everything needed to resume, and chain-calls `vault-loop` Mode B with an opt-out prompt so the durable bits land in `decisions/`, `concepts/`, etc. in the same wrap-up step.

**Key insight**: the vault is reasoning substrate; the repo is operational truth. sessions/ is the bridge — the place where a heavy session's full state is captured so the next agent (you tomorrow, a different Claude, a colleague) can resume without context loss.

## Paths

- Vault sessions dir: `/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps/sessions/`
- Vault log: `/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps/log.md`
- Vault _INDEX: `/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps/sessions/_INDEX.md` (auto-regenerated, never edit manually)
- Repo root: `/Users/stefanodellapietra/dev/Projects/hotelops/` (used by Mode A for git cross-check)
- Repo STATUS: `/Users/stefanodellapietra/dev/Projects/hotelops/STATUS.md`

## Two modes

### Mode A — Resume (start of session)

Triggers: "where were we", "riprendiamo", "dove eravamo", "carica ultima sessione", "what was I doing", or first hotelops prompt after >24h gap.

Steps:

1. **Read `vault/workstreams/_INDEX.md` + the relevant hub(s)** — dai 2026-07-11 i fronti sono la memoria di ripresa primaria: ogni hub ha "Dove sono / Prossimo passo / Thread aperti" curati.
2. List `vault/sessions/*.md` sorted by date descending and read the most recent file (frontmatter `status` is normally `closed` — the narrative is still the richest context for "cosa è successo l'ultima volta"). A file still in `open-threads` = thread non landati (drift): surface it.
3. Compute gap = days between today and the session file's date.
4. **If gap > 3 days**: cross-check git. Run `git log --since=<session-date> --oneline` in the repo. Optionally `git log --since=<session-date> --name-only --pretty=format: | sort -u` to get file activity. For each item in the session's §Open threads, check whether files mentioned in the thread have commits since — surface this as **factual data only** (e.g., "0 commits touching that file"), never as interpretation ("thread resolved"). The user reads the data and decides.
5. Surface to user in **≤6 lines total**, format roughly:
   ```
   Last session: <date> · <slug>
   [If gap>3d:] ⚠️ stale Nd · M commits since: <category summary>
   Open threads: <count> · top: <thread #1>
   Next move: <top item from §Next moves>
   If stuck on <X>: ask <person> "<exact question>" (from §Blockers)
   ```
6. Don't dump the whole file. Surface only what's needed to resume. The user reads the file themselves if they want detail.

### Mode B — Reflect (end of session)

Triggers: "wrap up", "salva sessione", "save session", "fine sessione", "chiudiamo", "salviamo", "wrap rapido", "quick wrap". (Note: "capture" / "cattura" / "loop chiusura" go to `vault-loop` Mode B standalone — see §Relationship to other skills.)

Steps:

1. **Propose a slug** from session content (snake_case_lower, 2-5 words, e.g. `kernel_closure_planning`). Ask user to confirm or override before writing.
2. **Choose verbosity** based on content density:
   - Light/tactical session (1 fix, no decisions) → tight, ~30-60 lines, bullets only, Summary 1 sentence
   - Balanced session (1 decision, 2-3 threads) → ~60-100 lines, occasional prose
   - Heavy/meta session (multiple decisions, deep design) → ~100-200 lines, prose where it carries weight
   - **Escape phrases** "wrap rapido" / "quick wrap" force tight even if content is heavy
3. **Write** `vault/sessions/<YYYY-MM-DD>_<slug>.md` using the template below.
4. **Landa i thread nei workstream hub (stesso turno)**: ogni item di §Open threads deve dichiarare una **destinazione** — `→ [[workstreams/<FRONTE>]]` (e aggiorni il hub: checkbox in "Thread aperti", refresh di "Dove sono/Prossimo passo" se serve; hub nuovo solo se nasce un fronte nuovo), `→ STATUS (HANDOFF)` per azioni manuali di Stefano, oppure **drop esplicito** con motivo. Il session file nasce con `status: closed`; `open-threads` si usa SOLO se restano thread genuinamente non landabili (atteso: quasi mai). Un thread senza destinazione non esiste.
5. **Auto-flip prior session** (residuale): se esiste ancora un file precedente in `open-threads` i cui thread sono stati risolti o landati, flippalo a `closed` con nota `> Threads resolved in [[YYYY-MM-DD_<this-slug>]]`.
6. **Regenerate** `vault/sessions/_INDEX.md` from scratch by scanning all `sessions/*.md` files and their frontmatter. Format described in §Index file convention. **Warn se i file 🟡 superano 5** — è il segnale che i thread non stanno atterrando nei hub (drift del meccanismo).
7. **Append log entry** to `vault/log.md`:
   ```
   ## [YYYY-MM-DD] session | <slug> → <one-line summary>
   ```
8. **Chain to vault-loop Mode B with opt-out** — present:
   ```
   ✓ Session file written: sessions/<file>.md
     <N> insights flagged as "→ candidate for vault" in §Key insights
   
   Extract durable insights to vault/ (decisions, concepts, reports)?
   [yes] / skip
   ```
   Default is yes (enter). If yes, invoke vault-loop Mode B reading §Key insights of the just-written file. If skip, done.
9. **δ — soft prompt on wrap signals**: this is separate from explicit trigger phrases. If during normal conversation (no explicit "wrap up") the user signals end-of-session (says "buonanotte", "abbiamo finito", "ci sentiamo domani", closes a topic with no continuation), the agent MAY propose **once**: "Stiamo per chiudere — vuoi un session-reflect?" Soft suggestion, no auto-fire. If user says no or doesn't respond, drop it.

**Never auto-write.** Always show the draft after step 3, get sign-off, then write. The vault is Stefano's reasoning substrate, not a write target.

## Template (Mode B output)

The template has 9 sections. **Skip any section that has no content** — never write placeholder text like "no decisions this session". Absence = signal that section doesn't apply.

```markdown
---
type: session
date: YYYY-MM-DD
duration: ~Nh
mode: light | balanced | heavy
status: closed | open-threads
agent: <model-id>
related_commits: [<hash>, ...]
files_touched:
  - <path>
---

# Session — <topic>

## Summary

1 sentence (light), 2-3 sentences (balanced), 2-4 sentences (heavy). What was this about, what was the main thrust, what was the outcome at high level. A future agent should be able to read this alone and decide whether to dig deeper.

## What was done

Concrete bullets. Actions, not feelings. Mark `(proposed)` for things not yet committed. Note verification when done.

## Key insights (durable, candidate for vault)

Non-obvious things learned or articulated. Each insight that's durable enough for vault capture (concept/decision/ontology) should note `→ candidate for <vault path>`. The chain-call to vault-loop Mode B reads this section.

Skip this section if no durable insights emerged.

## Decisions made / confirmed

Bulleted list with links to decision files if they exist. Note `(not yet in vault/decisions/)` if made in conversation but not written.

Skip if no decisions.

## Open threads (carry over)

Things started but not finished. `[ ]` checkboxes so they read as actionable. Each item needs enough context that a fresh agent understands what to do without re-reading the whole session — **and each item ends with its destination**: `→ [[workstreams/<FRONTE>]]` (landato nel hub nello stesso wrap), `→ STATUS (HANDOFF)`, o `→ drop: <motivo>`. Il session file è narrativa; la liveness vive nel hub.

Bad: `[ ] fix the bug`
Good: `[ ] Apply fix to concepts/INFRASTRUCTURE_VS_LOOPS.md:17 — remove Streamlit/CLI from Infrastructure row (it duplicates Apps row) → [[workstreams/KERNEL_TOOLING]]`

Skip if everything closed cleanly.

## Next moves (prioritized)

Top 3-5 actions, ranked. Brief rationale for #1 vs #2 if non-obvious.

## Blockers / questions to ask

The core differentiator. For each potential blocker, write a **preformulated question** + who to ask + minimal context. Format:

- **If stuck on <X>**: ask <person> "<exact question>" — context: <1-line>

The point: a future agent reads this and knows exactly how to unblock without re-deriving the question.

Skip if no anticipated blockers.

## Files touched

Absolute paths (vault and repo). Skip if trivial (e.g., 1 file editing a typo).

## Related

Links to previous sessions, decisions, concepts, reports, commits, journal entries. Skip if nothing relevant.
```

## Index file convention

`vault/sessions/_INDEX.md` is **auto-regenerated** by the skill in Mode B step 5. Never edit manually — changes will be overwritten next wrap-up.

Generation rule: scan all `sessions/*.md` files, read frontmatter, produce table with **all open-threads files + last 10 closed files**, newest first.

Format:

```markdown
# Sessions — auto-regenerated index

⚠️ Do not edit manually. Regenerated by `session-reflect` skill on each Mode B invocation.
Filesystem (`ls sessions/*.md`) is source of truth; this file is convenience navigation.

Status: 🟡 open-threads · 🟢 closed

| Date | Status | Topic | Threads | File |
|------|--------|-------|---------|------|
| 2026-05-10 | 🟡 | vault_karpathy_kernel_assessment | 5 | [[2026-05-10_vault_karpathy_kernel_assessment]] |

---

Last regenerated: <ISO timestamp>
Total sessions: <count> (X open, Y closed)
Closed older than the last 10 are not listed here but still exist in the directory.
```

## Relationship to other skills

- **`session-context`** — manages `repo/STATUS.md`: short, recent, in-flight. session-reflect is richer and lives in the vault. session-context can still fire if Stefano wants STATUS.md updated; they don't overlap (different files).
- **`vault-loop` Mode B** — **subsumed by chain-call** from session-reflect step 7 with opt-out. Standalone vault-loop Mode B only fires on triggers "capture" / "cattura" / "loop chiusura" — used rarely, when Stefano wants vault capture WITHOUT writing a session file.
- **`vault-loop` Mode A** (bootstrap) — unchanged, standalone. Reads constitutional layer (INVARIANTS, AI_INSTRUCTIONS).
- **`vault-loop` Mode C** (lint) — unchanged, standalone. On-demand drift check.
- **`journal/`** — narrative breakthroughs (e.g., "Discovering the HotelOps Kernel"). A session can produce both a journal entry (epiphany) and a session file (bookkeeping). They don't replace each other.

## Anti-goals

- **Don't reflect every chat.** Operational-only sessions (single bug fix, single CLI run) don't need reflection — they should go straight to commit. session-reflect is for sessions where carry-over exists.
- **Don't duplicate `vault-loop` Mode B in the session file.** §Key insights flags durable bits with `→ candidate for vault`; the chain-call extracts them. Don't restate full decision content inside the session file.
- **Don't auto-write.** Always propose, get sign-off, then write. Same for chain-call to vault-loop — opt-out prompt mandatory.
- **Don't write fake confidence.** If unsure whether a thread is open or closed, leave it 🟡 and surface as open. §Blockers/questions exists exactly to surface uncertainty.
- **Don't write placeholder sections.** If a section has no content, skip it entirely. Never "No decisions this session." just absence.
- **Don't bloat tactical sessions.** A 20-minute bug fix wrap should produce ~30 lines, not 100. Match verbosity to content density. Heavy meta-sessions (>200 lines) are legitimate exceptions, not the norm.
- **Don't interpret git data on stale resume.** Mode A step 4 surfaces git facts ("0 commits touching that file") never interpretations ("thread done"). The user reads facts and decides.
- **Don't manually edit `_INDEX.md`.** It's auto-regenerated. Manual edits are lost on next Mode B.

## When this skill might be wrong for the moment

- User is in the middle of debugging — wait until the debug resolves before reflecting.
- User explicitly says "no, just continue" to a δ soft prompt — respect that, drop it.
- Mode A: if no open-threads files exist, say so and start fresh — don't read closed files unsolicited.
- Mode A with gap > 3 days but user is mid-conversation already (not resuming) — don't fire β cross-check uninvited.

## One-line compression

> Mode A — Resume: read most recent open-threads file; if gap >3d, cross-check git (facts only); surface ≤6 lines.
> Mode B — Reflect: write sessions/<date>_<slug>.md (template, skip-if-empty, match verbosity); **landa ogni thread nel suo workstream hub / STATUS / drop esplicito — file nasce closed**; auto-flip prior session if resolved; regenerate _INDEX (warn 🟡>5); append log; chain-call vault-loop Mode B with opt-out [yes]/skip.
> δ soft prompt on wrap signals: agent may suggest once, never auto-fires.
