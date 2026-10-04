# Budget per driver — primo pezzo: camere Hotel Panorama

**Data:** 2026-10-04 · **Stato:** bozza, in attesa di rilettura di Stefano · **Vertical:** condges

## La domanda

*Quanto dobbiamo vendere di camere nel 2027, a che prezzo, e perché — e a
consuntivo, dove e per quale motivo ci stiamo scostando?*

Hotelops produce la risposta; il **Management OS** (repo `mgmt_os`, Quadro Unico)
è l'unico posto dove Stefano la legge, accanto alle priorità. Hotelops non
pubblica una pagina propria per il budget (decisione 2026-09-24 «una sola
superficie», confermata il 2026-10-04).

## Decisioni già prese (Stefano, 2026-10-04)

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
| Ricavo camere netto | `f_produzione_pms`, classe `01ROOM` | c'è; settembre e ottobre da caricare |
| Notti e prezzo per categoria | `f_bookings_tipologia` | c'è; base gestionale, scarto ~3% dal `01ROOM` |
| Inventario per categoria | `d_camere` (2026) | c'è; il 2027 è una variante dichiarata dal progetto |
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

Ricavo camere di budget = Σ categoria (notti × prezzo). Il ricavo per segmento
(serve a HotelCube) si ottiene ripartendo il totale con l'indice di prezzo per
segmento osservato nel 2026, dichiarato accanto al numero.

Scostamento budget → consuntivo, in quest'ordine, con somma esatta:

1. capacità (notti disponibili),
2. occupazione (notti vendute a parità di capacità),
3. mix (spostamento tra categorie a prezzi di budget),
4. prezzo (a parità di mix).

Confrontabilità: solo mesi chiusi e caricati per intero; un mese mancante dà
NULL, mai zero; nessun bersaglio annuo diviso per dodici.

## Flusso

1. `hotelops budget base` — calcola la base 2026 e genera il foglio (`.xlsx`),
   una riga per mese × segmento e per mese × categoria, con colonne: base 2026,
   budget 2027 (precompilato = base), ragione, prezzo base Lybra.
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

## Punti aperti (servono a Stefano)

1. **Base del prezzo per categoria.** `f_bookings_tipologia` e `01ROOM` distano
   ~3%. Proposta: budget e confronto per categoria sulla base gestionale; il
   totale riportato alla base `01ROOM` col rapporto mensile osservato nel 2026,
   mostrato come riga di raccordo.
2. **Tabella del budget.** Proposta: `f_budget_driver` (le versioni si
   accumulano, come le fotografie di `f_prenotazioni_otb`) + `f_budget_versioni`
   per stato e approvazione. INVARIANTS (I2) elenca già il budget tra gli
   SNAPSHOT; le *previsioni* restano fuori dal pool `f_*`.
3. **Date di apertura e chiusura 2027.** Il foglio Budget Rooms assume
   16 aprile – 15 ottobre; Pasqua 2027 è il 28 marzo.
4. **Nome commerciale** delle due suite del terzo piano (Suite o Luxury Suite).
5. **Allotment TUI** (oggi 10 Standard + 7 Superior): al terzo piano quelle
   categorie spariscono.
6. «Budget dietro in hotelops» è stato confermato con un «forse»: si rivede dopo
   questo primo pezzo.

## Prerequisiti (di Stefano)

- `gcloud auth login`.
- Esportazioni PMS di settembre e ottobre.
- Un'esportazione del rapporto per segmento (occupazione e produzione).
- Un'esportazione da Lybra, anche del 2026.
- Avvisare Rosa prima dello spegnimento del budget vecchio.
