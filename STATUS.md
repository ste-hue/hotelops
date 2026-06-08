# Status — 2026-06-08

## In corso
- **cash_control v1** (CASSA, Loop B) -- design completo via grill (BQ-state authority, IMPEGNO-first projection, record-only decision-memory, 4/5 Kernel stages). Foundation in corso: **P0** re-baseline `f_movimenti_contabili` lineage-clean, **P1** load saldi certificati maggio, **P2** memory tables. Tutto bloccato su go esecuzione. Vedi `vault/sessions/2026-06-04_esolver_p0_and_cashflow_evaluation.md`.
- **F&B Looker pipeline** (mergiata su `main` 2026-05-22, commit `06abda7`): view refactor wide + bug fix v_fb_kpi 6.6x + audit tool (Streamlit+Form) + RistoCube Orders pipeline canonical. Pendente: refactor v_fb_kpi con CANTINA=100%Bar + esclusione 9 articoli UoM rotti.
- **Audit consumi F&B per direzione**: Streamlit `verticals/condges/audit_consumi_dashboard.py` (6 pagine, canonical-transformation-matrix) + Apps Script `audit_form.gs` (8 sezioni Form). Setup pendente: `createAuditForm()` su script.google.com + aggiornare FORM_URL + condividere col direttore.
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- v_ledger_movimenti: view SQL creata (`core/bq/views/v_ledger_movimenti.sql`), non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito
- **revman vertical**: mappatura completa 5 fonti HotelCube; Power BI Z_DataSet espone 12 report downstream. Solo Cruscotto/CruscottoMP ha loop dichiarato. **Bozza email a Lara pronta** (non inviata).
- **condges Rosa->Gasparotto integration**: spec + plan scritti (`c69abc1`, `beddc7e`). 2 task iniziali implementati. Plan in esecuzione.
- **Projects event-sourced Step 1**: spec scritta `docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md`. Plan TDD da generare, defer a Doc Refresh + cassa loop chiusi.
- **Vault loops restructure**: 2/12 loop specs scritti (`daily_reconciliation`, `cash_control`). Next candidate: `monthly_close`.
- **Doc Refresh Sprint**: Step 1+2+2.5 chiusi in working tree. Step 3 (README rewrite) in attesa OK. Step 4-9 in coda.

## Completato di recente
- 2026-06-08: **Produzione PMS — Task 8+9 (backfill + cleanup)** -- tabella `f_produzione_pms` creata; backfill intake+promote dei **6 file taglio-classe** (HOTEL/CVM/Angelina × 2025+2026, 2789 righe). Riconciliazione BQ **al centesimo** vs totali piano (HOTEL 2025 €3.282.683,39 ... CVM 2026 €53.588,04). 3 orfani lordo (`POWERBI_PRODUZIONE_ORTI_APPEND`) marcati REJECTED (reason NO_LOOP_TARGET). Docs aggiornati. Branch `feat/produzione-pms-lineage` pronto per merge. Occupazione (file `(2)`) NON ingerita — deferred.
- 2026-06-07: **Produzione PMS — spec+plan+Tasks 1–7** -- spec `2026-06-05-produzione-pms-lineage-design.md` (supersedes 2026-04-29), plan `2026-06-07-produzione-pms-lineage.md`, branch `feat/produzione-pms-lineage` (7 commit). Parser `f_produzione_pms` SNAPSHOT per (struttura,anno), cutover 2025-04-01, source `POWERBI_PRODUZIONE_ORTI_SNAPSHOT`, 18 test + riconciliazione reale OK. Verificato `intake`=raw-only.
- 2026-06-04: **Foundation cash_control + diagnosi P0 Esolver** (read-only) -- rotation aprile->maggio verificata (ORTI 13/0/7, INTUR 12/0/8, saldi = certificato); AEGRI scoperta = scheda contabile mis-ingerita in `f_movimenti_contabili`; 0/3863 righe con `raw_object_id` (I9 void); export "Lista movimenti contabili" completi validati come donor. Strategia: re-baseline-through-GCS.
- 2026-06-03: **Grill cash_control v1** -- 9 branch risolte, verdetto "genuine loop" (memory non control); reframe ipotesi: HotelOps = operational memory system. Vedi `vault/sessions/2026-06-03_cash_control_v1_kernel_loop_grill.md`.
- 2026-05-22: **Merge worktree-looker-fb su main** (commit `06abda7`, 40 commit, 20 file / 5584 insertions). F&B Looker pipeline completa: 4 viste F&B + audit tool + RistoCube Orders pipeline.
- 2026-05-21: **RistoCube Orders pipeline canonical** -- schema `RistocubeOrderRow`, tabella `f_ristocube_orders` (DAY partition, cluster sala/segmento/comanda_id), source `RISTOCUBE_ORDERS_ORTI_APPEND` (backend=gcs, APPEND), parser `ingest/flussi/ingest_ristocube_orders.py`. Backfill 8 file via intake+promote: **28.100 item righe, 7.197 comande, EUR271.377, range 16/04/25->21/05/26**.
- 2026-05-21: **Audit tool F&B per direzione** -- spec+plan canonical-transformation-matrix (6 layer x 3 vertical Breakfast/Ristorante/Bar), Streamlit+Form via subagent-driven 10 task. Range industria espliciti (pizzeria 15% / medio 25-35% / Michelin 38%). Pronto per audit con direttore.
- 2026-05-21: **Re-ingest `f_consumi_economato` consolidato** -- file `Consumptions F&B Data.xlsx` 22.763 righe vs 15.869 precedenti, 33 reparti vs 25 (+16 nuovi: DIPEND, DEPERIMENTO, HSK_*, MAN_*, EVENTI*, D*=Dotazioni). TRUNCATE+ingest con mapping HC code->canonical reparto_id.
- 2026-05-20: **Refactor 4 viste F&B in wide + v_fb_kpi v2 split Breakfast/Lunch/Dinner** -- bug fix critico: `ricavi_fb_totali` sommava tutte le classi gonfiando KPI 6.6x. Fix: filtro codici 02FB. Refactor v_fb_ricavi/v_fb_consumi (+is_anomalia)/v_fb_pasti/v_fb_kpi in wide. ricavi_room_totali (01ROOM) esposto.
- 2026-05-20: **Re-ingest `f_ricavi_fb` (Produzione Netta)** -- 43 xlsx Power BI (HP+ANG+CVM x 2025+2026), 993 righe, HOTEL 2025 EUR499k -> **EUR3.28M reale** (file precedenti erano filtrati). SNAPSHOT lifecycle.
- 2026-05-17: **Ripristino view BigQuery + loader deploy** -- dataset aveva solo 4 view su 21. Ri-deployate tutte e 21. Nuovo modulo `core/bq/load/load_views.py` (topological sort, deploy idempotente). CLI `hotelops deploy-views`.

## Decisioni aperte
- **SNAPSHOT per (struttura, anno) per produzione** (deciso 2026-06-07): la produzione è fotografia rivedibile (storni) → SNAPSHOT scope-replace, NON APPEND (raddoppierebbe sugli storni). Regola generale: evento immutabile→APPEND, fotografia rivedibile→SNAPSHOT.
- **`hotelops intake` = raw-only** (verificato 2026-06-07): l'auto-promote `AUTO` vive solo in `hotelops capture`; `intake` registra solo il raw_object. Promote richiede `--raw-object-id` esplicito.
- **File occupazione produzione = oggetto separato, deferred** (deciso 2026-06-07): NON ingerirli sotto `POWERBI_PRODUZIONE_ORTI_SNAPSHOT` (che ora = taglio classe/Imponibile→`f_produzione_pms`). Evitare ripetizione caso AEGRI (file valido, source semanticamente sbagliato). Da proporre: source separato RAW_ONLY o estensione registry con subtype/report_variant. Non implementato.
- **BQ largo / Looker filtra** (deciso 2026-05-20): BigQuery espone tutti i dati senza filtri preventivi, ogni filtro vive nel layer dashboard. Pattern da estendere a future view.
- **No mezza pensione, solo B&B** (chiarito 2026-05-20): Hotel Panorama opera B&B-only con breakfast scorporato (SCBKFBB ~EUR10/pax board value). Nessun "pensione gap" da chiudere.
- **Canonical-transformation-matrix F&B** (articolato 2026-05-21): framework 6-layer (Ricavi->Consumi->Coperti->KPI->Range->Alert) x 3 vertical. Range industria: pizzeria 15% / medio 25-35% / Michelin 38% / beverage 10-30%.
- **CANTINA = 100% Bar/Beverage** (chiarito 2026-05-21 da analisi Excel utente): anche il vino servito al ristorante esce da CANTINA -> classificato come Bar cost. CUCINA 100% Ristorante, BRK 100% Breakfast. Da riflettere in v_fb_kpi.
- **9 articoli UoM rotti**: BEV.CAF.00014 (caffe in grani) + 8 altri caricati con UM g come kg/sacchi, causano -EUR166k storno maggio 2025 + gonfiature Giu-Ott. Da escludere dai KPI come anomalia sistemica.
- **D-prefix HotelCube = Dotazioni** (NON Dipendenti): DRECEPTI, DUFFICID, DHSKHOTE, DMANHOTE, DSPIAGGI, DCOLAZIO sono consumabili operativi del reparto host.
- **Modifiche piano dei conti HotelCube possibili manualmente** (deciso 2026-05-21): no API ma modifiche al piano dei conti via UI HotelCube / supporto. Esiti audit possono includere ricalibrare SCBKFBB, sospendere codici, aggiungere scorporo cena.
- **Admin SDK in parking lot** (parcheggiato 2026-05-10): seconda SA `workspace-admin` con scope admin readonly. Triggering: quando serve query "quante mailbox attive?" o audit log.
- **Workspace Controller architecture** (deciso 2026-05-10): `workspace/` e SDK + scoop layer, NON destinazione canonical. Drive transit, GCS truth.
- **Forward-only GCS su main + `verticals-v2` frozen** (deciso 2026-05-09): main resta operativo, forward-only GCS additivo, parser legacy invariati. NO Phoenix merge, NO drop dati, NO cherry-pick massivo.
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche -> `docs/`. Business/ontology -> vault. Deciso 2026-04-09.
- **revman come verticale #3**: confermato. Scope dipende da risposta API HotelCube.
- **Pattern integrazione API HotelCube**: client diretto da hotelops CLI, auth apiKey + IP whitelist (deciso 2026-04-18).
- **Projects come dimensione di primo livello (CapEx)**: deciso 2026-04-21, refined 2026-04-26 con event-sourcing 3 tab.
- **Fonti CLI/APP in `f_piano_finanziario_input` cieche a `v_previsione_cassa`** (emerso 2026-04-23): decidere se promuovere fonti a canonical o consolidare.
- **Drift `bank_reconciliation` vs `bank_ledger_reconciliation`** in vault loops: decidere se coesistono o si unificano.
- **Frame canonico HotelOps = Company OS** (non "digital twin") -- articolato 2026-05-02. CLAUDE.md linea "digital twin" debito da risolvere in Doc Refresh Step 4.
- **GCS come Raw layer immutabile** (deciso 2026-05-02, implementato pilot 2026-05-05): bucket `hotelops-raw`. Resta aperto bulk flip 12 sources + pattern FK additivo.
- **Bulk flip 12 sources rimanenti -> `backend: gcs`** (emerso 2026-05-05): flip on-demand quando un loop la richiama.
- **Backfill rows storiche `file://` -> `gs://`** (emerso 2026-05-05): decidere se backfill upload + relink o lasciarle local-only.
- **Primo Kernel loop = cash_control v1** (deciso 2026-06-03, grill). "cassa giornaliera quadra y/n" declassata a *candidate detective control*. Anchor `f_saldi_banca_chiusura_mensile`, IMPEGNO-first projection, record-only memory.
- **Re-baseline-through-GCS** (deciso 2026-06-04): `f_movimenti_contabili` ripulita via intake->promote (lineage FK) + DELETE chirurgico patchwork; NON dedup-in-place. AEGRI (scheda contabile) rimossa da movimenti, re-routed via `ingest_scheda_contabile`.
- **f_movimenti_contabili scope = PNC prima nota** (deciso 2026-06-04); registro fatture FT/AFT/COR separato. Kross escluso dall'anchor. INTUR-marzo saldi certificati, tenuti.
- **Budget baseline scostamento = GASPAROTTO** (da confermare; CONS2025_* = baseline anno scorso, non il piano).
- **CASSA vs COMPETENZA vs scheda** (articolato 2026-06-04): banca diretta = cassa reale (tutto, real-time, `f_banche_movimenti`); Esolver movimenti = competenza registrata (`f_movimenti_contabili`); scheda contabile/AEGRI = bank ledger registrato (conto 190101, subset in ritardo). Bridge = reconciliation (tesi CM3070 / `reconcile_banca`).
- **Regola operativa ingest** (articolata 2026-05-02): scope dell'ingest settato dal discrimination need del loop, non dalla disponibilita del dato.
- **Glossario `segmento_cliente` parziale** (Ristocube): INLE/INTUI/GRLE/GRBU/GRSE/ZRIST* noti. TBD: vuoto, GRWE, FERR25, ZRISRES.

## Rotto / da fixare
- v_fb_kpi non riflette CANTINA=100%Bar: oggi tratta CUCINA+CANTINA come unico bucket. Da rifattorizzare con CANTINA -> Bar bucket separato.
- 9 articoli UoM rotti in f_consumi_economato: BEV.CAF.00014 + 8 altri. Oltre alla maschera maggio 2025, da escludere sistemica dai KPI.
- Pipelines stale >36h: `ingest_scheda_contabile` + `ingest_partite_aperte` ultimo OK run 2026-04-30.
- **f_movimenti_contabili: lineage void** -- 0/3863 righe con `raw_object_id`; `ingest_movimenti_contabili` non ha path GCS-intake (solo `--file`), viola I9. Risolve P0 re-baseline.
- **AEGRI mis-ingerita** in `f_movimenti_contabili` (scheda contabile conto 190101 via pipeline movimenti sbagliata) -- doppio conteggio leg banca. Da rimuovere + re-route via `ingest_scheda_contabile`.
- **Previsione cassa maggio ~110k troppo pessimista** (forecast €471k vs certificato €581k) -- ipotesi apertura anticipata (Apr 3 vs 16) + Godimento intercompany €147k. Decomporre post-P0.
- f_pms_statistiche freshness: dati fermi al 2026-04-11. Da estrarre 60 file Cruscotto giornalieri.
- Banche stale: INTUR/INTESA 53gg, ORTI/INTESA 32gg, INTUR/MPS 31gg, ORTI/MPS+MPS_KROSS 15gg. Solo INTUR/SELLA fresh.
- Gap residuo crash totale `send_email` -> `mark_alerts_sent`. Scelta consapevole "alert duplicato > alert perso".
- Mislabel MPS <-> MPS_KROSS per ORTI in `extract_saldo_mps2026` -- difetto latente confermato, fix deferred (content-detection IBAN autoritativa sul filename).

## Prossimi passi
- **Produzione — merge branch** `feat/produzione-pms-lineage` su main (Task 8+9 chiusi). Debiti residui: overlap 02FB con `f_ricavi_fb` (doppio drill-down stessa classe), `d_classi_produzione` TBD (mapping classe → BU/cod_conto/categoria_ce).
- **Produzione occupazione** (file `(2)`, deferred): proporre source separato RAW_ONLY o registry subtype/report_variant. Da affrontare quando serve RevPAR/ADR/occupazione camere.
- **Refactor v_fb_kpi** con CANTINA=100%Bar split + esclusione 9 articoli UoM rotti -- primo step F&B post-merge.
- **Generare Google Form per audit direzione** via `createAuditForm()` su script.google.com -> aggiornare `FORM_URL` in `verticals/condges/audit_consumi_dashboard.py`.
- **Condividere audit (Streamlit + Form) col direttore** -- decidere hosting: Streamlit Cloud, localtunnel, o sessione shared.
- **Capture vault dei 9-10 insights** sessione 2026-05-21 -- flaggati in `vault/sessions/2026-05-21_fb_canonical_model_and_audit_tool.md`.
- **P0: re-baseline `f_movimenti_contabili`** -- intake->promote export Esolver completi + DELETE patchwork+AEGRI (keystone: sblocca cash delta + BVA + cash_backcheck). Serve go + fresher ORTI export (->31 mag).
- **P1: load saldi certificati maggio** (5 righe, Kross escluso) -- pre-stage anchor rotation giugno. Verificare loader `f_saldi_banca_chiusura_mensile`.
- **P2: cash_control memory tables** + moduli evaluation: BVA (COMPETENZA, GASPAROTTO) + `cash_backcheck` (CASSA, PF forecast vs Esolver, backwards check).
- **Rotation maggio->giugno** ~fine giugno (timing paradigm); inputs staged in `pianfin/{PF,scadenziari}`.
- **Aggiornare CLAUDE.md** con nuova v_fb_kpi v2 columns, 33 reparti consumi, audit tool entries.
- **Viste F&B su f_ristocube_orders** (daily granularity) -- sblocca split Lunch/Dinner via orario/sala, scontrino medio per pasto, daily food cost.
- **Piano dei conti finale per ANG+CVM** in `pianodeicontilavoro.xlsx` (HP fatto 79/79, gli altri skeleton).
- **d_codici_pms_ricavi dimension table** dopo piano dei conti completo, con Pasto + Tipo per ogni codice.
- **Mappatura codice consumo -> codice vendita** (caso paradigmatico banchetti). Round con chef per matrice categoria_prodotto -> ricetta.
- **Lordo vs netto in `f_consumi_economato.importo`** (carry-over da 2026-05-19).
- **Smoke test workspace su Drive write** -- verificare impersonation `--write-as`. Cleanup folder orfani prima.
- **Production run HPAN25PIANO1** -- `hotelops workspace mine-capex --project HPAN25PIANO1`. Dopo smoke verde.
- **FK end-to-end smoke su MPS file fresh** -- al prossimo export bancario non storico.
- **Doc Refresh Sprint Step 3-9** -- README rewrite -> CLAUDE.md -> counts/tests -> Cutover decision -> TODO markers -> Agent Epistemology.
- **Materializzare** v_ledger_movimenti + v_condges_banca_dettaglio su BQ.
- **Inviare email a Lara Durisotti** (bozza pronta) -- sblocca revman.
- **condges Rosa->Gasparotto plan resume** -- continuare esecuzione plan `beddc7e`.
- **Loop spec `monthly_close`** -- Gasparotto file, COMPETENZA mensile.
- **Capture `vault/concepts/SEGMENTO_CLIENTE.md`** -- glossario codici Ristocube.
- Investigare CVM Trip.com avg 4.57 (sotto threshold alert 6.0).
- **Fix mislabel MPS/MPS_KROSS** -- content-detection IBAN autoritativa sul filename in `ingest/banca/ingest.py`.
