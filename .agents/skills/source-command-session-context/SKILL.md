---
name: "source-command-session-context"
description: "Load current project state into session. Use at session start to know what's in progress, recent decisions, and next steps. Also use to update status at end of session."
---

# source-command-session-context

Use this skill when the user asks to run the migrated source command `session-context`.

## Command Template

# Session Context

Read `STATUS.md` in the project root. This is the project's working memory between sessions.

## On load

1. Read `STATUS.md`
2. Summarize to the user in 3-4 lines: what's in progress, what's blocked, suggested next step
3. Ask: "Vuoi continuare su qualcosa o c'e' altro?"

## On update (user says "aggiorna lo status", "salva stato", "update status")

1. Review what was done in this session (git log, conversation context)
2. Update `STATUS.md` with:
   - Move completed items from "In corso" to "Completato di recente" with today's date
   - Add any new in-progress work
   - Update "Decisioni aperte" if decisions were made or new ones emerged
   - Update "Rotto / da fixare" if issues were found or resolved
   - Update "Prossimi passi" based on current state
3. Keep the format identical. Keep it concise — no paragraphs, just bullet points.
4. Show the user what changed before writing.

## Rules

- Never invent status. Only report what you can verify from git log, files, and conversation.
- Dates use YYYY-MM-DD format.
- "Completato di recente" keeps last 10 items max. Oldest roll off.
- One line per item. Link to relevant files when useful.
