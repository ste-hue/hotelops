# HotelOPS — cosa stiamo costruendo

Aggiornato: 2026-10-09. Mappa di prodotto per orientare persone e sviluppatori.
Descrive la direzione e i confini; non certifica deployment, freschezza dei dati
o integrazioni live. Gli invarianti restano in [INVARIANTS.md](INVARIANTS.md),
la struttura del repo in [SYSTEM_MAP.md](SYSTEM_MAP.md), lo stato operativo in
[STATUS.md](../../STATUS.md).

## Scopo

HotelOPS è il sistema con cui Gruppo Panorama rende osservabili le proprie
operazioni, conserva memoria e governa decisioni e risultati. Deve ridurre il
lavoro necessario per ricostruire dove stanno le cose, che cosa è cambiato e
che cosa richiede una decisione.

Collega dati, documenti, comunicazioni e impegni. Le applicazioni specialistiche
servono le persone che lavorano nei diversi ambiti; il Hub offre un ingresso
comune. Una nuova schermata ha valore quando migliora un ciclo aziendale
verificabile: dal problema osservato alla decisione, all'esecuzione, al risultato.

## Nomi e tre moduli di direzione

**HotelOPS** indica l'ecosistema aziendale; `hotelops` è anche il repository
dell'infrastruttura condivisa e di alcuni verticali. **Management OS** indica
la superficie di governo. **Regia** è il suo modulo gestionale;
`mgmt-os` è il repository che oggi ne implementa motore e Quadro, insieme a
una lettura provvisoria dei numeri. I nomi di prodotto non impongono un solo repo.

| Modulo | Domanda | Responsabilità |
| --- | --- | --- |
| Regia | A che punto siamo e cosa deve succedere adesso? | Fronti, risultati attesi, decisioni, responsabili, priorità, scadenze, dipendenze e verifiche. Motore in `mgmt-os`. |
| Controllo di gestione | Quanto rispetto al budget, e perché? | Consuntivi, budget approvati, forecast distinti, scostamenti e driver. Dati e calcoli governati da `hotelops`; Regia può mostrarne la lettura. |
| Piano industriale | Il percorso di crescita e investimento è sostenibile? | Ipotesi pluriennali, investimenti, finanziamenti, servizio del debito e condizioni di sostenibilità. Riusa il nucleo presente in `mutui-tracker` e raccorda il modello Canone; collegamento complessivo ancora da definire. |

Gli investimenti attraversano questi tre moduli: dettaglio nei progetti,
conseguenze economiche nei modelli, decisioni e verifiche in Regia. Un'unica
porta non richiede la fusione dei motori o una seconda copia modificabile
degli stessi dati.

## Come si collegano i pezzi

1. **Acquisizione e memoria documentale.** PMS, ERP, banche, Gmail, Drive e
   documenti forniscono osservazioni ed evidenze. `workspace/` riusa gli accessi
   condivisi; raw e lineage conservano la provenienza secondo il regime della
   sorgente. Un riferimento a un file non prova che il suo contenuto sia archiviato.
2. **Fatti affidabili.** Contratti, validazione e viste canoniche in `hotelops`
   determinano come leggere i numeri. Fonte, periodo, società e dimensione
   CASSA / COMPETENZA / IMPEGNO restano espliciti.
3. **Governo.** Regia collega evidenze e metriche agli impegni. Il motore
   gestionale conserva stato e storia; completamento e verifica sono distinti.
4. **Esecuzione.** Applicazioni di reparto e progetto, Calendar e Trello sono
   superfici da collegare con identità e responsabilità dei campi esplicite.
   La loro presenza nell'ecosistema non prova una sincronizzazione automatica.

L'autorità è per concetto: BigQuery per i fatti governati, il workspace SQLite
di `mgmt-os` per lo stato gestionale, il modello finanziario designato per le
ipotesi. Un journal o una pagina pubblicata non sostituiscono questi proprietari.

## I due journal

| Memoria | Cosa conserva | Come entra nel software |
| --- | --- | --- |
| Journal tecnico HotelOPS | Sessioni, scelte architetturali, implementazioni, test, limiti e fili aperti. | Una scelta confermata aggiorna i documenti del repo; un'implementazione va verificata su codice e stato corrente. |
| Work Journal / diario di bordo | Eventi aziendali, conversazioni, osservazioni, insight e domande ancora aperte; condensato settimanale in Obsidian. | Fornisce contesto, requisiti e proposte gestionali con riferimenti alle fonti. Non applica automaticamente decisioni o assegnazioni. |

Le due memorie si collegano tramite fonti, date e codici espliciti. Un insight
può diventare requisito; un requisito può diventare lavoro tecnico; il risultato
va poi verificato nell'uso aziendale. I settimanali conservano la finestra
storica: una priorità vecchia richiede riconciliazione prima di diventare stato
corrente. Nessuna traccia trovata significa esito non verificato nelle fonti
lette, con copertura dichiarata.

## Ruolo dell'AI

Gli agenti possono acquisire contesto autorizzato, confrontare evidenze con
impegni, evidenziare discordanze e preparare proposte circoscritte. Umani e
agenti usano gli stessi contratti applicativi; le mutazioni gestionali passano
dal motore, i fatti dal gate dati. Una proposta deve mostrare origine,
motivazione e prima/dopo; una scrittura deve poter essere riletta e riconciliata.

API, CLI e interfacce devono rendere il sistema osservabile e controllabile.
MCP può esporre queste capacità: non definisce il significato dei fatti o
l'autorità delle decisioni. Il ciclo completo evidenza → proposta → revisione
→ aggiornamento → verifica è la direzione di sviluppo, non una pipeline già
attestata come attiva.

## Stato e raccordi aperti al 9 ottobre

- **Presente nel codice:** infrastruttura dati e Hub; budget camere di base;
  Quadro, motore gestionale, import numeri/cantieri e lettura dei due settimanali;
  modello Canone in `verticals/condges`; Piano Industriale e API scenario in
  `mutui-tracker`. Il repo `app-mutui` letto non contiene quel modulo.
- **Pubblicazione riportata:** `STATUS.md` del 6 ottobre descrive Regia e Canone
  pubblicati; il Hub contiene le relative porte e quella Mutui. La disponibilità
  e i permessi delle destinazioni non sono stati ricollaudati per questa mappa.
- **Da completare:** versioni/approvazione e viste del nuovo CdG, API del budget,
  persistenza condivisa in produzione, proposte journal → Quadro, raccordo
  Piano Industriale / Canone / budget e autorità dei campi Calendar/Trello.
  La scheda Numeri usa ancora il BP come ponte; l'app CdG precedente è ritirata.

Le regole storiche del budget e i checkpoint M3a non attestano il nuovo
percorso completo. L'AI documentation contiene anche indicazioni storiche su
DSCR e perimetri che vanno riallineate con i modelli correnti prima di usarle
come specifica di integrazione. Questa mappa segnala lo scarto e non cambia
silenziosamente formule, invarianti o fonti canoniche.

## Riferimenti per continuare

- [Direzione Regia](https://github.com/ste-hue/mgmt-os/blob/main/docs/REGIA_DIRECTION.md)
  e [README mgmt-os](https://github.com/ste-hue/mgmt-os).
- [Budget camere](../superpowers/specs/2026-10-04-budget-camere-panorama-design.md)
  e [budget dalla Regia](../superpowers/specs/2026-10-06-budget-backend-regia-design.md).
- [Piano Industriale in Mutui](https://github.com/ste-hue/mutui-tracker/blob/main/public/js/piano_industriale.js)
  e [contratto dello scenario](https://github.com/ste-hue/mutui-tracker/blob/main/docs/superpowers/specs/2026-07-17-scenario-piano-in-proiezioni-sostenibilita-design.md).
- [Canone: motore](../../verticals/condges/canone_sim.py).

La mappa è stata verificata sui main `hotelops@d130003`, `mgmt-os@715d387`
e `mutui-tracker@6ef260c`, e confrontata con i journal forniti e la direzione
espressa in conversazione il 9 ottobre. Non sono stati interrogati account,
database operativi o scenari salvati live.
