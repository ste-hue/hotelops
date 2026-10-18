# Issue tracker: GitHub

Issue e specifiche tecniche vivono in `ste-hue/hotelops`. Usare `gh` o il
connettore GitHub disponibile specificando repository e numero. È un repository
pubblico: checkpoint tecnici e fixture sintetiche, senza copiare dati privati
dal vault o dai sistemi operativi.

## Operazioni

- Leggere: `gh issue view NUMERO --repo ste-hue/hotelops --json number,title,body,labels,comments`.
- Cercare prima di creare: `gh issue list --repo ste-hue/hotelops --state all --search 'testo'`.
- Creare: `gh issue create --repo ste-hue/hotelops --title 'titolo' --body-file /tmp/task.md`.
- Aggiornare: `gh issue comment NUMERO --repo ste-hue/hotelops --body-file /tmp/checkpoint.md`.
- Etichettare: `gh issue edit NUMERO --repo ste-hue/hotelops --add-label 'LABEL'`.
- Chiudere solo il risultato effettivamente verificato, collegando prove e PR.

**PRs as a request surface: no.** La PR consegna una modifica; la issue conserva
obiettivo e criteri. Verificare il tipo perché issue e PR condividono i numeri.

Quando una skill dice di pubblicare una specifica, riusare la issue pertinente e
collegare gli eventuali documenti già in `docs/superpowers/specs/` o
`docs/superpowers/plans/`. Non creare una specifica concorrente dello stesso lavoro.

Per task figli usare sub-issue e dipendenze GitHub quando disponibili; altrimenti
task list nel padre e `Part of: owner/repo#N` / `Blocked by: owner/repo#N` nel figlio.
`wayfinder` riusa la mappa esistente. Un blocker risulta risolto da prove correnti,
non dalla sola memoria della sessione.

Le sessioni condividono l'account GitHub: l'assignee `@me` non distingue gli agenti.
Il coordinatore serializza i claim con agente, worktree, branch e base SHA nel
commento di incarico descritto in [workflow.md](workflow.md). Il commento non è un
lock atomico; nessun auto-claim o riassegnazione silenziosa di un task occupato.
