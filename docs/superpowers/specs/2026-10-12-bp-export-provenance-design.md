# BP → pagina: identità e qualificazioni dell'export

**Data:** 2026-10-12 · **Stato:** bozza da rivedere, nessuna implementazione o approvazione del piano · **Audience:** operatori e revisori del piano.

> Conservata nel consolidamento del 17/10 come proposta collegata alla issue
> #148. Il nuovo Excel di raccolta occupazione/produzione 2027 è una superficie
> di lavoro preparatoria: non implementa questa pipeline, non approva il budget
> e non sostituisce il contratto di versionamento previsto qui.

Proposta tecnica di provenienza per export da workbook.
Questa proposta definisce il primo incremento di provenienza nel percorso
integrato della issue #148: budget operativo ORTI → Piano Industriale → Regia.
Gli incrementi hanno criteri di verifica propri e un unico raccordo di prodotto.

## Problema

Il lettore deve poter rispondere: «Da quale copia vengono questi numeri, quali
trasformazioni hanno subito e quali ipotesi li qualificano?».

Una copia acquisita e il suo derivato ricalcolato possono avere hash diversi.
Le cache del workbook possono essere assenti o precedenti; serve una ricevuta
che colleghi acquisizione, trasformazione e risultati esportati. Controllare
alcune celle non equivale a verificare l’intero pacchetto.

Le qualificazioni delle ipotesi devono accompagnare sia l’HTML sia le serie
strutturate, con ambito esplicito. Il confronto con dati reali e le relative
ricevute rimangono nel fascicolo privato.

## Soluzione

Produrre un pacchetto di export verificabile: copie conservate, dati
strutturati, HTML e una ricevuta che identifica ciascun artefatto. Il pacchetto
si dichiara completo soltanto dopo la riconciliazione dei risultati e delle
qualificazioni. La sua validità non dipende da un ricalcolo sul computer del
destinatario né dalla disponibilità corrente di Drive.

Il lettore vede «risultati ottenuti ricalcolando la copia acquisita», con fonte
e data. Un altro consumer riceve le stesse qualificazioni nei dati strutturati.
La ricevuta verifica una catena tecnica; non approva le ipotesi finanziarie.

## Integrazione nel percorso #148

Il risultato atteso è una catena leggibile dal management: fatti e fonti osservate
→ obiettivi, strategia e forecast distinti → scenario del Piano Industriale
→ conseguenze economiche e di cassa → lettura e decisioni in Regia.
La provenienza accompagna i passaggi; non costituisce un prodotto parallelo.

| Incremento | Risultato verificabile | Dipendenze |
| --- | --- | --- |
| A. Baseline BP ed export identificato, descritto qui | La lettura della baseline risale alle copie e alle ipotesi effettive, senza attribuire approvazione o attualità | Artefatti e mappa di estrazione verificati; può avanzare subito |
| B. Budget camere e versioni (#137) | Base comparabile, obiettivo, strategia e scarto distinti; versioni e approvazione esplicite | Audit dei dati e completamento del contratto camere esistente |
| C. Attività, costi e margini ORTI (#148) | Budget mensile in COMPETENZA riconciliato al CE, con allocazioni e residui dichiarati | Audit delle attività e dei conti; adozione del contratto di versione per il perimetro esteso |
| D. Raccordo budget → Piano Industriale (#148) | Scenario che identifica gli input operativi adottati e spiega il passaggio ai flussi di CASSA e alla copertura del debito | Versioni operative identificabili, modello designato e mappatura verificata dei passaggi |
| E. Editor camere (#138) e lettura del piano in Regia (percorso #148) | La bozza si modifica tramite il contratto Hotelops; il piano si legge dal pacchetto verificato | L'editor camere dipende da B; la lettura della baseline BP può usare A; i risultati integrati richiedono D |

A può avanzare insieme agli audit di B e C. L'editor camere non aspetta il
completamento dei costi di tutte le attività. Il raccordo D si verifica per
perimetri espliciti: le parti ancora fondate su ipotesi del BP sono dichiarate,
senza presentare un'integrazione parziale come un budget ORTI completo.

### Contratto del raccordo operativo-finanziario

- Hotelops conserva fatti, versioni del budget, driver e riconciliazioni.
  Il modello finanziario designato conserva le trasformazioni pluriennali;
  Regia mostra risultati e governa decisioni. Non si duplica il calcolo nel consumer.
- Lo scenario identifica le versioni operative adottate, il loro stato,
  perimetro e periodo, la grandezza consumata (obiettivo, risultato della
  strategia o forecast), più la mappa dalle voci mensili agli input del piano.
  Una bozza può alimentare uno scenario candidato esplicitamente etichettato;
  non diventa per questo budget o piano approvato.
- Il passaggio da margini in COMPETENZA a flussi di CASSA dichiara tempi di
  incasso/pagamento, CCN, imposte, capex, finanziamenti e trasferimenti
  infragruppo pertinenti. EBITDA e CFADS non sono intercambiabili.
- La ricevuta dell'export riferisce anche queste identità quando il raccordo
  esiste. Per il BP storico registra la provenienza disponibile, senza
  inventare una versione del budget approvato.
- Un input operativo nuovo produce un confronto e uno scenario candidato.
  L'adozione nel piano e la pubblicazione restano atti espliciti; le versioni
  precedenti rimangono identificabili.

Il collaudo integrato segue una variazione dichiarata di un driver dalla
bozza operativa ai ricavi e costi incrementali, poi allo scenario finanziario
e alla lettura Regia. Mostra il prima/dopo e verifica che budget approvati e
pagine già pubblicate non siano modificati automaticamente. Questo collaudo
si aggiunge ai controlli del pacchetto A; non impone di realizzare tutto #148
nella prima PR.

## Storie d'uso

1. Come operatore, voglio identificare la copia letta anche dopo una modifica su Drive.
2. Come operatore, voglio distinguere originale acquisito e derivato ricalcolato senza confonderli con versioni approvate.
3. Come lettore, voglio risalire da un numero alla cella o alle celle che lo sostengono.
4. Come lettore, voglio distinguere un risultato prospettico sotto ipotesi da un fatto osservato.
5. Come consumer JSON, voglio ricevere qualificazioni e provenienza senza dover interpretare l'HTML.
6. Come operatore, voglio sapere se una differenza riguarda una cache precedente o un errore nell'export.
7. Come operatore, voglio che un'acquisizione instabile o un calcolo fallito non producano un pacchetto dichiarato verificato.
8. Come revisore, voglio rilevare un artefatto sostituito anche se conserva nome e numeri visibili.
9. Come sviluppatore, voglio verificare lo stesso pacchetto consumato dalla pagina, con esempi sintetici ripetibili.
10. Come operatore, voglio mantenere separati questo export, le approvazioni del piano e gli eventuali invii.

## Decisioni di implementazione proposte

### Un modulo di export, un'interfaccia da verificare

Hotelops possiede l'acquisizione e il modulo di export del BP. L'interfaccia
riceve una sorgente identificata, il profilo del workbook e la configurazione
del motore di ricalcolo; produce il pacchetto completo e il rapporto di verifica,
oppure un errore esplicito. La pagina consuma i risultati già verificati.

Riutilizzare l'accesso Drive, la conservazione dei raw e i contratti esistenti
dove applicabili. Non introdurre un motore finanziario, nuove tabelle di fatti
o un framework generale per Excel. L'eventuale registrazione raw segue il
regime I9 della sorgente; nessuna scrittura su fatti canonici è richiesta qui.
Un hash SHA-256 del pacchetto non sostituisce gli identificatori o gli hash
già usati dal registro raw.

### Ricevuta e conservazione

La ricevuta dichiara versione del contratto, istante dell'export e versione
del produttore e della mappa di estrazione. Contiene:

- **Acquisizione:** provider, file ID, metadati osservati prima/dopo, marcatore
  di revisione quando disponibile, dimensione, SHA-256 dei byte scaricati e
  riferimento alla copia conservata.
- **Ricalcolo:** hash dell'input acquisito, hash e dimensione dell'output,
  motore, versione, modalità, esito e riferimento alla copia conservata.
- **Risultati:** hash e riferimenti di ogni JSON/HTML generato, mappa di
  provenienza dei valori e risultato dei controlli.
- **Qualificazioni:** identità, testo, evidenza sorgente e ambito esplicito
  delle serie e dei periodi interessati.

Ogni artefatto deve corrispondere al proprio hash. Non si richiede uguaglianza
tra originale e ricalcolato. L'HTML identifica l'export; la ricevuta esterna
ne registra l'hash dopo la generazione, evitando riferimenti circolari.
Le copie devono restare recuperabili fuori da directory temporanee. Nessun
hash, da solo, dimostra che la copia sia conservata.

Se il marcatore della sorgente cambia durante l'acquisizione, l'operazione
si interrompe o riparte da una nuova acquisizione. Timestamp e dimensione
invariati non equivalgono a una revisione nativa verificata: la ricevuta
espone il livello di evidenza disponibile. Per gli artefatti storici si
registra solo quanto verificato; versione del motore o rapporto di derivazione
non dimostrati restano non verificati, senza ricostruirli per supposizione.

### Numeri e trasformazioni

Ogni valore di dominio esposto in serie, tabelle, tessere o tooltip identifica
società/perimetro, periodo, unità, natura del dato e dimensione temporale
pertinente. Le metriche derivate mantengono il riferimento alle dimensioni
dei loro componenti; non si assegna una dimensione unica a tutto il pacchetto.

La provenienza ammette una cella del ricalcolato oppure un insieme di celle
con trasformazione di presentazione dichiarata: minimo e relativo anno,
subtotale, variazione, conversione di unità o arrotondamento. Queste
trasformazioni sono verificate dal produttore dell'export; non introducono
nuove regole di previsione o selezione delle fonti nel consumer.

Precisione, tolleranza e unità sono dichiarate per metrica. Cache mancanti,
errori di formula e valori non finiti non diventano zero. Il rapporto distingue
cache assente nell'acquisito, cache diversa dal ricalcolato e risultato
esportato discordante dal ricalcolato: quest'ultimo impedisce un export valido.

### Qualificazioni con ambito esplicito

Il profilo del workbook associa le evidenze alle serie pertinenti, comprese
le dipendenze rilevanti. «Condizioni non deliberate» accompagna le proiezioni
che le assumono anche se l'avviso non è accanto alla cella finale.
«Statico/superato» si applica ai risultati storici che lo richiedono, senza
contaminare il canone del modello vivo. L'assenza di quel marcatore non rende
il canone privo di altre ipotesi.

La mappa è esplicita e versionata; non si deduce da nomi simili dei fogli né
da una ricerca di parole. Le qualificazioni sono dati strutturati accessibili
al consumer JSON e visibili nella presentazione. Un campo senza mappatura
non equivale a «nessuna qualificazione applicabile».

## Decisioni sui test

Il punto di verifica proposto è il **pacchetto completo di export**. I test
controllano ciò che il consumer riceve, non il numero di chiamate agli helper.
Usare workbook sintetici piccoli per gli errori e un readback privato sul
caso reale. I file finanziari e le credenziali non entrano nei fixture pubblici
del repository. Il ricalcolo effettivo richiede anche un controllo d'integrazione
con versione e modalità dichiarate; un doppio di test non prova il motore reale.

| Caso | Risultato atteso |
| --- | --- |
| Input e ricalcolato hanno hash diversi, ma la catena è documentata e verificata | Pacchetto valido; nessuna scrittura su Drive necessaria |
| Copia acquisita, ricalcolato, JSON o HTML sostituiti a ricevuta invariata | Errore che identifica l'artefatto |
| Sorgente cambiata durante l'acquisizione | Nessun pacchetto dichiarato completo |
| Solo metadati, senza byte conservati e verificati | Nessuna dichiarazione di identità verificata |
| Cache acquisita precedente/assente; export corretto dal ricalcolato | Diagnostica esplicita, nessun falso errore di export |
| Un numero, anno, unità o trasformazione non riconcilia | Export non valido con posizione dell'errore |
| Tessera o tooltip introduce un numero di dominio non mappato | Export non valido |
| Condizioni ipotetiche rimosse dai risultati dipendenti a numeri invariati | Verifica delle qualificazioni fallita |
| Storico statico e canone vivo presenti nello stesso workbook | Avvisi corretti per ambito, senza trasferimenti automatici |
| Motore fallisce o una cella necessaria nel ricalcolato contiene errore/cache assente | Nessun JSON/HTML finale dichiarato verificato |
| Pacchetto verificato senza accesso a Drive | Identità e riconciliazione restano verificabili; nessuna pretesa di attualità |

Precedenti riusabili: conservazione degli input identificati del modello
Canone, adattatori di lettura con dipendenze esplicite, test del foglio budget
camere e dei contratti raw. La presenza di tali componenti non attesta che
questa catena sia già implementata.

## Fuori dal primo incremento A

- Modifica di formule, calendario, prezzi, costi o assunzioni del MASTER.
- Approvazione delle versioni del BP, revoche e registrazione delle consegne.
- Scritture su Drive, invii a destinatari esterni, deployment o pubblicazione automatica.
- Controllore di freschezza della pagina e gestione della persistenza Regia.
- Nuovo motore del debito, sostituzione del workbook o migrazione a mutui-tracker.
- Implementazione degli incrementi B–E: restano nello stesso percorso #148,
  con le dipendenze indicate sopra e PR verificabili separatamente.
- Garanzia che ogni applicazione del destinatario ricalcoli il workbook nello stesso modo.

## Note e riferimenti

- [ADR 0005](../../adr/0005-ai-native-operating-infrastructure.md): autorità per concetto, fonte/versione/dimensione/data per ogni numero.
- [Budget camere](2026-10-04-budget-camere-panorama-design.md) e [backend Regia](2026-10-06-budget-backend-regia-design.md): contratti da integrare mantenendo le rispettive responsabilità.
- [Issue #148](https://github.com/ste-hue/hotelops/issues/148): percorso complessivo; [#137](https://github.com/ste-hue/hotelops/issues/137) e [#138](https://github.com/ste-hue/hotelops/issues/138): dipendenze operative già aperte. Questa bozza dettaglia A e il raccordo previsto; non attesta l'implementazione degli altri incrementi.
- MASTER acquisito: riferimento e hash nel fascicolo privato di provenienza; un link mutabile non identifica da solo il riscontro storico.
- [Skill to-spec, revisione letta](https://github.com/mattpocock/skills/blob/49dd158d1076134a641b33efb035946536778336/skills/engineering/to-spec/SKILL.md).

Questa bozza non attribuisce retroattivamente un'approvazione al MASTER né
promuove la provenienza storica parziale a una pipeline verificata. Prima di
implementare, il confronto riguarda questa interfaccia e questi criteri, non
la riapertura delle decisioni economiche.
