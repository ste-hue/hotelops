# HotelOps Hub — layer di presentazione sopra i vertical

**Data:** 2026-06-12
**Stato:** spec approvata a voce, in review scritta
**Dipendenze:** spec gemella `2026-06-12-pf-generazionale-design.md` (per la pagina Cassa);
contratto `verticals/condges/fb_dashboard.py::render()` dal worktree `fb-looker` (per la pagina F&B)

## Cos'è (e cosa non è)

Il hub è il **layer di presentazione** di hotelops: un'unica app Streamlit multipage che dà
accesso visivo ai risultati dei vertical, oltre il CLI. **Non è un vertical** (revman resta
il vertical #3 confermato): non possiede dati né logica di dominio, monta lenti sui vertical
esistenti.

Motivazione: le 4 app Streamlit esistenti soffrivano di "mondo congelato" — mostravano dati
stantii mentre il motore sotto maturava. Il hub legge **solo BigQuery** (mai file a runtime)
e espone la freshness dei dati come cittadino di prima classe.

## Utenti e ruoli

- **Fase 1 (questa spec): solo Stefano, localhost.** Nessuna auth.
- **Fase 2 (fuori scope, vincolata dal design): team in sola lettura, azioni solo Stefano.**
  Deploy Cloud Run + IAP; ruoli admin/viewer. Il design di fase 1 non deve bloccarla.

## Architettura

```
verticals/hub/                  <- layer di presentazione (NON un vertical)
  app.py                        <- entry: streamlit run verticals/hub/app.py
  home.py                       <- home-store: card + freshness
  freshness.py                  <- query freshness per card (riusa logica `hotelops health`)
  pages_/
    cassa.py                    <- App 1: Cassa/PF — specchio con memoria
    fb.py                       <- App 2: monta fb_dashboard.render() (worktree fb-looker)
    reviews.py                  <- App 3: monta la dashboard reviews esistente
    ingest.py                   <- App 4: layer di ingestione (aggiunta 2026-06-12)
```

Niente moduli speculativi (vincolo esplicito 2026-06-12): `bva.py`, `auth.py` e `actions.py`
nascono quando servono, non ora.

### Regole architetturali

1. **Zero logica di dominio nel hub.** Ogni pagina importa dal suo vertical
   (`cdg_engine`, `pf_mirror`, `fb_dashboard`, query esistenti). Se una pagina cresce,
   il codice scende nel vertical. Ogni app resta staccabile (porta aperta verso
   l'architettura "portale + app separate" se mai servisse).
2. **Azioni solo via registry (fase 2), con un'eccezione dichiarata.** Quando arriveranno,
   le azioni (pf-rotate, chiudi, health) passeranno da un registry unico `actions.py`
   (nome → handler → ruolo minimo); i bottoni non chiamano mai i worker direttamente.
   **Eccezione fase 1: la pagina Ingest** (decisione 2026-06-12) — unica superficie di
   scrittura, chiama direttamente le stesse funzioni del CLI (`ingest/classify.py`,
   `ingest/intake.py`, `ingest/promotion.py`). Niente registry per un consumatore solo
   (simplicity first); `ingest.py` sarà il primo cliente di `actions.py` quando nascerà.
3. **BigQuery unica fonte dati delle viste.** Lo specchio PF funziona perché ogni
   post-rotate è ingerito come generazione (spec gemella); il hub non sa che esistono file.

## Home (layout "store di card")

Header: titolo + stato health complessivo (verde/giallo/rosso da `freshness.py`, con
drill-down testuale: quali fonti sono stale e da quanto).

Sotto, una card per app montata — **Cassa/PF**, **F&B**, **Reviews**, **Ingest** (niente
card BVA "prossimamente": nasce con `bva.py`). Ogni card: nome, semaforo freshness dei
dati che quella app legge, un numero chiave (saldo banche certificato totale; food cost
ristorante; media reviews ultimo mese; per Ingest: conteggio raw objects non-PROMOTED),
click per entrare. Nessun pannello azioni.

## Pagina Cassa/PF — lo specchio con memoria

La prima app a dover funzionare ("caffè della mattina").

- **Specchio**: griglia voce × mesi come l'Excel (entrate, uscite, saldo progressivo);
  mesi chiusi = consuntivo, mesi avanti = previsione della generazione corrente
  (`v_pf_corrente` via `v_piano_finanziario_mensile`). Selettore società ORTI/INTUR.
  In testa: saldi banca certificati dell'ultimo fine mese + semaforo liquidità.
- **Memoria — confronto generazioni (modalità A, delta overlay)**: attivando
  "confronta con <generazione>", ogni cella mostra valore corrente + variazione colorata
  rispetto alla generazione scelta. Le generazioni si identificano per `raw_object_id` /
  `file_sorgente` (es. "file 2026-04", "file 2026-05").
- **Badge shadowing**: celle il cui valore corrente viene da una correzione CLI/APP
  *precedente all'ultima generazione* mostrano un badge esplicito (semantica di precedenza
  conservata, vedi spec gemella — il rischio si rende visibile, non si nasconde).
- **Evoluzione (modalità C) — fase successiva, prevista**: tab dedicata con la traiettoria
  della previsione attraverso le rotazioni ("il saldo di agosto visto da feb/mar/apr/mag").
  Il modello dati la supporta già; la UI arriva dopo la A.

La logica (pivot dello specchio, calcolo delta tra generazioni, individuazione shadowing)
vive in un modulo puro **`verticals/condges/pf_mirror.py`** — testabile senza Streamlit
né BQ. La pagina `cassa.py` resta sottile.

## Pagina F&B

Monta `from verticals.condges.fb_dashboard import render` — il modulo in costruzione nel
worktree `fb-looker`, progettato importabile (niente `set_page_config` interno). È il
monitoraggio operativo di Stefano. L'**audit tool direzione resta superficie separata**
(`audit_consumi_dashboard.py`), fuori scope; eventualmente seconda pagina in futuro.

## Pagina Ingest — il layer di ingestione (aggiunta 2026-06-12)

La porta d'ingresso visiva dei dati, lineage-first (stesso path della skill
`hotelops-ingest`: mai parser diretti, mai scritture senza raw_object):

1. **Drop**: `st.file_uploader` multi-file (xlsx, csv, txt).
2. **Classifica**: per ogni file, i detector di `ingest/classify.py` propongono
   source + società; l'utente conferma o corregge (select dai source del registry).
   File non riconosciuto → messaggio esplicito ("source non nel registry — va definito
   prima, vedi skill hotelops-ingest"); la pagina NON crea source nuovi.
3. **Intake**: registra il raw_object (upload GCS + `f_raw_objects`), mostra
   `raw_object_id`. Raw-only, coerente con la decisione 2026-06-07.
4. **Promote**: bottone esplicito per raw_object; esito visibile, incluso
   `VALIDATE_FAIL` con l'errore in chiaro (mai fallimenti silenziosi — oggi un
   VALIDATE_FAIL si scopre solo interrogando gli eventi).
5. **Inbox**: tabella da `v_raw_objects_current` degli oggetti recenti non-PROMOTED
   (RAW_ONLY / CLASSIFIED / PROMOTABLE / REJECTED) — la coda di lavoro dell'ingestione.

In fase 2 questa pagina è admin-only per costruzione (è scrittura).

## Pagina Reviews

Riusa `verticals/reviews/app.py` (185 righe): estrazione di una `render()` importabile con
lo stesso contratto di `fb_dashboard`, montata da `reviews.py`.

## Donatori e destino delle app esistenti

- `app_cdg.py`: dona query e grafici tesoreria alla pagina Cassa; non viene montato.
- `audit_consumi_dashboard.py`: resta com'è (superficie direzione).
- `app_scadenzario.py`: resta dov'è; la sezione chiusura mese verrà assorbita da
  `actions.py` in fase 2.

## Error handling

- BQ irraggiungibile / query fallita → la pagina dichiara "dati non disponibili" con
  l'ultimo timestamp noto. Mai cache silente.
- Query con `st.cache_data` TTL 5 minuti + bottone refresh esplicito.
- Generazione richiesta nel confronto inesistente → messaggio chiaro, non griglia vuota.

## Test

- `pf_mirror.py`: pivot, delta tra generazioni, shadowing — unit test puri.
- `freshness.py`: soglie staleness (riusa/estende i test di `hotelops health`).
- Pagine: smoke `streamlit run verticals/hub/app.py` (avvio pulito, niente eccezioni
  import-time). Le pagine sottili non hanno logica da testare.
- Contratto `fb_dashboard.render()`: test di importabilità (coordinamento worktree fb-looker).

## Ordine di esecuzione

1. Spec gemella PF generazionale (migrazione + smoke + seed) — commit atomici propri.
2. Hub: scaffold + home + freshness.
3. `pf_mirror.py` + pagina Cassa (specchio, poi confronto A, poi badge shadowing).
4. Pagine fb.py / reviews.py (quando `fb_dashboard.render()` atterra su main).
5. Fase 2 (separata): actions.py + registry ruoli + deploy Cloud Run/IAP.
