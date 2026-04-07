# Status — 2026-04-07

## In corso
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito

## Completato di recente
- 2026-04-07: app_cdg — unified CDG app (CE riclassificato + Budget + Tesoreria + Indicatori), replaces 3 separate apps
- 2026-04-07: cdg_engine — pure computation module (CE cascade, EBITDA/BEP indicatori, proiezione anno con stagionalità)
- 2026-04-07: reviews cron pipeline — Gmail SMTP, ALTRO→GENERICA, weekly report con dettaglio
- 2026-04-02: help command CLI + content-based bank format detection fallback
- 2026-04-02: mese_sort_label aggiunto a v_condges_cashflow e v_economato_consumi
- 2026-04-02: bilancino log corretto (saldo invece di avere)
- 2026-03-31: manifest command + budget fonte priority fix
- 2026-03-28: Looker views (v_condges_budget_consuntivo, v_condges_pf_mensile, v_condges_cashflow, v_economato_consumi, v_economato_pareto)

## Decisioni aperte
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste (`docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md`), parking lot

## Rotto / da fixare
- (niente di noto)

## Prossimi passi
- Materializzare v_condges_banca_dettaglio su BQ
- Eseguire piano tesoreria app
- Valutare esecuzione xlsx-movimenti-parser
