# Domain docs

Layout a contesto unico. Seguire l'ordine in [AGENTS.md](../../AGENTS.md):
[INVARIANTS.md](../architecture/INVARIANTS.md),
[AI_INSTRUCTIONS.md](../architecture/AI_INSTRUCTIONS.md),
[LE_3_DIMENSIONI.md](../architecture/LE_3_DIMENSIONI.md),
[STATUS.md](../../STATUS.md) e [ADR 0005](../adr/0005-ai-native-operating-infrastructure.md).
Poi leggere CLAUDE.md e gli ADR pertinenti in `docs/adr/`.

Il vocabolario canonico è già in `docs/architecture/AI_INSTRUCTIONS.md`;
schemi, registry e manifest mantengono le responsabilità descritte in AGENTS.md.
Non copiarli in un secondo glossario. Se viene introdotto `GLOSSARY.md`, deve
collegare le fonti e definire solo termini nuovi risolti; l'assenza attuale non
richiede scaffolding. Usare `domain-modeling` solo quando c'è una decisione reale.
Esporre conflitti con ADR e invarianti prima di cambiare comportamento.

La memoria nel vault può essere storica: verificare fatti tecnici contro repo e
fonti operative. Il raccordo resta [.claude/commands/vault-loop.md](../../.claude/commands/vault-loop.md),
con lint deterministico documentato in [meta/vault-loop/README.md](../../meta/vault-loop/README.md).
Questo setup non crea una seconda procedura di scrittura nel vault.
