# Welcome to HotelOps — Gruppo Panorama

## How We Work

Start with [AGENTS.md](AGENTS.md) and its canonical architecture references,
then [STATUS.md](STATUS.md) for the current handoff. Personal usage statistics
are not part of the repository's operational contract.

## Your Setup Checklist

### Codebases
- [ ] hotelops — https://github.com/ste-hue/hotelops · the data platform: `core/` world model, `ingest/` reality capture, `verticals/` apps, `cli.py`
- [ ] mgmt-os — https://github.com/ste-hue/mgmt-os · HotelOPS Regia, the management surface ("what do I do now, who owns it"). Private; ask Stefano for access
- [ ] obsidian-vault — private · the reasoning layer (decisions, concepts, workstreams, session history). Ask Stefano; it is not required to run code

### MCP Servers to Activate
- [ ] Google Drive e Gmail — connettori opzionali, da attivare con i permessi personali autorizzati. Verificare copertura e accesso prima di citare una fonte.

### Skills to Know About
- [ ] `/session-reflect` — writes the session's full state to the Obsidian vault (what was done, open threads with destinations, preformulated questions for blockers) so the next person can resume without asking "where were we?". Used at the end of substantive sessions
- [ ] `/recap` — one-paragraph summary of where the current session stands. Cheap, use it often
- [ ] `/vault-loop` — loads the constitutional layer (INVARIANTS, AI_INSTRUCTIONS) at session start, or lints vault↔repo drift on demand. The deterministic part is `python -m scripts.vault_loop.reconcile`
- [ ] `/session-context` — reads and updates `STATUS.md`, the live operational diary. Complementary to `/session-reflect`: STATUS is tactical and current, the vault is narrative and historical
- [ ] `hotelops-data-analyst` — the financial copilot: knows the two lenses (CASSA vs COMPETENZA), the three temporal dimensions, and which table is canonical for what. Use it before writing a BigQuery query by hand
- [ ] `hotelops-tech-lead` — codebase governance: what's drifting, what to refactor, what to prioritize
- [ ] `/auto-mode-setup` and `/remote-control` — auto mode runs work through Bash with a permission classifier; remote control lets sessions on different machines reach each other
- [ ] `/omarchy` — Linux desktop and Hyprland config. Machine-specific, only relevant on the Arch workstation

## Team Tips

Ogni sessione di sviluppo concorrente usa un proprio worktree. Fatti e calcoli
appartengono a HotelOps, stato gestionale a Regia, ragionamento al vault. La
presenza di un link non concede accesso alla fonte; i connettori usano i permessi
della persona autenticata.

## Get Started

Leggere `AGENTS.md` e `STATUS.md`, controllare branch e modifiche locali, quindi
scegliere un'attività già documentata. I comandi canonici delle skill sono in
`.claude/commands/`; gli adapter locali di altri agenti devono rimandare a quei
file, senza mantenerne copie divergenti.

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. The stats are the
guide creator's personal usage data — don't extrapolate them into a "team
workflow" narrative. -->
