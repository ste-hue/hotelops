# Status — 2026-04-21

## In corso
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- v_ledger_movimenti: view SQL creata (`core/bq/views/v_ledger_movimenti.sql`), non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito
- **revman vertical**: mappatura completa 5 fonti HotelCube (rates+availability forward, pickup operativo, produzione giornaliera, dettaglio fiscale, prenotazioni). **Bozza email a Lara pronta** (non ancora inviata) con richiesta doc API RMS esistenti + proposta call. Punto 5 (prenotazioni) potenzialmente già coperto da API RMS Proxima.
- **condges Rosa→Gasparotto integration**: spec + plan scritti (`c69abc1`, `beddc7e`). 2 task iniziali implementati (`19619de` parse Budget_Indici2025 via CE cross-ref, `143f60e` timedelta decoder cod_conto corrotti). Plan in esecuzione.
- **Projects MVP Binario A**: seed committato (`d60e5b7`, HPAN25PIANO1 + 28 vendor), spec S2 authoritative (`docs/superpowers/specs/2026-04-20-projects-mvp-design.md`), plan normalizzato archiviato (`25fa57d`). MVP flat da costruire. Vault: `concepts/PROGETTO.md` + `decisions/2026-04-21_Progetto_First_Class_Dimension.md` + `verticals/CONDGES.md` boundary reconciler/project-engine.

## Completato di recente
- 2026-04-21: **audit tech-lead + Projects MVP pivot + vault captures** — audit ha identificato d_voci `390521` duplicate (ENTRATE_CAPARRE + ENTRATE_CAPARRE_INTUR 🔴), CLAUDE.md drift residuo (3 moduli core non documentati), 2 views non materializzate. Projects pivotato a Binario A: plan normalizzato archiviato (`25fa57d`), Binario A seed `d60e5b7`. 3 vault captures: concept PROGETTO + decision Progetto_First_Class_Dimension + CONDGES boundary.
- 2026-04-21: **condges Rosa→Gasparotto integration** — spec `c69abc1` (CE-sheet parser pivot, libreoffice recalc) + plan `beddc7e` + `2024531` WI-1 Task 2 simplify. Implementazioni iniziali: `19619de` parse Budget_Indici2025 via CE cross-ref, `143f60e` timedelta decoder cod_conto corrotti XLSX Gasparotto.
- 2026-04-21: **commit untracked + checkpoint** — `692589f` + `6a45183` committano cassa_giornaliera + tests (580+273 LOC, 23 test verdi), `v_economato_costo_unitario.sql`, `scripts/coperti-daily.sh`, `.claude/commands/vault-loop.md`. CLAUDE.md checkpoint 2026-04-21.
- 2026-04-20: **bank routing + spec iniziali** — `f825ccf` route bank files a `{banca}` subfolder + cache mirror. `1cc4201` projects MVP spec iniziale. `caad836` spec condges Rosa→Gasparotto iniziale.
- 2026-04-19: refactor **coupling audit** — L1: accodamenti parser promosso a `core/parsers/accodamenti.py` (`d19144c`), `condges/` non importa più da `ingest/`. L2: BQ client singleton `core/bq/client.py::get_client()` (44 siti consolidati). L3: rclone/Drive sync centralizzato in `core/datahub_sync.py` (7 siti). Commit `e9d43a3` + `d19144c`. Tutti i test verdi.
- 2026-04-18: revman **discovery API HotelCube** — inventariati 5 export xlsx manuali (Dashboard Manager, Stampa Cassa, Availability Search, Rates Dashboard, Pickup). Analizzato PDF AccodamentoIntegration v2.2 (Proxima = HotelCube, stessa azienda). Identificate API RMS esistenti da richiedere prima di ragionare su custom. Bozza email a Lara pronta con 5 gruppi dati in ordine di priorità.
- 2026-04-17: condges **`cassa_giornaliera.py`** — porting da `reconciliation_dino`: parser TXT accodamenti HotelCube + aggregazione giornaliera POS/contanti/caparre → Excel 2 sheet (Riepilogo + Dettaglio strutture). Nuovo CLI `hotelops accodamenti` (con rclone sync da Drive). 23 test TDD passati. Smoke test 40 giorni match reference CSV.
- 2026-04-16: fix **ORTI Cc2/Cc3 bank mapping** — Cc2=MPS, Cc3=MPS_KROSS (era invertito). Verificato su Esolver "Elenco Banche" 2026-04-15. Fix in `classify.py`, `ingest_scheda_contabile.py`, `CLAUDE.md`.
- 2026-04-16: ingest **`ingest_bilanci_annuali.py`** — parser bilanci XBRL markdown → `f_bilanci_annuali`. SNAPSHOT per (societa, anno). DELETE+INSERT.
- 2026-04-16: view **`v_ledger_movimenti.sql`** — view per bank reconciliation. Dedup SCHEDA_190101 vs PNC: giorni con SCHEDA usano solo SCHEDA, altri usano PNC. Esclusi "Ripresa saldi".

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche (runbook, protocolli) → `docs/` nel repo. Business/ontology → Obsidian vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste, parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive
- Gap detection euristica (`len(kept)==cap`): da rivedere dopo 2-4 settimane di dati reali — oggi falsi positivi su property piccole a first-run
- **revman come verticale #3**: confermato. Scope dipende da risposta API HotelCube. Se API disponibili → ingest automatico. Se no → export manuali periodici + pipeline parse.
- **Pattern integrazione API HotelCube**: client diretto da hotelops CLI (non via Esolver), auth apiKey dedicata + IP whitelist. Deciso 2026-04-18.
- **Projects come dimensione di primo livello (CapEx)**: deciso 2026-04-21. Concept `vault/concepts/PROGETTO.md` + decision `vault/decisions/2026-04-21_Progetto_First_Class_Dimension.md`. Approccio **Binario A** (flat MVP prima, normalizzato post-evidenza su 28 vendor reali). Aperte: vertical #4 vs CONDGES extension; naming `progetto_*` (vault) vs `projects_*` (spec repo) — riconciliare post-MVP-flat.

## Rotto / da fixare
- 🔴 **d_voci pattern duplicate `390521`** tra ENTRATE_CAPARRE e ENTRATE_CAPARRE_INTUR in `core/bq/dimensioni/d_voci_piano_finanziario.csv` — potenziale double-count caparre se view non filtra per societa. Audit tech-lead 2026-04-21. Da verificare.
- ✅ ~~**`extract_saldo_mps2026` date parsing**~~ — fixato 2026-04-16: aggiunto parse_date per testo + future-date guard.
- 🟡 **Gap residuo crash totale** `send_email` → `mark_alerts_sent` — il fix `af685b2` cattura il caso streaming buffer (retry + pending file), ma se il processo muore completamente tra send_email e persist_pending non c'è traccia locale. Scelta consapevole "alert duplicato > alert perso" ancora in piedi, ora blast radius molto ridotto.
- 🔴 Google rotto 5+ settimane prima del 9 aprile — `MAX(data_review)` Google pre-watermark = 2026-03-03 vs Booking/Expedia 2026-04-06. Root cause sconosciuta. Il prossimo cron post-watermark ci dirà se era scraping rotto o review reali mancanti.
- 🟡 Crash window tra `send_email` e `mark_alerts_sent` UPDATE — scelta consapevole "alert duplicato > alert perso", da rivedere se succede.

## Prossimi passi
- **Verifica d_voci `390521` double-count** — controllare se view filtra per societa, altrimenti fix necessario (audit P0 2026-04-21)
- **Projects MVP flat build** — implementare Binario A su HPAN25PIANO1 + 28 vendor seed. 2-3 settimane validation prima di rewrite normalizzato.
- **condges Rosa→Gasparotto plan resume** — continuare esecuzione plan `beddc7e` dopo task iniziali (`19619de`, `143f60e`).
- **Doc drift `CLAUDE.md`** — riflettere nuovi moduli condivisi: `core/parsers/`, `core/bq/client.py`, `core/datahub_sync.py`; views count 14→16; tests list 7→20 (audit 2026-04-21, drift residuo post-`6a45183`)
- **Inviare email a Lara Durisotti** (bozza pronta) — sblocca tutto su revman
- **Documento interno `docs/hotelcube-api-extension.md`** — mappatura 5 export → campi → uso BQ (reference per confronto con doc API RMS)
- Materializzare v_ledger_movimenti + v_condges_banca_dettaglio su BQ
- **Mail produzione giornaliera** — email semplice con occupazione + revenue per BU dal dato in `f_pms_statistiche`
- **Struttura `revman/`** — creare verticale con dashboard occupazione/ADR/RevPAR (dopo risposta HotelCube)
- Investigare CVM Trip.com avg 4.57 (sotto threshold alert 6.0) — capire se review reali o parsing
- Instrumentare banca/flussi pipeline con `PipelineRun` (context manager è già generico)
- Valutare email alert per `check_watermark_staleness` dopo 2-3 settimane di dati (oggi solo display CLI)
- Investigare perché Google era rotto prima del 9 aprile (confronto con prossimo cron post-fix)
- Valutare esecuzione xlsx-movimenti-parser
- Test Google reviews scrape manuale (`hotelops reviews --scrape --only google`) — verificare se actor funziona post-monitoring
