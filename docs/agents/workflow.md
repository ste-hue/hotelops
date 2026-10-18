# Engineering coordinato

Le skill di [Matt Pocock](https://github.com/mattpocock/skills) usano i file
`issue-tracker.md`, `triage-labels.md` e `domain.md` in questa directory.
Le istruzioni dell'utente e gli invarianti del repository prevalgono sulle
ricette generiche. Le skill non attribuiscono diritti sui sistemi operativi.

## Team e assegnazione

Il team concordato è di quattro agenti: `coordinatore` (Codex), `regia`,
`hotelops` e `knowledge` (Claude). Il coordinatore assegna risultati e dipendenze;
`hotelops` cura il codice di questo repo. Il revisore deve essere un membro
diverso dall'autore. Non creare altri agenti, merger o sotto-team automaticamente.
`implement-spec`, `research` e `code-review` devono usare i membri disponibili;
in assenza di capacità, eseguire in sequenza o segnalare il limite al coordinatore.

GitHub conserva incarichi e prove; Herdr trasporta messaggi tra sessioni esistenti.
Prima dell'invio verificare ambiente Herdr, identità del destinatario, stato e
prompt: non sovrascrivere bozze o dialoghi, né interrompere lavoro non concordato.
Il trasporto non fornisce monitoraggio continuo o scheduler.

## Ciclo di lavoro

1. Leggere AGENTS, CLAUDE, STATUS, issue, specifiche e worktree già esistenti.
   Verificare remoto, branch, SHA e working tree. Non riaprire decisioni risolte.
2. Usare `to-spec` / `to-tickets` se mancano risultato e incrementi verificabili;
   `grill-with-docs` soltanto per questioni aperte. Per un fix circoscritto basta
   il ticket con criteri chiari.
3. Registrare il claim del coordinatore prima delle modifiche. Un worktree per
   autore attivo, branch e base SHA espliciti. Non resettare worktree esistenti
   per seguire una ricetta; niente force push o cleanup del lavoro altrui.
4. Implementare con `implement`, `tdd` o `diagnosing-bugs` secondo necessità.
   Verificare comportamento e contratti; controlli proporzionati al cambiamento.
   Per soli documenti bastano diff e riferimenti, senza test artificiali.
5. Consegnare SHA immutabile al revisore. Verificare separatamente requisiti e
   standard; un solo revisore può svolgere i due controlli in sequenza.
   Nuove modifiche richiedono review del nuovo diff.
6. Preparare PR con problema, risultato, controlli reali e limiti (`pr`).
   Il coordinatore verifica diff e CI; merge e deploy seguono l'autorizzazione
   specifica del task, non sono impliciti nella label.
7. Pubblicare handoff tecnico sulla issue/PR. `handoff` può creare un supporto
   temporaneo, ma non sostituisce il checkpoint durevole. Per la memoria usare
   `vault-loop` e `session-reflect` canonici, rispettando i loro confini.

## Formati di checkpoint

```text
INCARICO
Risultato / criteri di accettazione:
Agente / revisore:
Repository / issue / dipendenze:
Worktree / branch / base SHA:
Perimetro file / controlli:
Effetti esterni autorizzati:
Stato: READY | CLAIMED | BLOCKED | IMPLEMENTED | REVIEWED
Prossimo checkpoint:

CONSEGNA
Agente / issue / branch / commit SHA:
Comportamento cambiato:
Verifiche eseguite e risultati:
Review: revisore, base SHA, head SHA, rilievi e risoluzione:
Limiti / servizi non verificati / mutazioni esterne:
PR / CI / prossimo risultato verificabile:
```

Il claim termina con completamento o riassegnazione registrata dal coordinatore;
non scade per presunzione. In caso di collisione fermare le modifiche sovrapposte.
Distinguere implementato, revisionato, integrato, pubblicato e verificato live.

## Uso delle skill

Installare il plugin ufficiale per client secondo il README upstream. Evitare
copie manuali aggiuntive delle stesse skill. In Claude preferire il namespace
`mattpocock-skills`, per esempio `/mattpocock-skills:implement`; in Codex
selezionare la skill del plugin dal catalogo. Ricaricare le sessioni libere dopo
l'installazione e verificare la disponibilità effettiva. Le skill omonime locali
non vengono sovrascritte da questa configurazione.
