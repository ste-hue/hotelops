# Cashflow Vertical (hub app) — design spec

**Date:** 2026-06-18 · **Status:** design (awaiting review) · **Branch:** `feat/cash-pf-engine`
**Slice:** unified Cashflow app surface su motore `pf-rotate` canonico + run-log BQ

## Scope

Un **vertical "Cashflow"** montato nel hub: guscio Streamlit sottile che wrappa il motore
canonico `pf_rotate.rotate()` (rotation mensile completa del Piano Finanziario), così che
l'amministrazione generi il PF del mese successivo senza CLI e senza spuntare a mano fornitore
per fornitore. Ogni run viene loggato su BigQuery per una **memoria storica mese×mese**
(previsione di cassa). **Stateless**: PF + scadenziario + saldi si caricano a ogni run.

Il cash flow qui è una **previsione di cassa** (quanto dovremo pagare), non lo storico
contabile (quello vive in Esolver). Lo **scaduto rotola avanti** (non pagato → mese successivo);
lo scadenziario porta i **buckets per mese di pagamento** → lavorando maggio si vede il
progressivo forward giugno/luglio/…

Questa slice è la **surface di "Metà B"** del cash-pf-engine (memory layer), nella forma
minima compatibile con l'MVP stateless: niente authority BQ della proiezione, solo run-log.

### Verifica Fase 0 (già fatta, 2026-06-18) — motivazione
Verifica read-only su file reali aprile→maggio: il motore **funziona, i numeri tornano**.
- Saldo cutover ORTI = €332.611,44 = MPS €245.171,52 (certificato 30/04) + Intesa €87.439,92.
- Roll-forward scaduto + buckets forward (mag→ago/set) corretti (ORTI −573k, INTUR −887k aperto).
- 22/23 controlli OK; l'unico "ERRORE" è un **falso positivo** del controllo catena
  (non esenta la colonna-cutover che per design ospita il saldo iniziale hardcoded).
- Sbavature solo in controlli/presentazione, non nei calcoli. → vedi §4 e Follow-up.

## Esplicitamente fuori da questa slice (MVP)
- **Statefulness / auto-load** dell'ultimo PF dalla memoria (Fase 3 piena). Solo run-log.
- **Editing in-UI del CSV fornitori** per i non mappati (Fase 4). Si surfacano e basta.
- **Storage GCS** dell'xlsx generato (solo download nell'MVP).
- **Card vetrina** (Cloudflare `publish/`) che linka la pagina hub → giro successivo.
- **BQ authority** della proiezione / xlsx puro render (Metà B completa).
- Fix del **doppio conteggio** controlli (CLI gen-time vs formule in-foglio) e delle
  **label-mese stale** dell'header → follow-up annotati, non bloccanti.

---

## 1. Architettura: Surface → Engine → Kernel/BQ

```
SURFACE (sottile — UI/IO + intent, MAI scrittura canonical né build xlsx)
  verticals/condges/app_cashflow.py   (NEW)  — espone render()
        │  raccoglie input, mostra controlli/risultati, offre download
        ▼
ENGINE / RENDER (esistente, invariato internamente)
  verticals/condges/pf_rotate/rotate.py::rotate()   — rotation CANONICA completa
  verticals/condges/scadenze_parse.py::parse_scadenze()
  verticals/condges/pf_rotate/step1_saldi.py::fetch_saldi_da_bq()
        │
        ▼
KERNEL / BQ
  cash_pf_service.log_cash_projection_run()  (NEW) → f_cash_projection_runs  via gate I1
  (fetch_saldi_da_bq legge f_saldi_banca_chiusura_mensile — anchor saldi)

HUB MOUNT
  verticals/hub/pages_/cashflow.py  (NEW) — render() → app_cashflow.render()
  verticals/hub/app.py              — st.Page(cashflow.render, title="Cashflow",
                                      icon="💸", url_path="cashflow")
  (card vetrina → giro successivo, fuori MVP)
```

**Regole del confine:**
- La surface legge, mostra, raccoglie intent. Non scrive canonical, non costruisce SQL/xlsx.
- L'unico write BQ della slice è `cash_pf_service.log_cash_projection_run` → `bq_write_validated`.
- `rotate()` e gli step restano invariati internamente; cambia solo **chi lo chiama** (la surface)
  + il fix mirato a `step5_controlli` (§4).

## 2. Flusso UI (stateless)

`app_cashflow.render()` (Streamlit, nessun `streamlit run` proprio: montato dal hub):

1. **Società** ORTI/INTUR.
2. **Upload PF** (xlsx) del mese da chiudere.
3. **Upload scadenziario** (Esolver "Situazione partite", `--scad-tipo sintetica`).
4. **Mese-chiuso** (default dedotto da PF/data; override manuale).
5. **Saldi banca**: pre-compilati da `fetch_saldi_da_bq(societa, data_saldo)` al cutover,
   **editabili** (override manuale per banca).
6. **Fornitori non mappati**: lista esplicita + scelta policy — **default `skip`** (procede
   con warning, non blocca l'amministrazione) / `fail` (blocca). *(In-UI CSV editing → Fase 4.)*
7. **Genera** → `rotate(...)`. Mostra:
   - esito **controlli** (OK/ERR/INDET) — con dettaglio degli ERR (post-fix §4);
   - **scaduto** roll-forward (totale in primo mese aperto);
   - **progressivo forward per mese** (buckets mag→…);
   - **saldo proiettato** per mese.
8. **Download** del nuovo PF (`<societa>_PF_<YYYY-MM>_post-rotate_<ts>.xlsx`).
9. **Run loggato** su BQ (§3).

## 3. Memoria = run-log BQ (`f_cash_projection_runs`)

Nuovo modello Pydantic `CashProjectionRunRow` (`core/schemas.py`) + nuova tabella + config id.
Una riga per `(societa_id, anno, mese_chiuso)`, **snapshot** idempotente.

```
CashProjectionRunRow:
  societa_id: SocietaId
  anno: int
  mese_chiuso: int                  # 1..12
  data_saldo: str                   # ISO date del cutover
  saldo_cutover: float              # totale banche al cutover
  scaduto_totale: float             # roll-forward (negativo = debito)
  totale_partite_aperte: float
  forward_buckets_json: str         # JSON {mese: importo}
  saldo_proiettato_finale: float | None
  n_controlli_ok: int
  n_controlli_err: int
  n_controlli_indet: int
  fonte: str = "APP_CASHFLOW"
  data_caricamento: str             # ISO timestamp
  raw_object_id: str | None = None
```

`cash_pf_service.log_cash_projection_run(intent) -> SaveResult`:
- costruisce 1 `CashProjectionRunRow`,
- `bq_write_validated(F_CASH_PROJECTION_RUNS, [row], mode="snapshot",
  natural_key=["societa_id","anno","mese_chiuso"])`.

Abilita la **vista storica mese×mese** (previsione vs realtà) come incremento successivo
(una `v_cash_projection_history` o pannello nell'app) senza statefulness.

## 4. Controlli — mostrati as-is (NO fix in questa slice)

L'app **mostra i controlli così come li riporta `rotate()`** (`RotateResult.n_controlli_ok/
err/indet`), con una nota che l'eventuale ERR su ORTI è **sotto investigazione separata**.

**Correzione di rotta (2026-06-18):** la diagnosi Fase-0 ("il controllo non esenta la
colonna-cutover") era **incompleta**. `_check_C3_cascade_chain` **già esclude** il cutover
(`tail_cols = col_letters[cutover_idx+1:]`). Il vero problema è una **discrepanza**: il
controllo rileva cutover = colonna I e verifica la catena J:R, ma il **saldo hardcoded
(332.611) sta in J** = `tail_cols[0]`, una colonna *dopo* il cutover. O il saldo-writer
scrive sulla colonna sbagliata (off-by-one), o writer e controllo non concordano sul cutover.
Serve un mini-debug, non un fix a sentimento.

**Fuori da questa slice** → task separato (`systematic-debugging`):
- discrepanza colonna-saldo (J) vs cutover-detection (I) in `step5_controlli`/saldo-writer;
- riconciliare il **conteggio** CLI (`RotateResult` gen-time) vs controlli live in-foglio
  (13/0/7 vs 22/1/0);
- label-mese **stale** dell'header (template GEN..APR; cutover reale in `J31`).

## 5. Deprecazioni

- `verticals/condges/app_scadenzario.py` (path **parziale** divergente: scrive scadenze nel
  PF senza azzerare il mese chiuso né i controlli) → **banner di deprecazione** che punta a
  `app_cashflow`; rimozione del wiring se presente. **File non cancellato.**
- `verticals/condges/tesoreria.py` + `cmd_tesoreria` (CLI) → banner deprecazione → hub
  Cashflow. **Non rimosso** finché Stefano non decide post-merge.

Razionale CLAUDE.md: dead code correlato si **segnala**, non si cancella nello stesso giro.

## 6. Error handling

- `SaldiIncompletiError` (saldi mancanti) → UI mostra quali banche mancano, l'utente li
  compila a mano; nessun run loggato finché non si genera con successo.
- Fornitori non mappati con policy `fail` → blocco con lista; con `skip` → warning + procede.
- Errore parsing scadenziario → messaggio chiaro, nessun run.
- Eccezioni `rotate()` → surfacate in UI, **niente run-log** (si logga solo un run riuscito).
- Controlli con ERR reali → mostrati in evidenza; il download resta possibile (decisione
  amministrativa), ma con avviso.

## 7. Test / golden path

- **`tests/test_cash_pf_service.py`** (append): `log_cash_projection_run` chiama il gate con
  (a) `CashProjectionRunRow` validato, (b) `mode="snapshot"`,
  (c) `natural_key=["societa_id","anno","mese_chiuso"]`. Gate mockato, assert su args.
- **Smoke headless**: `rotate()` su ORTI+INTUR aprile→maggio (file reali) → genera output,
  **0 ERR reali**, `log_cash_projection_run` chiamato (gate mockato).
- `render()` non unit-testato (Streamlit) → smoke import/parse di `app_cashflow.py` +
  `pages_/cashflow.py`.
- `pf_rotate` esistenti invariati.

**Definition of done della slice:**
- App `Cashflow` montata nel hub (pagina + nav); gira `render()`. (Card vetrina fuori MVP.)
- Genera il PF del mese successivo via `rotate()` canonico (upload PF+scadenziario, saldi
  pre-fill BQ editabili, scelta policy fornitori), con download.
- Ogni run riuscito logga `f_cash_projection_runs` via gate I1 (snapshot idempotente).
- L'app mostra i controlli come riportati da `rotate()` (no fix `step5` in questa slice).
- `app_scadenzario`/`tesoreria` deprecati (banner), non cancellati.
- `pytest -q` e `ruff check` verdi sui file della slice.

## Related
- Slice precedente (stesso branch): `2026-06-09-cash-pf-engine-consolidation-design.md`
  (write-path budget/previsione dietro `cash_pf_service` + gate I1). Questa slice estende
  il service con `log_cash_projection_run`.
- Engine: `verticals/condges/pf_rotate/` (rotate, step1_saldi, step3_scadenzario,
  step5_controlli), `scadenze_parse.py`.
- Gate I1: `core/bq/write.py::bq_write_validated`. Anchor saldi:
  `f_saldi_banca_chiusura_mensile`.
- Hub mount pattern: `verticals/hub/pages_/spiaggia.py` + `verticals/hub/app.py`.
- Metà B (next increment): authority BQ della proiezione, vista storica mese×mese,
  statefulness/auto-load, supplier-mapping UX in-UI, storage GCS.
