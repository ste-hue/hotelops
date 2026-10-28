# CdG — il modulo dei numeri. Prima sezione: Competenza

**Data:** 2026-10-28 · **Stato:** bozza, in approvazione · **Vertical:** condges · **Sessione:** 2026-10-27/28 (categorie gestionali, CE quadrato con Esolver, movimenti ORTI/INTUR ingeriti)

> Questa spec è il **primo tab** del modulo CdG descritto in `2026-10-28-cdg-controllo-finanziario-integrato-design.md` (mandato a sei fasi: PF storici, consuntivi, cash flow integrato, simulatore CAPEX, canone, cruscotto). Le decisioni di superficie, lettori e infrastruttura stanno lì; qui solo il contenuto della sezione Competenza.

## La domanda

*Cosa abbiamo prodotto e cosa abbiamo consumato, per struttura, per categoria e per
società, mese per mese e in progressivo — e dove sta andando il rapporto tra i due?*

È la domanda della dimensione **COMPETENZA** (il passato, mese chiuso). Il CdG ha
tre sezioni, una per dimensione temporale (`docs/architecture/LE_3_DIMENSIONI.md`):

| Sezione | Domanda | Quando |
| --- | --- | --- |
| **Competenza** | cosa abbiamo prodotto e consumato | questa spec |
| Cassa | quanto c'è in banca oggi e cosa è entrato e uscito | spec del mandato, Fasi 2–3 |
| Impegno | cosa dobbiamo pagare e incassare, saldi proiettati, piano finanziario, progetti, scenari | spec del mandato, Fasi 3–5 |

Ogni sezione risponde a una domanda sola; dentro la sezione ogni blocco si giustifica
contro quella domanda (regola «una pagina, una domanda», CLAUDE.md §Pagine hub).

## Cosa ha detto Stefano (2026-10-27/28, parole sue, in ordine)

1. «quando apro cdg ho accesso a budget ... e consuntivo con scostamento ... gruppi e
   centri di costo ... delta ... le solite cose da monitorare».
2. I movimenti contabili e la produzione consolidata «non hanno un head ... sono headless».
3. «cdg è controllo di gestione quindi tutto ciò che è numeri dovrebbe farlo lui in
   dettaglio ... poi magari in regia mettiamo le viste più classiche ... quanto
   produciamo ... i costi ... il budget ... i piani finanziari e i saldi proiettati ...
   competenza (passato) cassa (presente) impegno (futuro)».
4. «sì competenza prima, vai».
5. «regola del 65% era una semplificazione dobbiamo vedere i costi veri ... capire quando
   sono intercompany e trattarli così e anche budget vero in base a cassa vera».
6. Esempio guida per Impegno: il soft restyling a 5 k a camera deciso dal padre va
   rappresentato contro i movimenti di cassa veri, non contro un'opinione.

## Decisioni già prese che questa spec eredita

| Tema | Decisione | Fonte |
| --- | --- | --- |
| Tre moduli | Regia (`mgmt_os`: cosa faccio adesso) · **Controllo di gestione** (hotelops: quanto rispetto al previsto e perché) · Piano industriale (BP). «Numeri» in Regia è la lettura di sintesi, il CdG è il dettaglio | STATUS 2026-10-06, concept `TRE_MODULI_REGIA_CDG_PIANO` |
| `app_cdg` | ritirata per sempre: non si riaccende e non si ridisegna. Il CdG nuovo nasce da zero | STATUS 2026-10-06 |
| CE backbone | `f_bilancino` (COMPETENZA, cumulato YTD); prima nota e fatture sono solo drill-down | decisione 2026-06-22 |
| Categorie | le dieci categorie gestionali (Personale, Commerciali, Acquisti operativi, Utenze, Manutenzioni, Amministrativi, Affitti e canoni, Imposte, Finanziari, Investimenti) + Ricavi sono la classificazione canonica: `d_categorie_gestionali` (136 conti), `v_ce_mensile_bilancino.importo_gestionale`, quadrata al centesimo con gli xls Esolver al 30/09 | commit `16e5399`, 2026-10-27 |
| Intercompany | tre conti marcati `is_intercompany`: canone ramo d'azienda ORTI `65.11.01` ↔ INTUR `53.01.33`; fitto Angelina ORTI `65.01.05.91` (INTUR lo porta a segno opposto). Il canone CVM `65.01.05.90` resta un costo verso terzi | 2026-10-27, «vai» |
| Incidenza costi | base progressivo YTD; il 65% è un **tetto a consuntivo** deciso il 18/10 ma Stefano lo ha ridimensionato il 28/10: «era una semplificazione». Nella pagina il rapporto è un numero osservato con il limite dichiarato accanto, non un semaforo che decide | #157, 2026-10-18; parole del 28/10 |
| Budget 2026 | `f_budget_mensile` (Gasparotto, MAPPATURA, INCIDENZA…) è **ritirato**; il budget nuovo nasce dal basso per driver (prima camere Hotel 2027). Nel 2026 non esiste un budget contro cui misurare lo scostamento | decisione 2026-10-04, spec `2026-10-04-budget-camere-panorama-design.md` |
| Superficie | i cruscotti riservati vivono come **app edge**: builder in hotelops → HTML self-contained → push KV → Worker Cloudflare dietro Access nominativo; il hub è solo la porta (Bilancini, Canone, Regia) | concept `HUB_EMBED_VS_EDGE`, 2026-07-15 |
| Gate di lettura | nessuna pagina si unisce senza che Stefano abbia visto il render con dati reali | CLAUDE.md §Pagine hub |

### Superficie, riconciliata (28/10, «sì confermo»)

La decisione del 2026-10-04 (punto 8, vault `2026-10-04_Budget_Per_Driver`) diceva: «una sola
superficie: il Management OS è il cruscotto di numeri». Stefano ha confermato il 28/10 la
lettura che le fa convivere: la Regia resta il cruscotto **di sintesi** (pochi numeri,
versionati, con bersaglio), il CdG è il **dettaglio autorevole** che la Regia linka, come
oggi linka Bilancini. Il CdG copre l'intero modulo, non solo il registrato: PF mese per
mese, budget, produzione, entrate e uscite, budget di progetto che vedono la cassa.

## Perimetro di questo pezzo

**Dentro.** Sezione Competenza, anno 2026 (con 2025 dove c'è), ORTI e INTUR separate e
consolidate, tre blocchi:

### Blocco A — Produzione: cosa abbiamo prodotto

Fonte: `f_produzione_pms` (produzione giornaliera HotelCube per classe, **imponibile**,
`01ROOM` = ricavo camere canonico), `f_pms_statistiche` (notti vendute, capacità modale
sui giorni con vendite, mai MAX). Strutture: HOTEL, RESIDENCE, CVM. 2025 e 2026 entrambi
presenti a oggi (2026 fino al 18/10).

- Tabella struttura × mese: ricavo per classe (camere, F&B, parcheggio, spiaggia
  ospiti, altro), notti, ADR, occupazione. Colonna 2025 dello stesso mese e delta.
  Raggruppamento classi (scelta del costruttore): `01ROOM` camere; classi F&B al loro
  gruppo; `04BEALL`, `05BEOL`, `06BEABB`, `09BEBAN`, `10BEBAR` → spiaggia ospiti;
  `11FITTO`, `80AFFITT`, `07DIV`, `99ACC` → altro. ADR = `01ROOM` / notti vendute
  (`f_pms_statistiche.camere_vendute`), mai `revenue_room`.
- Totale ORTI per mese, confronto con la riga Ricavi del bilancino dello stesso mese
  (ponte PMS → contabilità: la differenza è il «raccordo» da spiegare, non da nascondere).
- Il Lido non entra: ha la sua pagina Spiaggia. Un rimando, non un duplicato.

### Blocco B — Costi: cosa abbiamo consumato

Fonte: `v_ce_mensile_bilancino` (`importo_gestionale`, `categoria_gestionale`,
`is_intercompany`), per società e consolidato.

- Tabella categoria × mese, mese e progressivo, con la riga «Ricavi» in testa e il margine
  operativo in coda. Vista per società (ORTI, INTUR) e **consolidata** con le tre righe
  intercompany eliminate ed esposte a parte («di cui intercompany», per categoria). Il
  consolidato esiste solo nei mesi con entrambi i bilancini; l'eliminazione è a importo
  registrato (nessuna rettifica di periodo: se ORTI e INTUR registrano il canone in mesi
  diversi, il residuo resta visibile come «intercompany non riconciliato»).
- Incidenza di ogni categoria sui ricavi (mese e YTD). Per ORTI anche il rapporto costi
  operativi / ricavi, progressivo YTD, con due letture affiancate: tutto incluso e al netto
  dell'intercompany. Perimetro del rapporto = il contratto del report 18/10 §6 (classi
  55–71, come `v_incidenza_costi_componenti`); regola del mese = quella di
  `v_ce_mensile_bilancino` (conto sparito dalla foto = saldo 0, delta registra il rientro,
  verificata il 27/10), non quella della vista incidenza: le due viste divergono e la pagina
  segue il backbone. Il limite 65% compare come riga dichiarata («tetto deciso il 18/10»),
  grigio, mai come colore che decide. Conti senza categoria: riga «Da classificare»
  esplicita con importo a segno bilancio.
- **Drill-down a due livelli**: categoria → conto (dal bilancino, saldo del mese e YTD) →
  registrazioni del mese (da `f_movimenti_contabili`: data, causale, partitario, dare,
  avere). È la testa dei movimenti che oggi manca. Avvertenza nella pagina: la prima nota
  ORTI non porta i ricavi dal PMS (corrispettivi via accodamenti), quindi il terzo livello
  è completo solo sui costi.

### Blocco C — Copertura e quadratura: quanto fidarsi di questi numeri

- Per società: ultimo mese di bilancino caricato, data di ingresso, flag «mese parziale»
  (stessa regola di `canone_fonti._parziale`), numero di conti senza categoria.
- Produzione: ultimo giorno caricato per struttura.
- Movimenti: ultimo giorno per società e data dell'ultimo export completo ingerito.
- Note fisse sulle trappole note: personale di settembre 2026 ORTI ~70 k spostato dal
  bilancino di agosto (foto presa prima delle paghe), YTD esatto.

**Fuori** (pezzi successivi o altre pagine): sezioni Cassa e Impegno; budget vs consuntivo
(torna quando esiste il budget per driver, con la colonna «budget» e lo scostamento già
previsti nel layout di B); centri di costo sui costi (il bilancino non porta la struttura;
le allocazioni per BU sono una decisione di modello, non un dato); Lido; qualunque
scrittura su BigQuery; proiezioni e forecast; confronto CE 2025 (nessun bilancino 2025 in
BigQuery: si aggiunge quando viene caricato, il layout lo prevede).

## Come viene fatta (scelte del costruttore, da confermare o correggere)

| Scelta | Decisione | Perché |
| --- | --- | --- |
| Forma | App edge `cdg.panorama-host.com`: builder `verticals/condges/build_cdg_artifact.py` → `index.html` self-contained + `data.json` + `data.csv` → push KV → Worker `panorama_apps/cdg` (clone del Worker bilancini: Access verificato in-Worker, `Cache-Control: private, no-store`). Nel hub la riga `cdg` passa da `soon` a pagina-porta come `bilancini.py` | stesso pattern di Bilancini e Canone, già collaudato; Streamlit nel hub è escluso dalla decisione del 10/06 e dal concept HUB_EMBED_VS_EDGE |
| Comando | `hotelops cdg [--push]`, registrato in `cli.py` accanto a `canone` | rito mensile: dopo il promote dei bilancini e dei movimenti si rigenera e si pubblica |
| Dati | tutto embedded nell'HTML, come Bilancini. Il terzo livello (movimenti, ~17 k righe 2026) viaggia in `data.json` separato caricato dalla pagina al primo clic su un conto, così la pagina resta leggera | il Worker serve già più chiavi KV; niente API nuove |
| Frontend | HTML + CSS + JS senza framework, grafici SVG disegnati a mano come in Bilancini, skill `dataviz` per forma e palette; segni in presentazione con la stessa dignità dei segni nei dati (margine positivo ✓, scostamento «sopra» mai come numero negativo grigio) | coerenza con le app edge esistenti; nessuna dipendenza esterna |
| Navigazione | una pagina con tre tab (Produzione, Costi, Copertura) e un selettore società (ORTI · INTUR · Consolidato) condiviso; la sezione Competenza è il primo tab di primo livello, Cassa e Impegno arriveranno accanto come tab spenti con la loro domanda scritta | «una pagina, una domanda» a livello di sezione; il lettore vede subito la mappa delle tre dimensioni |
| Accesso | Access nominativo: Stefano, direttore (gm@), Rosa (amministrazione@) e stedepi@ («stesse persone più stedepi», 28/10) = policy Access esistente «Canone — nominativa», riusata. Grant hub `cdg` in `roles.py` a Rosa e stedepi (gm@ lo ha già). Token Cloudflare con permessi Access in 1Password, vedi spec del mandato | stessi lettori del Canone; dati riservati (S1) |
| Vista BigQuery | nessuna vista nuova obbligatoria: il builder legge `v_ce_mensile_bilancino`, `f_produzione_pms`, `f_pms_statistiche`, `f_movimenti_contabili`, `f_bilancino` (copertura). Se durante il piano emerge che la Regia deve leggere lo stesso rapporto, nasce `v_incidenza_costi_orti` con il contratto del report 18/10 §6 | semplicità: la logica di aggregazione sta nel builder, testata con fixture |
| Test | fixture di righe BQ → `build_payload` deterministico; golden sui totali YTD 30/09 verificati con Esolver (ORTI ricavi 4.322.453,08 / costi 3.122.670,96; INTUR 790.185,98 / 832.260,12); test del consolidato (intercompany eliminato = −600 k canone, −60 k Angelina); test del mount hub e del registry | il numero sbagliato più costoso è quello che torna per caso |
| Pulizia movimenti | **fatta il 28/10**: DELETE scoped per hash di 579 righe stale 2026 (INTUR 3.102 → 2.862, pareggia al centesimo; ORTI 14.259 → 13.920, residuo 31,40 € da tre righe collassate dall'hash e due coppie ambigue lasciate) | il drill-down mostrerebbe registrazioni che Esolver non ha più |

## Anti-goals

- Un semaforo che decide al posto di chi legge: il 65% è una riga dichiarata, non un colore.
- Un consuntivo per struttura inventato allocando i costi: senza fonte, non si mostra.
- Un budget 2026 preso da `f_budget_mensile` «tanto per avere la colonna».
- Riaccendere o rattoppare `app_cdg`.
- Ricalcoli in Regia: la Regia legge, il CdG calcola.

## Criteri di accettazione

1. Stefano apre `cdg.panorama-host.com`, tab Costi, ORTI, e legge le dieci categorie per
   mese e YTD con totali identici al centesimo agli xls Esolver al 30/09.
2. Consolidato: il canone 600 k e il fitto Angelina 60 k non compaiono né nei ricavi né nei
   costi, ma sono leggibili nella riga «di cui intercompany».
3. Clic su «Utenze · settembre» → conti → registrazioni del mese con causale e partitario.
4. Tab Produzione: Hotel settembre 2026 vs settembre 2025, ricavo camere `01ROOM`, notti,
   ADR, occupazione; il totale ORTI mese affiancato alla riga Ricavi del bilancino.
5. Tab Copertura dice da solo fino a quando sono aggiornati bilancini, produzione e
   movimenti, e quanti conti restano da classificare.
6. `hotelops cdg --push` rigenera e pubblica senza redeploy del Worker.
7. Render con dati reali visto da Stefano prima del merge.

## Cosa resta al costruttore

Layout fine delle tabelle e dei grafici (dentro la skill `dataviz`), struttura del
payload, nome delle chiavi KV, ordine dei task nel piano, scelta se il terzo livello vive in
`data.json` o in chiavi per società.

## Domande chiuse il 28/10

1. **Superficie.** Confermata: Regia = sintesi, CdG = dettaglio autorevole con la sua app
   edge («sì confermo»), scope l'intero modulo.
2. **Lettori.** Stefano, direttore, Rosa più stedepi@ (policy «Canone — nominativa»).
3. **Pulizia movimenti.** Fatta («vai»), 579 righe.

Nessuna domanda aperta resta su questa sezione; quelle del modulo stanno nella spec del mandato.
