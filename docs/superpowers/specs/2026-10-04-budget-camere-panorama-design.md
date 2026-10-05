# Budget per driver — primo pezzo: camere Hotel Panorama

**Data:** 2026-10-04 · **Stato:** approvato da Stefano il 2026-10-05 (punti 1–3 chiusi) · **Vertical:** condges

## La domanda

*Quanto dobbiamo vendere di camere nel 2027, a che prezzo, e perché — e a
consuntivo, dove e per quale motivo ci stiamo scostando?*

Hotelops produce la risposta; il **Management OS** (repo `mgmt_os`, Quadro Unico)
è l'unico posto dove Stefano la legge, accanto alle priorità. Hotelops non
pubblica una pagina propria per il budget (decisione 2026-09-24 «una sola
superficie», confermata il 2026-10-04).

## Decisioni già prese (Stefano, 2026-10-04 e 2026-10-05)

| Tema | Decisione |
| --- | --- |
| Budget | Uno solo, costruito dal basso dall'osservato 2026. Il budget di inizio anno (`f_budget_mensile`) è ritirato. |
| Base | Osservato PMS 2026 riga per riga. Riga non toccata = uguale al 2026. Ottobre 2026 = fatto al 4/10 + prenotazioni in portafoglio, marcato come stima. |
| Dettaglio | Volume per **segmento di mercato** (come le schermate HotelCube «Budget Occupazione/Produzione»). Prezzo per **categoria di camera**. |
| Effetti | Capacità → occupazione → mix di categoria → prezzo. Ogni effetto ha una ragione scritta. |
| Capacità 2027 | 86 camere. Progetto `HPAN26PIANO3` dentro il budget, consegna all'apertura. |
| Terzo piano | 9 Deluxe, 7 Classic, 3 Executive, 2 Suite (oggi 10 Superior, 6 Standard, 3 Comfort, 1 Family; H323 Classic invariata). Fonte: fit-out camera per camera di Hospitality Project (01/09) × `d_camere`. |
| Soglia prezzo | Prezzi base di Lybra, per categoria e periodo. Tre livelli distinti: base (Lybra), budget, effettivo (PMS). |
| Inserimento | Foglio generato dal sistema, già compilato con la base; ricaricato diventa una versione. |
| Approvazione | Un gradino alla volta. Approva solo Stefano. |
| Budget vecchio | Letture spente subito; nessuna riga cancellata; la previsione di cassa di Rosa non si tocca. |
| Calendario 2027 | Prima notte venduta 20 aprile, ultima 20 ottobre: 184 giorni (11 + 153 + 20). Deciso il 2026-10-05. |
| Come si decide il prezzo | Stefano scrive un **aumento %** per mese × categoria sul prezzo medio 2026 di quella categoria in quel mese. Il foglio calcola il prezzo 2027. |
| Base del prezzo | Gestionale (rapporto per tipologia venduta); il totale è riportato alla base `01ROOM` col rapporto mensile osservato, mostrato come riga di raccordo. |
| Tabelle | `f_budget_driver` (le versioni si accumulano) + `f_budget_versioni` (stato e approvazione). |

## Perimetro di questo pezzo

Dentro: business unit `HOTEL`, società `ORTI`, anno 2027, ricavo camere netto
IVA, notti, presenze, capacità, prezzo per categoria.

Fuori (pezzi successivi, stesso schema): Angelina, CVM, ristorazione, spiaggia,
costi, canone e rate ricalcolati sul budget, uscita per HotelCube, previsione
aggiornata in corso d'anno, anni 2028–2030.

## Dati

| Serve | Fonte | Stato |
| --- | --- | --- |
| Notti vendute, capacità | `f_pms_statistiche` (capacità = valore modale sui giorni con vendite) | c'è |
| Ricavo camere netto | `f_produzione_pms`, classe `01ROOM` | c'è fino al 2 ottobre 2026 (verificato il 2026-10-05); ottobre da caricare a mese chiuso |
| Notti e prezzo per categoria | `f_bookings_tipologia` (tipologia **venduta**) | osservato solo fino a luglio: l'unico file è del 2 agosto, da agosto in poi contiene prenotazioni e non consuntivo. **Serve un'esportazione nuova.** Scarto dal `01ROOM` non costante: aprile −6%, maggio −1%, giugno −7%, luglio −6% |
| Inventario per categoria | `d_camere` (2026): 11 categorie, 86 camere | c'è; il 2027 è una variante dichiarata dal progetto. `d_camere` dà anche la mappa codice PMS → categoria (16 codici, es. `DDLX`/`TDLX` → Deluxe) |
| Notti e presenze per segmento | nessuna | **fonte nuova**: serve un'esportazione vera del rapporto dietro le schermate HotelCube |
| Prezzi base | nessuna | **fonte nuova**: serve un'esportazione vera da Lybra |
| Prenotazioni in portafoglio (stima ottobre) | `f_prenotazioni_otb` | c'è; include gli extra, va riportata alla base camere |

Regola del repo: una fonte nasce da un file reale. Le due fonti nuove si
definiscono con la skill `hotelops-ingest` quando arrivano i file.

## Modello

Unità del budget, per mese:

- **Volume** — per segmento: notti, presenze.
- **Prezzo** — per categoria: notti, prezzo medio.
- **Capacità** — inventario per categoria × giorni di apertura (date di apertura
  e chiusura sono input).

Vincolo: per ogni mese la somma delle notti per segmento è uguale alla somma
delle notti per categoria. Il caricamento che non lo rispetta è rifiutato.

Base, sul calendario 2027: per ogni mese × categoria, notti e prezzo medio
del 2026 contati solo sui giorni tra il 20 aprile e il 20 ottobre. Un mese
è `osservato` se il file per tipologia è stato esportato dopo il suo ultimo
giorno; altrimenti è `stima` e il raccordo a `01ROOM` resta vuoto (mai zero).

Notti 2027 precompilate: le notti 2026 di ogni categoria sono scalate col
rapporto camere 2027 / camere 2026 di quella categoria, poi riportate al
totale notti del mese (che resta uguale al 2026). Così il foglio non toccato
mostra già l'effetto mix del terzo piano a prezzi 2026. La tipologia è quella
venduta, l'inventario è quello fisico: la regola è un'approssimazione
dichiarata, e Stefano può correggere le notti a mano.

Prezzo 2027 = prezzo medio 2026 × (1 + aumento %). L'aumento è l'input di
Stefano, per mese × categoria, con la sua ragione.

Ricavo camere di budget = Σ categoria (notti × prezzo). Il ricavo per segmento
(serve a HotelCube) si ottiene ripartendo il totale con l'indice di prezzo per
segmento osservato nel 2026, dichiarato accanto al numero.

Quattro effetti, in quest'ordine, con somma esatta. Valgono sia per
2026 → budget 2027 sia per budget → consuntivo:

1. capacità: ricavo `01ROOM` 2026 sul calendario 2027 meno ricavo 2026 reale;
2. occupazione: (notti − notti base) × prezzo medio base del mese;
3. mix: Σ (notti × prezzo base di categoria) − notti × prezzo medio base;
4. prezzo: Σ notti × (prezzo − prezzo base di categoria).

Confrontabilità: solo mesi chiusi e caricati per intero; un mese mancante dà
NULL, mai zero; nessun bersaglio annuo diviso per dodici.

## Flusso

1. `hotelops budget base` — calcola la base 2026 e genera il foglio (`.xlsx`),
   una riga per mese × categoria, con colonne: camere 2026 e 2027, notti e
   prezzo medio 2026, notti 2027 (precompilate), aumento % (precompilato 0),
   prezzo e ricavo 2027 (formule), prezzo base Lybra, ragione. Un secondo
   foglio dà per mese i totali e i quattro effetti, con formule vive. Il
   taglio per segmento si aggiunge quando arriva l'esportazione vera.
2. Stefano modifica le celle e scrive le ragioni.
3. `hotelops intake` del foglio → GCS (`gs://hotelops-raw`) + `f_raw_objects`.
   L'identità della versione è l'impronta del **contenuto delle celle**: un
   foglio ricaricato identico non crea una versione; un foglio con struttura
   cambiata è rifiutato.
4. `hotelops promote` → righe in tabella, stato `bozza`.
5. `hotelops budget approva --gradino camere-hotel --versione <id>` — solo
   Stefano; le versioni approvate non si modificano, una correzione è una
   versione nuova.

## Cosa legge il Management OS

Tre viste, nessuna logica da ricopiare a valle (I8):

- `v_camere_consuntivo_mensile` — BU × mese: notti, capacità, ricavo `01ROOM`,
  prezzo medio; e per categoria. Oggi questa logica vive solo dentro
  `v_booking_curve`.
- `v_budget_approvato` — le righe della versione approvata, per gradino.
- `v_budget_camere_scostamento` — budget, consuntivo, i quattro effetti e la
  ragione scritta, per mese.

Finché queste viste non esistono, la scheda «Numeri» di `mgmt_os` continua a
leggere il foglio Budget Rooms (ponte, numeri provvisori).

## Spegnimento del budget vecchio (deciso, cambio separato)

`hotelops bva`, la colonna budget di `app_cdg`, la colonna budget in
`v_piano_finanziario_mensile`. Le righe di `f_budget_mensile` restano. Prima del
cambio: Stefano avvisa Rosa e vede il render con dati veri (gate delle pagine hub).

## Verifica

- La base 2026 del foglio coincide con BigQuery al centesimo (test dorato).
- La somma dei quattro effetti è uguale allo scostamento, per ogni mese.
- Stesso foglio ricaricato → nessuna versione nuova. Struttura cambiata → rifiuto.
- Mese non chiuso o non caricato → NULL in tutte le colonne di confronto.
- Stefano vede il foglio generato con i dati veri prima del merge.

## Due piani

1. **Base e foglio** — `docs/superpowers/plans/2026-10-05-budget-camere-base-foglio.md`.
   Solo lettura da BigQuery: nessuna tabella nuova. Stefano ottiene il foglio
   e ci scrive gli aumenti.
2. **Versioni, approvazione, scostamento** — si scrive quando esiste un foglio
   compilato vero (regola del repo: il parser nasce dal file reale). Contiene
   intake/promote, le due tabelle, l'approvazione e le tre viste per il
   Management OS.

## Punti aperti (servono a Stefano)

1. **Regola delle notti 2027 precompilate** (vedi Modello): da confermare
   guardando il primo foglio generato.
2. **Volume per segmento**: rinviato finché non c'è l'esportazione del
   rapporto. Fino ad allora il volume si decide per categoria.
3. **Scarto tra rapporto per tipologia e `01ROOM`**: 6–7% in tre mesi su
   quattro, e a maggio il rapporto per tipologia ha 105 notti in più delle
   statistiche. Da capire col direttore prima dell'approvazione.
4. **Nome commerciale** delle due suite del terzo piano (Suite o Luxury Suite).
   Nel foglio stanno in «Suite».
5. **Allotment TUI** (oggi 10 Standard + 7 Superior): al terzo piano quelle
   categorie spariscono.
6. «Budget dietro in hotelops» è stato confermato con un «forse»: si rivede dopo
   questo primo pezzo.

## Prerequisiti (di Stefano)

- Un'esportazione nuova di «Detailed Data for Bookings» del Panorama, anno
  2026 (oggi ferma al 2 agosto); un'altra a stagione chiusa.
- Esportazione PMS di ottobre, a mese chiuso.
- Un'esportazione del rapporto per segmento (occupazione e produzione).
- Un'esportazione da Lybra, anche del 2026.
- Avvisare Rosa prima dello spegnimento del budget vecchio.
