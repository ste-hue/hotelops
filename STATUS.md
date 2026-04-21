# Status — 2026-04-19

## In corso
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- v_ledger_movimenti: view SQL creata (`core/bq/views/v_ledger_movimenti.sql`), non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito
- **revman vertical**: mappatura completa 5 fonti HotelCube (rates+availability forward, pickup operativo, produzione giornaliera, dettaglio fiscale, prenotazioni). **Bozza email a Lara pronta** (non ancora inviata) con richiesta doc API RMS esistenti + proposta call. Punto 5 (prenotazioni) potenzialmente già coperto da API RMS Proxima.
- **cassa_giornaliera feature**: `condges/cassa_giornaliera.py` + `tests/test_cassa_giornaliera.py` (597 LOC + 23 test) verdi dopo refactor coupling, untracked — pronti per commit quando si decide di shippare.

## Completato di recente
- 2026-04-19: refactor **coupling audit** — L1: accodamenti parser promosso a `core/parsers/accodamenti.py` (`d19144c`), `condges/` non importa più da `ingest/`. L2: BQ client singleton `core/bq/client.py::get_client()` (44 siti consolidati). L3: rclone/Drive sync centralizzato in `core/datahub_sync.py` (7 siti). Commit `e9d43a3` + `d19144c`. Tutti i test verdi.
- 2026-04-18: revman **discovery API HotelCube** — inventariati 5 export xlsx manuali (Dashboard Manager, Stampa Cassa, Availability Search, Rates Dashboard, Pickup). Analizzato PDF AccodamentoIntegration v2.2 (Proxima = HotelCube, stessa azienda). Identificate API RMS esistenti da richiedere prima di ragionare su custom. Bozza email a Lara pronta con 5 gruppi dati in ordine di priorità.
- 2026-04-17: condges **`cassa_giornaliera.py`** — porting da `reconciliation_dino`: parser TXT accodamenti HotelCube + aggregazione giornaliera POS/contanti/caparre → Excel 2 sheet (Riepilogo + Dettaglio strutture). Nuovo CLI `hotelops accodamenti` (con rclone sync da Drive). 23 test TDD passati. Smoke test 40 giorni match reference CSV.
- 2026-04-16: fix **`extract_saldo_mps2026` date parsing** — aggiunto handling date testo (via `parse_date` DD/MM) + guard date future. Previene snapshot con date sbagliate in `f_saldi_banca_snapshot`.
- 2026-04-16: docs **vault-code drift fix** — REVIEWS.md aggiunto Trip.com (5a piattaforma), CONDGES.md corretto nomi app Streamlit (`app_cdg.py`, `app_scadenzario.py`), PLATFORM.md aggiornato da 9 a 15 views.
- 2026-04-16: fix **ORTI Cc2/Cc3 bank mapping** — Cc2=MPS, Cc3=MPS_KROSS (era invertito). Verificato su Esolver "Elenco Banche" 2026-04-15. Fix in `classify.py`, `ingest_scheda_contabile.py`, `CLAUDE.md`.
- 2026-04-16: ingest **`ingest_bilanci_annuali.py`** — parser bilanci XBRL markdown → `f_bilanci_annuali`. SNAPSHOT per (societa, anno). DELETE+INSERT.
- 2026-04-16: ingest **`ingest_scheda_190101.py`** — movimenti ledger banca da scheda contabile Esolver conto 190101 → `f_movimenti_contabili`. Copre gap dove prima nota non include dettaglio banca.
- 2026-04-16: view **`v_ledger_movimenti.sql`** — view per bank reconciliation. Dedup SCHEDA_190101 vs PNC: giorni con SCHEDA usano solo SCHEDA, altri usano PNC. Esclusi "Ripresa saldi".
- 2026-04-12: banca **cross-format dedup fix** — hash `f_banche_movimenti` ora format-agnostic: `md5(societa, banca, d_op, d_val, netto)` senza `desc`. `load_hashes` computa sia legacy hash che nuovo hash da righe BQ esistenti per backward compat. Testato: 334 dupes cross-formato riconosciuti su file ORTI/MPS (XLS classic vs XLSX 2026).

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche (runbook, protocolli) → `docs/` nel repo. Business/ontology → Obsidian vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste, parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive
- Gap detection euristica (`len(kept)==cap`): da rivedere dopo 2-4 settimane di dati reali — oggi falsi positivi su property piccole a first-run
- **revman come verticale #3**: confermato. Scope dipende da risposta API HotelCube. Se API disponibili → ingest automatico. Se no → export manuali periodici + pipeline parse.
- **Pattern integrazione API HotelCube**: client diretto da hotelops CLI (non via Esolver), auth apiKey dedicata + IP whitelist. Deciso 2026-04-18.

## Rotto / da fixare
- ✅ ~~**`extract_saldo_mps2026` date parsing**~~ — fixato 2026-04-16: aggiunto parse_date per testo + future-date guard.
- 🟡 **Gap residuo crash totale** `send_email` → `mark_alerts_sent` — il fix `af685b2` cattura il caso streaming buffer (retry + pending file), ma se il processo muore completamente tra send_email e persist_pending non c'è traccia locale. Scelta consapevole "alert duplicato > alert perso" ancora in piedi, ora blast radius molto ridotto.
- 🔴 Google rotto 5+ settimane prima del 9 aprile — `MAX(data_review)` Google pre-watermark = 2026-03-03 vs Booking/Expedia 2026-04-06. Root cause sconosciuta. Il prossimo cron post-watermark ci dirà se era scraping rotto o review reali mancanti.
- 🟡 Crash window tra `send_email` e `mark_alerts_sent` UPDATE — scelta consapevole "alert duplicato > alert perso", da rivedere se succede.

## Prossimi passi
- **Committare `condges/cassa_giornaliera.py` + `tests/test_cassa_giornaliera.py`** (feature accodamenti, verde dopo refactor coupling)
- **Doc drift `CLAUDE.md`** — riflettere nuovi moduli condivisi: `core/parsers/`, `core/bq/client.py`, `core/datahub_sync.py`
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
