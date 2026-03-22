# CHANGELOG

## 2026-03-21 (sessione 2 — App PF)

### Added
- `dashboard/app_piano_finanziario.py` — App Streamlit Piano Finanziario per Rosa.
  Funzionalità: saldo banca anchor, griglia entrate/uscite editabile (consuntivo read-only, previsione editabile), cash flow + saldo proiettato con semaforo 🟢🟡🔴, drill-down scadenzario per voce uscita con dettaglio fornitori lazy-loaded, save in BQ (DELETE-INSERT con fonte='APP', logica APP=new-budget_costi), export Excel.
  Avvio: `streamlit run dashboard/app_piano_finanziario.py`

---

## 2026-03-21 (sessione 1 — igiene + fondamenta)

### Fixed
- `pipelines/banca/ingest.py`: SELLA routing bug — file `.xls` riconvertiti a `xlsx` dal content-detector cadevano nel parser MPS sbagliato. Ora `"SELLA" in sb` è guardia esterna indipendente dall'ext.
- `pipelines/banca/ingest.py`: `upsert_saldo_snapshot` fallback schema allineato alla tabella reale (4 campi, rimossi `file_sorgente` e `data_caricamento`).

### Changed
- `pyproject.toml`: `bank-reconcile` spostato da `dependencies` a `optional-dependencies.reconcile`. `pip install -e .` ora funziona senza il pacchetto privato.
- `lib/config.py`: creato — costanti PROJECT/DATASET + tutti i table ID come `F_*`, `D_*`, `V_*`.
- `validate_batch()` attivato nei 4 punti di scrittura BQ mancanti: `cli.py` (f_chiusura_mensile), `update_previsione.py` (f_piano_finanziario_input), `ingest_gasparotto.py` (f_budget_mensile), `ingest.py` banca (f_banche_movimenti). `ingest_partite_aperte.py` era già corretto.
- `CLAUDE.md`: rimossi row count, "Current status", "Pending work". Lo stato lo dà `hotelops health`.

### Removed
- `pipelines/notion/` → `_archive/`
- `ontology/` → `_archive/`
- `services/` → `_archive/`
- `tools/` → `_archive/`
- `dashboard/` → `_archive/`
- `run_all.sh` — sostituito dall'orchestratore `pipelines/orchestrate.py`
- `bq/v_budget_vs_consuntivo.sql` — duplicato della versione canonica in `bq/views/`
