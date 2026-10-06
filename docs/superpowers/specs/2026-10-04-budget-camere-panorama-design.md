# Budget per driver — primo pezzo: camere Hotel Panorama

**Data:** 2026-10-04 · **Stato:** approvato da Stefano il 2026-10-05 (punti 1–3 chiusi); piano 1 unito il 2026-10-06 (#130, #131); piano 2 disegnato il 2026-10-06, da approvare · **Vertical:** condges

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
| Budget e strategia | Il **budget è l'obiettivo per mese**: ricavo camere 2026 sugli stessi giorni × (1 + crescita). Crescita di partenza 12%, modificabile per mese. I prezzi per categoria sono la **strategia** per arrivarci (revenue management), non il budget: il foglio mostra lo scarto tra i due. Il «perché» si legge a consuntivo, scomponendo il 2027 vero contro il 2026 vero nei quattro effetti. Deciso il 2026-10-05. |
| Come si scrive la strategia | Stefano scrive il **prezzo 2027** per mese × categoria. La cella è precompilata col prezzo medio 2026 più un aumento di partenza (7%, un solo parametro); l'aumento % di ogni riga è calcolato. |
| Base del prezzo | Gestionale (rapporto per tipologia venduta); il totale è riportato alla base `01ROOM` col rapporto mensile osservato, mostrato come riga di raccordo. |
| Tabelle | `f_budget_driver` (le versioni si accumulano) + `f_budget_versioni` (stato e approvazione). Dettaglio in «Piano 2». |
| Versione | Una versione = **tutto il foglio**: obiettivi per mese e prezzi per categoria insieme. Una correzione ai prezzi è una versione nuova anche se gli obiettivi non cambiano. Deciso il 2026-10-06. |
| Moduli | Tre moduli, una domanda ciascuno (2026-10-06, sessione CdG): **Regia** (`mgmt_os`: cosa faccio adesso), **Controllo di gestione** (hotelops: quanto rispetto al budget e perché), **Piano industriale** (BP Solo Terzo, 5 anni). Questo pezzo sta tutto nel secondo; le tre viste sono l'interfaccia CdG → Regia. `app_cdg` è ritirata per sempre: non si riaccende e non si ridisegna. |

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
è `osservato` se (a) il `01ROOM` è caricato per ogni giorno del calendario,
(b) il file per tipologia è stato esportato dopo l'ultimo giorno del mese e
(c) le sue notti coprono almeno il 97% delle notti delle statistiche;
altrimenti è `stima` e il raccordo a `01ROOM` resta vuoto (mai zero). Per le
viste che non usano i dati per categoria basta (a).

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
   prezzo medio 2026, notti 2027 (precompilate), prezzo 2027 (precompilato,
   da scrivere), aumento % e ricavo 2027 (formule), prezzo base Lybra, ragione.
   Il foglio «Budget» dà per mese obiettivo, risultato dei prezzi scritti e
   scarto; il foglio «Mesi» i quattro effetti, con formule vive. Il
   taglio per segmento si aggiunge quando arriva l'esportazione vera.
2. Stefano modifica le celle e scrive le ragioni.
3. `hotelops budget carica <file.xlsx>` — intake del foglio → GCS
   (`gs://hotelops-raw`) + `f_raw_objects`, poi promote → righe in tabella,
   stato `bozza`. L'identità della versione è l'impronta del **contenuto delle
   celle**: un foglio ricaricato identico non crea una versione; un foglio con
   struttura cambiata è rifiutato.
4. `hotelops budget approva --versione <id>` — solo Stefano; le versioni
   approvate non si modificano, una correzione è una versione nuova.

## Piano 2 — versioni, approvazione, viste

### Caricamento

- Fonte `HOTELOPS_BUDGETCAMERE_ORTI_APPEND` (grammatica a 4 parti; sistema
  `HOTELOPS` perché il file lo genera hotelops stesso). Lifecycle APPEND: ogni
  versione aggiunge righe, nessuna riga si cancella o si riscrive (I2).
- Il parser legge i fogli `Budget`, `Prezzi`, `Mesi` **per intestazione**
  (`foglio.COL_BUDGET`, `COL_PREZZI`, `COL_MESI`): colonne spostate vanno bene,
  colonne rinominate o mancanti → rifiuto con il nome della colonna. Legge i
  **valori calcolati** delle formule: serve il file salvato da Excel; un file
  con formule senza valore (mai aperto in Excel) è rifiutato con istruzioni.
- Impronta = hash dei valori di tutte le celle dei tre fogli, nell'ordine delle
  intestazioni (non dei byte del file: un risalvataggio non è una versione —
  stessa regola adottata da `mgmt_os`, commit `e516560`). `versione` = primi 12
  caratteri dell'hash. Impronta già presente → «versione già caricata», uscita
  0, nessuna riga.
- Un foglio con mesi in stato `stima` si carica ma **non si può approvare**
  (il raccordo manca, i totali sono n.d.): l'approvazione rifiuta e dice quali
  mesi.

### Tabelle

`f_budget_versioni` — una riga per versione. Chiave: `versione`.

| Colonna | Tipo | Note |
| --- | --- | --- |
| `versione` | STRING | impronta del contenuto |
| `gradino` | STRING | `camere-hotel` (poi `camere-residence`, `fb`, …) |
| `anno` | INT64 | 2027 |
| `anno_base` | INT64 | 2026 |
| `apertura`, `chiusura` | DATE | calendario del budget |
| `stato` | STRING | `bozza` → `approvato` → `ritirato` |
| `caricato_il` | TIMESTAMP | |
| `approvato_il` | TIMESTAMP | NULL finché bozza |
| `approvato_da` | STRING | account gcloud di chi lancia `approva` |
| `ritirato_il` | TIMESTAMP | quando una versione successiva viene approvata |
| `raw_object_id` | STRING | lineage del file |

`f_budget_driver` — le righe del foglio. Chiave:
`[versione, business_unit_id, mese, voce, categoria]`.

| Colonna | Tipo | Note |
| --- | --- | --- |
| `versione` | STRING | → `f_budget_versioni` |
| `gradino`, `anno`, `societa_id`, `business_unit_id` | | `camere-hotel`, 2027, ORTI, HOTEL |
| `mese` | INT64 | 1–12 |
| `voce` | STRING | vedi sotto |
| `categoria` | STRING | NULL per le voci di mese; nome categoria per quelle di categoria |
| `valore` | NUMERIC | netto IVA; notti e camere come interi |
| `base` | NUMERIC | valore 2026 sugli stessi giorni (obiettivo: ricavo `01ROOM`; prezzo: prezzo medio 2026; notti: notti 2026) |
| `crescita_pct` | NUMERIC | obiettivo: la cella gialla del foglio Budget; prezzo: aumento % calcolato |
| `stato_mese` | STRING | `osservato` / `stima`, dal foglio Mesi |
| `ragione` | STRING | colonna Ragione del foglio Prezzi; NULL per le voci di mese |
| `fonte` | STRING | `FOGLIO_BUDGET_CAMERE` (tag `fonte`, regola di governance) |

Voci di mese (`categoria` NULL): `ricavo_camere` (obiettivo 2027, foglio Budget
col. E), `giorni` (calendario), `raccordo` (foglio Mesi col. Q). Voci di
categoria: `prezzo`, `notti`, `camere` (foglio Prezzi: K, I, E).

Il ricavo «con i prezzi scritti» (foglio Budget col. F) non si salva: è
Σ notti × prezzo × raccordo, e si ricalcola nella vista. Una sola verità per
numero.

### Approvazione

- `hotelops budget approva --versione <id>`: la versione passa a `approvato`;
  la versione prima approvata dello stesso `gradino` e `anno` passa a
  `ritirato` nello stesso comando. Una sola approvata alla volta per gradino.
- Rifiuta se la versione ha mesi `stima`, se è già approvata o ritirata, se
  non esiste.
- `hotelops budget versioni [--gradino X]`: elenco con stato e date.
- Nessun comando «modifica»: una riga approvata non cambia mai (I2). Nessun
  comando «cancella»: si ritira approvando una versione nuova.

### Cosa legge il Management OS

Tre viste in `core/bq/views/`, nessuna logica da ricopiare a valle (I8).
Colonne concordate con la sessione «Numeri» di `mgmt_os` il 2026-10-06.

`v_camere_consuntivo_mensile` — `anno, business_unit_id, mese, giorni_calendario,
giorni_caricati, notti, capacita, ricavo_camere, prezzo_medio, stato_mese`.
Base: `f_pms_statistiche` (notti, capacità modale sui giorni con vendite) +
`f_produzione_pms` classe `01ROOM` imponibile. `stato_mese = 'osservato'` se e
solo se `giorni_caricati = giorni_calendario` (ogni giorno del mese nel
calendario di apertura ha una riga `01ROOM`); altrimenti `stima`. Per HOTEL il
calendario è quello della versione approvata dell'anno (`f_budget_versioni`) o,
se non c'è, l'intero mese; per RESIDENCE e CVM l'intero mese. Oggi questa
logica vive solo dentro `v_booking_curve`: la vista la estrae, non la duplica.

`v_budget_approvato` — `anno, business_unit_id, mese, voce, categoria, valore,
versione, stato, approvato_il, approvato_da, base, crescita_pct,
calendario_giorni, stato_mese, ragione, fonte`. Solo le righe con
`stato = 'approvato'`. `mgmt_os` legge `voce = 'ricavo_camere'` per la scheda
Numeri e `voce IN ('prezzo', 'notti')` per la sezione revenue management.

`v_budget_camere_scostamento` — `anno, business_unit_id, mese, versione,
budget, consuntivo, stato_mese, scarto, scarto_pct, base_anno_prima,
con_prezzi_scritti`. `consuntivo`, `scarto` e `scarto_pct` sono NULL se
`stato_mese = 'stima'`: mai una somma parziale. I **quattro effetti a
consuntivo** (calendario, occupazione, mix, prezzo) non sono in questo piano:
servono le notti e i prezzi per categoria del 2027 (`f_bookings_tipologia`),
che esistono da aprile 2027. Le colonne nascono allora, con dati veri davanti
(gate delle pagine).

Finché queste viste non esistono, la scheda «Numeri» di `mgmt_os` continua a
leggere il foglio Budget Rooms (ponte, numeri provvisori) e dichiara provvisoria
la propria scomposizione a tre effetti (`mgmt/numbers.py`), che si spegne
quando legge `v_budget_camere_scostamento`.

### Verifica del piano 2

- Foglio generato da `budget base` → `carica` → le righe in `f_budget_driver`
  riproducono ogni cella letta, al centesimo (test di andata e ritorno).
- Stesso file risalvato → nessuna versione nuova. Colonna rinominata → rifiuto
  col nome. File senza valori calcolati → rifiuto con istruzioni.
- `approva` su versione con mesi `stima` → rifiuto con i mesi. `approva` due
  volte → la prima passa a `ritirato`, una sola `approvato`.
- `v_camere_consuntivo_mensile`: i mesi aprile–settembre 2026 di HOTEL sono
  `osservato`, ottobre 2026 è `stima` finché non arriva l'esportazione di
  fine mese.
- Stefano vede le tre viste con dati veri (le sue righe approvate, il
  consuntivo 2026) prima del merge.

## Spegnimento del budget vecchio (deciso, cambio separato)

`hotelops bva` e la colonna budget in `v_piano_finanziario_mensile`. `app_cdg`
non va toccata: è ritirata intera, non si spegne a pezzi. Le righe di
`f_budget_mensile` restano. Prima del cambio: Stefano avvisa Rosa.

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
2. **Versioni, approvazione, viste** — sezione «Piano 2» sopra; piano
   `docs/superpowers/plans/2026-10-06-budget-camere-versioni-approvazione.md`.
   Il file reale da cui nasce il parser è il foglio generato da `budget base`
   (`budget_camere_HOTEL_2027_base_*.xlsx`), già esistente.

## Punti aperti (servono a Stefano)

1. **Regola delle notti 2027 precompilate** (vedi Modello): da confermare
   guardando il primo foglio generato. Al 2026-10-06 il foglio non è ancora
   stato guardato.
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
7. **Budget in HotelCube.** Stefano vuole il 2027 caricato in HotelCube e lo
   scostamento in tempo reale letto da lì. Le righe di `f_budget_driver` hanno
   `voce` e `categoria`, ma la mappa verso le voci HotelCube non si inventa:
   domanda per il direttore — «HotelCube importa il budget da file o si scrive
   a mano nelle schermate Budget Occupazione/Produzione? E le righe sono per
   segmento, per categoria, o entrambe?». Dalla risposta nasce una dimensione
   `d_voci_hotelcube` e un comando di esportazione, non colonne nuove ora.

## Prerequisiti (di Stefano)

- Un'esportazione nuova di «Detailed Data for Bookings» del Panorama, anno
  2026 (oggi ferma al 2 agosto); un'altra a stagione chiusa.
- Esportazione PMS di ottobre, a mese chiuso.
- Un'esportazione del rapporto per segmento (occupazione e produzione).
- Un'esportazione da Lybra, anche del 2026.
- Avvisare Rosa prima dello spegnimento del budget vecchio.
