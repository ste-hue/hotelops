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

Il coordinatore assegna risultati e dipendenze; `hotelops` cura il codice di
questo repo, `regia` il prodotto mgmt-os, `knowledge` la memoria, `researcher`
le fonti, `tools` gli strumenti e le review indipendenti, `tester` il collaudo.
Il `consigliere` aiuta Stefano a chiarire requisiti e decisioni, senza assegnare
incarichi o autorizzare operazioni. Composizione e incarichi correnti sono nel
[registro del team](https://github.com/ste-hue/mgmt-os/issues/52), non nel
conteggio storico delle sessioni. Il revisore deve essere diverso dall'autore.
Nuovi agenti o sotto-team richiedono un incarico esplicito.
Le skill di implementazione, `research` e `code-review` usano i membri disponibili;
in assenza di capacità, eseguire in sequenza o segnalare il limite al coordinatore.

Gli incarichi arrivano tramite Herdr. Il coordinatore registra assegnazioni,
integrazioni e puntatori alle prove nella issue pertinente. I referti locali
conservano il lavoro; il loro esito va riportato nella PR prima del merge.
Herdr ospita le sessioni e permette lo scambio con gli agenti già aperti.
Prima dell'invio verificare ambiente Herdr, identità del destinatario, stato e
prompt: non sovrascrivere bozze o dialoghi, né interrompere lavoro non concordato.
Il trasporto non fornisce monitoraggio continuo o scheduler.

Le precisazioni sullo stesso incarico possono arrivare durante il lavoro;
cambi di perimetro e interruzioni di altri incarichi si coordinano col titolare.
Prima di scrivere prodotto assegnato a un altro owner, il coordinatore registra
il passaggio di titolarità. Ogni ricognizione ha un solo raccoglitore: risposta
unica al destinatario indicato, senza rilanciare la domanda agli altri agenti.

## Ciclo di lavoro

1. Leggere AGENTS, CLAUDE, STATUS, issue, specifiche e worktree già esistenti.
   Verificare remoto, branch, SHA e working tree. Non riaprire decisioni risolte.
2. Definire risultato e incrementi verificabili con le skill presenti nel
   catalogo della sessione. Chiarire soltanto le decisioni aperte. Per un fix
   circoscritto basta il ticket con criteri chiari.
3. Registrare il claim del coordinatore prima delle modifiche. Un worktree per
   autore attivo, branch e base SHA espliciti. Non resettare worktree esistenti
   per seguire una ricetta; niente force push o cleanup del lavoro altrui.
4. Implementare usando `tdd` o `diagnosing-bugs` quando pertinenti.
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
`mattpocock-skills`, per esempio `/mattpocock-skills:code-review` se disponibile; in Codex
selezionare la skill del plugin dal catalogo. Ricaricare le sessioni libere dopo
l'installazione e verificare la disponibilità effettiva. Le skill omonime locali
non vengono sovrascritte da questa configurazione.
L'installazione è per utente/macchina: versionare questi documenti non installa
il plugin sugli altri computer o in CI.
Nei prompt trasmessi da Herdr scrivere «usa la skill `mattpocock-skills:...`»
e verificare il caricamento effettivo; una forma slash può arrivare come testo
del prompt invece di essere interpretata dalla TUI.
