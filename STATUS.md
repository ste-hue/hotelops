# Status — 2026-04-26

## In corso
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- v_ledger_movimenti: view SQL creata (`core/bq/views/v_ledger_movimenti.sql`), non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito
- **revman vertical**: mappatura completa 5 fonti HotelCube (rates+availability forward, pickup operativo, produzione giornaliera, dettaglio fiscale, prenotazioni). **Bozza email a Lara pronta** (non ancora inviata) con richiesta doc API RMS esistenti + proposta call. Punto 5 (prenotazioni) potenzialmente già coperto da API RMS Proxima.
- **condges Rosa→Gasparotto integration**: spec + plan scritti (`c69abc1`, `beddc7e`). 2 task iniziali implementati (`19619de` parse Budget_Indici2025 via CE cross-ref, `143f60e` timedelta decoder cod_conto corrotti). Plan in esecuzione.
- **Projects event-sourced Step 1**: spec scritta `docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md`. Pivot da S2 (8 tabelle normalizzate, archiviata) a **3 tabelle event-sourced** (`d_progetti`, `f_progetto_voci`, `f_progetto_eventi`) con 5 tipi evento (PREVENTIVO/IMPEGNO/FATTURA/PAGAMENTO/DOCUMENTO). Validation seed su 2 progetti reali (HPAN25PIANO1 maturo + SPIAGGIA_LOTTO7 early-stage), 10 voci, 19 eventi. Vault aggiornato: `concepts/PROGETTO.md` §thread (event-log), ADR `2026-04-21_Progetto_First_Class_Dimension.md` amended (3 tab event-sourced). **Plan TDD da generare** via `superpowers:writing-plans` skill, poi implementazione Step 1.
- **Vault loops restructure**: 2/12 loop specs scritti (`daily_reconciliation`, `cash_control`). Next candidate: `monthly_close` (Gasparotto, COMPETENZA) per completare trilogia base.

## Completato di recente
- 2026-04-26: **Projects event-sourced design** — spec `docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md` (~390 righe, 12 sezioni: TL;DR, why event log, schema 3 tab, 5 tipi evento + Pydantic metadata, 4 view derivate per COSA/CHI/QUANTO/QUANDO, seed 2 progetti, multi-progetto generalization, Step 1 IN/OUT, roadmap 3 fasi forward-only→reversed→agent-loop, Excel→eventi mapping, anti-goals, related, implementation gate). Spec S2 archiviata in `docs/superpowers/specs/archive/2026-04-20-projects-mvp-design.md`. Vault captures: `concepts/PROGETTO.md` §thread aggiornato (event-log scelto, status candidate→active, domande 4-5 chiuse) + ADR `2026-04-21_Progetto_First_Class_Dimension.md` amended (Implementation approach: 3 tab event-sourced, domande 2-3-5 chiuse). User approval esplicita.
- 2026-04-23: **vault foundation + primi loop specs** — commit vault `48e594d`: IDENTITY.md (statement canonico "company operating system per hospitality: loops, oggetti tipizzati, azioni auditable, agents narrow"), loops/_INDEX.md (registry 12 loops in 3 categorie con status 🟢/🟡/⚪ + template 10 sezioni), loops/daily_reconciliation.md (backoffice, CASSA giornaliera), loops/cash_control.md (Rosa, CASSA settimanale), INDEX.md aggiornato (Foundation + nuova sezione 🔁 Loops).
- 2026-04-23: **parser account-based + hardening cassa + shell scripts** — commit `c72e66a`: classificazione event_type via conto 39.05.21 (definizionale, non euristica progressivo=0), risolve caparre mis-classificate; no-lumping aggregatore; `_normalize_date` return-empty+warning; fattura senza IVA scartata con warning; `_QUADRA_TOLERANCE` estratta; struttura unknown su prefisso filename fuori {H,R,C}. 7 test parser + 3 test cassa, 34 test verdi. Commit `966542d`: shell scripts — preflight venv, log lock-held, .env warning non-fatale, `rc=$?` + `exit "$rc"` preserva exit code reale.
- 2026-04-23: **CLAUDE.md drift + v_economato ABC per società** — commit `8bd8d00`: CLAUDE.md checkpoint 2026-04-21, 3 moduli core documentati (datahub_sync, bq/client, parsers/accodamenti, pipeline_run), views 14→16, tests list ri-allineata. v_economato_costo_unitario.sql ora partiziona ABC su (societa, anno, mese, reparto) — prima mischiava ORTI e INTUR.
- 2026-04-22: **accodamenti ingest + fix rglob cartelle-data** — HotelCube ha iniziato a organizzare TXT in sotto-cartelle per data (`ACCODAMENTI HOTEL CUBE/19_04_2026/…`). Il glob non-ricorsivo saltava tutto. Fix `0527594`: `rglob` + `rel_path` param. Ingest reale: parsed=222, new=99, dupes=123. `f_accodamenti` ora 376 righe, `MAX(data_registrazione)` 2026-04-21 (era 2026-03-21). Hash MD5 path-independent → nessuna invalidation storiche.
- 2026-04-21: **audit tech-lead + Projects MVP pivot + vault captures** — audit ha identificato d_voci `390521` duplicate (ENTRATE_CAPARRE + ENTRATE_CAPARRE_INTUR 🔴), CLAUDE.md drift residuo (3 moduli core non documentati), 2 views non materializzate. Projects pivotato a Binario A: plan normalizzato archiviato (`25fa57d`), Binario A seed `d60e5b7`. 3 vault captures: concept PROGETTO + decision Progetto_First_Class_Dimension + CONDGES boundary.
- 2026-04-21: **condges Rosa→Gasparotto integration** — spec `c69abc1` (CE-sheet parser pivot, libreoffice recalc) + plan `beddc7e` + `2024531` WI-1 Task 2 simplify. Implementazioni iniziali: `19619de` parse Budget_Indici2025 via CE cross-ref, `143f60e` timedelta decoder cod_conto corrotti XLSX Gasparotto.
- 2026-04-21: **commit untracked + checkpoint** — `692589f` + `6a45183` committano cassa_giornaliera + tests (580+273 LOC, 23 test verdi), `v_economato_costo_unitario.sql`, `scripts/coperti-daily.sh`, `.claude/commands/vault-loop.md`. CLAUDE.md checkpoint 2026-04-21.
- 2026-04-20: **bank routing + spec iniziali** — `f825ccf` route bank files a `{banca}` subfolder + cache mirror. `1cc4201` projects MVP spec iniziale. `caad836` spec condges Rosa→Gasparotto iniziale.
- 2026-04-19: refactor **coupling audit** — L1: accodamenti parser promosso a `core/parsers/accodamenti.py` (`d19144c`), `condges/` non importa più da `ingest/`. L2: BQ client singleton `core/bq/client.py::get_client()` (44 siti consolidati). L3: rclone/Drive sync centralizzato in `core/datahub_sync.py` (7 siti). Commit `e9d43a3` + `d19144c`. Tutti i test verdi.
- 2026-04-18: revman **discovery API HotelCube** — inventariati 5 export xlsx manuali (Dashboard Manager, Stampa Cassa, Availability Search, Rates Dashboard, Pickup). Analizzato PDF AccodamentoIntegration v2.2 (Proxima = HotelCube, stessa azienda). Identificate API RMS esistenti da richiedere prima di ragionare su custom. Bozza email a Lara pronta.
- 2026-04-17: condges **`cassa_giornaliera.py`** — porting da `reconciliation_dino`: parser TXT accodamenti HotelCube + aggregazione giornaliera POS/contanti/caparre → Excel 2 sheet. Nuovo CLI `hotelops accodamenti` (con rclone sync da Drive). 23 test TDD passati.

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche (runbook, protocolli) → `docs/` nel repo. Business/ontology → Obsidian vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste, parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive
- Gap detection euristica (`len(kept)==cap`): da rivedere dopo 2-4 settimane di dati reali — oggi falsi positivi su property piccole a first-run
- **revman come verticale #3**: confermato. Scope dipende da risposta API HotelCube. Se API disponibili → ingest automatico. Se no → export manuali periodici + pipeline parse.
- **Pattern integrazione API HotelCube**: client diretto da hotelops CLI (non via Esolver), auth apiKey dedicata + IP whitelist. Deciso 2026-04-18.
- **Projects come dimensione di primo livello (CapEx)**: deciso 2026-04-21, refined 2026-04-26 con scelta **event-sourcing su 3 tabelle** (`d_progetti`, `f_progetto_voci`, `f_progetto_eventi` con 5 tipi evento). Naming risolto: italiano `progetto_*`. Spec attiva `2026-04-22-projects-event-sourced-design.md`. Aperta: vertical #4 vs CONDGES extension (decisione rinviata a fine Step 1).
- **Fonti CLI/APP in `f_piano_finanziario_input` cieche a `v_previsione_cassa`**: la view filtra solo `fonte='PIANO_FINANZIARIO'`, quindi `hotelops previsione` e save da app Streamlit non si riflettono nella proiezione. Emerso scrivendo loop `cash_control` (2026-04-23). Decidere: promuovere fonti a canonical o consolidare. Richiede decision esplicita prima di toccare la view.
- **Drift `bank_reconciliation` vs `bank_ledger_reconciliation`** nel vault loops: `_INDEX.md` linka `[[bank_reconciliation]]` (backoffice, mensile, via `condges/reconcile_banca.py`); file creato oggi 2026-04-23 è `bank_ledger_reconciliation.md` (Rosa, giornaliero, CASSA vs COMPETENZA su conti 57*). Semanticamente sono due loop diversi — decidere se coesistono o si unificano. File non committato ancora.

## Rotto / da fixare
- ✅ ~~**`extract_saldo_mps2026` date parsing**~~ — fixato 2026-04-16: aggiunto parse_date per testo + future-date guard.
- ✅ ~~**d_voci pattern duplicate `390521`**~~ — verificato 2026-04-23: non causa double-count, le righe sono per società distinte (ORTI vs INTUR).
- 🟡 **Gap residuo crash totale** `send_email` → `mark_alerts_sent` — il fix `af685b2` cattura il caso streaming buffer (retry + pending file), ma se il processo muore completamente tra send_email e persist_pending non c'è traccia locale. Scelta consapevole "alert duplicato > alert perso" ancora in piedi, ora blast radius molto ridotto.
- ✅ ~~Google rotto 5+ settimane prima del 9 aprile~~ — risolto. Test manuale 2026-04-24 (`hotelops reviews --scrape --only google`): actor ok (SUCCEEDED 3/3 BU, 45 raw). HOTEL fresh `MAX(data_review)=2026-04-18`; RESIDENCE+CVM ferme a 2025-09-13 ma = ipotesi "niente review nuove fuori stagione" (l'actor prende nuove quando esistono, dimostrato da HOTEL). Da confermare con check manuale su Google Maps per RESIDENCE/CVM.
- 🟡 Crash window tra `send_email` e `mark_alerts_sent` UPDATE — scelta consapevole "alert duplicato > alert perso", da rivedere se succede.

## Prossimi passi
- **Loop spec `monthly_close`** — Gasparotto, COMPETENZA mensile, tocca `hotelops chiudi` + `v_budget_canonical` + `f_chiusura_mensile`. Completa trilogia base (daily/weekly/monthly) e introduce dimensione COMPETENZA dopo le 2 CASSA già scritte.
- **Risolvere drift bank_reconciliation vs bank_ledger_reconciliation** — decidere se sono due loop distinti (mensile backoffice + giornaliero Rosa) o uno solo. Il file `bank_ledger_reconciliation.md` è stato creato da agente parallelo oggi, non ancora committato.
- **Test cassa giornaliera su 1 giorno reale** — usare il nuovo stream `f_accodamenti` (post-fix rglob) per validare `condges/cassa_giornaliera.py` su un giorno specifico vs riferimento manuale. Sblocca uso operativo.
- **Backfill `file_sorgente` sulle 277 righe vecchie** (non urgente) — consistenza con nuovo formato `ACCODAMENTI HOTEL CUBE/DD_MM_YYYY/<file>.txt` vs bare `<file>.txt`. Cosmetico, non blocca query.
- **Discussione separata `SOCIETA_DEFAULT = "INTUR"`** — le righe da cartella `ingresso/accodamenti/ORTI/…` vengono taggate INTUR via default. Da ragionare se va fixato o se il default era intenzionale per altro motivo.
- **Projects Step 1 plan TDD** — generare plan eseguibile via `superpowers:writing-plans` skill su spec `2026-04-22-projects-event-sourced-design.md`. Target: 3 CREATE TABLE + Pydantic discriminated union + seed loader (10 voci HPAN25PIANO1 + SPIAGGIA_LOTTO7) + view `v_progetto_voci_stato` + tests. No UI, CLI, LLM in Step 1.
- **condges Rosa→Gasparotto plan resume** — continuare esecuzione plan `beddc7e` dopo task iniziali (`19619de`, `143f60e`).
- **Inviare email a Lara Durisotti** (bozza pronta) — sblocca tutto su revman
- **Documento interno `docs/hotelcube-api-extension.md`** — mappatura 5 export → campi → uso BQ (reference per confronto con doc API RMS)
- Materializzare v_ledger_movimenti + v_condges_banca_dettaglio su BQ
- **Mail produzione giornaliera** — email semplice con occupazione + revenue per BU dal dato in `f_pms_statistiche`
- **Struttura `revman/`** — creare verticale con dashboard occupazione/ADR/RevPAR (dopo risposta HotelCube)
- Investigare CVM Trip.com avg 4.57 (sotto threshold alert 6.0) — capire se review reali o parsing
- Instrumentare banca/flussi pipeline con `PipelineRun` (context manager è già generico)
- Valutare email alert per `check_watermark_staleness` dopo 2-3 settimane di dati (oggi solo display CLI)
- Verifica manuale su Google Maps se RESIDENCE + CVM hanno review post-2025-09-13 (se sì: bug ordering; se no: fuori stagione come ipotizzato)
- Valutare esecuzione xlsx-movimenti-parser
