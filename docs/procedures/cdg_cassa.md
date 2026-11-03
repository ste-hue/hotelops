---
subsystem: condges
code_paths:
  - verticals/condges/cassa_motore.py
  - verticals/condges/cassa_fonti.py
  - verticals/condges/cassa_scenario.py
  - verticals/condges/build_cassa_artifact.py
  - verticals/condges/cassa_template.html
  - ingest/flussi/ingest_scenario_cassa.py
  - scripts/provision_cdg.sh
last_verified: 2026-10-29
source: Task 11 del piano docs/superpowers/plans/2026-10-29-cdg-cassa-pagina.md
---

# Procedura: pagina Cassa del Controllo di Gestione (cdg.panorama-host.com)

La pagina Cassa mostra i saldi mensili di ORTI e INTUR dal Piano Finanziario vivo, con i
minimi, lo slider del canone ORTI → INTUR, progetti e finanziamenti accendibili e spostabili.
Il calcolo gira nel browser (porting JS del motore Python, verificato dai test); nessuna
scrittura dal browser verso BigQuery. Spec: `docs/superpowers/specs/2026-10-29-cdg-cassa-pagina-design.md`.

## 1. Aggiornare la pagina (dopo un nuovo PF, nuovi saldi, nuovi fatti)

    hotelops cdg cassa --aggiorna --push

- `--aggiorna` rilegge BigQuery in **sola lettura** (saldi di chiusura, PF vivo, eventi dei
  progetti, scenari salvati) e salva uno snapshot datato in `.hotelops_state/cdg_cassa/`
  (`latest.json` + copia con timestamp). Senza `--aggiorna` la pagina si rigenera dall'ultimo
  snapshot: utile per cambiare template o seme senza toccare BigQuery.
- `--push` pubblica pagina e payload nel KV del Worker `cdg` (chiavi `cassa_html`, `cassa_data`).
  Richiede nel `.env`: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CDG_KV_NAMESPACE_ID`.
- Senza flag scrive solo `docs/reports/artifacts/cassa.html` (gitignored): aprilo in locale.
- Il builder **si ferma** se una società ha due versioni di PF (`BaselineNonUnica`): prima si
  ri-promuove (punto 3), poi si rigenera.
- Dentro un worktree: `python -m cli cdg cassa …` (il comando `hotelops` del venv punta al clone principale).

## 2. Salvare uno scenario (versionato, mai sovrascritto)

1. Nella pagina, regola le leve e premi **Esporta scenario**: scarica
   `cassa-scenario-<nome>.json` (schema `cdg-cassa-scenario/2`, con dentro la base PF usata; i
   file `/1` già salvati si rileggono e si promuovono come prima).
2. Registra il file:

       hotelops cdg scenario salva FILE --nome "Nome scenario"

   fa intake nel lineage (source `CDG_SCENARIOCASSA_GROUP_APPEND`, raw su GCS) e promote nelle
   tre tabelle `hotelops_previsioni.p_scenari`, `p_scenario_flussi`, `p_progetti_pagamenti`
   (append-only, importi in centesimi, `raw_object_id` obbligatorio). Il nome vive nel documento.

   **Una volta, dopo il merge dei progetti a livelli e prima di salvare qualsiasi scenario:**

       python -m core.bq.load.create_previsioni_tables

   aggiunge a `p_progetti_pagamenti` le colonne `macro` e `area` (ALTER idempotente: rilanciarlo
   non fa danni; `--dry-run` stampa le istruzioni senza eseguirle). Se lo si dimentica, il promote
   si ferma **prima di scrivere** con `RuntimeError: … senza colonne ['macro', 'area']: esegui prima
   python -m core.bq.load.create_previsioni_tables … Nessuna riga scritta.`: si lancia il comando e
   si ripete il salvataggio, nessuna riga da pulire.
3. `hotelops cdg scenario lista` elenca gli scenari salvati. Al prossimo `--aggiorna` entrano
   nel menu Scenario della pagina, con l'ora di salvataggio; se la base PF è cambiata sono
   marcati «base diversa».
4. Il **seme** (scenario di partenza, `.hotelops_state/cdg_cassa/base_scenario.json`) è un file
   locale: dopo averlo cambiato va ri-salvato con il punto 2. Un salvato con lo **stesso nome**
   del seme non entra nel menu (il seme è la versione viva) ed è dichiarato in «Fonti e versioni».
   Il seme può anche **ritirare** dei nomi dal menu: `"scenari_ritirati": ["Base 29/10", "Base 30/10"]`
   nel file. Le righe su BigQuery restano (lineage append-only); la pagina li elenca in «Fonti e
   versioni» con l'ora e il motivo «ritirato nel seme». Per rimetterli nel menu basta togliere il nome.

5. **Esporta Excel** (bottone accanto a «Esporta scenario») scarica un solo `.xlsx` con nove fogli per
   lo scenario in vista, in euro: Minimi, Saldi mese per mese, Calendario (una riga per rata, lordo in
   cassa, più il canone), Canone (scenario contro PF), Progetti, Finanziamenti (erogazioni e rate),
   Voci PF corrette, PF (la base di Rosa nell'orizzonte), Fonti. È scritto dal browser senza librerie
   (`<script id="excel">`, zip di SpreadsheetML); `hotelops cdg tabelle` resta l'export da riga di comando.

6. **Vocabolario di stato** (brief UI del 31/10, §A). Ogni numero in pagina porta una di quattro parole,
   come attributo `data-stato` sul chip `.stato`: **attestato** (documento di terzi: estratto, atto,
   delibera) · **dichiarato** (dai nostri libri o da una persona, nessun documento) · **da verificare**
   (atteso, non riscontrato) · **non registrato** (vuoto perché nessuno l'ha scritto, che non è «0 €» e si
   disegna tratteggiato). La card del minimo elenca le sue condizioni con questi chip (saldo di partenza,
   finanziamenti non attestati che entrano prima del minimo, assenza di mesi PF); la barra fissa li
   ripete come puntini. Lo stato di un finanziamento nasce dalla parola libera del documento (`stato`):
   «deliberato», «contratto», «firmato» → attestato; «da verificare», «ipotesi» → da verificare; altro →
   dichiarato. I colori sono provvisori fino al passaggio dataviz (§E).
7. **Finanziamenti**: due riquadri, «Quando la banca ti dà i soldi · tranche» e «Quando li restituisci ·
   rate del mutuo». Il documento può portare `importo` (centesimi, facoltativo) = quanto la banca ha
   promesso: la pagina mostra «erogato X di Y» e il generatore delle tranche ha tre forme: tutto insieme,
   metà a metà lavori e metà a fine lavori, a cadenza. Senza rate di rimborso la pagina lo dice nel
   riquadro: entra solo il denaro erogato, il minimo è ottimista.

8. **Scenario a tutto schermo** (brief UI, punto 5). Dal riepilogo di «Scenario e leve» il bottone
   «a tutto schermo» (o l'indirizzo `#leve`, `#leve/finanziamenti`…) apre la vista: barra alta
   traslucida con «‹ Cassa», il nome dello scenario e «Salva»; i due minimi sempre sotto; cinque
   segmenti (Progetti, Finanziamenti, Voci corrette, Calendario, Strumenti). La lista è una riga per
   leva; toccandola si apre **un solo editor**: un foglio dal basso al telefono (si chiude tirandolo
   giù, toccando lo sfondo, con ✕ o Esc; la velocità del rilascio decide), un pannello a destra dai
   900 px. Dentro una leva resta aperto un pagamento alla volta. Con «riduci movimento» il foglio
   appare e sparisce in dissolvenza. Stesso DOM della pagina, una classe sul body: motore e formato
   non cambiano.

9. **Grossolano, poi fine.** Una rata si **divide** (÷: metà resta nel suo mese, metà va al mese dopo,
   sommandosi se c'è già una rata; il resto dei centesimi resta dov'era) e si **unisce** (⇥: con la
   rata successiva di quel pagamento). La somma non cambia mai; poi la rata si trascina nel calendario.
   Ogni pagamento può portare i suoi **documenti** (titolo + link Drive: preventivo, contratto,
   fattura), mostrati come chip accanto al nome; ogni progetto la sua **cartella Drive**. Nel documento
   dello scenario sono campi facoltativi (`documenti` sul pagamento e sul finanziamento, `drive_url`
   sul progetto), nelle tabelle BigQuery viaggiano dentro `parametri`; l'Excel li porta nei fogli
   Progetti e Finanziamenti. Sul finanziamento il documento tipico è la relazione notarile o la
   delibera: attesta l'importo e la banca, non le date delle tranche, che restano dichiarate.

10. **Pagamento e «come paghi un fornitore».** Il *pagamento* è la riga con i suoi mesi: è l'unica cosa
    che il calcolo legge. «Come paghi un fornitore» (nel documento: `contratti` del progetto) sono i patti
    con quel fornitore, anticipo, SAL, ritenuta, o quote in percentuale: «Genera i pagamenti» li traduce
    in righe di pagamento verso quel fornitore, sostituendo le sue e lasciando le altre, e la pagina
    controlla che i pagamenti reali li seguano ancora. In pagina non si chiama più «contratto».

11. **La bozza nel browser.** Ogni pubblicazione rigenera la pagina dal seme: quello che si scrive a mano
    senza «Salva scenario» sparirebbe al ricaricamento. Il browser ricorda da solo l'ultima bozza modificata
    (`localStorage`, solo in quel browser) e al ricaricamento la propone: «Riprendi» la mette nel menu e la
    apre, «Scarta» la toglie. «Salva scenario (.json)» la marca come salvata. Se la base PF è cambiata la
    riga lo dice. Senza memoria del browser (navigazione privata) la pagina avvisa prima di chiudere.
    Non è un salvataggio condiviso: per fissare una bozza nel seme serve ancora il file .json e il Mac.

12. **Il fornitore come oggetto** (brief UI, punto 8, primo passo). Un fornitore è l'**id** scritto in
    «fornitore» dentro i pagamenti (lo stesso in ogni pagamento) più una scheda nella mappa `fornitori`
    dello scenario: nome, codice Esolver, società, cartella Drive. La scheda «Fornitori» (e il segmento
    nella vista a tutto schermo) elenca chi è usato nei pagamenti e chi è nella mappa, con totale lordo,
    numero di pagamenti, mesi, documenti e progetti. L'**anagrafica Esolver** (`d_fornitori`, senza
    intercompany ed esclusi) entra nel payload come `fornitori` e serve a **riconoscere** il codice da un
    nome scritto a mano: proposta («Esolver? 1640», bottone «usa»), mai imposta. `hotelops cdg tabelle` ha
    la tabella `fornitori` e l'Excel il foglio «Fornitori» con le stesse colonne. Il **nome è il nostro**
    («AMCN», «Prisco il tappezziere»): il codice aggancia Esolver, il cui nome resta come dettaglio.
    **Patti abituali**: dentro «Come paghi <fornitore>» il bottone «ricorda come patti abituali» salva la
    forma dei patti nella scheda del fornitore (anticipo, SAL, ritenuta o quote, con i mesi come distanze
    dall'inizio, senza totale); un contratto nuovo ancora vuoto li eredita appena scrivi quel fornitore,
    uno già scritto li prende solo con «usa i patti abituali». La scheda li mostra in una riga, con
    «× dimentica»; la colonna `patti_abituali` è nella tabella e nel foglio.

13. **PF corretto.** Una voce del PF che una persona dichiara diversa dal file di Rosa (le tasse del
    31/10) non è una leva dello scenario: vive in `.hotelops_state/cdg_cassa/pf_corretto.json`
    (`correzioni: [{societa, voce_id, mese, importo_cent, dichiarato_da, dichiarato_il, fonte}]`) e al
    `cdg cassa` prende il posto della voce **prima** di ogni scenario, Solo PF compreso. La pagina la
    mostra in «Voci del PF corrette» col chip «dichiarato · Rosa», i limiti la dichiarano, `cdg tabelle`
    ha la tabella `pf_correzioni` e l'Excel il foglio «PF corretto». Una correzione su un mese fuori dal PF
    non si applica e resta elencata. Si toglie dal file quando il PF di Rosa porta la cifra.

14. **Importa budget** (brief UI, punto 8, ultimo passo). In «Strumenti», «Importa budget (.xlsx/.csv)»
    legge il file nel browser (zip di SpreadsheetML letto dalla directory centrale, deflate del browser;
    CSV con «;» o «,» e decimali italiani), sceglie il foglio con più importi, indovina le colonne dalle
    parole della riga di testa (fornitore · area di intervento/opera · totale/importo · note, tutte
    cambiabili) e mostra l'**anteprima** prima di applicare: per ogni riga il fornitore riconosciuto
    (scheda già nello scenario → «scheda»; anagrafica Esolver → «Esolver? codice»; altrimenti «nuovo»; vuoto
    o TBD → «senza fornitore»), l'importo netto e **come si paga** (dai patti abituali del fornitore se ci
    sono, altrimenti una rata al mese scelto). Le righe di totale, imprevisti e IVA si saltano da sole; ogni
    riga si accende o spegne. «Aggiungi N pagamenti» li mette nel progetto scelto (o in uno nuovo, spento)
    con stato «ipotesi», crea le schede dei fornitori nuovi col codice se riconosciuto, e la bozza resta nel
    browser come sempre. Il foglio di Drive «Budget interno terzo piano» (per opera) si importa così com'è.
    Le righe entrano come sottovoci di una **macro nuova col nome del file**: «Importa budget» aggiunge,
    non sostituisce. Per rifare un progetto (o una sua macro) da un foglio Excel, vedi il punto 15.

15. **Progetti a livelli e giro Excel.** Dentro ogni progetto c'è una tabella a tre livelli: **budget del
    progetto → macro → sottovoci** (fornitore, area, netto, «quando», IVA). Si scrive nelle celle; per
    aggiungere si scrive nell'ultima riga vuota. Le sottovoci consumano il budget della macro, le macro
    consumano il budget del progetto; quello che non è assegnato si paga nei mesi del budget («da
    assegnare»). Il calcolo legge solo i pagamenti, che la pagina deriva dai livelli a ogni modifica.
    Sopra la tabella, tre bottoni:
    - **Esporta (.xlsx)** scarica `<progetto>-<AAAA-MM-GG>.xlsx`: un foglio col nome del progetto, colonne
      Macro · Sottovoce · Fornitore · Area · Totale netto € · Quando · IVA % · Note. Una riga per
      sottovoce; i budget in testa («budget progetto» nella colonna Macro, «budget» nella colonna
      Sottovoce). «Quando» è testo che si riscrive a mano: `mar 27`, `gen 27–mar 27 ×3`,
      `ott 26 15% · nov 26–mar 27 ×5 · mag 27 10%`.
    - **Esporta vuoto** scarica `<progetto>-<AAAA-MM-GG>-vuoto.xlsx`: solo l'intestazione e la riga del
      budget del progetto, da riempire in Excel.
    - **Importa (.xlsx/.csv)** legge un foglio e **sostituisce**. Un file **con** la colonna «Macro»
      sostituisce **tutto il progetto**. Un file **senza** (il foglio «Per fornitore» di hpan26-soft:
      Struttura · Fornitore · Area di intervento · Totale netto € · Note) sostituisce **solo la macro
      scelta** nell'anteprima; di default è una macro nuova col nome del file. Senza «Quando» ogni riga
      è una rata al mese scelto; senza «IVA %» vale l'IVA scelta («come la macro» di default).
    Prima di applicare, l'**anteprima** dice riga per riga cosa **entra**, cosa **cambia** (prima → dopo) e
    cosa **sparisce**, le righe **da sistemare** (importo, «quando» o IVA illeggibili, un secondo «budget»
    della stessa macro o un secondo «budget progetto»: non entrano), il
    totale del progetto prima → dopo (lordo in cassa e netto) e il **minimo della società** prima → dopo.
    Ogni riga si spegne: spenta, resta com'è nel progetto; una macro spenta vale con tutte le sue righe.
    Un file uguale al progetto dice «nessuna differenza». «Sostituisci» applica, crea le schede dei
    fornitori nuovi e il messaggio in basso ha «annulla». Le righe di totale, IVA e imprevisti e quelle a 0
    (da prezzare) si saltano; «Da assegnare», TBD e vuoto diventano sottovoci **senza fornitore**, che
    consumano il budget della macro. Una sottovoce ritrovata (stessa macro, sottovoce e fornitore) tiene
    stato e documenti. Se il suo «Quando» è cambiato, il testo vince: i patti di quel fornitore cadono e
    l'anteprima lo scrive («i patti di AMCN si perdono: le rate vengono dal file»). Con una macro scelta
    cadono solo i patti legati alle sottovoci di quella macro; quelli dello stesso fornitore in altre
    macro restano.
    **Quando l'orizzonte scorre** (nuovo mese chiuso), la pagina ricalcola il «da assegnare» sui mesi del
    budget non ancora passati (i mesi oltre l'ultimo allungano l'orizzonte, punto 16). Le tabelle Python (`hotelops cdg tabelle`) e BigQuery invece leggono i
    pagamenti salvati al momento del salvataggio. Per uno scenario `/2` salvato prima che l'orizzonte
    scorresse, pagina e tabelle possono quindi dare cifre diverse sul «da assegnare» finché lo scenario
    non viene ri-esportato e ri-salvato (punto 2).

16. **Orizzonte lungo: «non pianificato» non è zero, e la banda cresce con h.** Il PF vivo è un file solo
    su due anni (colonne datate per anno dall'ingest, wrap dicembre→gennaio); si allunga con
    `pf-extend --to AAAA-MM` sul master, alla finestra, come atto dichiarato nel verbale. L'ingest non
    emette celle a zero, quindi un mese con la colonna ma senza righe per una società è **non
    pianificato** (`mesi_non_pianificati` per società nello snapshot, calcolato in `cassa_fonti`): il
    motore (Python e JS, in parità) lo tratta come un mese senza PF per il minimo, la pagina lo marca
    «non pianificato» (§A non registrato) nella tabella, nella scheda del minimo e nel grafico, mai
    con uno 0; l'Excel e `cdg tabelle` portano la colonna accanto a «senza PF». Sotto ogni minimo la
    **banda d'errore per h** (mesi dall'ancora): misurata fino a 3 mesi (file locale `banda_pf.json`
    accanto al seme, dal rapporto del 30/10: INTUR ottimista, ORTI pessimista; le misure non stanno
    nel repo), oltre solo il segno e la crescita; nel
    grafico un corridoio fino a h 3 e la deriva tratteggiata oltre. Se il PF arriva oltre 12 mesi
    dall'ancora, in testa compare «documento di pianificazione, non previsione».

## 3. Ri-promuovere un PF (nuovo file di Rosa)

1. Intake + promote del file (policy AUTO):

       python -m ingest.drive_fetch --source-name ESOLVER_PF_ORTI_SNAPSHOT --file-id <id>
       python -m ingest.drive_fetch --source-name ESOLVER_PF_INTUR_SNAPSHOT --file-id <id>

   (Drive via service account `~/.config/hotelops/drive-audit-key.json`; niente download a mano).
2. **Ricevuta attesa**: in `f_piano_finanziario_input` una sola `file_sorgente` per società
   (la promozione per versione sostituisce la precedente); `hotelops cdg cassa --aggiorna` non
   deve fermarsi su `BaselineNonUnica`; in «Fonti e versioni» compare il nome del file nuovo e la
   data di caricamento.
3. Il canone Fitto Hotel e i fitti verso terzi vengono isolati dal foglio dettaglio per etichetta della riga («Fitto Hotel», «Ramo d'Azienda»)
   (`_riclassifica_dettaglio`), non per somma di voce: se il foglio cambia nome alle righe, la
   pagina perde il canone e lo slider parte da zero. Controllare «Canone come nel PF» in testa.

## 4. Vocabolario della pagina

| Parola | Significato |
|---|---|
| **dichiarato** | saldo preso dal foglio di Rosa (`f_saldi_banca_chiusura_mensile`), senza estratto che lo attesti |
| **attestato** (quadratura per conto) | saldo per cui esiste una chiusura precedente dello stesso conto e i movimenti bancari in BigQuery coprono fino alla data e, sommati alla chiusura precedente, danno esattamente il saldo dichiarato (`cassa_fonti.leggi_ancore`). Altrimenti «dichiarato», con il motivo accanto: nessuna chiusura precedente, nessun movimento, movimenti che si fermano prima, scostamento in euro |
| **ancora** | il saldo di partenza per società (somma dei conti) alla data dell'ultima chiusura mensile |
| **solo PF, nessuna leva** | la baseline: PF vivo senza canone modificato, progetti, finanziamenti o righe manuali |
| **seme** | lo scenario di partenza caricato dal file locale; nel menu con il suffisso «· seme» |
| **senza PF** (mesi oltre l'ultimo mese coperto) | nessun saldo previsto: la pagina mostra solo l'effetto cumulato delle leve dopo l'ultimo mese PF |
| **da verificare** | finanziamento o pagamento ipotizzato, non deliberato o con condizioni ignote (es. IVA della Staff House) |
| **base diversa** | scenario salvato con una versione di PF diversa da quella corrente: si può aprire, ma i numeri non sono confrontabili |
| **non riconciliato** | pagamento registrato (`f_progetto_eventi`) che non trova un pagamento previsto dello stesso fornitore nello scenario: conta comunque come uscita |
| **una gamba** | flusso intercompany presente su una sola società (o verso terzi): resta dov'è, non si inventa la contropartita |
| **peso sul minimo** | di quanto cambierebbe il minimo della società togliendo (o accendendo) quella leva |

## 5. Accessi

- Edge app dietro Cloudflare Access, policy nominativa «Canone — nominativa» (Stefano, direttore,
  Rosa, padre). Aggiungere una persona = modificare la policy in Zero Trust, non il Worker.
- Tile nel hub (`verticals/hub/roles.py`): `cdg` è sensibile (S1), concesso a mano.
- Provisioning iniziale: `scripts/provision_cdg.sh` stampa i comandi per Stefano (KV, Worker,
  custom domain, app Access, AUD). Il Worker sta in `panorama_apps/cdg` (repo sul Mac; copia in
  `~/.local/share/hotelops/cdg-cassa-handoff/panorama_apps_cdg` su tong).

## Tabelle per Excel (`hotelops cdg tabelle`)

La pagina esporta lo **scenario** (le leve). Per avere **tutto quello che la pagina sa** in una
forma che Excel apre senza conversioni:

    python -m cli cdg tabelle                                  # dalla pagina appena generata
    python -m cli cdg tabelle dati.json --out cartella         # dal payload scaricato
    python -m cli cdg tabelle cassa.html --scenario mio.json   # con uno scenario esportato

Sorgente: la pagina `.html` (legge il blocco `<script id="dati">`), oppure il payload `.json`,
che è anche quello che il Worker serve su `/cassa/data.json`. Nessuna lettura di BigQuery, quindi
gira anche dove le credenziali non ci sono.

Tredici CSV con separatore `;`, virgola decimale e BOM: Excel italiano li apre con un doppio clic,
senza procedura di importazione. Niente separatore delle migliaia, altrimenti Excel legge i numeri
come testo. Gli importi sono in euro; dentro il JSON restano centesimi interi.

| file | cosa c'è |
|---|---|
| `saldi_mensili.csv` | mese per mese e società per società, saldo iniziale, entrate e uscite per origine, saldo finale, due volte: `solo PF` e lo scenario |
| `minimi.csv` | mese critico e saldo minimo, per scenario e società |
| `pf_voci.csv` | il PF voce per voce |
| `flussi_fra_societa.csv` | canone e godimento, con lo stato (`pf`, `una_gamba`, `scenario`) |
| `ancore_per_conto.csv` | i saldi di partenza conto per conto, se quadrano coi movimenti e perché no |
| `canone_rate.csv` | le rate nel PF accanto a quelle del contratto, con la colonna che dice quale rata il PF non ha |
| `canone_rate_fuori_orizzonte.csv` | le rate prima del primo mese della pagina: senza queste l'annuo non torna |
| `progetti.csv`, `pagamenti.csv` | progetti con totale netto; ogni pagamento con mese, netto, imposta e lordo |
| `finanziamenti.csv` | erogazioni e rate di rimborso, una riga per mese |
| `fatti.csv` | i pagamenti registrati davvero |
| `limiti.csv` | le cose che la pagina dichiara di non sapere, una per riga |
| `versioni.csv` | quando è stata generata, da quali file PF, il canone dichiarato |

**Per un agente, non per Excel:** `python -m cli cdg tabelle SORGENTE --json --out cartella` scrive le stesse
tabelle come JSON modulari, un file per tabella (`{"schema","tabella","colonne","unita","righe":[{campo: valore}]}`)
con gli importi in **centesimi interi** e le date ISO, più `manifest.json` che le elenca con colonne, numero di
righe e sha256, la data della pagina, lo scenario e i file PF di base. Un agente legge il manifesto e prende solo
quello che gli serve. Sono dati riservati: restano dentro il perimetro Access o sul disco, mai nel repository, che
è pubblico.

I saldi dello scenario sono **ricalcolati dal motore Python**, non copiati dalla pagina. Il comando
confronta il solo-PF ricalcolato con quello scritto nel payload e, se divergono, stampa i mesi e
esce con codice 3: una divergenza fra il JavaScript della pagina e il Python è un difetto, non un
dettaglio di export.
