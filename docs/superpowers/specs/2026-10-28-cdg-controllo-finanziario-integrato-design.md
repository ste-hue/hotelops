# CdG — Controllo finanziario integrato INTUR–ORTI

**Data:** 2026-10-28 · **Stato:** bozza, in approvazione · **Vertical:** condges · **Mandato:** documento «HOTELOPS / CdG — Piano di implementazione» consegnato da Stefano il 28/10 («questo piano è quello che dobbiamo fare»), qui calato sulla realtà di hotelops dopo la ricognizione (Fase 0, lato hotelops, fatta in sessione).

## La domanda

*Quanto possiamo investire, quando, e cosa succede alla cassa di ORTI e di INTUR se lo
facciamo?* Prima di autorizzare un impegno (terzo piano, soft restyling a 5 k a camera,
terrazza) Stefano deve vedere il minimo di cassa dei prossimi dodici mesi, con i piani
finanziari veri, i consuntivi veri e il canone trattato come trasferimento tra casse.

Il CdG è il **modulo dei numeri** del gruppo: tutto ciò che è numero, in dettaglio, sulle
tre dimensioni temporali. La **Regia** (`mgmt_os`) ne prende la sintesi e linka il
dettaglio (deciso il 28/10: supera il punto 8 della decisione 2026-10-04 «una sola
superficie», che resta vero per la sintesi).

| Sezione | Dimensione | Domanda |
| --- | --- | --- |
| Competenza | passato | cosa abbiamo prodotto e consumato (spec `2026-10-28-cdg-competenza-design.md`, diventa un tab di questo modulo) |
| Cassa | presente | quanto c'è in banca, cosa è entrato e uscito, previsto contro vero |
| Impegno | futuro | cosa dobbiamo pagare e incassare, saldi proiettati, progetti, scenari |

## Decisioni di Stefano (28/10, in sessione)

| Tema | Decisione |
| --- | --- |
| Mandato | Il piano a sei fasi è quello da fare, nell'ordine: ricognizione → PF storici → consuntivi e scostamenti → cash flow integrato → simulatore CAPEX → canone e indicatori → cruscotto e Regia |
| Superficie | Regia = sintesi; CdG = dettaglio autorevole, app edge `cdg.panorama-host.com` dietro Access |
| Lettori | Stefano (entrambe le email), direttore gm@, Rosa amministrazione@, stedepi@ — è la policy Access riusabile «Canone — nominativa», già esistente |
| Previsioni in BigQuery | Sì, in un **dataset separato dai fatti**: `hotelops_previsioni`. La decisione 2026-06-19 («proiezioni mai nelle `f_*`») si riscrive: i fatti restano in `hotelops`, le previsioni e gli scenari vivono accanto, con la stessa lineage. `f_pf_rotazioni` (che già la violava) migra lì |
| Orizzonte PF | Sempre dodici mesi aperti, allungamento automatico a ogni rotazione (commit `e7cc85d`). Il mandato chiede «almeno dicembre 2027»: Stefano il 28/10: «da ottobre lo faremo almeno fino a dicembre 2027», cioè il PF di Rosa stesso arriva a dic 2027 (`pf-extend` al rito di ottobre). La cascata saldi si ferma dove finisce il PF: mai mesi inventati |
| PF settembre | I due file `ORTI_PF_2026-09` / `INTUR_PF_2026-09` (saldi al 31/08, da settembre tutto proiezione) sono in lineage dal 28/10 (raw `26a5f25d`, `5c7120bf`); INTUR porta `DATA RILEVAZ` 30/09 e affidamento Sella 150 k (BQ `f_affidamenti`: 50 k): da chiarire con Rosa |
| Il 65% | Era una semplificazione. Si guardano i costi veri per categoria, l'intercompany si riconosce e si tratta come tale, il budget vero nasce dalla cassa vera |
| Entrate | Nei PF le entrate sono sempre state previsioni. Il consuntivo incassi è la **Stampa Cassa** HotelCube per struttura (tre export del 28/10, in GCS) |
| Infrastruttura Cloudflare | Token con permessi Access/KV/Workers in 1Password (`panorama_apps · CLOUDFLARE_API_TOKEN access · prod`, vault `work`): Worker, KV, dominio e app Access li crea il costruttore con `cf` e `wrangler` |
| Movimenti stale | Cancellate il 28/10 le 579 righe 2026 non più presenti negli export completi (INTUR pareggia al centesimo, ORTI residuo 31,40 €) |

## Fase 0 — Ricognizione: cosa esiste davvero

La ricognizione lato hotelops è fatta. Le sei repo esterne del mandato sono state guardate per nome, README e albero: nessuna va integrata come codice.

### Dentro hotelops (riusare)

| Capacità del mandato | Esiste | Dove | Stato |
| --- | --- | --- | --- |
| PF storici per versione (Fase 1) | **sì** | `f_pf_rotazioni` (hash con `file_sorgente`, ogni vintage coesiste) + `core/bq/load/load_pf_rotazioni.py` + parser `ingest/flussi/ingest_piano_finanziario_xlsx.py` (colonne datate per anno) | caricati mar/apr/mag 2026 ×2 società (giugno 2026). Mancano giu/lug/ago 2026 e set–dic 2025 |
| PF vivo | sì | `f_piano_finanziario_input` fonte `PIANO_FINANZIARIO`, source `ESOLVER_PF_{ORTI,INTUR}_SNAPSHOT` via lineage, vista `v_pf_corrente` (ultima generazione per chiave) | master 2026-07 promossi il 21/08; health rosso dal 30/09 |
| Motore rotazione mensile | sì | `verticals/condges/pf_rotate/` (`hotelops pf-rotate`, `pf-extend`, generatore `pf-genera`) | vivo, orizzonte rolling dal 28/10 |
| Consuntivo per voce PF (Fase 2) | **in parte** | `v_piano_finanziario_consuntivo` (movimenti Esolver + banche → voci PF via `d_voci_piano_finanziario`) e `v_piano_finanziario_mensile` (previsto vs consuntivo, finestra −6/+12) | il confronto è contro il PF vivo, non contro una versione; le entrate vengono dalla prima nota, non dalla cassa |
| Consuntivo incassi per struttura | **raw** | source `HOTELCUBE_STAMPACASSA_ORTI_APPEND` (RAW_ONLY dal 12/07, parser mai scritto); tre export 28/10 in GCS: Panorama 9.878 doc / 4.544.359,40 €, Angelina 2.300 / 634.486,69 €, CVM 905 / 229.003,65 €, 1/1–28/10/2026 | parser `f_stampa_cassa` = primo task della Fase 2 |
| Saldi banca veri | sì | `f_saldi_banca_chiusura_mensile` (ancora del loop), `f_saldi_banca_snapshot`, `f_banche_movimenti` | ORTI MPS fermo al 16/09 (health rosso) |
| Cash forward (Fase 3) | sì | `v_previsione_cassa`: ancora bancaria + consuntivo mesi chiusi + PF mesi aperti, 12 mesi, `stato_liquidita` | da estendere all'orizzonte PF e al consolidato |
| Scadenze fornitori | sì | `f_partite_aperte_fornitori` (snapshot Esolver) | fermo al 26/09 (health rosso) |
| Mutui (Fase 3, §9) | **fuori BQ** | app edge `mutui.panorama-host.com` (repo locale `app-mutui`, Worker + KV scenari), dati in `public/data/mutui_completi.json`: 5 finanziamenti attivi, rate ricalcolate dai contratti il 02/09/2026 | il PF di Rosa ha già la riga «Mutui e Finanziamenti»: il JSON è la fonte autorevole dei piani di ammortamento, il PF la cassa. Doppio conteggio da evitare per costruzione |
| Canone e DSCR (Fase 5, §8) | **sì** | `verticals/condges/canone_sim.py` (motore annuale 2027–2031, porting testato del BP), `canone_fonti.py` (osservati da BQ), `build_canone_artifact.py` → `canone.panorama-host.com` | è già il «motore Canone» del mandato; la repo `panorama-businessplan` contiene solo l'xlsx del BP |
| Progetti CAPEX (Fase 4) | **seme** | `d_progetti` (2 progetti: HPAN25PIANO1, SPIAGGIA_LOTTO7), `f_progetto_voci` (10), `f_progetto_eventi` (19); spec `2026-04-22-projects-event-sourced-design.md` («la cassa nasce dall'impegno, non dalla fattura»), mai portata avanti; skill `progetto-capex` e tracking xlsx su Drive (`HPAN26PIANO3_Tracking.xlsx`) | il simulatore si appoggia a questo modello, non ne inventa uno |
| Scenari | no | — | nasce con il dataset `hotelops_previsioni` |
| Regia (Fase 6) | sì | `mgmt_os/mgmt/actuals.py` legge `f_pms_statistiche` e `f_produzione_pms` in BigQuery; Regia su `regia.panorama-host.com` | gli indicatori nuovi si aggiungono allo stesso collettore |

### Fuori hotelops (chiudere o citare)

| Repo del mandato | Cos'è davvero | Verdetto |
| --- | --- | --- |
| `panorama-businessplan` | un solo file: il BP 2026–2035 xlsx | fonte del Piano industriale, non codice. Il motore canone è già in hotelops |
| `bilancio-riclassificato` | script Python 2024 (riclassificazione Palumbo da CSV) | superato dal bilancino in BigQuery e dalle categorie gestionali; da archiviare |
| `HotelOPS-fornitori` | vuota (`.gitkeep`, `CLAUDE.md`) | nulla da integrare; i fornitori sono in `d_fornitori` e `f_partite_aperte_fornitori` |
| `app-mutui` (= `mutui-tracker`) | app edge viva, dati JSON | fonte dei piani di ammortamento (sopra) |
| `investimenti2026` | app del vecchio piano a 139 camere (2025) | superata da `d_progetti` e dal tracking P3; da archiviare |
| `canone.panorama-host.com` | app edge di hotelops | già integrata |

## Modello dati

Un dataset nuovo, **`hotelops_previsioni`**, stesso progetto, stessa lineage (`f_raw_objects`, `raw_object_id` obbligatorio), scrittura solo via `bq_write_validated` (I1). Nomi con prefisso `p_` per non confonderli con i fatti.

| Tabella | Grana | Note |
| --- | --- | --- |
| `p_pf_versioni` | una riga per file PF caricato: società, versione (`YYYY-MM` del primo mese aperto), data elaborazione (dal file, non dal nome), orizzonte, `raw_object_id` | sostituisce la colonna `file_sorgente` di `f_pf_rotazioni` |
| `p_pf_righe` | società × versione × voce × anno × mese × importo (+ `direzione` entrata/uscita, `occorrenza`) | migrazione di `f_pf_rotazioni`; carica anche set–dic 2025 e giu–ago 2026 |
| `p_scenari` | scenario: nome, versione PF base, stato, parametri (canone, ipotesi entrate), progetti inclusi, creato il | gli scenari si accumulano, mai sovrascritti. **Li scrive solo la CLI** (`hotelops cdg scenario ...`, Stefano): l'app edge non ha write-path verso BigQuery, come nessuna app edge del gruppo |
| `p_scenario_flussi` | scenario × società × mese × voce × importo, con `origine` (pf_base / progetto / canone / mutuo / manuale) | il motore scrive qui i flussi che il simulatore aggiunge o toglie |
| `p_progetti_pagamenti` | progetto × scenario × data × importo × modalità (rate uniformi, acconto-SAL-saldo, calendario) | **solo ipotesi**: impegni, fatture e pagamenti sono fatti e stanno in `f_progetto_eventi` (`hotelops`, evento `PAGAMENTO` da aggiungere ai tre esistenti). Il motore legge entrambe: i fatti sostituiscono le ipotesi dello stesso progetto man mano che arrivano |
| `p_mutui_rate` | finanziamento × società × mese × importo rata (capitale + interessi insieme) | il JSON dell'app Mutui porta totali annui e parametri, non un calendario: il calendario lo **esporta l'app stessa** (il suo codice JS, eseguito una volta, scrive il JSON mensile) e si carica via lineage. Nessun quinto motore sul debito in Python. Fa fede la repo `app-mutui` al suo HEAD (rate ricalcolate il 02/09/2026; il campo `data_compilazione` 30/04 è un'etichetta stale, da aggiornare lì) |

I fatti restano dove sono: `f_stampa_cassa` (nuova, in `hotelops`), `f_saldi_banca_*`, `f_banche_movimenti`, `f_movimenti_contabili`, `f_partite_aperte_fornitori`, `f_bilancino`.

## Il motore

Headless, Python puro, nessun I/O nei calcoli (stesso principio di `canone_sim`):

- **Saldo**: per società e mese, `saldo_finale = saldo_iniziale + incassi − pagamenti`; l'ancora è l'ultimo saldo banca vero; i mesi chiusi usano i consuntivi, i mesi aperti il PF della versione scelta più i flussi dello scenario.
- **Consolidato**: somma delle due società con le righe intercompany (canone, fitto Angelina) riconosciute e nettate; le disponibilità bancarie restano distinte, mai sommate come se fossero una cassa sola. Nel foglio PF di ORTI il canone non ha riga propria (sta in «Godimento Beni di Terzi» con Angelina e il canone CVM verso terzi) e la gamba ORTI (2,53 M) non coincide con quella INTUR (2,19 M): il canone si **isola dal foglio dettaglio** per voce del master di Rosa (fornitore INTUR), non per somma di voce; lo scarto tra le due gambe si espone come «intercompany non riconciliato», non si forza.
- **Mesi chiusi nella cascata saldi**: li riempie il solo movimento bancario (`f_banche_movimenti`), l'unico che riconcilia con l'ancora. Prima nota e Stampa Cassa misurano gli scostamenti per voce (Fase 2), non la cassa bancaria: sono due consuntivi diversi e la pagina dice quale sta leggendo.
- **Scostamenti**: per voce e mese, `consuntivo − previsione(versione)` e rapporto con `SAFE_DIVIDE`; consuntivo assente = mancante, mai zero; previsioni di marzo, giugno e settembre affiancate per la stessa voce.
- **Progetti**: un progetto distribuisce pagamenti secondo la modalità; la somma delle rate coincide con l'importo con controllo degli arrotondamenti; attivabile per scenario.
- **Canone**: la scaletta contrattuale vale sia per il DSCR (`canone_sim`, annuale, **netta**) sia per la cassa (rate alle scadenze contrattuali, oggi bimestrali da 122 k = 100 k + IVA 22%, **lorde**). Il motore cassa applica l'IVA alla scaletta netta. Nel consolidato l'IVA non si netta (debito INTUR e credito ORTI hanno timing diverso): resta come flusso fiscale di ciascuna società.
- **Mutui**: rate dal calendario esportato dall'app Mutui, per società titolare; il PF le contiene già nella riga «Mutui e Finanziamenti»: il motore sostituisce **solo le righe del foglio dettaglio che corrispondono ai cinque finanziamenti** e lascia il resto (Kross, Unicredit, leasing, interessi fidi se presenti).
- **Riproducibilità**: stesso snapshot delle fonti, stesso scenario, stesso risultato; ogni cifra porta `origine` e `raw_object_id`.

## Le fasi, calate su hotelops

| Fase | Mandato | Cosa si fa davvero | Accettazione |
| --- | --- | --- | --- |
| 0 | Ricognizione | fatta sopra; resta da archiviare le repo superate e scrivere la matrice nel vault | ogni componente ha una fonte autorevole dichiarata (questa tabella) |
| 1 | PF storici | dataset `hotelops_previsioni`; migrazione di `f_pf_rotazioni` → `p_pf_righe` + `p_pf_versioni`; **source nuove** `ESOLVER_PFSTORICO_{ORTI,INTUR}_APPEND` (canonical `p_pf_righe`, una source = un target, il gate non cambia): lo stesso file entra due volte, una per il PF vivo e una per l'archivio; intake dei 22 file di Drive «PIANI FINANZIARI» (2025 set–dic ×2, 2026 mar–set ×2). I file 2025 sono pre-standard: dry-run del parser su tutti prima di stimare (il detector anno accetta marker 2025–2030) | totali per versione riconciliati con i file al centesimo; differenze documentate |
| 2 | Consuntivi e scostamenti | parser `ingest/flussi/ingest_stampa_cassa.py` → `f_stampa_cassa` sul **layout del 28/10** (report raggruppato per modalità: è lo standard; il tracciato per-documento di luglio descritto nel registry è un altro report e il parser lo rifiuta con messaggio). Ogni riga porta la **sezione** del report. **Incasso del mese** = «Documenti pagati e caparre incassate/restituite» + «Rientri del sospeso»; «Documenti sospesi» = crediti, esposti a parte, mai cassa; «Totalmente incassati con caparra» = cassa già entrata quando la caparra fu versata, informativa. Data = data documento (l'unica nel report), dichiarata in pagina. Vista `v_scostamenti_pf` (versione × voce × mese); incassi consuntivi = Stampa Cassa per ENTRATE_HOTEL/RESIDENCE/CVM, prima nota e banche per il resto | ogni scostamento ricostruibile dai dati sorgente; per struttura, somma delle sezioni = TOTALE GENERALE del report al centesimo |
| 3 | Cash flow integrato | motore saldi per società e consolidato sull'orizzonte PF; `p_mutui_rate` dal JSON Mutui; canone alle scadenze contrattuali; partite aperte come informativa; estensione di `v_previsione_cassa` o vista nuova sul dataset previsioni | saldi riconciliati con i PF di Rosa a parità di input; intercompany non duplicato |
| 4 | Simulatore CAPEX | `p_scenari`, `p_scenario_flussi`, `p_progetti_pagamenti`; motore distribuzione pagamenti; progetti iniziali: terzo piano, soft restyling, terrazza | un progetto da 120 k in sei rate da 20 k produce sei uscite e muove i saldi successivi |
| 5 | Canone e indicatori | leva canone collegata a `canone_sim` (DSCR) e al motore cassa (rate); mutui collegati | a parità di input, stessi risultati di `canone.panorama-host.com`, salvo differenze motivate |
| 6 | Cruscotto e Regia | app edge `cdg.panorama-host.com` con i tab Competenza · Cassa · Impegno e le viste del mandato (Fotografia, Scostamenti, Investimenti, Simulazione, Decisioni); indicatori per Regia nel collettore `actuals.py` | Stefano vede il render con dati reali prima del merge; Regia legge, non ricalcola |

Ogni fase è un piano a sé (`docs/superpowers/plans/`), una PR su hotelops e, dove serve, una su `panorama_apps`. La Fase 1 è la prima: senza versioni dei PF non esistono né scostamenti né scenari.

## Regole di liquidità (proposta del costruttore, da confermare in Fase 3)

- **Cassa minima** = minimo del saldo proiettato per società sui dodici mesi aperti.
- **Riserva** = soglia per società sotto cui un mese è «in tensione»; valore versionato nello scenario, non costante nel codice (oggi `v_previsione_cassa` usa 50 k per ATTENZIONE e 0 per PERICOLO: sono i valori di partenza).
- **Fabbisogno aggiuntivo** = quanto manca per riportare il mese peggiore alla riserva.
- **Investimento sostenibile** = l'importo massimo di un progetto che, con la sua distribuzione, lascia ogni mese sopra la riserva.
- **Liquidità disponibile** = saldo proiettato + fidi non utilizzati (oggi solo INTUR SELLA 50 k); i fidi si mostrano separati dal saldo.
- Un mese senza consuntivo e senza PF non è zero: è «non valutabile» e interrompe la cascata con un avviso.

## Scelte del costruttore dopo la revisione (28/10, da controllare leggendo)

Un revisore indipendente ha letto il documento; queste sono le risposte che ho dato io, non Stefano:

1. **Scenari**: li crea solo la CLI (Stefano); la pagina ha leve vive in JavaScript come l'app Canone, senza salvare; in BigQuery entrano solo gli scenari promossi da CLI.
2. **Stampa Cassa**: standard = layout del 28/10; incasso del mese = pagati + rientri sospeso; sospesi fuori dalla cassa; data documento.
3. **Canone**: isolato dal foglio dettaglio (fornitore INTUR), IVA applicata in cassa, non nettata nel consolidato.
4. **Mutui**: calendario mensile esportato dall'app, fa fede la repo al suo HEAD; sostituzione solo delle righe corrispondenti.
5. **Progetti**: fatti in `f_progetto_eventi`, ipotesi in `p_progetti_pagamenti`.
6. **Archivio PF**: source nuove `ESOLVER_PFSTORICO_*_APPEND`, stesso file due intake.
7. **Cascata saldi**: mesi chiusi dal solo movimento bancario.

## Anti-goals

- Un gestionale nuovo: si integrano i sistemi che esistono.
- Scenari che diventano impegni da soli; rate di mutui o canone contate due volte; casse di ORTI e INTUR sommate come una.
- Soglie o semafori cablati nelle query.
- Regia che ricalcola.
- Riscrivere `app_cdg` o riaccenderla.

## Cosa resta al costruttore

Nomi definitivi delle tabelle `p_*` e delle viste, struttura del payload dell'app edge, ordine dei task dentro ogni fase, scelta tra estendere `v_previsione_cassa` o affiancarle una vista sul dataset previsioni, formato di import del JSON Mutui.

## Domande ancora aperte per Stefano

1. **Chi paga i progetti**: terzo piano, soft restyling e terrazza non sono in `d_progetti`. Per ciascuno, la cassa che si muove è INTUR (proprietaria dell'immobile) o ORTI (gestore)? Decide quale saldo scende e se il canone c'entra.
2. **Data di elaborazione dei PF storici**: il mandato dice di non fidarsi del nome del file. Nei file c'è `DATA RILEVAZ` solo per INTUR (e in quello di settembre dice 30/09 mentre i saldi sono al 31/08); per ORTI vale la data di modifica su Drive o la chiedo a Rosa?
3. **Riserva minima di cassa** per società (i 50 k attuali sono un default, non una tua decisione).
4. **Canone in cassa**: le rate restano bimestrali da 122 k anche negli scenari con canone diverso, o la periodicità è una leva?
