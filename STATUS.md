# Status — 2026-04-07

## In corso
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito

## Completato di recente
- 2026-04-07: app_cdg — unified CDG app (CE riclassificato + Budget + Tesoreria + Indicatori), replaces 3 separate apps
- 2026-04-07: cdg_engine — pure computation module (CE cascade, EBITDA/BEP indicatori, proiezione anno con stagionalità)
- 2026-04-07: reviews cron pipeline — Gmail SMTP, ALTRO→GENERICA, weekly report con dettaglio
- 2026-04-07: fix cron reviews — full python path (hotelops alias non disponibile in cron), .env leading spaces
- 2026-04-07: email switched da Gmail API (OAuth broken) a Gmail SMTP con app password
- 2026-04-07: scrape limitato a 20 review più recenti per piattaforma (risparmio Apify credits)
- 2026-04-07: report settimanale migliorato — tabella dettaglio con data, BU, score, categoria, riassunto
- 2026-04-07: categoria ALTRO rinominata GENERICA (code + 341 righe BQ aggiornate)
- 2026-04-07: fix route_file return path + test setup — 155/155 test verdi
- 2026-04-06: reviews vertical completa — scrape, classify, alert, dashboard, cron
- 2026-04-02: help command CLI + content-based bank format detection fallback
- 2026-04-02: mese_sort_label aggiunto a v_condges_cashflow e v_economato_consumi
- 2026-04-02: bilancino log corretto (saldo invece di avere)

## Decisioni aperte
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste (`docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md`), parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive (COLAZIONE, CAMERE, etc.)

## Rotto / da fixare
- (niente di noto)

## Prossimi passi
- Tornare su condges: materializzare v_condges_banca_dettaglio su BQ
- Eseguire piano tesoreria app
- Valutare esecuzione xlsx-movimenti-parser
