# Controllo di Gestione HotelOps — stato reale e incidenza costi ORTI

**Data:** 2026-10-18 · **Perimetro di questa lettura:** repo `hotelops` (main `e5630b9`), vault Obsidian
(concetti, architettura, decisioni, workstream — non le sessioni), mgmt-os `7e4e0af` in sola lettura.
**BigQuery:** interrogato in sola lettura la mattina del 18/10 (ore 09 Europe/Rome) dopo il login di Stefano; la prima stesura, poche ore prima, era senza accesso (copertura di `f_bilancino`,
identità dei conti di classe 65, rapporto osservato: §4-bis). Il resto dei numeri di copertura viene da `STATUS.md`,
issue e vault.

Questo documento è un inventario e un contratto proposto. Non attiva soglie, non cambia viste, non
sceglie definizioni gestionali ancora aperte.

## 1. La domanda e la risposta corta

> «Come vedo se i costi restano entro il 65% dei ricavi?»

**Oggi non si vede, e non per mancanza di codice: per mancanza di dati ingeriti e di un contratto scritto.**

- La **definizione di piano** del 65% esiste ed è stata confermata da Stefano (decisione vault
  `2026-10-16_Incidenza_Costi_ORTI_65`, confermata il 18/10 — vedi §4). È una definizione **ORTI, annuale,
  ante canone intercompany, a livello EBITDA**.
- La **definizione di controllo** (su quale base temporale leggere il consuntivo, da quale fonte) non è
  scritta da nessuna parte nel repo. Si deduce, non si trova.
- Il **calcolo è tecnicamente disponibile** da `f_bilancino` via `v_ce_mensile_bilancino` (COMPETENZA,
  YTD cumulato → mese per differenza). Settembre è **già acquisito** per entrambe le società: ORTI
  2026-09 185 righe (`raw 0cac12f0`), INTUR 2026-09 153 righe (`raw 28d25435`), promossi il 16/10 con
  DELETE del parziale del 25/09 e verificati conto per conto contro i PDF provvisori
  (`docs/reports/2026-10-16-bilanci-provvisori-30-09-estrazione-pdf.md`, nota in
  `2026-10-17-regia-ripristino-e-allineamento.md`). Ottobre è mese aperto: gli export «al 15/10» non
  sono un mese chiuso e non vanno promossi come tale. **Verificato su BigQuery il 18/10 mattina**: ORTI e INTUR
  2026-06…2026-09, un raw object per mese, settembre caricato il 16/10 (ORTI 185 righe, INTUR 153).
- Il canale alternativo (`v_budget_vs_consuntivo` / `hotelops bva`, da prima nota) è **inutilizzabile**:
  prima nota ricavi ORTI 2026 = 0 in BQ (workstream CDG, thread 2026-09-24), il consuntivo non filtra i
  conti patrimoniali (`actuals` legge tutta `f_movimenti_contabili` senza `tipo_conto='CE'`), il budget
  in BQ è il Gasparotto senza 525 k di voci reali (STATUS 2026-09-26) ed è stato dichiarato da spegnere
  (decisione 04/10, workstream CDG).

## 2. Inventario verificato dei moduli del CdG

Legenda: *fonte autorevole* = dove nasce il dato; *accesso headless* = come lo legge un programma senza UI.

| Modulo | Fonte autorevole | Natura / dimensione | Periodo e frequenza | Calcoli esistenti | Superficie | Accesso headless | Limiti di copertura noti |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Bilancini** | Esolver «Bilancio di verifica» → `f_bilancino` (SNAPSHOT, sorgenti `ESOLVER_BILANCINO_{ORTI,INTUR}_SNAPSHOT`, cadenza mensile, mode SEMI) | COMPETENZA, saldo cumulato YTD a segno-bilancio (ricavi <0, costi >0) | mensile, mese chiuso | `v_ce_mensile_bilancino` (mese per differenza, `categoria_ce`/`tipo_costo` via `d_categorie_conti`); `build_bilancini_artifact.py` (KPI ricavi/costi/margine YTD e mese, albero per prefisso) | edge `bilancini.panorama-host.com` (Access OTP); hub = link | `/data.json`, `/data.csv` sull'edge (per conto × mese: saldo YTD e delta) | 2026 ORTI e INTUR al 30/09 (settembre promosso il 16/10, controllo incrociato PDF); ottobre aperto; ~147 conti «Da definire» in `d_categorie_conti`; promozione manuale con `--mese` quando il filename non ha l'anno |
| **F&B** | HotelCube economato → `f_consumi_economato`; Power BI → `f_ricavi_fb` (Produzione Netta mensile), `f_vendite_fb`; Sheet coperti → `f_coperti_giornalieri` | COMPETENZA gestionale, netto IVA | mensile (consumi, ricavi), giornaliero (coperti, vendite) | `v_fb_kpi` (food cost % per bucket breakfast/ristorante/bar, €/pasto, YoY), `v_fb_ricavi`, `v_fb_consumi`, `v_fb_pasti`, `v_fb_modello_mensile` | pagina hub «Food & Beverage» (`fb_dashboard.py`, Streamlit) | solo BigQuery (nessun edge) | economato al 01/07, RistoCube 17/08, Moolty 27/09, vendite/corrispettivi al 06/07 (`health`, STATUS 18/10 in PR #156). Non è un CE: è food cost, non incidenza costi totale |
| **Canone ORTI→INTUR** | BP Solo Terzo (inputs nel secret `canone-model-inputs`) + osservati BQ (`canone_fonti.py`: `f_produzione_pms`, `f_bilancino`, `f_saldi_banca_chiusura_mensile`) | IPOTESI (BP, COMPETENZA annua) accanto a OSSERVATO (COMPETENZA/CASSA) | annuale 2026–2031; refresh job `canone-push` 09:30 | `canone_sim.py`: EBITDA ante canone = ricavi × (1 − incidenza), banda min INTUR / max ORTI, DSCR; `canone_fonti.py` legge ricavi/costi/canone dal bilancino dell'ultimo mese | edge `canone.panorama-host.com`; hub = link | nessuno: il KV ha solo la chiave `html` | **gira ancora al 62 %** (61 % dal 2030): la pagina mostra uno scenario non più adottato (decisione 16/10); mutui «non collegati: i piani vivono nell'app Mutui, qui valgono le rate annue copiate nel BP» |
| **Mutui** | app `mutui-tracker` (Worker + KV, `mutui.panorama-host.com`) | IMPEGNO (piani di ammortamento) + scenario Piano Industriale | contrattuale | ammortamenti, simulatore, scenario (fuori repo) | edge; hub = link | snapshot KV del Worker, **non BigQuery** | in BQ i mutui esistono solo come **cassa** (voce PF `USCITE_MUTUI`, ramo BANCHE «PAGAMENTO RATA») e in `v_condges_banca_dettaglio`; interessi 750305 **non mappati** (#83, stop deliberato per non duplicare la rata) |
| **Piano Finanziario** | master xlsx di Rosa su Drive (ORTI/INTUR, layout diversi) ruotato da `hotelops pf-rotate`; input in `f_piano_finanziario_input`; ancora cassa `f_saldi_banca_chiusura_mensile` | CASSA. Saldo iniziale **osservato** (ancora banche) distinto da entrate/uscite e saldi **proiettati** (`v_previsione_cassa`: `saldo_ancora + cumsum(netto_pf)`; `v_cash_position`: quadratura lorda per conto) | mensile, rotation al mese chiuso; orizzonte giugno anno+1 | `v_piano_finanziario_mensile` (rolling −6/+12, budget da `v_budget_canonical`), `v_previsione_cassa`, `v_cash_position`, `pf_rotate/*` | hub «Cashflow» (`app_cashflow.py`, sensitive); `hotelops pf`, `saldo`, `chiudi` | BigQuery | PF post-rotate fermo al 21/08 (`health`); ancore 30/06 mancanti Kross+BCP (#91); scarti saldi 30/06 aperti (#69) |
| **Budget** | `f_budget_mensile` (9 fonti, precedenza in `v_budget_canonical`); budget camere per driver (`hotelops budget base`, PR #130; piano 2 #137 non implementato); foglio `Budget_2027_Hotel_Panorama.xlsx` del 18/10 (Drive, fonte proposta `BUDGET2027_HC`, non ingerito) | COMPETENZA previsionale | annuale per mese | `v_budget_canonical`, `v_budget_vs_consuntivo`, `v_condges_budget_consuntivo`; `hotelops bva` | nessuna pagina attiva (cdg = «soon», `app_cdg` ritirata #140) | BigQuery | budget 2026 in BQ = Gasparotto per conto senza OTA/canoni/interessi (525 k); deciso di **spegnere** le letture del budget vecchio (04/10) senza ancora farlo; #84 (6 fonti legittime, doc da aggiornare) |

### Come il codice tratta ricavi, costi, società e intercompany

- **Società sempre separate.** Ogni fatto porta `societa_id`; nessuna vista produce un consolidato CE. Il solo
  «consolidato» esistente è il Livello B del cashflow consuntivo (giri/trasferimenti neutralizzati), non il CE.
- **Segni.** Bilancino: dare−avere (costi >0, ricavi <0); `v_ce_mensile_bilancino` espone `importo` positivo su
  entrambi i lati (ricavi = −saldo). Prima nota (`v_pl_movimenti`, `v_ce_macro_mensile`): ricavi = classi
  41/43/45/47/48/53, costi = resto; ammortamenti (73), oneri finanziari (75), imposte (77) sono **classi di
  costo** come le altre: nessuna vista oggi distingue «costi operativi» da «sotto l'EBITDA».
- **Intercompany.** Il canone d'affitto d'azienda è il conto **65.11.01** in ORTI e **53.01.33** in INTUR
  (`canone_fonti.py`, `d_voci_piano_finanziario` → `USCITE_CANONE_PASSIVO`); `d_fornitori` marca
  PANORAMA COMPANY / INTUR con `is_intercompany` e la nota «netta solo nel consolidato». Il fitto Angelina
  (INTUR, 60 k) e il fitto CVM (650105, «Canoni locazione CVM SDP» = 65.01.05.90 nel mapping Gasparotto)
  stanno in classe 65 accanto al canone. **Nessuna vista elimina l'intercompany**: le viste CE sono per
  società e il canone resta dentro i costi ORTI e dentro i ricavi INTUR.
- **Il motore canone** è l'unico posto dove «costi operativi ORTI» esiste come concetto: è un **input**
  (`operatingCostRate`, % dei ricavi) del BP, non una lettura dei fatti. `canone_fonti.leggi_bilancino`
  somma tutti i costi CE del bilancino (canone incluso) e li mostra accanto, come evidenza, senza
  ricalcolare l'incidenza.

## 3. Regia: cosa legge oggi e cosa può leggere

`mgmt-os` «Numeri» (`mgmt/numbers.py`, `mgmt/actuals.py`) legge da BigQuery solo `f_pms_statistiche` e
`f_produzione_pms` (ORTI): vocabolario `BUS × METRICS` con metriche **solo di ricavo** (`room_nights_available`,
`rooms_sold`, `occupancy`, `adr`, `room_revenue`, `other_revenue`, `revenue`, `revenue_objective`). I bersagli
vengono dal BP (`import-budget`, fingerprint del file). **Nessuna metrica di costo, nessuna lettura del bilancino.**
È coerente con la direzione: i Numeri di Regia sono selettivi, la completezza economica sta nel CdG HotelOps
(`docs/architecture/PRODUCT_OVERVIEW.md`, `mgmt-os/docs/REGIA_DIRECTION.md`).

## 4. La definizione del 65 %: cosa è deciso e cosa no

**Deciso (vault `decisions/2026-10-16_Incidenza_Costi_ORTI_65`, status active; confermato da Stefano il 18/10 —
sessione vault e nota STATUS in PR #156, non ancora su main):**

| Elemento | Definizione |
| --- | --- |
| Perimetro società | **ORTI** (INTUR non si muove: il canone è un ricavo per lei a prescindere) |
| Numeratore | costi operativi = **classi Esolver 55–71**, con la classe 65 **esclusi 651101** (canone affitto ramo d'azienda a INTUR) **e 65010590** |
| Denominatore | **totale ricavi ORTI**, tutte le BU (camere + altri ricavi hotel + Angelina + CVM + spiaggia ospiti + affitti), non i soli ricavi camere |
| Posizione nel CE | **ante canone**: equivalente a margine EBITDA ante canone = 35 % |
| Esclusi per costruzione | ammortamenti (73), oneri finanziari (75), imposte (77), canone intercompany, il fitto escluso sopra |
| Natura | **ipotesi di piano** («costi di piano mai sotto il 65 %»), base annuale, adottata in via provvisoria finché la scheda costi per famiglia non mostra dove nascerebbero i 3 punti |

**Due regole, non un semaforo.** La decisione del 16–18/10 fissa un **minimo prudenziale di piano**
(«costi di piano mai sotto il 65 %»: il BP non può assumere un'efficienza non dimostrata). La domanda di
Stefano riguarda un **massimo da controllare a consuntivo** («i costi restano entro il 65 %?»). Stessa
grandezza, due usi: il primo vincola chi scrive il piano, il secondo misura chi lo esegue. Il contratto in
§6 espone il rapporto osservato e lascia la soglia fuori dalla vista proprio perché le due regole possono
avere valori e periodi diversi (il floor è annuale; il controllo potrebbe essere YTD).

**Non deciso (e qui non si sceglie):**

1. **Base temporale del controllo**: mese singolo (volatile, stagionale), progressivo YTD (ciò che il bilancino
   dà nativamente), o atterraggio annuo previsto (richiede un forecast che non esiste in BQ). Il 65 % di piano
   è annuale; i bilancini 2026 ad agosto stavano al 56 % e il Q4 di costi fissi porta l'anno verso il 65 %
   (memo 25/09): un semaforo mensile direbbe «verde» per sette mesi e «rosso» per cinque senza dire nulla.
2. **Fonte del consuntivo**: bilancino (COMPETENZA, mese chiuso, disponibile) oppure prima nota + fatture
   (`v_ce_macro_mensile`, oggi rotta sul 2026). La decisione 22/06 «f_bilancino = CE backbone» risponde già,
   ma va scritta nel contratto.
3. **Identità di 65010590 — risolta sul dato, aperta sull'intenzione.** Nel bilancino ORTI al 30/09
   `65.01.05.90` = «Canoni locazione CVM SDP» (100.000 €) e `65.01.05.91` = «Canoni locazione Angelina
   Residence» (60.000 €, intercompany: INTUR porta lo stesso conto con segno opposto). La sessione del 18/10
   scrive «65010590 = fitto Angelina»: **il codice e il nome non coincidono**. Se l'intenzione è escludere
   l'intercompany (coerente con la decisione del 16/10 e con `2026-09-04_Fitto_Angelina_a_INTUR`), il conto da
   escludere è `65010591`; se è escludere il canone CVM, è `65010590` ma la motivazione va scritta (il
   locatore SDP non è una società del gruppo). Stefano deve dire quale.
4. **Due perimetri nello stesso dominio.** Il BvA del 26/09 conta gli interessi mutui e il POS (144 k) tra i
   costi fuori budget; il 65 % di piano è a livello EBITDA e li esclude. Entrambi legittimi, mai riconciliati
   per iscritto: la vista deve esporre il livello (operativo vs totale) come colonna, non sceglierlo.
5. **Trattamento dei mesi parziali** e della quota «di cui altri ricavi hotel — quota di raccordo»
   (813 k nel BP 2026, etichettata `COMPOSIZIONE DA VERIFICARE`): nel consuntivo non esiste, quindi il
   denominatore osservato e quello di piano non sono la stessa cosa finché il piano non è per centro.

### 4-bis. Rapporto osservato (bilancino ORTI, COMPETENZA, progressivo YTD) — evidenza, non semaforo

Query eseguita il 18/10 mattina su `f_bilancino`, segni gestionali, rapporto = somma costi / somma ricavi dall'inizio
dell'anno. Nessuna soglia applicata; le tre colonne a destra sono le tre letture possibili della definizione.

| YTD al | Ricavi totali | Costi 55–71 | Canone 651101 | CVM 65010590 | Angelina 65010591 | Classe 75 | escl. canone+Angelina | escl. canone+CVM | escl. solo canone | totale CE / ricavi |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-06 | 1.730.541 | 1.042.048 | 0 | 50.000 | 0 | 100.392 | 0,602 | 0,573 | 0,602 | 0,660 |
| 2026-07 | 2.496.779 | 1.921.974 | 400.000 | 100.000 | 60.000 | 121.685 | 0,586 | 0,570 | 0,610 | 0,819 |
| 2026-08 | 3.495.011 | 2.372.761 | 400.000 | 100.000 | 60.000 | 143.952 | 0,547 | 0,536 | 0,565 | 0,720 |
| 2026-09 | 4.322.453 | 2.954.318 | 600.000 | 100.000 | 60.000 | 168.353 | **0,531** | 0,522 | 0,545 | 0,722 |

Letture che contano più dei decimali:

- A gennaio–marzo il rapporto YTD sta sopra 2,0 (hotel chiuso, costi fissi): un controllo **mensile o YTD di
  inizio anno** non dice nulla sul 65 %, che è una grandezza annuale. È il motivo per cui §4.1 va deciso, non dedotto.
- Al 30/09 il rapporto ante canone sta a 0,53–0,55 contro il 0,56 di agosto del memo 25/09; l'atterraggio annuo
  verso 0,65 dipende dal Q4 di costi fissi e dalle registrazioni che il bilancino provvisorio non ha ancora.
- Il **bilancino provvisorio non contiene ammortamenti (73) né imposte (77)**: la sola classe «sotto EBITDA»
  presente è la 75 (oneri finanziari, 168 k). Il confronto con il 66,3 % del bilancio 2025 depositato va fatto a
  dicembre, sul bilancino di chiusura.
- Il canone registrato a settembre è 600 k su 1,0 M annuo: la colonna «totale CE / ricavi» (0,72) include il
  canone ed è la lettura standalone che il consolidato elimina.
- Conti CE ORTI 2026-09 senza categoria in `d_categorie_conti`: **30 conti, 333 k in valore assoluto**. Non
  toccano il rapporto totale (che non usa la categoria), toccano la lettura per famiglia.

**Disponibilità tecnica ≠ definizione gestionale.** Con le quattro righe sopra chiuse, il calcolo è una vista
di ~40 righe su `v_ce_mensile_bilancino` (filtro classi + esclusioni + rapporto). Senza, qualsiasi
semaforo misura una definizione scelta dall'agente.

## 5. Cosa manca davvero (senza un secondo sistema contabile)

| # | Lacuna | Tipo | Dove si chiude |
| --- | --- | --- | --- |
| 1 | Dati: bilancino di **ottobre** quando il mese chiude (settembre è già in BQ, vedi §1); lista A di `health` (vendite, corrispettivi, acquisti, movimenti ORTI) serve al BvA e al canale prima nota, **non** al rapporto dal bilancino | ingest, manuale | export Esolver/Power BI → `hotelops intake/promote` (contratto freshness già nel registry) |
| 2 | Contratto scritto del 65 % (i quattro punti di §4) | decisione Stefano | questo documento → `docs/architecture/` o ADR quando confermato |
| 3 | Vista canonica `v_incidenza_costi_orti` (COMPETENZA, bilancino): ricavi totali, costi operativi, incidenza mese e YTD, flag mese parziale, esclusioni esplicite per conto | 1 vista + test | `core/bq/views/` (I8: la regola sta nella vista, non in Regia né in Streamlit) |
| 4 | `d_categorie_conti`: ~147 conti «Da definire» (134 k ORTI / 83 k INTUR sul 2026) | dimensione | prerequisito per leggere l'incidenza **per famiglia**, non per il totale |
| 5 | `v_budget_vs_consuntivo`: il consuntivo include conti patrimoniali (nessun filtro CE) e la prima nota ricavi 2026 è vuota | fix vista + ingest | solo se si vuole tenere il canale prima nota accanto al bilancino |
| 6 | Cruscotto canone a 62 %: l'input `operatingCostRate` non riflette la decisione del 16/10 | config (secret `canone-model-inputs`) | `hotelops canone --push` dopo il cambio input — **non eseguito qui** (scrittura su dato aziendale) |
| 7 | Costi ORTI per famiglia (personale, acquisti, utenze, servizi, fitti) accanto all'incidenza unica | scheda del MASTER + `categoria_ce` | #148 (budget operativo 2027 per driver) |

Nessuna di queste richiede una nuova tabella dei fatti né un secondo piano dei conti.

## 6. Raccordo verso Regia — contratto proposto (non implementato)

| Campo | Valore proposto |
| --- | --- |
| Indicatore | `orti.cost_ratio` — incidenza costi operativi ORTI; accanto `orti.operating_costs` e `orti.revenue_total` così il rapporto è ricalcolabile |
| Perimetro | ORTI, tutte le BU, ante canone, classi 55–71 con esclusioni **esplicitate per conto nella vista** |
| Dimensione | COMPETENZA (bilancino). Non si mischia con la cassa del PF né con il BP |
| Periodo | mese chiuso e progressivo YTD, entrambi esposti; **nessuna soglia** finché §4.1 non è deciso. La soglia, quando c'è, è un bersaglio `kind=budget` importato in Regia come gli altri, non una costante nella vista |
| Fonte | BigQuery `v_incidenza_costi_orti` (da creare) ← `v_ce_mensile_bilancino` ← `f_bilancino` |
| Aggiornamento | al promote del bilancino mensile (SEMI, Stefano); la vista espone `letto_il` / `data_ingresso` e `mese_parziale` |
| Copertura | la riga dice da sola se il mese è chiuso, parziale o assente; `comparable=false` in Regia quando il bersaglio non c'è (stesso contratto di `regia-mappa-budget.md` §6) |
| Dettaglio autorevole | link alla pagina Bilancini (`bilancini.panorama-host.com`, Access) e `/data.json` per il drill per conto; il motore economico resta in HotelOps |
| Cosa NON fa Regia | non ricalcola costi da conti, non applica esclusioni, non decide la soglia |

Contratto della vista `v_incidenza_costi_orti` (colonne e regole), così come andrà scritto nel SQL e nei test:

| Regola | Specifica |
| --- | --- |
| Grana | una riga per (`societa_id`, `anno`, `mese`); solo ORTI finché il perimetro non cambia, ma la colonna resta |
| Unità | euro netti IVA a segno gestionale (ricavi > 0, costi > 0, da `v_ce_mensile_bilancino.importo`); rapporti come frazione 0–1 (`0.65`), mai percentuale già moltiplicata |
| Numeratore | `costi_operativi` = somma dei conti CE con classe 55–71, esclusi i conti elencati in una CTE `esclusi` (`65.11.01`, e il conto del fitto Angelina una volta confermato); `costi_totali_ce` = tutti i costi CE, esposto accanto |
| Denominatore | `ricavi_totali` = somma di `sezione = 'Ricavi'` del bilancino, tutte le BU |
| Periodo | `*_mese` dal delta del bilancino; `*_ytd` = **rapporto delle somme** gennaio→mese (`SUM(costi)/SUM(ricavi)`), mai media dei rapporti mensili |
| Nulli | `SAFE_DIVIDE` con `NULLIF(ricavi, 0)`: ricavi zero o assenti → rapporto `NULL`, non 0 né ∞; un mese senza bilancino non produce riga, non eredita il precedente |
| Copertura | `mese_parziale` (bilancino caricato prima della fine del mese, stessa regola di `canone_fonti._parziale`), `n_conti_esclusi`, `n_conti_da_definire` (conti CE senza categoria), `ultimo_mese_disponibile` |
| Aggiornamento | `letto_il` = `MAX(data_ingresso)` del bilancino di quel mese; nessuno scheduler: la vista cambia quando cambia `f_bilancino` |
| Soglia | **assente**. Nessuna colonna `semaforo`, `stato` o costante 0,65 |
| Test | fixture a segni bilancino con canone e fitto presenti; caso ricavi zero; caso YTD ≠ media dei mesi; caso mese parziale |

Dipendenza lato mgmt-os: estendere il vocabolario `METRICS` (oggi solo ricavi) e il collector `actuals.py`
con una query sulla vista. È lavoro di Regia, da fare **dopo** la vista e il contratto.

## 7. La domanda minima per Stefano

> **Il 65 % del CdG si legge sul progressivo YTD del bilancino ORTI (mese chiuso, COMPETENZA), con costi =
> classi 55–71 meno il canone 651101 e meno il fitto Angelina `65010591` — oppure volevi escludere il canone CVM
> `65010590`, che non è intercompany?**

Una risposta sì/no più la scelta tra i due conti chiude §4.1–4.3 e sblocca la vista (§4.4 si risolve esponendo entrambi i livelli). L'atterraggio annuo e la
scheda per famiglia restano nel perimetro di #148.

## 8. Vault Obsidian: cosa è stale rispetto a questo stato

Lettura parallela di `architecture/`, root, `loops/`, `concepts/`, `decisions/`, `ontology/`, `workstreams/`,
`verticals/` del vault (`~/Documents/Obsidian Vault/HotelOps`), sessioni e journal esclusi. Il vault è
memoria di ragionamento, non fonte canonica: queste righe dicono dove la memoria contraddice repo e stato.

**Ciò che il vault dice sul 65 %.** Una sola pagina formale: `decisions/2026-10-16_Incidenza_Costi_ORTI_65`
(§4). Nessun concept, loop o pagina di architettura definisce una soglia costi/ricavi o un semaforo di
incidenza; `INCIDENZA` compare altrove solo come nome di una fonte budget (payroll stimato). Le soglie
che esistono sono di cassa (`loops/cash_control`: OK / ATTENZIONE < 50 k / PERICOLO < 0) e di DSCR
(`GRUPPO_PANORAMA`, `DSCR_DUE_GAMBE`). La dottrina dell'incidenza vive nel repo
(`docs/reports/2026-09-25-…`, `2026-09-26-briefing-romita-…`, `canone_sim.py`), non nel vault.

**Catena decisionale canone / incidenza, con le contraddizioni vive:**
25/07 scaletta 1.000/1.200/1.445/1.520 con DSCR «tutti sopra covenant» (`authority: normative`) →
25/09 canone 2026 = 1,0 M + IVA, scaletta come banda, «il numero da guardare è l'incidenza, non il canone» →
02/10 cruscotto canone edge con **uno scenario, non una decisione** (1.000/1.185/1.235/1.280/1.280, a 62 %) →
11/10 MASTER a 62 % → 16/10 il 65 % diventa base di piano, DSCR dell'11/10 da ricalcolare →
18/10 il 65 % diventa floor («costi di piano mai sotto il 65 %») e precondizione di un pagamento reale (AMCN).
Contraddizioni non risolte nel vault: (i) tre DSCR ORTI 2027 diversi in tre decisioni tutte `active`
(1,25 · 1,20 · 0,95); (ii) il 2027 del canone è «normativo» il 25/07, «banda» il 25/09, «scenario» il 02/10,
«non deciso» il 16/10; (iii) la scaletta usata dal cruscotto non coincide con nessuno dei due BP confrontati;
(iv) il 05/10 dichiara «i costi non seguono una crescita, conta il margine», il 18/10 impone un floor
d'incidenza: sono la stessa cosa detta in due modi, ma nessuna pagina lo riconcilia.

**Intercompany e consolidato nel vault.** `loops/intercompany_governance` (⚪ planned, 2026-06-07): DSCR mai
standalone ORTI, sempre di gruppo; failure mode n.1 = «fitto ORTI→INTUR non cancellato → doppio conteggio»;
promette `v_dscr_gruppo`, mai nata. `ontology/financial/PL_RECONCILIATION_2025` è l'unica pagina che
spiega l'eliminazione del canone infragruppo (ORTI standalone 0,37x «WRONG» vs gruppo 1,58x), ma con
numeri al 31/12/2024 (canone 732–938 k). `relationships/INTUR_ORTI` è `canonical` al 07/08: precede sia il
canone 1,0 M (25/09) sia il fitto Angelina a INTUR (04/09). Il vault non conosce `canone_sim.py`, i conti
65.11.01 / 53.01.33 né la pagina hub Canone; `GRUPPO_PANORAMA` porta ancora la banda 1.000→1.520 e un
residuo «24,62 %» accanto al 38,50 %.

**Mutui nel vault.** Cinque contratti (ORTI: MPS 3,5 M, Intesa ex BPER; INTUR: Intesa 2015, MPS 75 k,
MPS 1,2 M), residui al 31/12/2024, rate 2026 619 k / 2027 729 k; INTUR 157.188 / 264.086 coincidono al
centesimo con la fonte `SCADENZIARIO` in BQ e con `mutui_completi.json` del tracker. Due serie parallele
(`ontology/loans/*` e `ontology/financial/Mutuo_*`) incoerenti su Intesa INTUR; l'MPS 75 k di ORTI
dichiarato in bilancio non esiste nel vault; il nuovo debito 2.016.260,50 sta solo in `workstreams/BP_BANCA`.
Confermato da entrambe le parti: **nessun fatto BigQuery per i mutui**, piani nell'app Mutui (KV), in BQ solo
la cassa (`USCITE_MUTUI`, nessun writer per la fonte `SCADENZIARIO`).

**Le pagine più stale per il CdG (da aggiornare o archiviare):**
1. `LOOPS.md` (`canonical`, 2026-05-17): app sbagliate (`app_cdg` per cash_control e monthly_close), `v_dscr_gruppo` fantasma, zero Regia; citata da 13 file.
2. `verticals/CONDGES.md` (senza frontmatter): `app_cdg` «in attesa di redesign» (ritirata), `v_budget_canonical` «non implementata» (lo è dal 04/2026), `USCITE_MUTUI` a doppia fonte.
3. `decisions/2026-07-04_CdG_Redesign_Per_Foglio_Gasparotto` («DECISO — brainstorm in corso»): nessun sotto-progetto aperto, perimetro sostituito dal budget per driver/centro.
4. `decisions/2026-04-17_Budget_Canonical_View`: il budget che risolveva è stato ritirato in blocco il 04/10; i consumer da migrare sono quelli da spegnere.
5. `decisions/2026-07-25_Scaletta_Canone_1200_2027` (`normative`): DSCR del fascicolo mai ritirati formalmente.
6. `architecture/Condges_Excel_Architecture` + `Condges_Simplification_Guide` + `Architecture_Gaps_Audit_2026-05-10`: target «app CdG 6 tab» costruito e poi spento; `core/kernel|loops|ontology` mai nati; path `condges/`, NanoClaw-centrici.
7. `ontology/financial/{DEBT_SUMMARY,EXECUTIVE_SUMMARY_2025,PL_RECONCILIATION_2025}` (28/02/2026): DSCR 6,36x e canone 732 k contro il BP di ottobre.
8. `workstreams/FB.md` (31/07): `f_produzione_pms` «non creata» e «mergiata» nello stesso file; pipeline F&B ferme da agosto.
9. `loops/monthly_close.md` e `loops/cash_control.md`: baseline budget che ignora `f_bilancino`, superficie `app_cdg.py`.
10. `PLATFORM.md` (09/10, la più aggiornata): ma «15 Views» (sono 41), `f_bilancino` «202 righe ORTI gen-mar», `v_ce_mensile_bilancino` assente, `Repo: ~/dev/Projects/hotelops`.
Trasversali: `INDEX`, `IDENTITY`, `architecture/INVARIANTS|AI_INSTRUCTIONS` citano «I1–I8» (il repo è a I10) e path `~/dev/Projects/` o `/Users/stefanodellapietra/...`; i workstream hanno `last_refresh` recente ma testa «Dove sono» ferma a luglio (CDG, CASH_PF, CAPEX, HUB, INGEST_CHIUSURE); `decisions/_index.md` indicizza 3 file su 91 con righe duplicate.

**Concepts.** Nessun concept definisce il perimetro del CdG per intero (società/consolidato, livello di
margine, interessi e ammortamenti, esclusioni canoniche): si ricompone da `BILANCINO_SEMANTICS` (per società,
YTD cumulato), `BVA_PERIMETRO` (il perimetro è una lista di conti da esibire prima dei delta; interessi mutui +
POS **dentro** il confronto), `DSCR_E_COPERTURA` (DSCR su EBITDA, quindi **ante** interessi), `CODICI_ESOLVER`
(righe intercompany e «Chiusura a CE» fuori dal costo), `FINANCIAL_RULES` (Rule 6: intercompany escluso solo
nella lente CASSA). `BUDGET_TRE_LIVELLI` (18/10) è l'unica pagina che chiama il 65 % «soglia» operativa e cita
una «vista di incidenza» che nel repo non esiste. Più stale: `FINANCIAL_RULES` (canone 732 k in 6 rate, KPI
`[TBD]`, DSCR target 1,3× — ma è l'unica fonte di semafori, da riscrivere non archiviare), `GASPAROTTO_MODEL`
(CdG = tradurre il modello in `app_cdg`), `DATA_SOURCES` (2026-05-02: `app_cdg` come write-surface,
Σ stagionalità 12,0 contro 1,00 di `STAGIONALITA`), `PF_ROTATION_WORKFLOW` (`app_scadenzario` inesistente),
`BUDGET_BASELINE_LOTTERY` (bug ROW_NUMBER già chiuso con DENSE_RANK), `CDG_VS_REVMAN` («CdG = solo passato,
fonte Esolver»), `FOOD_COST` («food cost % non calcolabile», oggi in `v_fb_kpi`), `TRE_MODULI_REGIA_CDG_PIANO`
(le tre viste di interfaccia CdG→Regia non esistono). Buco di memoria principale: nessun concept recepisce
«bilancio 2025 = 66,3 %» né «ogni punto di incidenza ≈ 0,1 di DSCR», che stanno solo nei report del repo.
Suggerimento (non eseguito: il vault è fuori perimetro di scrittura): una pagina `concepts/PERIMETRO_CDG` che
fissi i punti di §4 una volta decisi.

## 9. Da passare a Codex / mgmt-os

**HotelOps espone già (headless):** `f_bilancino` + `v_ce_mensile_bilancino` (COMPETENZA, per società, per conto e
mese, `categoria_ce`/`tipo_costo`); `v_fb_kpi` (food cost per bucket); `v_previsione_cassa` / `v_cash_position`
(CASSA, ancora osservata vs saldi proiettati); `v_budget_canonical`; edge Bilancini con `/data.json` e `/data.csv`
(per conto × mese, Access OTP). Il canone come fatto: conti 65.11.01 (ORTI) / 53.01.33 (INTUR) nel bilancino.

**Solo proposto (non implementato, non deciso):** vista `v_incidenza_costi_orti` (§6, issue #157) e il contratto
dell'indicatore `orti.cost_ratio` (+ `orti.operating_costs`, `orti.revenue_total`); nessuna soglia nella vista.

**Dipendenze:** (1) risposta di Stefano a §7; (2) ottobre quando chiude (settembre è già in BQ); (3) lato mgmt-os, estensione di `METRICS` in `mgmt/domain.py` e di `actuals.py` — **dopo** la vista;
(4) la soglia, quando decisa, entra in Regia come bersaglio importato (`kind=budget`), non come costante;
(5) floor di piano e massimo di controllo restano due regole distinte, mai lo stesso semaforo; i prompt che
leggono l'indicatore ricevono fonte, periodo e copertura dalla riga e dichiarano quando il confronto non è possibile.

**Non fare in Regia:** ricalcolare costi da conti, applicare esclusioni intercompany, leggere il BP come consuntivo.

**Link:** issue #157 (contratto vista incidenza), #148 (budget operativo ORTI 2027 — scheda costi per famiglia), #83 (750305 interessi mutui),
#140 (ritiro `app_cdg`), #137/#138 (viste budget e API Regia), #52 (rollup `categoria_ce`);
`mgmt-os/docs/regia-mappa-budget.md` §3 (riga «Costi operativi ORTI: lacuna»); vault
`decisions/2026-10-16_Incidenza_Costi_ORTI_65`, `workstreams/CDG.md`.

## Fonti lette

- Repo: `AGENTS.md`, `CLAUDE.md`, `STATUS.md` (testa, note 25–26/09, 01–02/10, 17/10), `docs/architecture/PRODUCT_OVERVIEW.md`,
  `docs/architecture/LE_3_DIMENSIONI.md`, `docs/reports/2026-09-25-canone-2026-e-scaletta.md`,
  `docs/reports/2026-08-16-riconciliazione-canone-2026.md`, `docs/reports/2026-10-17-consolidation-handoff.md`,
  `verticals/hub/registry.py` e `pages_/{bilancini,fb,canone,mutui,regia,cashflow}.py`,
  `verticals/condges/{canone_sim,canone_fonti,build_bilancini_artifact,build_canone_artifact,fb_data}.py`,
  `core/bq/views/{v_ce_mensile_bilancino,v_ce_macro_mensile,v_pl_movimenti,v_budget_vs_consuntivo,v_budget_canonical,v_fb_kpi,v_previsione_cassa,v_cash_position,v_piano_finanziario_mensile}.sql`,
  `core/source_registry.yaml`, `core/bq/dimensioni/{d_voci_piano_finanziario,d_mapping_piano_finanziario,d_fornitori}.csv`, `cli.py`.
- GitHub: issue #148, #140, #137, #138, #83, #84, #52; PR #153, #155, #156 (aperte).
- mgmt-os (sola lettura): `docs/REGIA_DIRECTION.md`, `docs/regia-mappa-budget.md`, `mgmt/{numbers,actuals,domain}.py`, issue #27, #52.
- Vault: `decisions/2026-10-16_Incidenza_Costi_ORTI_65.md`, `workstreams/CDG.md`; per il §8 vedi gli elenchi degli agenti.
