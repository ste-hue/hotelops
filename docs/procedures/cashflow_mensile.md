---
subsystem: condges
code_paths:
  - verticals/condges/pf_rotate/rotate.py
  - verticals/condges/pf_rotate/extend.py
  - verticals/condges/pf_rotate/excel_model.py
  - verticals/condges/pf_rotate/saldi_registry.py
  - verticals/condges/pf_rotate/pf_writer.py
  - verticals/condges/scadenze_parse.py
  - verticals/condges/guida_rosa.py
  - ingest/flussi/ingest_piano_finanziario_xlsx.py
  - core/bq/load/load_pf_rotazioni.py
  - core/bq/load/load_saldi_banca_chiusura_mensile.py
  - core/bq/dimensioni/d_saldi_banca_chiusura_mensile.csv
  - core/bq/dimensioni/d_fornitori.csv
last_verified: 2026-11-03
source: tribal knowledge (Rosa) → first written 2026-05-13; riscritta dall'inizio il 2026-11-03 (indice A/B/C di knowledge, parola di Stefano)
---

# Procedura: il ciclo mensile del Piano Finanziario (Cashflow)

Questo file è **l'unico posto** in cui la procedura è scritta. Nel vault c'è un puntatore, non una
copia. La sezione A è scritta per Rosa e la sua guida HTML si **genera da qui** (`hotelops` →
`python -m verticals.condges.guida_rosa docs/procedures/cashflow_mensile.md --out <file.html>`),
non si riscrive a mano.

Tre sezioni, tre persone: **A. Rosa** (il file), **B. Stefano** (le decisioni e le firme),
**C. Tecnica** (carico, archivio, ancora, push: chi esegue la finestra). L'ordine del mese è
A → B → C; dentro C nessun passo si salta.

Storia breve: dal 2026-06-23 la rotazione non usa più `app_scadenzario.py` (file cancellato) ma
l'**app Cashflow** nel hub (`verticals/condges/app_cashflow.py`), che gira lo stesso motore della
CLI (`pf_rotate.rotate()`); la mappatura dei fornitori è permanente su BigQuery (`d_fornitori`,
MERGE su `codice_fornitore + societa_id`), il CSV `core/bq/dimensioni/d_fornitori.csv` è solo
seed/export. Il motore legge **due layout** di master: ORTI «month-closed» (saldi nella colonna
del mese chiuso) e INTUR «fixed-snapshot» (saldi fissi in colonna C), e dal 2026-11-03 riconosce
INTUR sia con l'intestazione «DATA RILEVAZ» in C1 sia con la **data scritta in C1** (#209).

---

## Quando — il rito del giorno 1 (regola di Stefano, 2026-10-26)

**Il giorno 1 di N+1 devono esistere gli input datati all'ultimo giorno di N**: i saldi dei sette
conti al 30/31 di N nel foglio di Rosa, i due scadenziari Esolver esportati il 30/31 di N **o
dopo**. La rotazione di N si fa appena il mese è chiuso, non «tra il 5 e il 10». Chiudere un mese
con uno scadenziario di quattro giorni prima è un debito da rifare, non una rotazione.

---

## A. Rosa — il file del mese

Questa parte è per Rosa. Niente nomi di comandi, niente codici: solo cosa fare e come capire se è
andata bene. Si lavora una società per volta: prima ORTI, poi INTUR.

### A1. Quando
Il giorno 1 del mese nuovo, o subito dopo. Se manca un pezzo (un saldo, uno scadenziario), lo si
dice e si aspetta: non si parte con i numeri del mese prima.

### A2. Il foglio «Saldi Banca Fine Mese»
Nel foglio su Drive, la colonna del mese appena chiuso va compilata per **tutti i conti
dell'elenco** (oggi: ORTI Intesa, MPS, MPS Kross, Unicredit; INTUR Sella, MPS, Intesa; BCP è
chiuso e resta fuori). Se un conto nuovo entra nell'elenco, entra anche qui.
**Un conto senza numero non è zero**: se un estratto non c'è ancora, la cella resta vuota e lo si
scrive a Stefano. **Il numero è il saldo dell'ultimo giorno del mese chiuso**, non di quando lo
guardi: se l'estratto è del 3 novembre, il saldo del 31 ottobre è un'altra riga. Non copiare un
numero da un'altra riga per «far tornare» il totale, e non incollare valori sopra le celle che
hanno una formula: i subtotali li calcola il foglio.

### A3. La rotazione nell'app Cashflow
L'app Cashflow è a questo indirizzo: <link> (sezione Finanza, riquadro «Cashflow»), con l'account
di amministrazione. Serve il PF del mese da chiudere, preso su Drive dalla cartella
«PIANI FINAZIARI › 2026» (la cartella dei PF, con il nome che vedi tu), e lo scadenziario Esolver
della stessa società («Situazione partite sintetica per fornitori», esportato in .xlsx, senza
filtri). **Guarda la data di esportazione dichiarata sullo scadenziario: se è prima dell'ultimo
giorno del mese che stai chiudendo, non si parte**, si chiede un export nuovo. Nell'app:
1. **Società**: ORTI o INTUR.
2. **PF del mese da chiudere**: carica il file di quella società. **Se nella cartella ci sono due
   file della stessa società per lo stesso mese, fermati e chiedi quale**: non scegliere il più
   recente.
3. **Scadenziario fornitori**: carica lo scadenziario della stessa società. **Prima, apri lo
   scadenziario e controlla che la ragione sociale in alto sia quella della società che stai
   chiudendo**: l'export «ORTI» può contenere INTUR. Sotto, l'app scrive quanti fornitori ha letto
   e i mesi che copre: la riga non deve essere vuota.
4. **Ultimo mese con saldi banca certificati**: il numero del mese che stai chiudendo. Se il
   file che hai caricato ha i saldi al 30/09, stai chiudendo **ottobre**, quindi **10**: è il
   mese che finirà nel nome del file che stai per produrre (A7), **non** di quello caricato.
   **Anno**: quello del mese che stai chiudendo.
5. **Saldi banca al cutover** (il campo si chiama così: vuol dire alla data di chiusura, l'ultimo
   giorno del mese chiuso): un campo per conto, già compilato se i saldi sono nel sistema.
   Confrontali con il tuo foglio; se un numero non torna, correggi a mano.
6. **Fornitori non mappati**: scegli **«fail (blocca)»**: se un fornitore manca, l'app si ferma e
   non lascia fuori niente in silenzio.
7. **Genera PF mese successivo** (fino a 30 secondi), leggi gli esiti, poi **Scarica**.

Cosa deve uscire: fornitori da mappare **0** (se compaiono, vedi A4); **Controlli: ERR = 0**.
INDET non è un errore (vuol dire «non abbastanza dati per decidere», per esempio una cella che
Excel non ha ancora ricalcolato). Con ERR maggiore di 0 il file **non si usa**: il nome finisce
con `_FAILED_CHECKS`, e i controlli falliti si mandano a Stefano.

### A4. Mappatura dei fornitori
Se l'app mostra «fornitori da mappare», per ognuno si sceglie la voce del PF (Materie prime,
Utenze, Consulenze, Varie ed eventuali…). **La scelta è permanente**: vale anche per i mesi dopo.
Se un fornitore non deve mai entrare nel PF, «escludi sempre». Se non sai dove metterne uno,
scrivi nome e codice a Stefano prima di scegliere: con «fail (blocca)» l'app aspetta. **Se ti
accorgi dopo di aver scelto la voce sbagliata, non toccare il file: dillo, si corregge nel
sistema.**

### A5. Le somme di riga nei fogli di dettaglio
In ogni foglio di dettaglio (Utenze, Salari, Materie prime…) la colonna **C** è la somma della
riga su tutti i mesi. Nei file prodotti dall'app dal 2026-11-03 in poi la somma arriva da sola
fino all'ultimo mese del foglio. **Per vederlo: clicca la cella C della riga e guarda che la
selezione evidenziata arrivi fino all'ultima colonna-mese del foglio.** Nei file **vecchi**, o se
la selezione si ferma prima, si allunga la somma a mano fino all'ultima colonna-mese (è successo
nel PF di ottobre ORTI).

### A6. Aprire il file in Excel e salvarlo
**Sempre.** L'app scrive le formule ma non i risultati; il sistema legge i risultati. Un file
scaricato e non salvato da Excel **arriva vuoto senza nessun errore** (è successo con il PF di
ottobre INTUR). Quindi: apri il file, guarda che «Piano Finanziario» e «Controlli» abbiano senso,
**salva da Excel**. **Poi chiudi e riapri il file: se il foglio «Controlli» è vuoto o tutto a
zero, il salvataggio non ha preso** e si rifà.

### A7. Su Drive con il nome pulito
Rinomina il file in `ORTI_PF_AAAA-MM.xlsx` (per INTUR uguale, con INTUR): il mese nel nome è
quello del **file che produci**, cioè il mese che hai appena chiuso (saldi al 31/10 →
`..._2026-10`; deciso il 4/11/2026, prima era il mese nuovo). È lo stesso numero che hai
messo al punto 4 di A3. Caricalo
nella cartella «PIANI FINAZIARI › 2026» su Drive, accanto a quelli del mese prima.

### A8. Dire che è pronto
Scrivi a Stefano che i due file sono su Drive e **dichiara «aperto e salvato da Excel»** per
ciascuno: chi fa il controllo dopo deve sapere se il passo è stato fatto. **Rosa non carica niente
nel sistema**: il carico, la promozione e la pagina sono passi tecnici con una firma (sezione B e
C). Poi il file torna a Rosa per compilare incassi e costi dei mesi nuovi: il PF arriva a dicembre
2029 e **le rate dei mutui da luglio 2027 sono già scritte dai contratti: non riscriverle**.

### Se qualcosa va storto
- «Genera» gira e non finisce mai: ricarica la pagina e rifai i passi; se succede due volte, manda a
  Stefano l'ora e la società.
- Riquadro rosso «Rotation fallita: …»: copia tutto il testo e mandalo a Stefano. Il file non è
  stato prodotto, non c'è niente da buttare.
- Controlli con ERR maggiore di 0: non usare il file; manda a Stefano i controlli falliti.

---

## B. Stefano — le decisioni

### B1. Apertura della finestra e chi esegue
Ogni mese la finestra tecnica (sezione C) si apre con una parola di Stefano («apri la finestra»)
e ha **un solo esecutore** dichiarato (una sessione, una macchina). Chi produce il file (Rosa
nell'app, oppure una sessione con la CLI che poi Rosa rivede) lo dice Stefano; il file di Rosa è
l'input, un file nostro è un confronto.

### B2. Gli scadenziari Esolver
Due export «Situazione partite sintetica per fornitori», uno per società, senza filtri,
**esportati il 30/31 del mese chiuso o dopo**, con la **data di esportazione dichiarata** nel nome
o nel messaggio (il controllo della ragione sociale in testa all'export lo fa chi lo carica, A3).
Un export precedente alla chiusura non vale: si rifà.

### B3. Voci non-fornitori e merito
L'app aggiorna le voci di uscita legate ai fornitori. Restano decisioni di merito, da dire a Rosa
o scrivere nel file: le **entrate** (Hotel, Residence, CVM, Supermercato, Rientro sospesi,
Caparre), **Salari**, **Tasse e imposte** oltre lo schema ricorrente, i **mutui** fuori contratto,
il **canone** e i fitti verso terzi, i progetti (cantiere, soft restyling) che entrano come leve
nella pagina Cassa e non nel PF. Un numero «scritto» (una stima, un tetto) resta tale finché non ha
una fonte: la pagina lo mostra come dichiarato, non come attestato.

### B4. Le firme dei passi non reversibili
Tre passi scrivono fuori dal file e si fanno **solo su parola di Stefano**, uno per uno:
1. il **carico** dei file in BigQuery (archivio delle rotazioni e piano vivo);
2. la **promozione** del piano vivo (sostituisce il piano precedente per società);
3. il **push** della pagina Cassa (`pubblica`).
Chi esegue dichiara prima lo SHA di `main` con cui gira, e dopo scrive la ricevuta nel verbale
della finestra. Le cifre vere restano fuori dai commit e dalle PR (repository pubblico).

---

## C. Tecnica — carico, archivio, ancora, push

Esecutore: uno solo, dichiarato in B1. Ogni passo ha un comando, un dry-run dove esiste, e una
ricevuta misurata. Si gira da un clone allineato a `origin/main`, con lo SHA scritto accanto a ogni
ricevuta. Il verbale della finestra è il posto delle ricevute.

### C1. Controllo dei valori in cache — PRIMA di tutto
Un file di Rosa salvato da Excel porta i risultati delle formule; un file prodotto dall'app e non
risalvato no, e il loader lo legge come **vuoto senza errore**. Controllo:

    python -m ingest.flussi.ingest_piano_finanziario_xlsx --file <PF.xlsx> --dry-run

Il dry-run stampa le righe lette: un PF intero ne porta decine (ORTI ~110, INTUR ~70 nell'ultimo
anno); poche righe o zero = formule senza cache. Il loader rifiuta il carico di un file «sottile»
(meno di una quota delle righe oggi in tabella per società) salvo `--accetta-sottile`, che non si
usa. Rimedio: Rosa riapre e salva da Excel (A6); in alternativa il ricalcolo headless

    soffice --headless --calc --convert-to xlsx --outdir <cartella> <PF.xlsx>

che **produce un file nuovo con un altro sha256**: nel verbale si scrivono entrambi, «in ingresso
→ ricalcolato», con la riga esatta del comando. Il dry-run e il carico girano sul file ricalcolato.
Nota: il ricalcolo headless non ripara le formule che Excel non ha mai calcolato in un file
costruito a mano; il controllo sulle righe lette resta la prova.

### C2. Saldi di fine mese e scadenziari
**Saldi.** Il CSV `core/bq/dimensioni/d_saldi_banca_chiusura_mensile.csv` è la verità e il carico
**sostituisce tutta la tabella** (WRITE_TRUNCATE): una riga per (società, data di riferimento,
conto), la nota cita il foglio di Rosa e la data di lettura. **Un conto mancante non si scrive a
zero**: la riga non c'è, e il motore della rotazione si ferma (gate O-A) invece di saltarlo.

    python -m core.bq.load.load_saldi_banca_chiusura_mensile --dry-run
    python -m core.bq.load.load_saldi_banca_chiusura_mensile

Ricevuta: `SELECT societa_id, banca_id, saldo_eur FROM f_saldi_banca_chiusura_mensile WHERE
data_riferimento = '<AAAA-MM-GG>'` = sette righe, i numeri del foglio di Rosa.

**Scadenziari.** Intake dal Drive con il nome di sorgente del registry (freschezza `grace_day: 1`:
dal 2 del mese `hotelops health` segna STALE finché non c'è la foto di fine mese):

    python -m ingest.drive_fetch --source-name ESOLVER_PARTITE_ORTI_SNAPSHOT --file-id <id>
    python -m ingest.drive_fetch --source-name ESOLVER_PARTITE_INTUR_SNAPSHOT --file-id <id>

Ricevuta: il raw in lineage con la data di esportazione dichiarata (B2).

### C3. Rotazione e allungamento (due layout)
Stesso motore dell'app Cashflow, dalla CLI:

    hotelops pf-rotate --pf <PF di N> --scad <partite al 30/31 di N> --scad-tipo sintetica \
      --societa ORTI --mese-chiuso <N> --anno <AAAA> --unmapped-policy fail [--exclude 264]

Il motore legge i saldi da BigQuery (C2), azzera il mese chiuso senza toccare formule, avanza la
cascata, scrive i fornitori nei fogli di dettaglio e produce `<SOC>_PF_<mese dei saldi>_post-rotate_<ts>.xlsx`
(saldi al 30/09 → `_2026-09`; convenzione decisa il 4/11/2026, commit 2bb4538);
con ERR nei Controlli il file esce con suffisso `_FAILED_CHECKS`. I due layout: ORTI month-closed
(saldi nella colonna del mese chiuso), INTUR fixed-snapshot (saldi in colonna C; riconosciuto con
«DATA RILEVAZ» in C1 oppure con la **data in C1**, #209: la data resta una data, non testo).
Più mesi arretrati = più giri in catena sull'output precedente.

**Allungamento dell'orizzonte** (una volta l'anno, o quando serve; atto dichiarato nel verbale con
lo SHA):

    hotelops pf-extend --pf <PF.xlsx> --to AAAA-MM [--trim-before AAAA-MM]

Copia il pattern dell'ultima colonna-mese con traduzione dei riferimenti, sposta la colonna TOTALI
del master e **ripunta anche i totali di riga a sinistra dei mesi nei fogli di dettaglio** (#218:
prima restavano fermi all'ultimo mese vecchio e le colonne nuove uscivano dal totale); il foglio
Controlli viene riallineato all'orizzonte nuovo (#214). Un totale di riga che già non arrivava
all'ultimo mese non viene allungato: è un range corto di chi ha scritto il file, si sistema a
mano (A5). I mesi aggiunti sono **vuoti**: nel piano vivo e nella pagina sono «non pianificati»,
mai zero (vedi `cdg_cassa.md`, punto 15).

### C4. Archivio delle rotazioni e promozione del piano vivo
Due tabelle, due carichi, due ricevute.

**Archivio `f_pf_rotazioni`** (tutte le versioni, una riga per società·voce·anno·mese·fonte·file,
con `occorrenza` nell'hash per le voci ripetute nello stesso mese, #168). Carico normale del mese:

    python -m core.bq.load.load_pf_rotazioni --dry-run <PF ORTI> <PF INTUR>
    python -m core.bq.load.load_pf_rotazioni <PF ORTI> <PF INTUR>

Il loader fa DELETE per `file_sorgente` + INSERT. Se la chiave di riga è cambiata (come con #168)
la corsa deve coprire **tutti** i file in tabella in una volta: `--ricarico-completo` con l'elenco
completo, e il loader rifiuta una corsa parziale finché restano righe con la chiave vecchia.
Ricevuta (dichiarata prima, misurata dopo):

    SELECT COUNT(*) AS totale,
           COUNTIF(hash_riga = TO_HEX(MD5(CONCAT(societa_id,'|',voce_id,'|',CAST(anno AS STRING),'|',CAST(mese AS STRING),'|',fonte,'|',file_sorgente)))) AS chiave_vecchia,
           COUNT(DISTINCT hash_riga) AS hash_distinti,
           COUNT(DISTINCT file_sorgente) AS file
    FROM `hotelops-suite.hotelops.f_pf_rotazioni`

attesa: `chiave_vecchia = 0`, `totale = hash_distinti`, `file` = numero di file in archivio, e per
file le stesse righe del dry-run rifatto subito prima della corsa.

**Piano vivo `f_piano_finanziario_input`** (chiave naturale `[societa_id, fonte]`: la promozione
**sostituisce** il piano precedente della società, come fa il foglio). Intake + promote dal Drive
(policy AUTO) o dal file:

    python -m ingest.drive_fetch --source-name ESOLVER_PF_ORTI_SNAPSHOT --file-id <id>
    python -m ingest.drive_fetch --source-name ESOLVER_PF_INTUR_SNAPSHOT --file-id <id>
    # oppure, dal file: python -m ingest.flussi.ingest_piano_finanziario_xlsx --file <PF.xlsx> [--dry-run]

Ricevuta: una sola `file_sorgente` per società; `hotelops cdg cassa --aggiorna` non si ferma su
`BaselineNonUnica`; in «Fonti e versioni» della pagina compare il file nuovo con la data di
caricamento. Il canone e i fitti verso terzi vengono isolati per etichetta della riga nel foglio
di dettaglio: se cambia il nome della riga, la pagina perde il canone (controllare «Canone come
nel PF» in testa).

### C5. Controllo d'ancora — prima della promozione
Il PF di N+1 porta i saldi di fine N per conto (righe «Saldo <banca>» del master; «SALDO MESE
PRECED.» = la loro somma nella colonna del primo mese aperto). Prima di promuovere, si confrontano
**conto per conto** con `f_saldi_banca_chiusura_mensile` alla data di fine N e con i valori noti
sbagliati del foglio dei saldi (subtotali incollati nelle righe banca, saldi copiati da un'altra
società). **Rosso = la promozione si ferma**: si scrive nel verbale cosa porta il file, la
correzione la fa Rosa nel foglio, non noi in BigQuery. Lo strumento:

    python -m verticals.condges.pf_rotate.controllo_ancora <PF ORTI> <PF INTUR> --riferimento <json fuori repo>

(oppure `HOTELOPS_ANCORA_RIFERIMENTO=<json>`): il JSON con i valori attesi e vietati sta **fuori dal
repository** (le cifre non si versionano); uscita 1 = rosso. **Nessun passo automatico lo lancia**:
è uno strumento a mano, e versionarlo non lo fa girare. Per questo la ricevuta è l'**esito**, non il
percorso: nel verbale della finestra una riga «C5 · comando + ora + uscita» con stato **passato /
fallito / non girato** («non girato» è uno stato scrivibile, non un'assenza).

### C6. Quadratura e i quattro controlli
**Quadratura al centesimo** (file per file, prima del carico): per ogni colonna-mese del master,
somma delle voci parsate = riga TOTALE ENTRATE e riga TOTALE USCITE del foglio; le differenze si
dichiarano con mese e importo, non si «sistemano».

    python -m verticals.condges.pf_rotate.pf_quadratura <file.xlsx o cartella> [...]

Cosa NON guarda: legge solo il master «Piano Finanziario» con i valori in cache e confronta i
totali per colonna-mese; **i totali di riga dei fogli di dettaglio (colonna C) le sono invisibili
per costruzione** (il loader non li usa), e un file senza valori in cache quadra zero contro zero:
C1 viene prima. Come C5, **nessun passo automatico lo lancia** e la ricevuta è l'esito: riga
«C6 · comando + ora + uscita», stato passato / fallito / non girato.

I quattro controlli operativi sul file, prima di passarlo a Rosa (e dopo, prima di promuovere):
1. **Eyeball di 3–5 fornitori chiave** (es. Le Croissant, Ausino, fitto INTUR): nel foglio di
   dettaglio della loro voce le celle del primo mese aperto corrispondono allo scadenziario.
2. **Totali**: la riga TOTALE USCITE del master si aggiorna via formula dai fogli di dettaglio;
   il valore del primo mese aperto è plausibile rispetto al mese chiuso.
3. **Saldi banca**: TOTALE BANCHE del master = somma di **tutti** i conti del registry (ORTI: MPS +
   Intesa + MPS Kross + Unicredit; INTUR: Sella + MPS + Intesa) e coincide con il foglio di Rosa;
   «SALDO MESE PRECED.» del primo mese aperto è uguale.
4. **Cash Flow** del primo mese aperto = TOTALE ENTRATE − TOTALE USCITE.
Il foglio «Controlli» del file li ripete per etichetta (C1–C16, #210): ERR = 0 è la condizione.

### C7. Push della pagina Cassa
Dal clone che ha le tre variabili Cloudflare nel `.env` (oggi il Mac), su parola «pubblica»:

    python -m cli cdg scenario salva .hotelops_state/cdg_cassa/base_scenario.json   # solo se il seme è cambiato
    python -m cli cdg cassa --aggiorna --push

Ricevuta: rilettura del KV (`cassa_html`, `generato_il` dell'ora del push) e, in pagina, «Fonti e
versioni» con il file PF nuovo, i saldi di partenza alla data di fine N, i mesi oltre il PF come
«senza PF» e i mesi vuoti come «non pianificati». I file locali accanto al seme (`pf_corretto.json`,
`canone_dichiarato.json`, `banda_pf.json`) non stanno nel repository: si portano a mano.

**Il giallo (deciso il 06/11/2026: avviso a 50.000 €).** Il campo «Avviso €» della pagina è un
campanello nostro: i mesi sotto quella cifra si colorano di giallo. **Il limite vero è zero.** Dove
compare lo stato «AVVISO» (chiusura mensile a video, tesoreria, Excel della tesoreria, app CdG,
viste `stato_liquidita` su BigQuery) vuol dire che il saldo previsto del mese è sotto il campanello,
**non** sotto zero: è un avviso, non un blocco. Sotto zero è un'altra cosa e si chiama «sotto zero».
**Se il campo «Avviso €» è a zero, il giallo non compare mai**: vuol dire che nessuno ha messo un
campanello, non che siamo lontani dal fondo; i seed salvati prima del 06/11 hanno zero finché chi
pubblica non scrive 50.000 nel seme. Rosa, nell'app Cashflow (sezione A), questo giallo non lo vede:
per questo la riga sta qui e non in A.

---

## Limitazioni note (aggiornate 2026-11-03)
- `app_scadenzario.py` è **cancellato** dal 2026-06-23: nessun passo lo usa; la mappatura dei
  fornitori è su BigQuery (`d_fornitori`), permanente, e il CSV è solo seed/export. **Doppia verità
  aperta**: gli upsert in-app non tornano nel CSV; `core/bq/load/load_fornitori.py` fa WRITE_TRUNCATE
  dal CSV (protetto da `--force`). Prima di qualsiasi reseed esportare la tabella nel CSV
  (`export_fornitori_to_csv`) e committare.
- Le voci non-fornitori (B3) restano a mano nel master.
- Il match dei fornitori per nome è fuzzy (containment ≥ 4 caratteri): il codice fornitore vince
  quando c'è.
- I nomi dei fogli con refuso (`Commisisoni Portali`, `Mutui e Finaziamenti`, ` Varie ed Eventuali`)
  sono nel motore: se Rosa cambia template, aggiornare la mappa.
- `verticals/condges/scadenzario_excel.py` è un flusso alternativo non collegato alla CLI: codice
  morto candidato a rimozione.
- Le stime oltre l'ultimo mese pianificato da Rosa (righe «Stima …» nei dettagli) oggi non sono
  distinguibili dal piano nel carico: proposta in corso (loader marca le righe, pagina le mostra
  come «stima»); finché non c'è, non si caricano.
