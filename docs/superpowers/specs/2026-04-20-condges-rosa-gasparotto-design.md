# Condges Rosa→Gasparotto Integration — Design Spec

**Date:** 2026-04-20
**Status:** Draft
**Scope:** Aggiornare l'ingest Gasparotto al nuovo file `gasparotto_Budget_Indici2025.xlsx`, chiudere il loop di alimentazione Rosa→Condges, e riallineare `app_cdg.py` alla struttura del workbook Gasparotto.
**Base:** `ingest/flussi/ingest_gasparotto.py`, `condges/app_cdg.py`, `condges/genera_excel.py`, `condges/app_scadenzario.py`

## Terminologia (canonical)

**condges = gasparotto**. La vista strategica completa (Stato Patrimoniale, Rating, Vendite, Conto Economico, Budget, Cash-Flow, Indicatori) è il vertical condges. L'app `condges/app_cdg.py` È l'app gasparotto.

**Rosa = subset operativo di condges**. Rosa gestisce il canale di dati supplier-level (scadenzario fornitori → proiezione cassa). I suoi output (`f_piano_finanziario_input`) alimentano il tab Cash-Flow di condges. Rosa non è un peer di Gasparotto: è uno degli input channel di condges.

| Layer | Owner | Tool | BQ target |
|---|---|---|---|
| Data-entry supplier-level | Rosa (amministrazione) | `app_scadenzario.py` + `update_previsione.py` | `f_piano_finanziario_input` |
| Strategic reporting | Gasparotto (condges) | `app_cdg.py` | legge da tutti i `f_*` |
| Budget annuale COMPETENZA | Gasparotto | `ingest_gasparotto.py` | `f_budget_mensile` (fonte=GASPAROTTO) |
| Rendering Excel | entrambi | `genera_excel.py` | Rosa.xlsx (subset) + Gasparotto.xlsx (full) |

## Purpose

Chiudere il ciclo Rosa→Condges in modo automatico:
1. Rosa aggiorna scadenziario mensile via `app_scadenzario` → scrive `f_piano_finanziario_input`
2. Condges legge live `f_piano_finanziario_input` nel tab Cash-Flow
3. Al bisogno, il workbook Gasparotto viene **rigenerato da BQ** — il suo sheet `Cash - Flow` diventa uno export automatico, non più copia-incolla manuale

Eliminare l'ingest del nuovo file Gasparotto 2025/26: il parser `ingest_gasparotto.py` va adattato al nuovo layout di `gasparotto_Budget_Indici2025.xlsx` (sheet `Budget` only).

## What Exists

### Ingest
- `ingest/flussi/ingest_gasparotto.py` (651 LOC): parser Budget sheet → `f_budget_mensile` fonte=GASPAROTTO. Header R10, MANUAL_COD_MAP con ~60 mapping descrizione→codice_conto. DELETE-INSERT per `(anno, fonte)`.
- `DEFAULT_FILE` hardcoded all'old path: `Master Completo Indici 2025 ORTI SRL_Budget26_AGG 17.03.xlsx`.

### App
- `condges/app_cdg.py` (1265 LOC, 4 tab): **CE, Budget, Tesoreria, Indicatori**. Tesoreria oggi mostra saldo banca proiettato.
- `condges/app_scadenzario.py` (694 LOC): Rosa tool, flusso scadenzario Esolver → PF.
- `condges/cdg_engine.py` (137 LOC): compute_ce_cascade, compute_indicatori.
- `condges/genera_excel.py`: genera Rosa.xlsx da `f_piano_finanziario_input`.
- `condges/update_previsione.py`: DELETE-INSERT parametrizzato su `f_piano_finanziario_input`.

### BQ source of truth
- `f_piano_finanziario_input`: 28 voci × mese × fonte. Unica fonte di verità CASSA.
- `f_budget_mensile`: codice_conto × mese × fonte. Fonte di verità COMPETENZA.
- `d_voci_piano_finanziario`: il bridge (voce_id ↔ codice_conto via LIKE pattern).

## Architecture

```
 ┌──────────────────────────────────────────────────────────┐
 │  DATA-ENTRY (Rosa subset)                                │
 │    Esolver scadenziario → app_scadenzario → f_fornitori  │
 │                                                           │
 │    Stefano/Rosa CLI → update_previsione.py               │
 └────────────────────────┬─────────────────────────────────┘
                          │ writes
                          ▼
 ┌──────────────────────────────────────────────────────────┐
 │  BQ CANONICAL LAYER                                       │
 │    f_piano_finanziario_input  ◄─ CASSA (Rosa's output)   │
 │    f_budget_mensile            ◄─ COMPETENZA (Gasparotto) │
 │    f_movimenti_contabili       ◄─ Esolver prima nota     │
 │    f_accodamenti, f_saldi_banca_snapshot, ...           │
 └────────────────────────┬─────────────────────────────────┘
                          │ reads
                          ▼
 ┌──────────────────────────────────────────────────────────┐
 │  CONDGES (= Gasparotto) REPORTING                        │
 │    app_cdg.py   : 4 tab attuali, evoluzione possibile    │
 │    genera_excel : ORTI Financial Plan.xlsx (Rosa subset) │
 │                 + Gasparotto.xlsx Cash-Flow sheet (new)  │
 └──────────────────────────────────────────────────────────┘
```

**Invariante I9 (nuova)**: `f_piano_finanziario_input` è l'unica fonte di verità per il cashflow CASSA. Ogni rendering (Rosa.xlsx, Gasparotto.xlsx Cash-Flow sheet, app_cdg tab Cash-Flow) è derivato. Nessun ingest reverse dei rendering.

### Context lock — ciclo di vita Rosa.xlsx

Rosa.xlsx è uno **snapshot mensile atomico**, non un documento vivo:

- Il 1° di ogni mese, Rosa (amministrazione) genera un nuovo file partendo da:
  - **Saldi banca end-of-previous-month** (snapshot chiuso)
  - **Scadenziario fornitori** (sintetica Esolver del mese)
- Il file NON evolve durante il mese: è un'istantanea chiusa del previsionale del mese di riferimento.
- Ogni ingest/update durante il mese scrive su BQ su chiave `(societa_id, anno, mese, voce_id, fonte)` con DELETE-INSERT — quindi sovrascrive ma non storicizza: la storicizzazione avviene per `fonte` (PIANO_FINANZIARIO = snapshot 1° del mese, SCADENZIARIO = run-time da app Rosa, APP = edit da app_cdg).
- Implicazione per WI-2 e WI-3: il tab Cash-Flow e il workbook rigenerato mostrano **stato corrente BQ**, non il "file Rosa di Aprile". Se serve il "Rosa di Aprile" come allegato, lo si esporta via `genera_excel --target rosa --mese 4` dopo il congelamento di fine mese.

## Scope (4 work items)

### WI-1 — Ingest adapter al nuovo file Gasparotto

**File:** `ingest/flussi/ingest_gasparotto.py`

**Cambio di target sheet.** Il sheet `Budget` in `gasparotto_Budget_Indici2025.xlsx` è **interamente formula-driven**: col B = `='Conto Economico'!B10`, col C = `='Conto Economico'!K10`, ecc. Conseguenza:
- `openpyxl(data_only=False)` → ritorna le stringhe-formula, inutile.
- `openpyxl(data_only=True)` → ritorna cached values che sono `None` se il workbook non è stato aperto/salvato da Excel con ricalcolo forzato. Pipeline non può dipendere da un human-in-the-loop.

**Decisione:** il parser legge **direttamente** il sheet `Conto Economico`, che è il ground truth:
- col A = `cod_conto`
- col B = descrizione
- col L = valore 2025
- col F = tipo

**Gestione cod_conto corrotti (timedelta).** Alcune celle col A sono state interpretate da Excel come date/delta (bug noto: es. `"47.91.02"` → `datetime.timedelta(days=2, seconds=1860)` per R11, R18, R20). Il parser DEVE:
1. Detectare `isinstance(cell.value, timedelta)` e tentare reverse-engineering da `(days, seconds)` → ricostruire la tripla dotted `XX.YY.ZZ` (days → secondo token, hours/minutes → terzo token).
2. Se reverse-engineering fallisce: fuzzy match su descrizione (col B) contro `d_piano_conti.descrizione` (ratio > 0.85).
3. Se anche il fuzzy fallisce: errore hard, NON silent drop.

**Altri cambi:**
- Aggiornare `DEFAULT_FILE` al nuovo path standardizzato in Drive.
- MANUAL_COD_MAP si riduce a ~5 mapping (solo intestazioni di sezione non-foglia che non hanno cod_conto neanche su `Conto Economico`).
- No tocco al sheet `Cash - Flow`: **non ingerire** (I9).

**Deliverable & gate:** dry-run produce `output/f_budget_gasparotto.csv` con:
- **0 UNMAPPED**
- **0 righe skipped per cod_conto corrotto** (tutte le timedelta risolte o erroriate, mai silenziate)
- Totale costi/ricavi coerente con R11–R40 del workbook Excel aperto con ricalcolo.

### WI-2 — Tab Cash-Flow live in app_cdg

**File:** `condges/app_cdg.py` (riscrivere `page_tesoreria` → `page_cashflow`)

- Rinominare tab `Tesoreria` → `Cash-Flow` per allineamento vocabolario workbook.
- Sostituire la query principale: da `f_saldi_banca_snapshot` aggregato a lettura diretta di `v_piano_finanziario_mensile` (28 voci × 12 mesi).
- Layout 1:1 col sheet `Cash - Flow` del workbook Gasparotto:
  - Sezione 1: SALDO BANCA (mese corrente + 11 successivi)
  - Sezione 2: ENTRATE (Hotel, Residence, CVM, Supermercato, Rientro Sospesi, Caparre)
  - Sezione 3: TOTALE ENTRATE
  - Sezione 4: USCITE (28 voci grouped per macro-categoria)
  - Sezione 5: TOTALE USCITE
  - Sezione 6: Cash Flow netto + Saldo finale
- Visualizzazione: fonte-badge per ogni riga (PIANO_FINANZIARIO / SCADENZIARIO / APP / BVA_2026) + link "modifica" che apre modal `update_previsione`.

**Granularità — voce-level, non supplier-level.** Il tab Cash-Flow in app_cdg resta a **livello voce** (28 voci aggregate). La granularità supplier-level di Rosa NON viene replicata nell'app: è una divergenza accettata rispetto al workbook Gasparotto per le voci operative (Salari, Fornitori, Utenze, etc.). Chi vuole supplier-drill-down va su `app_scadenzario.py`. Questo mantiene i due strati — strategic (condges) vs operational (Rosa) — disaccoppiati.

**Forward-compatibility `fonte=PROGETTI`.** Il badge fonte deve gestire le fonti attuali (`PIANO_FINANZIARIO`, `SCADENZIARIO`, `APP`, `BVA_2026`, `CLI`) e predisporre un caso per `PROGETTI` (cantieri) che arriverà dal vertical Projects — tracciato nel forward-flow della sessione `2026-04-20-projects-mvp-design.md`. Implementazione: leggere la lista fonti dinamicamente da `SELECT DISTINCT fonte FROM f_piano_finanziario_input` invece di hardcodare l'enum.

**Deliverable:** tab Cash-Flow che mostra esattamente lo stesso layout del sheet omonimo nel workbook Gasparotto, ma live da BQ.

### WI-3 — Estensione genera_excel per workbook Gasparotto

**File:** `condges/genera_excel.py` (aggiungere modulo/funzione)

- Nuovo CLI flag `--target gasparotto` (default resta `rosa`).
- Funzione `rigenera_cashflow_sheet_gasparotto(workbook_path, societa, anno)`:
  - Apre workbook Gasparotto in-place (preserve Budget, CE, SP, Rating, Vendite, Indicatori sheet).
  - Sostituisce righe del sheet `Cash - Flow` (R4–R45 circa) con valori da `v_piano_finanziario_mensile`.
  - Preserva formule esistenti (saldo, totali) se presenti.
  - Salva con suffix `_aggiornato_YYYYMMDD.xlsx`.
- CLI: `python -m condges.genera_excel --target gasparotto --input ~/Downloads/gasparotto_Budget_Indici2025.xlsx`

**Rischio formule obsolete + mitigazione.** Il workbook Gasparotto ha ~9000 formule, ~48 defined names, macro VBA (nessun chart/pivot — verificato, quindi openpyxl-survivable). Dopo `wb.save()`, openpyxl invalida i cached values di tutte le celle formulate: totali come `C94=C7+C28+C92` e saldi-chaining cross-month (`SaldoMar = SaldoFeb + CashMar`) restano con valori obsoleti finché qualcuno non apre il file in Excel.

Due opzioni, da scegliere e documentare in implementazione:
- **Opzione A (preservare dinamica Excel):** dopo `wb.save()`, invocare `libreoffice --headless --calc --convert-to xlsx --outdir <tmp> <file>` per forzare il ricalcolo. Richiede LibreOffice installato sulla macchina che rigenera (aggiungere check in CLI + messaggio di setup). Preserva tutte le formule.
- **Opzione B (scrivere i totali come valori):** computare in Python i totali di riga/colonna e scriverli come numeri plain. Si perde la dinamica "edita una cella → totale si aggiorna", ma il file è auto-contenuto e riproducibile ovunque.

**Raccomandazione:** Opzione A per v1 (LibreOffice è già presente su macOS del team via brew). Fallback documentato a Opzione B se LibreOffice non disponibile — il CLI deve detectare e scegliere, loggando la decisione.

**Deliverable:** comando che prende il workbook Gasparotto attuale, aggiorna il Cash-Flow sheet da BQ, produce una copia datata con totali ricalcolati (Opzione A o B).

### WI-4 — Documentazione invariante + vault

**File:** `<vault>/hotelops/INVARIANTS.md`

- Aggiungere invariante I9 (testo sopra).
- Aggiungere glossario: condges = gasparotto, Rosa = subset operativo data-entry.
- Aggiungere nota in `CLAUDE.md` (overview architettura) a chiarire la gerarchia.

## Non-goals (scope-cut)

Questi non fanno parte di questo spec. Vivono in spec successivi se prioritizzati:

- **Nuovi tab** in `app_cdg.py` (Stato Patrimoniale, Rating, Vendite, Investimenti). Il workbook li ha, l'app per ora no. Fase 2.
- **Ingest del Cash-Flow sheet** del workbook Gasparotto. Esplicitamente escluso da I9.
- **Reconciliation tile** CASSA vs COMPETENZA nel dashboard. Idea buona ma fuori scope qui.
- **Merge scadenzario→gasparotto unified app**. Rosa resta in `app_scadenzario.py` separata.

## Data integrity

| Rischio | Mitigazione |
|---|---|
| Workbook Gasparotto stale (Rosa aggiorna, copia manuale no) | WI-3 automatizza il refresh; aggiungere timestamp nel sheet |
| Doppia scrittura in `f_piano_finanziario_input` su stesso `(voce,mese,fonte)` | Già gestito: update_previsione fa DELETE-INSERT per `(societa,anno,mese,voce_id,fonte)` |
| Nuova voce in `d_voci_piano_finanziario` non rispecchiata nel Cash-Flow sheet | WI-3 legge le voci da BQ, non hardcoded |
| Budget annuale (COMPETENZA) incongruente con Σ annuo CASSA | Non bloccante; logged warning in WI-3 se delta > 10% |
| `ingest_gasparotto` UNMAPPED rows o cod_conto corrotti silently dropped | WI-1 impone gate duplice: 0 UNMAPPED + 0 skipped timedelta; fuzzy-match fallback su descrizione |

## Testing

- **WI-1:** rigenerare `tests/test_ingest_gasparotto.py` (se esiste, altrimenti crearlo) con fixture del nuovo file. Assert: conti_unique >= 60, totale ricavi > 0, 0 UNMAPPED.
- **WI-2:** test Streamlit (solo smoke): `streamlit run condges/app_cdg.py` boota, tab Cash-Flow si carica, query su `v_piano_finanziario_mensile` restituisce righe.
- **WI-3:** unit test su `rigenera_cashflow_sheet_gasparotto` con fixture workbook; assert cell values match BQ query result; assert altri sheet invariati (hash o row count).
- **WI-4:** N/A (doc only).

## Open Questions

1. ~~Il Cash-Flow sheet di Gasparotto va ingerito?~~ **Risolta**: no (I9).
2. ~~condges = Rosa + Gasparotto o condges = Gasparotto?~~ **Risolta**: condges = gasparotto, Rosa subset.
3. Nel WI-2, le "entrate" nel layout Gasparotto sono 4 voci (Hotel/Residence/CVM/Supermercato) mentre `d_voci_piano_finanziario` ha 11 voci entrata. Come gestire le voci extra (es. Caparre, Affitti)? **Proposta**: mostrare tutte, raggruppate per macro-sezione Hotel/Residence/CVM/Supermercato/Altre.
4. ~~WI-3 preserve-formula~~ **Risolta** nel blocco WI-3: Opzione A (LibreOffice headless recalc) preferita, Opzione B (scrivere totali come valori) fallback.
5. Timing di deploy: WI-1 indipendente, WI-2/WI-3 possono essere parallelizzati, WI-4 dopo. Sequenza suggerita: WI-1 → WI-2 → WI-3 → WI-4.

## Rollout

1. **Giorno 1** — WI-1 ingest adapter + test
2. **Giorno 2-3** — WI-2 tab Cash-Flow refactor
3. **Giorno 3-4** — WI-3 gasparotto excel regenerator
4. **Giorno 4** — WI-4 doc + invariant
5. Smoke run: Rosa aggiorna scadenzario → app_cdg tab Cash-Flow rispecchia → `hotelops gasparotto regenera` produce Excel aggiornato.
