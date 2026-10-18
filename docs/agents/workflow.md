# Engineering coordinato

Le skill di [Matt Pocock](https://github.com/mattpocock/skills) usano i file
`issue-tracker.md`, `triage-labels.md` e `domain.md` in questa directory.
Le istruzioni dell'utente e gli invarianti del repository prevalgono sulle
ricette generiche. Le skill non attribuiscono diritti sui sistemi operativi.
Questo è un adattamento locale del workflow, non una seconda costituzione.
Per dominio, ingest e memoria restano canoniche le skill HotelOps e `vault-loop`;
Pocock copre la meccanica engineering. I risultati di `research` destinati al repo
vanno in `docs/reports/`, rispettando la separazione tra tecnico e privato.
Le skill attivabili dal modello (tra cui `research`, `domain-modeling`,
`code-review` e `tdd`) restano dentro l'incarico, il team e i permessi assegnati;
l'attivazione non li amplia. Anche `domain-modeling` segue i puntatori e i limiti
di `domain.md`, senza duplicare le fonti canoniche.

## Team e assegnazione

Il team concordato è di quattro agenti: `coordinatore` (Codex), `regia`,
`hotelops` e `knowledge` (Claude). Il coordinatore assegna risultati e dipendenze;
`hotelops` cura il codice di questo repo. Il revisore deve essere un membro
diverso dall'autore. Non creare altri agenti, merger o sotto-team automaticamente.
`implement-spec`, `research` e `code-review` devono usare i membri disponibili;
in assenza di capacità, eseguire in sequenza o segnalare il limite al coordinatore.

GitHub conserva incarichi e prove; Herdr è il terminale locale che ospita le sessioni
e permette al coordinatore di scambiare messaggi con gli agenti già aperti.
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
   Non fare `pip install -e` nel worktree. Verificare che interpreter e import
   dei moduli interessati risolvano il codice di quel worktree, non l'editable
   install del checkout principale; altrimenti i test non provano il branch.
5. Consegnare SHA immutabile al revisore. Verificare separatamente requisiti e
   standard; un solo revisore può svolgere i due controlli in sequenza.
   Nuove modifiche richiedono review del nuovo diff.
   Il workflow CI `claude-code-review.yml` e le sue verifiche restano invariati;
   la review locale Pocock non li sostituisce e non introduce un secondo gate CI.
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

Gli stati nel template descrivono l'incarico engineering. Le label descrivono
il triage e i verdetti di thread; gli stati dei dati e del dominio mantengono
i loro contratti. Nessuna transizione aggiorna automaticamente gli altri piani.

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
L'installazione è per utente/macchina: versionare questi documenti non installa
il plugin sugli altri computer o in CI.
Nei prompt trasmessi da Herdr scrivere «usa la skill `mattpocock-skills:...`»
e verificare il caricamento effettivo; una forma slash può arrivare come testo
del prompt invece di essere interpretata dalla TUI.
