# CE per famiglie — incarico e verifica

## Incarico

- Autorizzazione: Stefano, «vai», 27 ottobre 2026; primo incremento A1 del piano Regia.
- Autore: sessione Codex corrente. Revisore indipendente: da assegnare nel team esistente.
- Branch: `feat/ce-famiglie-20261027`, base `16e5399ad9c87606bfc9aac5cf872603736cff67`.
- Worktree isolato in `/private/tmp/hotelops-ce-famiglie-20261027`; nessuna modifica al checkout principale.
- Perimetro: lettura e report del CE canonico; builder Bilancini esistente, nuovo modulo puro e test sintetici.
- Esclusi: riattivazione `app_cdg`, riclassificazione conti, scritture BQ, pubblicazione, Regia e distribuzione.
- Conflict check: worktree ruff, bilancino-snapshot, consolidation, freshness-contract letti; nessuna modifica a ingest, CLI condivisa, viste o mapping. Si prosegue dal commit CdG già esistente, senza duplicarne il lavoro.

## Piano verificabile

1. Leggere la vista canonica CE con parametri anno/mese; usare i bilancini come controllo indipendente dei progressivi.
2. Produrre in Python importi mensili/progressivi e incidenze per famiglia e conto. Nessuna riclassificazione nel renderer.
3. Rifiutare duplicati, valori non finiti e scarti oltre un centesimo. Un mese mancante rende non disponibile anche il delta successivo; il progressivo resta verificabile sullo snapshot.
4. Integrare una modalità «CE per famiglie» nel builder Bilancini, attivata esplicitamente con `--ce-mese`, con società separate, dettaglio, fonti e limiti. In questa modalità non si espongono i riepiloghi/CSV legacy, che calcolano i delta con regole differenti.
5. Test sintetici di quadratura, storni, conti azzerati, lacune, ricavi nulli, sconosciuti e intercompany; regressione del builder; generazione privata reale gennaio–settembre.

Il criterio di riuscita è un report leggibile prodotto dal codice del branch, con dettaglio riconciliato per conto/società/mese. Nessun risultato del report attesta completezza documentale, correttezza semantica del mapping o competenza di rettifiche non registrate.

## Decisione sulla superficie

Il vault CdG distingue il ritiro definitivo di `app_cdg` dalla vecchia voce `soon` nel registry. Si conserva il backend HotelOps e si estende l'artifact Bilancini già presente. La lettura futura in Regia userà questo produttore, senza trasferirvi formule. Non si modifica il deployment.

## Stato

IMPLEMENTED, non revisionato indipendentemente, non integrato e non pubblicato.

## Consegna

- `verticals/condges/ce_famiglie.py`: lettura parametrizzata della vista, contratto `hotelops.ce-famiglie.v1`, quadratura per conto/mese con gli snapshot, mensili/progressivi e incidenze, renderer e CSV dallo stesso contenuto.
- `build_bilancini_artifact --ce-mese 9 --out <percorso-privato>`: report HTML e snapshot `.ce.json`; la modalità preesistente senza flag resta invariata. Il CSV del CE è scaricabile dal report. Non è stato usato `--push`.
- Undici famiglie canoniche, conti e flag intercompany ereditati dalla vista; nessuna riclassificazione arbitraria e nessun consolidamento. I canoni sono distinti per conto nel dettaglio, non inferiti dalla descrizione.
- Nessuna dipendenza da budget, driver percentuali o Regia. Il 65% non produce costi osservati.
- La generazione fallisce prima di scrivere output in presenza di duplicati, importi non finiti, mismatch per conto o variazioni prive di snapshot. I mesi mancanti e le percentuali non calcolabili hanno valore nullo, mai zero sostitutivo.

## Prove eseguite il 27 ottobre

- RED/GREEN: test del contratto falliti prima del modulo; test CLI/render falliti prima dell'integrazione; prova negativa sui riepiloghi legacy prima della separazione della modalità CE.
- Suite mirata: `HOTELOPS_SKIP_BQ=1 python -m pytest tests/test_ce_famiglie.py tests/test_build_bilancini_artifact.py tests/test_hub_bilancini_mount.py tests/test_cdg_engine.py tests/test_incidenza.py tests/test_load_views.py -m 'not bq' -q`: **79 passati, 13 deselected** (integrazioni BQ non lanciate dalla suite; lettura reale verificata separatamente).
- Generazione reale con SELECT BigQuery: 9/9 mesi per ORTI e INTUR, 1.017 + 594 quadrature conto/mese entro 0,01 euro, nessun conto senza famiglia. Controllo del codice importato: il modulo risolve nel worktree del branch.
- HTML, JSON e CSV usano lo stesso snapshot; identificatore del contenuto stabile al riordino delle righe e alla sola rilettura. L'hash identifica il contenuto esportato, non una versione immutabile upstream.
- Sintassi JavaScript verificata con `node --check`; Ruff e `git diff --check` eseguiti sui file interessati.
- Ispezione browser della prima versione della scheda ORTI riuscita; verifica interattiva INTUR interrotta dal cambio pagina dell'utente. Il renderer finale separa i riepiloghi legacy ed è coperto dai test, ma non è stato ricollaudato visivamente. Non dichiarare collaudo UI completo.
- Baseline allargata: 18 passati, due test della vecchia app non eseguibili per `plotly` assente. Suite completa tentata: collection interrotta dopo cinque errori per `reportlab`, `plotly`, `anthropic`, `apify_client` mancanti. Nessuna installazione o modifica dell'ambiente condiviso.

## Limiti e prossimo risultato

La quadratura verifica coerenza tra vista e bilancino acquisito, non l'originale Esolver né la completezza delle registrazioni. Non attesta correttezza semantica di tutte le famiglie, ricavi netti IVA, attribuzioni per struttura o competenza mensile di canoni/registrazioni tardive. La categoria canonica «Investimenti» è una famiglia di conti CE: non è un totale CAPEX o un flusso di cassa. Nessun EBITDA, margine operativo o allarme 65% viene inventato.

Credenziali BQ verificate solo per lettura manuale; nessun servizio periodico verificato. Nessuna scrittura BigQuery, Regia, Notion, Drive, Trello o email. Nessun deployment. Il prossimo risultato verificabile è la review indipendente del branch e la validazione gestionale del mapping/competenza; poi una criticità verificata potrà alimentare la proposta Regia.

I dati reali e gli artifact restano in `/private/tmp/cdg-ce-20261027`, esclusi dal repository. Il commit del branch è il riferimento della consegna; usare `git log -1` per lo SHA, senza autoriferimenti nel documento.
