---
type: audit
date: 2026-09-09
scope: HotelOps — layer di acquisizione (confine vendor UI → HotelOps)
ground_truth: repo main @ 963c5c0 + BigQuery hotelops-suite.hotelops + Cloud Run/Scheduler europe-west1 + Gmail stefano@ (letti il 2026-09-09)
status: non committato, non ancora rivisto da Stefano
assunzione: nessun accesso API a Power BI/Hoxell nel breve (Stefano, 2026-09-09) — le priorità in §6 sono scritte per export manuale + ingest
---

# Audit tecnico-strategico — HotelOps come layer di acquisizione

> Tesi fissata in partenza: HotelOps non serve a "portare file in BigQuery". Serve a
> trasformare accessi umani ai sistemi aziendali in accessi programmatici affidabili.
> Questo audit misura quanto di quel confine è chiuso, quanto è ancora Stefano, e cosa
> del sistema necessario esiste già.

## 0. Metodo e fonti

- Repo letta per intero sui punti rilevanti: `core/source_registry.yaml` (48 source + 2 chiavi
  morte), `core/registry.yaml`, `ingest/`, `core/lineage/`, `cli.py`, `verticals/condges/cli_commands.py::cmd_health`,
  `verticals/hub/`, `scripts/cloud/`, `docs/architecture/`, `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`
  e `2026-06-14-acquisition-layer-design.md`, `STATUS.md`.
- Runtime verificato dal vivo: `__TABLES__` e `MAX(data)` per tabella, `f_raw_objects` per source e attore,
  `f_pipeline_runs`, `v_raw_objects_current`, Cloud Run jobs + Cloud Scheduler via REST, launchd locale,
  `hotelops health` eseguito.
- Vault: workstream `INGEST_CHIUSURE`, `INFRA`, sessione `2026-08-04_motore_firme_lsui_powerbi_api`, procedure Colazione.
- Gmail: thread con HotelCube (aprile 2026 e oggi), thread "Hoxell recap" (dic 2025).
- `gcloud` ha il token utente scaduto; tutto il runtime è stato letto con le Application Default Credentials.

## 1. Cos'è realmente HotelOps oggi

Un **layer di LOAD maturo con un layer di EXTRACT quasi assente**.

Lato interno (fatto, funziona, ha invarianti): GCS raw layer con versioning, `f_raw_objects` +
`f_lineage_events` con state machine e policy gate, 27 parser in `ingest/flussi/`, writer unico
validato, 60 tabelle canonical e 36 viste in BigQuery, hub Streamlit su Cloud Run dietro IAP con
6 app montate, rotation mensile del Piano Finanziario, chiusura mese.

Lato esterno (il confine con i vendor): **48 source registrate, 6 con acquisizione automatica,
17 riconosciute dal contenuto ma scaricate a mano, 25 completamente manuali**.

| Modalità | Source | Cosa significa |
|---|---|---|
| AUTOMATIC | 6 | coperti (Google Sheet), corrispettivi spiaggia (Drive vivo), PEC ×3 (IMAP). Reviews (Apify) è automatica ma non è nel registry |
| SEMI | 17 | banche ×5, Esolver movimenti/scheda/partite/bilancino/budget/PF, accodamenti, economato, consumi PBI, ricavi FB, coperti drop: Stefano scarica, `hotelops capture` riconosce e promuove |
| MANUAL | 25 | 11 Power BI, 4 fatture Esolver, RistoCube, Moolty, Spiagge.it, SDI, PEC personale, 6 RAW_ONLY senza parser |

Runtime, ultimi 30 giorni in `f_raw_objects`:

| Attore intake | Oggetti | Source distinte |
|---|---|---|
| cli (Stefano) | 54 | 21 |
| drive_sync | 15 | 1 |
| pec_fetch | 12 | 2 |
| hub:revenue | 2 | 1 |

Due terzi degli intake dell'ultimo mese sono mani di Stefano, su 21 source diverse.

Cloud, verificato via API il 2026-09-09: 5 Cloud Run Jobs schedulati, tutti verdi
(`pec-fetch` 04:00, `reviews-scrape` 07:00, `spiaggia-corrispettivi` 09:00, `coperti` 12:00,
`reviews-report` lunedì 08:00) e il servizio `hotelops-hub`. Sul Mac: nessun job HotelOps caricato
in launchd tranne `com.panoramagroup.consumi`, che fallisce con exit 78 da mesi su un path che non esiste più, e NanoClaw.

## 2. Il collo di bottiglia principale

**Il confine vendor UI → HotelOps, su due cluster precisi, più un problema cognitivo che li nasconde.**

Cluster A, **finanza** (Esolver ×7 famiglie ×2 società + 6 conti homebanking): è il cluster che
alimenta cashflow, chiusura mese, DSCR e monitoraggio MPS. È fermo da 3-10 settimane. Non ha mai
avuto un canale programmatico e nessuno ha ancora risposto alla domanda "dove gira Esolver".

Cluster B, **Power BI / HotelCube** (15 source, 11 puramente manuali): ogni export produce un
`data.xlsx` senza nome, con periodo e BU nascosti nel footer "Applied filters" con tre convenzioni
diverse fra loro. Il motore che riconosce questi file dal contenuto è la PR #117, **aperta e non
mergiata dal 4 agosto**. Il canale ufficiale (`executeQueries` sul semantic model `Z_DataSet`)
richiede il permesso Build che oggi il gruppo non ha: la richiesta a Fabio Di Prima è partita da
`stefano@panoramagroup.it` **oggi alle 08:48** (il journal del vault parla di invii il 16/08 e 28/08,
ma in questa casella non risultano).

Problema cognitivo: `hotelops health` misura la freschezza di ~10 tabelle con query e soglie
hardcoded, **non legge mai** `source_registry.yaml`, `f_raw_objects` né il manifest. Sa dire
"ORTI/MPS ferma da 20 giorni", non sa da quale sistema arriva, quale report serve, da quale data,
chi lo esporta, quale comando lo consuma. Il registry contiene già canonical_table, parser, lifecycle,
policy e loop_targets per 48 source: il join fra i due non è mai stato scritto.

**Freshness problem vs acquisition problem.** La staleness attuale non è un guasto di pipeline: le
5 source automatiche sono tutte fresche (coperti 08/09, corrispettivi 31/08, PEC 04/09, reviews 09/09).
Tutte le tabelle stale sono export umani non fatti. La freshness è il sintomo; l'acquisizione è la causa.
Un cockpit che "nudga" migliora il sintomo; solo il canale programmatico rimuove la causa.

Freshness reale al 2026-09-09 (max data contenuto):

| Tabella | Ultimo dato | Giorni | Modalità |
|---|---|---|---|
| f_banche_movimenti | 2026-08-17 … 08-21 | 19-23 | SEMI |
| f_movimenti_contabili | 2026-08-14 | 26 | SEMI |
| f_saldi_banca_snapshot (scheda) | 2026-07-31 … 08-18 | 22-40 | SEMI |
| f_partite_aperte_fornitori ORTI | 2026-06-30 | 71 | SEMI |
| f_fatture_righe | 2026-07-05 | 66 | MANUAL |
| f_produzione_pms | 2026-08-15 | 25 | MANUAL |
| f_pms_statistiche | 2026-08-31 | 9 | MANUAL |
| f_vendite_fb | 2026-07-29 | 42 | MANUAL |
| f_ristocube_orders | 2026-08-16 | 24 | MANUAL |
| f_consumi_economato | 2026-08-16 | 24 | SEMI |
| f_prenotazioni_otb (foto) | 2026-09-02 | 7 | MANUAL, rituale settimanale ok |
| f_ricavi_fb | 2026-09-02 | 7 | SEMI |
| f_spiaggia_reservations | 2026-06-13 | 88 | MANUAL dump |
| f_coperti_giornalieri | 2026-09-08 | 1 | AUTO |
| f_spiaggia_corrispettivi | 2026-08-31 | 9 | AUTO (1 riga/giorno, fine mese) |
| f_pec_messages | 2026-09-03 | 6 | AUTO |
| f_reviews | 2026-09-09 | 0 | AUTO |

## 3. Quanto siamo lontani dall'obiettivo originale

Per sistema, che è la misura giusta perché il confine si chiude per vendor e non per file:

| Sistema | Canale programmatico | Stato |
|---|---|---|
| Google Workspace (Sheet, Drive) | Drive API, SA keyless | ✅ chiuso |
| PEC Aruba | IMAP read-only | ✅ chiuso |
| OTA reviews | Apify | ✅ chiuso |
| Agenzia Entrate SDI | richiesta massiva sul portale | 🟡 canale ufficiale, batch, parser mancante |
| HotelCube / Power BI | executeQueries (chiesto oggi); "tracciato standard API" offerto da HotelCube ad aprile, mai documentato | 🔴 aperto, dipende dal vendor |
| Esolver | sconosciuto: dipende da dove gira | 🔴 mai indagato |
| Banche ×3 (MPS, Sella, Intesa) | nessuno; homebanking download | 🔴 mai chiesto |
| RistoCube, Moolty, Spiagge.it | nessuno | 🔴 export manuali |
| Hoxell | nessuno; un numero al giorno ricopiato a mano in un Google Form | 🔴 zero |

Il LOAD è a circa l'80% del disegno (mancano: coperti fuori lineage, 6 parser RAW_ONLY,
`promote --all-promotable` stub, `v_lineage_health`). L'EXTRACT è al 12% per numero di source e
allo 0% sui tre sistemi che contano di più. La spec `2026-06-14-acquisition-layer-design.md` aveva
già disegnato tutto questo (tier R/E/M, freshness contract, cockpit, puller): dei suoi 4 step sono
atterrati solo i puller, e solo su source dove il vendor era Google o un IMAP.

## 4. Sorgenti già sostanzialmente risolte

- **Reviews**: Apify → NLP → `f_reviews`, giornaliero, con watermark e cost guard. Unica anomalia: health confonde "0 recensioni nuove" con "pipeline stale" (TripAdvisor Residence 431 giorni).
- **Corrispettivi spiaggia**: Drive vivo → `drive_fetch` → intake → promote, giornaliero. Il pattern-modello per ogni futuro puller. Manca lo snapshot GCS anti-cancellazione già messo su coperti.
- **PEC ×3**: IMAP → intake → promote → classify, notturno. Secondo pattern-modello.
- **Coperti**: Sheet → BQ giornaliero, ma **bypassa il lineage** (nessun raw object, `--replace` etichettato APPEND) e dipende da un umano che ricopia Hoxell in un Google Form. Risolta la freschezza, non la provenienza.
- **Accodamenti HotelCube**: export nativo, riconosciuto dal contenuto, promozione AUTO. Manca solo il gesto del download.
- **SDI XML**: canale ufficiale AdE, dedup su `idfile`, procedura scritta; parser `ingest_fatture_sdi` da scrivere.

## 5. Sorgenti che dipendono ancora da Stefano come "human API"

| Vendor | Cosa fa l'umano | Frequenza attesa | Chi |
|---|---|---|---|
| Homebanking MPS ×3, Sella, Intesa ×2 | login, lista movimenti, download xls | mensile pieno | Stefano |
| Esolver movimenti, scheda, partite, bilancino ×2 società | export da UI, spesso via Rosa per mail | chiusura mese | Rosa → Stefano |
| Esolver fatture acq/vend ×2 | "Lista fatture … dettagliata" xlsx | chiusura mese | Rosa |
| Power BI ×15 report | filtro, "Esporta dati", `data.xlsx` | settimanale (OTB), mensile (produzione/ricavi), ad hoc | Stefano |
| RistoCube orders, stampa cassa | export xlsx | ad hoc | Stefano |
| Moolty | report xlsx | ad hoc | Stefano |
| Spiagge.it | dump JSON | stagionale | Stefano |
| Hoxell | conteggio colazioni ricopiato nel form | giornaliero | Responsabile breakfast |
| AdE SDI | XML richiesta + download zip | trimestrale | Stefano |

Nota: molti export Esolver e PF arrivano già come **allegati Gmail** da `amministrazione@panoramagroup.it`
("LISTA MOVIMENTI MPS", "PIANO FINANZIARIO", "PIANO FIN APRILE"). Lì l'umano nel giro è solo il
passaggio Gmail → Downloads → `hotelops capture`.

## 6. I tre interventi a maggiore leva

**Vincolo assunto (Stefano, 2026-09-09): nessun accesso programmatico a Power BI né a Hoxell nel
breve. Si resta su export umano + ingest.** Con questo vincolo la leva non sta nel togliere il click,
ma nel rendere il click **guidato, corto e impossibile da dimenticare**. I tre interventi, in ordine:

**6.1 Health come lista della spesa** (step 1-2 della spec di giugno, mai fatti). È l'intervento
che cambia di più l'esperienza a parità di export manuale. Aggiungere a `SourceDefinition` e a ogni voce
del registry: `refresh_tier`, `expected_cadence`, `grain`, `coverage_date_column`, `freshness_dims`,
`fetch_location`, `fetch_owner`, `export_report_name`, `export_filters`, `dormant`. Scrivere
`core/freshness.py` che per ogni source calcola ultimo periodo coperto dalla canonical, ultimo raw
atterrato da `f_raw_objects`, soglia per grain, e compone la frase "vai su X → esporta Y (filtri Z) →
dal giorno W → esegui `hotelops capture`". Riscrivere i blocchi 1-7 di `cmd_health` come loop su quel
motore; la pagina Ingest del hub e `verticals/hub/freshness.py` usano lo stesso motore. Aggiungere
`period_from/period_to` a `f_raw_objects` così la copertura del singolo file è nota e un export filtrato
male (caso partite INTUR: 30 righe invece di 331) si vede prima del promote. Poche centinaia di righe,
zero infrastruttura nuova. I filtri-trappola che oggi si reimparano ogni volta ("senza filtro Mese",
"filtro su data registrazione", "Anno 2025+2026", "senza filtri") diventano campi del registry.

**6.2 Rendere il click corto: riconoscimento dal contenuto + intake senza pensieri.**
(a) Mergiare PR #117: i 15 export Power BI si riconoscono da `data.xlsx`, quindi passano da MANUAL a
SEMI e `hotelops capture` fa tutto. (b) Estendere i detector alle source oggi senza (fatture Esolver ×4,
vendite FB, menu engineering, RistoCube, Moolty, andamento prenotazioni), così `capture` copre l'intero
giro mensile. (c) `promote --all-promotable` reale e `snapshot_date` dalla data di estrazione, non di
esecuzione. (d) Un `gmail_fetch` sul pattern di `pec_fetch` che pesca gli allegati che Rosa manda già a
`stefano@` (movimenti MPS, PF, bilancini): l'export resta umano, ma l'umano non è più Stefano.
Risultato: il rituale mensile diventa "scarica N file in una cartella, un comando, una lista di ✓".

**6.3 Il rituale come contratto, non come memoria.** Fissare per iscritto nel registry la cadenza
attesa di ogni source E (settimanale OTB, mensile pieno banche/Esolver, trimestrale SDI) e l'owner, e far
uscire da health un **nudge settimanale** con solo le righe rosse di ciascun owner (Stefano, Rosa, Antonio).
La domanda aperta Q3 della spec ("banche/Esolver settimanale o bisettimanale?") va decisa ora perché fissa
le soglie. Con snapshot GCS anche su `spiaggia-corrispettivi` come già fatto su coperti.

**In parallelo, a costo zero di sviluppo**: le due richieste ai vendor (§7) restano in piedi e non
bloccano nulla; se un giorno arriva un sì, il puller si scrive copiando `drive_fetch.py`.

## 7. Cosa chiedere a HotelCube e a Hoxell

**HotelCube / Proxima.** La mail di oggi è corretta nel tono. Tre cose da tenere pronte per la risposta:
1. Il minimo tecnico: permesso **Build** su `Z_DataSet` per un service principal o un utente dedicato,
   con i due tenant setting (service principal + Execute Queries REST) abilitati **solo per un security
   group**, così non tocca gli altri clienti del tenant Proxima. Se il modello ha RLS, utente dedicato.
2. Il secondo canale che loro stessi hanno nominato: il 7 aprile Lara Durisotti ha scritto che HotelCube
   può mettere a disposizione un **"tracciato standard delle API"** per gli accodamenti. Stefano ha chiesto
   la documentazione il 13/04 e sollecitato il 17/04 senza risposta. Vale la pena richiamarlo nella stessa
   conversazione: è un'offerta loro, non una richiesta nostra.
3. Piano di escalation scritto: se nessuna risposta entro 10 giorni, proposta di call di 15 minuti e
   apertura commerciale esplicita ("se è un modulo a pagamento, dimmelo"). Tre richieste in 13 mesi hanno
   ricevuto istruzioni su dove cliccare: il malinteso è di categoria, non di volontà.

**Hoxell.** La bozza proposta va bene. Due aggiunte la rendono concreta:
- Nominare i dati, perché Hoxell ha già dimostrato di saperli esportare: a dicembre 2025 Pietro Pompeo ha
  mandato ad Antonio un Excel "Pulizie per data e tipologia Panorama Group" e ha promesso "un export in
  excel simile al report nuovo housekeeping con lo split giornaliero". Chiedere quello, schedulato:
  **pulizie per data/tipologia/struttura**, **colazioni per giorno (previsti, serviti, per tipo ospite)**,
  eventualmente presenze/straordinari. Sono i tre dataset che oggi HotelOps non ha e che coprirebbero
  housekeeping, F&B e HR.
- Indirizzarla a Pietro Pompeo e Beatrice Capoferri in copia ad Antonio, perché la relazione la tiene lui.
- Chiedere esplicitamente la modalità più semplice per loro: export schedulato via e-mail o SFTP va bene
  quanto un'API, perché `pec_fetch`/`gmail_fetch` lo ingerisce senza umano.

## 8. L'esperienza ideale di `hotelops health` / ingestion

Un solo motore, tre superfici (CLI, pagina Ingest del hub, nudge settimanale). Output per source, non per tabella:

```
  SORGENTI — 2026-09-09

  🔴 ESOLVER_PARTITE_ORTI_SNAPSHOT     ultimo 30/06 (71gg, atteso ≤35)
     → Esolver › Situazione partite sintetica per fornitori › SENZA filtri › xlsx
     → owner Rosa · poi: hotelops capture <file>
     → blocca: cash_control, monthly_close
  🔴 MPS_BANCA_ORTI_APPEND             ultimo 20/08 (20gg, atteso ≤10)
     → Homebanking MPS › Lista movimenti › dal 15/08 (overlap sicuro, APPEND) › xls
     → owner Stefano · poi: hotelops capture <file>
  🟡 POWERBI_PRODUZIONE_ORTI_SNAPSHOT   ultimo 15/08 (25gg, atteso ≤31)
     → Power BI › Daily Production Report › Anno 2026, per struttura › Esporta dati
  ✓  RT_CORRISPETTIVISPIAGGIA_INTUR    automatico, job 09:00, ultimo run OK oggi
  ✓  PEC_MAILBOX_INTUR_APPEND          automatico, job 04:00, ultimo run OK oggi
  ⏸  INTESA_BANCA_ORTI_APPEND          dormiente (deciso 2026-06-30), silenzio atteso
```

Regole: automatico = silenzioso finché il job è verde; dormiente = non nagga; manuale = frase
completa con owner; `--json` per il hub e per NanoClaw; gli oggetti REJECTED/CLASSIFIED da giorni
compaiono come coda, non come rumore. Il nudge del lunedì manda a ciascun owner solo le sue righe rosse.

## 9. Cosa non conviene costruire adesso

- **RPA/Playwright** su Power BI o sui portali homebanking: fragile, con credenziali in gioco, e in
  contraddizione con la linea "canale ufficiale read-only" appena scritta ai vendor.
- **Un framework generico di connettori**: i due puller esistenti hanno la forma giusta; il terzo e il
  quarto si scrivono copiando `drive_fetch.py`, non astraendolo.
- **La data-API `hotelops-api`** e il cockpit JS: parcheggiati a giugno con criterio, restano parcheggiati.
- **Codice per Hoxell** prima della risposta del vendor.
- **Parser per le 6 source RAW_ONLY** (stampa cassa ×2, dettaglio prenotazioni, numero camera clienti,
  consprev pax, `f_ricavi_camera_anno`): il semantic model le rende superflue se arriva l'accesso, e
  nessun loop le consuma.
- **Riscrivere il legacy** `classify/orchestrate/datahub_sync`: va spento pezzo per pezzo quando
  l'ultimo consumer cade, non riprogettato.

## 10. Debiti trovati strada facendo (non richiesti, da non perdere)

- `core/source_registry.yaml:1082-1098`: due chiavi `ESOLVER_PARTITE_APERTE_*_APPEND` fuori da
  `sources:`, invisibili al resolver. Da cancellare.
- `core/registry.yaml` dichiara in testa di essere letto da `classify.py`: falso su main; vero solo nella PR #117.
- 4 `source_name` orfani in `f_raw_objects` e 2 prefissi GCS (`POWERBI_BUDGETFORECAST`, `POWERBI_BOOKINGS`) senza registry.
- `ingest/flussi/ingest_scheda_190101.py`: secondo writer su `f_movimenti_contabili`, senza lineage.
- `ingest/flussi/ingest_bilanci_annuali.py`: scrive `f_bilanci_annuali` senza source né lineage; nessun consumer.
- Coperti: job cloud scrive senza `intake/promote`; lifecycle nel registry dice APPEND, il job fa wipe+reload.
- `core/bq/manifest.yaml` generato il 2026-07-10; `docs/architecture/runtime-inventory.yaml` del 2026-07-15 elenca 4 job, sono 5.
- `hotelops promote --all-promotable` è uno stub Phase 1; `promote` data gli snapshot con il giorno di esecuzione.
- `~/Library/LaunchAgents/com.panoramagroup.consumi.plist` fallisce ogni notte (exit 78) su un path morto.
- Tabelle senza alcun consumer: `f_chiusura_mensile`, `f_pf_rotazioni`, `f_bilanci_annuali`, `f_bookings_tipologia`,
  `f_consprev_mensile`, `f_progetto_*`; il loop `season_forecast` dichiarato nel registry non esiste nel codice.
