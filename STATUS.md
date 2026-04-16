# Status — 2026-04-16

## In corso
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- v_ledger_movimenti: view SQL creata (`core/bq/views/v_ledger_movimenti.sql`), non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito
- **revman vertical**: identificato come verticale #3 (revenue management). Fonti dati mappate: Dashboard Manager (produzione giornaliera), Rates Dashboard (tariffe forward), Availability Search (disponibilità camere). Email inviata a HotelCube (Lara Durisotti) per documentazione API — in attesa risposta.

## Completato di recente
- 2026-04-16: fix **`extract_saldo_mps2026` date parsing** — aggiunto handling date testo (via `parse_date` DD/MM) + guard date future. Previene snapshot con date sbagliate in `f_saldi_banca_snapshot`.
- 2026-04-16: docs **vault-code drift fix** — REVIEWS.md aggiunto Trip.com (5a piattaforma), CONDGES.md corretto nomi app Streamlit (`app_cdg.py`, `app_scadenzario.py`), PLATFORM.md aggiornato da 9 a 15 views.
- 2026-04-16: fix **ORTI Cc2/Cc3 bank mapping** — Cc2=MPS, Cc3=MPS_KROSS (era invertito). Verificato su Esolver "Elenco Banche" 2026-04-15. Fix in `classify.py`, `ingest_scheda_contabile.py`, `CLAUDE.md`.
- 2026-04-16: ingest **`ingest_bilanci_annuali.py`** — parser bilanci XBRL markdown → `f_bilanci_annuali`. SNAPSHOT per (societa, anno). DELETE+INSERT.
- 2026-04-16: ingest **`ingest_scheda_190101.py`** — movimenti ledger banca da scheda contabile Esolver conto 190101 → `f_movimenti_contabili`. Copre gap dove prima nota non include dettaglio banca.
- 2026-04-16: view **`v_ledger_movimenti.sql`** — view per bank reconciliation. Dedup SCHEDA_190101 vs PNC: giorni con SCHEDA usano solo SCHEDA, altri usano PNC. Esclusi "Ripresa saldi".
- 2026-04-12: banca **cross-format dedup fix** — hash `f_banche_movimenti` ora format-agnostic: `md5(societa, banca, d_op, d_val, netto)` senza `desc`. `load_hashes` computa sia legacy hash che nuovo hash da righe BQ esistenti per backward compat. Testato: 334 dupes cross-formato riconosciuti su file ORTI/MPS (XLS classic vs XLSX 2026).
- 2026-04-12: banca **ingestion sessione** — 4 file ingeriti: INTUR/SELLA 25 righe, ORTI/MPS (XLS) 278, ORTI/MPS_KROSS 7 + saldo snapshot, ORTI/MPS (XLSX) 11 (solo righe nuove grazie al cross-format dedup). Totale: 321 righe nuove.
- 2026-04-12: banca **saldo snapshot cleanup** — cancellate 3 righe con date future (MM/DD parsing invertito in `extract_saldo_mps2026`), dedup tabella con `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY saldo_finale DESC)`.
- 2026-04-12: pms **`ingest_pms_statistiche.py`** — nuovo pipeline per HotelCube Dashboard Manager. Auto-detect BU da Camere Totali (86=HOTEL, 20=RESIDENCE, 10=CVM). Estrae: occupazione, ADR, RevPAR, revenue per classe (Room, F&B, Parking). Dedup su `(societa, bu, data)`. 27 righe caricate.
- 2026-04-12: pms **`PmsStatisticheRow` schema update** — da mensile a giornaliero, aggiunto `business_unit_id`, `camere_bloccate`, `revenue_fb`, `revenue_parking`, `revenue_totale`.
- 2026-04-11: reviews **Layer 2 single-write fix** (`0e5824a`) — refactor a event-sourcing: una sola INSERT su `__exit__` con stato finale. `check_crashed_runs` + status `RUNNING` rimossi.

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche (runbook, protocolli) → `docs/` nel repo. Business/ontology → Obsidian vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste, parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive
- Gap detection euristica (`len(kept)==cap`): da rivedere dopo 2-4 settimane di dati reali — oggi falsi positivi su property piccole a first-run
- **revman come verticale #3**: confermato. Scope dipende da risposta API HotelCube. Se API disponibili → ingest automatico. Se no → export manuali periodici + pipeline parse.

## Rotto / da fixare
- ✅ ~~**`extract_saldo_mps2026` date parsing**~~ — fixato 2026-04-16: aggiunto parse_date per testo + future-date guard.
- 🟡 **Gap residuo crash totale** `send_email` → `mark_alerts_sent` — il fix `af685b2` cattura il caso streaming buffer (retry + pending file), ma se il processo muore completamente tra send_email e persist_pending non c'è traccia locale. Scelta consapevole "alert duplicato > alert perso" ancora in piedi, ora blast radius molto ridotto.
- 🔴 Google rotto 5+ settimane prima del 9 aprile — `MAX(data_review)` Google pre-watermark = 2026-03-03 vs Booking/Expedia 2026-04-06. Root cause sconosciuta. Il prossimo cron post-watermark ci dirà se era scraping rotto o review reali mancanti.
- 🟡 Crash window tra `send_email` e `mark_alerts_sent` UPDATE — scelta consapevole "alert duplicato > alert perso", da rivedere se succede.

## Prossimi passi
- **Risposta API HotelCube** — in attesa da Lara Durisotti. Determina architettura revman (API vs export manuale)
- **Mail produzione giornaliera** — email semplice con occupazione + revenue per BU dal dato in `f_pms_statistiche`
- **Struttura `revman/`** — creare verticale con dashboard occupazione/ADR/RevPAR
- Materializzare v_ledger_movimenti + v_condges_banca_dettaglio su BQ
- Investigare CVM Trip.com avg 4.57 (sotto threshold alert 6.0) — capire se review reali o parsing
- Instrumentare banca/flussi pipeline con `PipelineRun` (context manager è già generico)
- Valutare email alert per `check_watermark_staleness` dopo 2-3 settimane di dati (oggi solo display CLI)
- Investigare perché Google era rotto prima del 9 aprile (confronto con prossimo cron post-fix)
- Valutare esecuzione xlsx-movimenti-parser
- Test Google reviews scrape manuale (`hotelops reviews --scrape --only google`) — verificare se actor funziona post-monitoring
