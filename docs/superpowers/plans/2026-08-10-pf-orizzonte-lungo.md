# PF Orizzonte Lungo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Il motore pf-rotate impara a distinguere gli anni (chiave periodo ordinale) e i master PF si estendono fino a giugno 2027, con rito annuale estendi+pota.

**Architecture:** La chiave mese `int 1-12` diventa `periodo = anno*12 + (mese-1)` (resta `int`, firme quasi invariate) lungo tutta la catena parse→rotate→write. L'anno di ogni colonna si deduce dalla riga-1 del foglio + wrap dic→gen. Un nuovo modulo `extend.py` allunga il template copiando il pattern dell'ultima colonna-mese con traduzione formule; `--trim-before` pota il passato ri-ancorando la prima colonna superstite.

**Tech Stack:** Python 3.11+, openpyxl (incl. `openpyxl.formula.translate.Translator`), pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-08-10-pf-orizzonte-lungo-design.md`

## Global Constraints

- **Mai mutare l'input**: ogni operazione su xlsx produce un file/bytes nuovo.
- **Mai toccare formule con riferimenti** in azzera/scritture (`is_value_cell` decide).
- **Niente `date.today()` come ancora di bucketing** (decisione 2026-06-12): l'ancora è sempre un oggetto di dominio passato esplicitamente.
- **Nessuna scrittura BQ** in questo piano (il PF è proiezione).
- **Convenzione importi**: debiti NEGATIVI / note credito POSITIVE (da `parse_scadenze`).
- Lavoro nel worktree `pf-orizzonte-lungo`; branch `worktree-pf-orizzonte-lungo`.
- Test: `python -m pytest` dalla ROOT del worktree (il modulo `verticals` si risolve dalla cwd — MAI `pip install -e` nel worktree).
- Lint: `ruff check .` pulito su ogni file toccato prima del commit.

---

### Task 0: Rebase su main (gate PR #121)

La base attuale (`626bef7`) non contiene il gate `HashCollisionError` di PR #121.

**Files:** nessuno (solo git).

- [ ] **Step 1: Fetch + rebase**

```bash
git fetch origin main
git rebase origin/main
```

Se il rebase segnala conflitti su `core/bq/write.py` o `tests/test_bq_write.py`: fermati e chiedi (non risolvere a mano — quel file è di PR #121).

- [ ] **Step 2: Verifica che il gate ci sia**

```bash
grep -c "HashCollisionError" core/bq/write.py
```
Expected: ≥ 1 (se 0, PR #121 non è ancora su main: annota e prosegui comunque — il piano non tocca `core/bq/write.py`).

- [ ] **Step 3: Baseline test**

```bash
python -m pytest -q 2>&1 | tail -2
```
Expected: tutti verdi (1237 se #121 non è in main, 1240 se c'è). Annota il numero: è la baseline.

---

### Task 1: Helpers periodo + guardia in `excel_model`

**Files:**
- Modify: `verticals/condges/pf_rotate/excel_model.py` (in testa, dopo `MESI_IT`)
- Test: `tests/test_pf_rotate_excel_model.py` (append)

**Interfaces:**
- Produces: `periodo(anno: int, mese: int) -> int` · `periodo_anno_mese(p: int) -> tuple[int, int]` · `require_periodo(p: int, nome: str = "periodo") -> None` · costante `PERIODO_MIN = 2000 * 12`. Tutti i task successivi li importano da `excel_model`.

- [ ] **Step 1: Write failing tests**

```python
# append a tests/test_pf_rotate_excel_model.py
import pytest
from verticals.condges.pf_rotate.excel_model import (
    periodo, periodo_anno_mese, require_periodo,
)


def test_periodo_roundtrip():
    p = periodo(2026, 6)
    assert p == 2026 * 12 + 5
    assert periodo_anno_mese(p) == (2026, 6)


def test_periodo_successivo_attraversa_l_anno():
    assert periodo(2026, 12) + 1 == periodo(2027, 1)


def test_require_periodo_rifiuta_mese_nudo():
    with pytest.raises(ValueError, match="mese nudo"):
        require_periodo(6)
    with pytest.raises(ValueError, match="mese nudo"):
        require_periodo(2026)  # anche un anno nudo è sospetto
    require_periodo(periodo(2026, 6))  # non solleva
```

- [ ] **Step 2: Run → FAIL** — `python -m pytest tests/test_pf_rotate_excel_model.py -q` → ImportError.

- [ ] **Step 3: Implement**

```python
# excel_model.py, dopo MESI_IT
PERIODO_MIN = 2000 * 12  # nessun periodo reale è sotto il 2000


def periodo(anno: int, mese: int) -> int:
    """Chiave periodo ordinale: gen 2026 e gen 2027 sono chiavi diverse."""
    return anno * 12 + (mese - 1)


def periodo_anno_mese(p: int) -> tuple[int, int]:
    anno, m0 = divmod(p, 12)
    return anno, m0 + 1


def require_periodo(p: int, nome: str = "periodo") -> None:
    """Guardia: periodo e mese nudo sono entrambi int — qui si separano."""
    if p < PERIODO_MIN:
        raise ValueError(
            f"{nome}={p} sembra un mese nudo (1-12) o un anno: serve un periodo "
            f"ordinale anno*12+(mese-1), es. periodo(2026, 6) = {2026 * 12 + 5}"
        )
```

- [ ] **Step 4: Run → PASS**, poi `ruff check verticals/condges/pf_rotate/excel_model.py`
- [ ] **Step 5: Commit** — `git add -- verticals/condges/pf_rotate/excel_model.py tests/test_pf_rotate_excel_model.py && git commit -m "feat(pf-rotate): chiave periodo ordinale — helpers + guardia"`

---

### Task 2: `find_month_periods` — colonne datate per anno

**Files:**
- Modify: `verticals/condges/pf_rotate/excel_model.py`
- Test: `tests/test_pf_rotate_excel_model.py` (append)

**Interfaces:**
- Produces: `find_month_periods(ws, header_row: int = 2, year_row: int = 1) -> dict[int, int]` (periodo → col_idx). Solleva `ValueError` se nessun anno dichiarato in `year_row`.
- La vecchia `find_month_columns` RESTA (per ora) reimplementata sopra la nuova — compat per i caller non ancora migrati; si cancella nel Task 6.

- [ ] **Step 1: Write failing tests**

```python
import openpyxl


def _ws_multi_anno():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["C1"] = 2026
    for i, nome in enumerate(
        ["APRILE", "MAGGIO", "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE",
         "OTTOBRE", "NOVEMBRE", "DICEMBRE", "GENNAIO", "FEBBRAIO", "MARZO",
         "APRILE", "MAGGIO", "GIUGNO"]
    ):
        ws.cell(2, 3 + i, nome)
    return ws


def test_find_month_periods_wrap_dic_gen():
    from verticals.condges.pf_rotate.excel_model import find_month_periods, periodo
    cols = find_month_periods(_ws_multi_anno())
    assert cols[periodo(2026, 4)] == 3
    assert cols[periodo(2026, 12)] == 11
    assert cols[periodo(2027, 1)] == 12   # wrap: DIC→GEN incrementa l'anno
    assert cols[periodo(2027, 4)] == 15   # APRILE 2027 ≠ APRILE 2026
    assert cols[periodo(2026, 4)] == 3    # ...che resta al suo posto
    assert len(cols) == 15


def test_find_month_periods_senza_anno_esplode():
    from verticals.condges.pf_rotate.excel_model import find_month_periods
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(2, 3, "APRILE")  # nessun anno in riga 1
    with pytest.raises(ValueError, match="[Aa]nno non dichiarato"):
        find_month_periods(ws)


def test_find_month_columns_compat_su_file_mono_anno():
    """La vecchia API resta identica sui file a un anno (i caller non migrati)."""
    from verticals.condges.pf_rotate.excel_model import find_month_columns
    ws = _ws_multi_anno()  # multi-anno: latest wins (comportamento storico)
    cols = find_month_columns(ws)
    assert cols[4] == 15  # APRILE: l'ultima colonna vince (storico documentato)
```

- [ ] **Step 2: Run → FAIL** (ImportError su `find_month_periods`).

- [ ] **Step 3: Implement**

```python
def find_month_periods(
    ws: Worksheet, header_row: int = 2, year_row: int = 1
) -> dict[int, int]:
    """Scan header_row per mesi ITA, datati per anno. Return {periodo: col_idx}.

    L'anno base è l'ultima cella numerica 1900<v<2100 in year_row fino alla
    prima colonna-mese inclusa (ORTI master: C1; fogli dettaglio: D1).
    L'anno incrementa a ogni wrap (numero mese che scende, es. DIC→GEN).
    Niente inferenze dall'orologio: senza anno dichiarato → ValueError.
    """
    months: list[tuple[int, int]] = []  # (col, mese 1-12) in ordine di colonna
    first_month_col: int | None = None
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if isinstance(v, str) and v.strip().upper() in MESI_IT:
            if first_month_col is None:
                first_month_col = c
            months.append((c, MESI_IT[v.strip().upper()]))
    if not months:
        return {}
    base_year: int | None = None
    for c in range(1, first_month_col + 1):
        v = ws.cell(year_row, c).value
        if isinstance(v, (int, float)) and 1900 < int(v) < 2100:
            base_year = int(v)
    if base_year is None:
        raise ValueError(
            f"Anno non dichiarato in riga {year_row} del foglio '{ws.title}': "
            "impossibile datare le colonne-mese."
        )
    result: dict[int, int] = {}
    year = base_year
    prev_mese: int | None = None
    for col, mese in months:
        if prev_mese is not None and mese < prev_mese:
            year += 1
        prev_mese = mese
        result[periodo(year, mese)] = col
    return result
```

E la vecchia diventa un wrapper (stesso comportamento storico "latest wins"):

```python
def find_month_columns(ws: Worksheet, header_row: int = 2) -> dict[int, int]:
    """DEPRECATA (compat transitoria): mese nudo → col. Latest col wins.

    Cancellare quando tutti i caller usano find_month_periods (Task 6).
    """
    out: dict[int, int] = {}
    for p, col in find_month_periods(ws, header_row=header_row).items():
        out[periodo_anno_mese(p)[1]] = col  # latest wins per costruzione (ordine col)
    return out
```

⚠️ La riscrittura di `find_month_columns` ora ESIGE l'anno in riga 1. I fixture
in `tests/conftest.py` lo hanno già (`pf["C1"] = 2026`, `ut["D1"] = 2026`,
INTUR `pf["D1"] = 2026`). Se qualche test costruisce fogli ad-hoc senza anno,
aggiungi `ws["A1"] = 2026` al fixture del test (l'anno è realtà dei file veri).

- [ ] **Step 4: Run TUTTA la suite** — `python -m pytest -q` → stessi verdi della baseline. I test che si rompono per "Anno non dichiarato" si sistemano aggiungendo l'anno al fixture, MAI indebolendo l'errore.

- [ ] **Step 5: Probe sui file reali** (verifica che i master veri abbiano l'anno):

```bash
python -c "
import openpyxl
from verticals.condges.pf_rotate.excel_model import find_month_periods, periodo_anno_mese
for f in ['pianfin-in/ORTI_PF_2026-07.xlsx', 'pianfin-in/INTUR_PF_2026-06.xlsx']:
    wb = openpyxl.load_workbook(f)
    for name in wb.sheetnames:
        try:
            cols = find_month_periods(wb[name])
            if cols:
                lo, hi = min(cols), max(cols)
                print(f'{f} · {name!r}: {periodo_anno_mese(lo)} → {periodo_anno_mese(hi)}')
        except ValueError as e:
            print(f'{f} · {name!r}: ⚠️ {e}')
"
```
Expected: ogni foglio-mese risolve `(2026, m)` → `(2026, 12)`. Se un foglio INTUR reale non ha l'anno → annotalo nel commit message: `extend.py` (Task 8) scrive comunque il marker anno, e il file esteso sarà conforme.

- [ ] **Step 6: Commit** — `git add -- verticals/condges/pf_rotate/excel_model.py tests/test_pf_rotate_excel_model.py tests/conftest.py && git commit -m "feat(pf-rotate): find_month_periods — colonne datate per anno (wrap dic→gen)"`

---

### Task 3: `parse_scadenze` → bucket per periodo (fix bug anno)

**Files:**
- Modify: `verticals/condges/scadenze_parse.py:115-139` (bucketing) e `:142-174` (`partite_df_to_scadenzario_data`)
- Test: `tests/test_scadenze_parse.py` (append)

**Interfaces:**
- Consumes: `periodo()` da `excel_model`.
- Produces: `parse_scadenze(...) -> tuple[pd.DataFrame, list[int]]` dove la lista è di **periodi** ordinati e le colonne df sono `mese_{periodo}` (es. `mese_24317` per giu 2026). La firma NON cambia; cambia il significato delle chiavi. `partite_df_to_scadenzario_data` segue (chiavi `totale_per_mese` = periodi).

- [ ] **Step 1: Write failing test** — il caso che oggi sbaglia in silenzio:

```python
def test_parse_scadenze_separa_gli_anni(tmp_path):
    """Giugno 2026 e giugno 2027 NON si sommano nello stesso bucket."""
    import openpyxl
    from datetime import datetime
    from verticals.condges.pf_rotate.excel_model import periodo

    wb = openpyxl.Workbook()
    ws = wb.active
    # layout sintetica: col 11 codice, col 12 nome, col 23 scadenza, col 26 saldo
    for r, (scad, imp) in enumerate(
        [(datetime(2026, 6, 15), -100.0), (datetime(2027, 6, 15), -900.0)], start=2
    ):
        ws.cell(r, 11, 5555)
        ws.cell(r, 12, "FORNITORE BIENNALE")
        ws.cell(r, 23, scad)
        ws.cell(r, 26, imp)
    p = tmp_path / "scad.xlsx"
    wb.save(p)

    from verticals.condges.scadenze_parse import parse_scadenze
    df, bucket_periodi = parse_scadenze(open(p, "rb"), primo_mese_aperto=(2026, 5))

    p26, p27 = periodo(2026, 6), periodo(2027, 6)
    assert set(bucket_periodi) == {p26, p27}
    row = df.iloc[0]
    assert row[f"mese_{p26}"] == -100.0
    assert row[f"mese_{p27}"] == -900.0   # oggi finirebbe sommato in giugno 2026
    assert row["scaduto"] == 0.0
```

- [ ] **Step 2: Run → FAIL** — `python -m pytest tests/test_scadenze_parse.py::test_parse_scadenze_separa_gli_anni -v` → KeyError/assert (oggi il bucket è `mese_6` sommato).

- [ ] **Step 3: Implement** — in `parse_scadenze`, sostituisci il ramo else (righe ~119-123):

```python
        else:
            p = periodo(inv["scad_year"], inv["scad_month"])
            all_months.add(p)
            key = f"mese_{p}"
            supplier_data[cod][key] = supplier_data[cod].get(key, 0.0) + amt
```

con import in testa: `from verticals.condges.pf_rotate.excel_model import periodo`.
Rinomina locale `all_months` → `all_periods` (e `bucket_months` → `bucket_periodi` nel return) per leggibilità. `partite_df_to_scadenzario_data` e `sintetica_list_to_scadenzario_data` non cambiano logica (iterano le chiavi che ricevono) — aggiorna solo i nomi dei parametri (`bucket_months` → `bucket_periodi`) e la docstring.

- [ ] **Step 4: Run → PASS il nuovo; la suite parziale** `python -m pytest tests/test_scadenze_parse.py tests/test_scadenzario.py -q`. I test esistenti che asseriscono `mese_5` vanno aggiornati a `f"mese_{periodo(ANNO, 5)}"` con l'anno che il test usa nel fixture (cerca `mese_` nel file e converti ogni occorrenza — meccanico, l'anno è quello delle date nel fixture del test).

- [ ] **Step 5: Commit** — `git commit -m "fix(pf-rotate): parse_scadenze bucketta per periodo — giugno 2027 non si somma più a giugno 2026"`

⚠️ Da qui la suite COMPLETA è rossa (rotate/write_pf ricevono periodi ma confrontano mesi): è atteso, si chiude nel Task 6. Commit comunque — i task 4-6 sono la catena che la rirende verde. NON pushare fino a fine Task 6.

---

### Task 4: `pf_writer` su chiave periodo (+ unificazione scanner colonne)

**Files:**
- Modify: `verticals/condges/pf_rotate/pf_writer.py` — `_build_month_col_map` (riga ~106), `write_pf` (~266-460)
- Test: `tests/test_pf_rotate_step3.py` (le fixture di write_pf vivono lì)

**Interfaces:**
- Consumes: `find_month_periods`, `periodo`, `require_periodo` da `excel_model`.
- Produces: `write_pf(pf_bytes, scad_df, bucket_periodi: list[int], fornitori_map, excluded, scaduto_periodo: int | None, clear_codici) -> tuple[bytes, dict]`; il summary dict guadagna la chiave `"oltre_orizzonte": dict[int, float]` (codice → importo non scrivibile). `_build_month_col_map` SPARISCE: sostituita da `find_month_periods`.

- [ ] **Step 1: Sostituisci lo scanner locale** — `_build_month_col_map(ws)` è un duplicato di `find_month_columns` (stessa semantica "latest wins", riga ~106-115). Cancellala e sostituisci ogni chiamata con `find_month_periods(ws, header_row=2)`. Le variabili `month_col` diventano dict periodo→col: i confronti `m >= current_month` funzionano invariati coi periodi (ordinali).

- [ ] **Step 2: Rinomina i parametri** — `bucket_months` → `bucket_periodi`, `scaduto_month` → `scaduto_periodo` in `write_pf`; in testa a `write_pf` aggiungi:

```python
    if scaduto_periodo is not None:
        require_periodo(scaduto_periodo, "scaduto_periodo")
    for _p in bucket_periodi:
        require_periodo(_p, "bucket_periodi[]")
```

Il default `date.today().month` per `current_month` (riga ~294) diventa `periodo(date.today().year, date.today().month)` — il fallback legacy resta ancorato a oggi SOLO quando nessun chiamante passa l'ancora (path app legacy, documentato).

- [ ] **Step 3: Secchio oltre-orizzonte** — nel loop di scrittura (~438-443), dove `col = month_col.get(month)` può essere `None`:

```python
        oltre_orizzonte: dict[int, float] = {}   # inizializzata a inizio write_pf
        ...
        for p, amount in netted.items():
            col = month_col.get(p)
            if col is None:
                oltre_orizzonte[codice] = oltre_orizzonte.get(codice, 0.0) + amount
                continue
            ...
```

e nel return: `summary["oltre_orizzonte"] = oltre_orizzonte`.

- [ ] **Step 4: Aggiorna i test di write_pf** — in `tests/test_pf_rotate_step3.py` definisci in testa:

```python
from verticals.condges.pf_rotate.excel_model import periodo

P = lambda m: periodo(2026, m)  # l'anno dei fixture è 2026
```

e converti ogni `mese_5` → `f"mese_{P(5)}"`, `bucket_months=[5, 6]` → `bucket_periodi=[P(5), P(6)]`, `scaduto_month=5` → `scaduto_periodo=P(5)`.

- [ ] **Step 5: Test nuovo per il secchio**:

```python
def test_write_pf_scadenza_oltre_orizzonte_va_nel_secchio(minimal_pf_orti_bytes):
    """Periodo senza colonna nel foglio: non scritto, non sommato altrove, riportato."""
    import pandas as pd
    from verticals.condges.pf_rotate.pf_writer import write_pf
    from verticals.condges.pf_rotate.excel_model import periodo

    p_fuori = periodo(2027, 7)  # il fixture arriva a dicembre 2026
    scad_df = pd.DataFrame([{
        "codice_fornitore": 18, "nome": "Acqua Ausino",
        "totale": -500.0, "scaduto": 0.0, f"mese_{p_fuori}": -500.0,
    }])
    out, summary = write_pf(
        pf_bytes=minimal_pf_orti_bytes, scad_df=scad_df,
        bucket_periodi=[p_fuori],
        fornitori_map={18: {"voce_id": "USCITE_UTENZE", "nome_pf": "Acqua - Ausino"}},
        excluded=set(), scaduto_periodo=periodo(2026, 5), clear_codici={18},
    )
    assert summary["oltre_orizzonte"] == {18: -500.0}
```

- [ ] **Step 6: Run** — `python -m pytest tests/test_pf_rotate_step3.py -q` → PASS. Commit: `git commit -m "feat(pf-rotate): pf_writer su chiave periodo + secchio oltre-orizzonte"`

---

### Task 5: step2 / step1 / controlli_sheet / step5 su periodo

**Files:**
- Modify: `verticals/condges/pf_rotate/step2_azzera.py` · `step1_saldi.py` (`write_saldi_banca`) · `controlli_sheet.py` · `step5_controlli.py`
- Test: `tests/test_pf_rotate_step2.py` · `test_pf_rotate_step1.py` · `test_pf_rotate_saldi_manual_block.py` · `test_pf_rotate_controlli_sheet.py` · `test_pf_rotate_step5.py`

**Interfaces:**
- Produces: `azzera_mese(wb, periodo_chiuso: int)` · `write_saldi_banca(wb, *, periodo_chiuso: int, data_saldo, saldi)` · `advance_controlli(wb, periodo_chiuso: int)` · `verifica_controlli(wb, *, periodo_chiuso: int)`. Ognuna apre con `require_periodo(periodo_chiuso, "periodo_chiuso")` e risolve le colonne con `find_month_periods`.

Pattern identico per i quattro moduli (mostrato su step2, replicare):

- [ ] **Step 1: step2_azzera** — rinomina `mese_chiuso` → `periodo_chiuso`; `find_month_columns` → `find_month_periods` (2 punti: master riga 71, dettagli riga 95); messaggio errore riga 73:

```python
    require_periodo(periodo_chiuso, "periodo_chiuso")
    mese_cols_master = find_month_periods(pf, header_row=2)
    if periodo_chiuso not in mese_cols_master:
        anno, mese = periodo_anno_mese(periodo_chiuso)
        raise ValueError(f"Periodo chiuso {anno}-{mese:02d} non trovato nel master.")
```

- [ ] **Step 2: step1_saldi** — stesso pattern su `write_saldi_banca` (usa `find_month_periods` per la colonna target; il branch fixed-snapshot INTUR non risolve colonne-mese e resta invariato).

- [ ] **Step 3: controlli_sheet** — `advance_controlli(wb, periodo_chiuso)`; riga 103 `mese_aperto = mese_chiuso % 12 + 1` diventa:

```python
        _, mese_aperto = periodo_anno_mese(periodo_chiuso + 1)
        _, mese_chiuso_cal = periodo_anno_mese(periodo_chiuso)
```

e le label usano `_MESE_NOME[mese_aperto]` / `_MESE_NOME[mese_chiuso_cal]` (riga 106).

- [ ] **Step 4: step5_controlli** — `verifica_controlli(wb, *, periodo_chiuso)`; `ordered_mesi = sorted(month_cols.keys())` ora ordina periodi → l'ordinamento multi-anno diventa corretto GRATIS (era il bug `index()`); `cutover_idx = ordered_mesi.index(periodo_chiuso)`.

- [ ] **Step 5: Aggiorna i 5 file di test** col helper `P = lambda m: periodo(2026, m)` (come Task 4): ogni chiamata `mese_chiuso=4` → `periodo_chiuso=P(4)`.

- [ ] **Step 6: Run** — `python -m pytest tests/test_pf_rotate_step1.py tests/test_pf_rotate_step2.py tests/test_pf_rotate_step5.py tests/test_pf_rotate_controlli_sheet.py tests/test_pf_rotate_saldi_manual_block.py -q` → PASS. Commit: `git commit -m "feat(pf-rotate): step1/2/5 + controlli su chiave periodo"`

---

### Task 6: rotate + step3 + bordi (CLI, app) — suite verde, golden intatto

**Files:**
- Modify: `verticals/condges/pf_rotate/rotate.py` · `step3_scadenzario.py` · `cli_handler.py` · `verticals/condges/app_cashflow.py` · `verticals/condges/pf_generator/blocchi.py` · `verticals/condges/skeleton_shift.py` (`hide_past_columns_rotation`) · `excel_model.py` (rimozione compat)
- Test: `tests/test_pf_rotate_golden.py` · `test_pf_rotate_cli_handler.py` · `test_pf_generator_blocchi.py` + suite completa

**Interfaces:**
- Produces: `rotate(*, pf_path, scad_df, bucket_periodi, societa, periodo_chiuso: int, data_saldo, ...) -> RotateResult`; `RotateResult.scadenzario_summary["oltre_orizzonte"]` propagato; `apply_scadenzario(..., bucket_periodi, scaduto_periodo, ...)`.
- Il CLI NON cambia superficie: `--mese-chiuso 1-12` + `--anno` restano; la conversione a periodo è interna.

- [ ] **Step 1: rotate.py** — `mese_chiuso` → `periodo_chiuso` con `require_periodo` in testa; riga 121 `primo_mese_aperto = mese_chiuso % 12 + 1` → `primo_periodo_aperto = periodo_chiuso + 1`; passa `scaduto_periodo=primo_periodo_aperto` a `apply_scadenzario`. La derivazione del nome file (righe 146-149) resta su `data_saldo` — invariata.

- [ ] **Step 2: step3_scadenzario.py** — rinomina parametri (`bucket_months` → `bucket_periodi`, `scaduto_month` → `scaduto_periodo`), propaga a `write_pf` e `blocco_a_per_voce`; nel summary aggiungi `"oltre_orizzonte": write_summary_dict` (dal Task 4). Riga 125: `primo = scaduto_periodo or min(bucket_periodi)`.

- [ ] **Step 3: blocchi.py + template.py (confine display)** — `blocco_a_per_voce` riceve periodi; i fogli DA MAPPARE/ESCLUSI sono report a 12 colonne calendario (`col_mese(m)` con m 1-12): al confine converti `mese_cal = periodo_anno_mese(p)[1]` e documenta nel docstring: *"fogli report su calendario: in un file multi-anno due periodi omonimi si aggregano qui (limite display accettato, non tocca le voci)"*.

- [ ] **Step 4: skeleton_shift.hide_past_columns_rotation** — risolve colonne via `find_month_periods` e nasconde quelle con `p < primo_periodo` (il parametro diventa un periodo; `require_periodo` in testa).

- [ ] **Step 5: cli_handler.py** — dopo il parse degli arg (riga ~144):

```python
    from verticals.condges.pf_rotate.excel_model import periodo
    anno = args.anno or date.today().year
    periodo_chiuso = periodo(anno, args.mese_chiuso)
```

`cutoff` (righe 145-148) resta tupla per `parse_scadenze`. La chiamata `rotate(..., periodo_chiuso=periodo_chiuso, ...)`. Dopo il print del summary aggiungi:

```python
    oltre = (result.scadenzario_summary or {}).get("oltre_orizzonte") or {}
    if oltre:
        tot = sum(oltre.values())
        print(f"\n⚠️ Oltre orizzonte (senza colonna nel PF): {len(oltre)} fornitori, {tot:,.2f} € NON scritti")
```

- [ ] **Step 6: app_cashflow.py** — riga 133 `primo_aperto` resta tupla; la chiamata `rotate(..., periodo_chiuso=periodo(anno, mese_chiuso) ...)`. Display buckets (righe 140-141 e 325-328): `MESI[m]` → `f"{MESI[periodo_anno_mese(p)[1]]} {periodo_anno_mese(p)[0]}"`. Dopo gli esiti aggiungi il warning oltre-orizzonte (`st.warning` con conteggio e totale, stesso calcolo del CLI).

- [ ] **Step 7: Cancella la compat** — rimuovi `find_month_columns` da `excel_model.py`; `grep -rn "find_month_columns" verticals/ tests/` deve dare 0.

- [ ] **Step 8: SUITE COMPLETA + golden** — `python -m pytest -q` → verde alla baseline +4 nuovi. Il golden (`test_pf_rotate_golden.py`, aggiornato con `P()` come gli altri) è il testimone di non-regressione: se un valore d'output differisce, il task NON è finito.

- [ ] **Step 9: Smoke sul file REALE** (il vero golden di non-regressione della spec):

```bash
python cli.py pf-rotate --pf pianfin-in/ORTI_PF_2026-07.xlsx --scad pianfin-in/situazionepartitefornitoriORTI.xlsx \
  --societa ORTI --mese-chiuso 6 --anno 2026 --banca MPS=726946.18 --banca INTESA=136312.45 \
  --unmapped-policy skip --fornitori-csv pianfin-in/d_fornitori_bq.csv --out pianfin-out
```
Expected: `Controlli: OK=13 ERR=0 INDET=7 · Fornitori scritti: 82` — identico al run pre-refactor del 2026-08-10 (output T18-13). Stesso smoke per INTUR (`--pf pianfin-in/INTUR_PF_2026-06.xlsx --scad pianfin-in/INTURscadenziario.xlsx --societa INTUR`): atteso 12/0/8, 26 scritti.

- [ ] **Step 10: ruff + Commit** — `ruff check . && git commit -m "feat(pf-rotate): motore year-aware end-to-end — periodo ovunque, mesi nudi solo ai bordi CLI/app"`

---

### Task 7: Fixture 15 colonne + collisione end-to-end

**Files:**
- Modify: `tests/conftest.py` (nuovo fixture)
- Test: `tests/test_pf_rotate_golden.py` (append)

**Interfaces:**
- Produces: fixture `minimal_pf_orti_15col_bytes` — come `_build_minimal_pf_orti` ma con 15 colonne-mese APR 2026 → GIU 2027 (GENNAIO col 12 porta il marker anno `2027` in riga 1 della stessa colonna).

- [ ] **Step 1: Fixture** — in `conftest.py`, aggiungi parametro a `_build_minimal_pf_orti(mesi_extra_2027: int = 0)`: dopo DICEMBRE (col 11) appende `mesi_extra_2027` colonne GENNAIO.. con `pf.cell(1, 12, 2027)` sul GENNAIO, replicando per ogni colonna nuova le stesse formule delle colonne esistenti (stesso loop che già scrive righe 12/15/16, esteso alle colonne nuove) e la catena `pf.cell(4, c, f"={get_column_letter(c-1)}37")`. Fixture: `minimal_pf_orti_15col_bytes = _build_minimal_pf_orti(mesi_extra_2027=6)`.

- [ ] **Step 2: Test end-to-end collisione**:

```python
def test_rotate_15col_giugno26_e_giugno27_in_colonne_diverse(
    minimal_pf_orti_15col_bytes, fornitori_csv_orti, tmp_path
):
    from verticals.condges.pf_rotate.excel_model import periodo, find_month_periods
    import openpyxl
    from io import BytesIO

    p26, p27 = periodo(2026, 6), periodo(2027, 6)
    pf_path = tmp_path / "in.xlsx"
    pf_path.write_bytes(minimal_pf_orti_15col_bytes)
    scad_df = pd.DataFrame([{
        "codice_fornitore": 18, "nome": "Acqua Ausino",
        "totale": -300.0, "scaduto": 0.0,
        f"mese_{p26}": -100.0, f"mese_{p27}": -200.0,
    }])
    result = rotate(
        pf_path=pf_path, scad_df=scad_df, bucket_periodi=[p26, p27],
        societa="ORTI", periodo_chiuso=periodo(2026, 5),
        data_saldo=date(2026, 5, 31), saldi={"MPS": 100.0, "Intesa": 50.0},
        fornitori_csv=fornitori_csv_orti, out_dir=tmp_path,
        unmapped_policy=UnmappedPolicy.FAIL,
    )
    wb = openpyxl.load_workbook(result.out_path)
    ut = wb["Utenze"]
    cols = find_month_periods(ut)
    v26 = ut.cell(_find_row(ut, "Acqua"), cols[p26]).value
    v27 = ut.cell(_find_row(ut, "Acqua"), cols[p27]).value
    assert (v26, v27) == (100.0, 200.0)   # write_pf scrive positivi sul PF
```

(`_find_row`: helper locale di 4 righe che scansiona la colonna B del foglio per il nome fornitore — copiane il pattern da `_find_supplier_row_by_name` in `pf_writer.py:151`.)

- [ ] **Step 3: Run → PASS.** Se il valore atteso di segno/riga non torna, leggi il summary di `write_pf` PRIMA di aggiustare l'assert: l'aspettativa giusta viene dal motore, i segni sono la trappola nota.
- [ ] **Step 4: Commit** — `git commit -m "test(pf-rotate): fixture 15 colonne — giugno 2026 e giugno 2027 su colonne distinte"`

---

### Task 8: `extend.py` — allungamento template

**Files:**
- Create: `verticals/condges/pf_rotate/extend.py`
- Modify: `verticals/condges/pf_rotate/cli_handler.py` (nuovo subcommand `pf-extend`) + `cli.py` se il wiring dei subcommand sta lì (verifica con `grep -n "pf-rotate" cli.py`)
- Test: Create `tests/test_pf_rotate_extend.py`

**Interfaces:**
- Consumes: `find_month_periods`, `periodo`, `periodo_anno_mese`, `require_periodo`, `find_layout`, `MESI_IT`.
- Produces: `extend_to(wb: Workbook, target_periodo: int) -> list[str]` (log delle modifiche, muta il wb in-place — il chiamante è responsabile di lavorare su una copia); CLI `hotelops pf-extend --pf FILE --to YYYY-MM [--out DIR]` che scrive `<societa>_PF_extended_<to>_<ts>.xlsx` in `--out` (default `pianfin-out/`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pf_rotate_extend.py
import openpyxl
import pytest
from io import BytesIO
from verticals.condges.pf_rotate.excel_model import (
    find_month_periods, periodo, is_formula_with_refs,
)
from verticals.condges.pf_rotate.extend import extend_to


def _wb(bytes_): return openpyxl.load_workbook(BytesIO(bytes_))


def test_extend_aggiunge_colonne_fino_al_target(minimal_pf_orti_bytes):
    wb = _wb(minimal_pf_orti_bytes)
    extend_to(wb, periodo(2027, 6))
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    assert max(cols) == periodo(2027, 6)
    assert min(cols) == periodo(2026, 4)          # l'esistente non si tocca
    assert pf.cell(1, cols[periodo(2027, 1)]).value == 2027  # marker anno sul GENNAIO


def test_extend_traduce_la_cascata_saldo(minimal_pf_orti_bytes):
    from openpyxl.utils import get_column_letter
    wb = _wb(minimal_pf_orti_bytes)
    extend_to(wb, periodo(2027, 6))
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    c_gen = cols[periodo(2027, 1)]
    # r4 del nuovo mese = catena dal saldo proiettato del mese precedente
    assert pf.cell(4, c_gen).value == f"={get_column_letter(c_gen - 1)}37"


def test_extend_estende_anche_i_dettagli(minimal_pf_orti_bytes):
    wb = _wb(minimal_pf_orti_bytes)
    extend_to(wb, periodo(2027, 6))
    for name in ("Utenze", "Materie Prime-Consumo "):
        assert max(find_month_periods(wb[name])) == periodo(2027, 6)


def test_extend_idempotente(minimal_pf_orti_bytes):
    wb = _wb(minimal_pf_orti_bytes)
    assert extend_to(wb, periodo(2026, 12)) == []   # target già coperto: no-op
```

- [ ] **Step 2: Run → FAIL** (modulo inesistente).

- [ ] **Step 3: Implement `extend.py`**

```python
"""Estensione dell'orizzonte del template PF — spec 2026-08-10.

Aggiunge colonne-mese fino al periodo target copiando il pattern dell'ultima
colonna-mese esistente con traduzione dei riferimenti (Translator). Non tocca
mai i valori esistenti. La colonna TOTALI (se presente, master) viene spostata
a destra e i suoi SUM estesi al nuovo range.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from verticals.condges.pf_rotate.excel_model import (
    MESI_IT,
    find_month_periods,
    periodo_anno_mese,
    require_periodo,
)

_NOME_MESE = {v: k for k, v in MESI_IT.items()}
_HEADER_ROW = 2
_YEAR_ROW = 1


def _extend_sheet(ws: Worksheet, target_periodo: int) -> list[str]:
    cols = find_month_periods(ws, header_row=_HEADER_ROW)
    if not cols:
        return []
    last_p = max(cols)
    if target_periodo <= last_p:
        return []
    src_col = cols[last_p]

    # TOTALI: colonna non-mese subito dopo l'ultimo mese (solo master).
    totali_col = src_col + 1
    has_totali = isinstance(ws.cell(_HEADER_ROW, totali_col).value, str)
    n_new = target_periodo - last_p
    if has_totali:
        ws.insert_cols(totali_col, n_new)  # sposta TOTALI a destra, formule NON tradotte
        # NB: le formule TOTALI restano testualmente identiche (=SUM(C6:K6), =K37):
        # i range esistenti non cambiano posizione, quindi restano corrette; si
        # estendono/ripuntano sotto.

    changed: list[str] = []
    for i in range(1, n_new + 1):
        p = last_p + i
        dst_col = src_col + i
        anno, mese = periodo_anno_mese(p)
        ws.cell(_HEADER_ROW, dst_col, _NOME_MESE[mese])
        if mese == 1 or i == 1 and periodo_anno_mese(last_p)[0] != anno:
            ws.cell(_YEAR_ROW, dst_col, anno)  # marker anno sul primo mese dell'anno nuovo
        for r in range(1, ws.max_row + 1):
            v = ws.cell(r, src_col).value
            if isinstance(v, str) and v.startswith("="):
                src_ref = f"{get_column_letter(src_col)}{r}"
                dst_ref = f"{get_column_letter(dst_col)}{r}"
                ws.cell(r, dst_col).value = Translator(v, origin=src_ref).translate_formula(dst_ref)
        changed.append(f"{ws.title}!{get_column_letter(dst_col)} ({anno}-{mese:02d})")

    if has_totali:
        new_totali_col = totali_col + n_new
        first_col_l = get_column_letter(min(cols.values()))
        last_col_l = get_column_letter(src_col + n_new)
        for r in range(1, ws.max_row + 1):
            v = ws.cell(r, new_totali_col).value
            if not isinstance(v, str) or not v.startswith("="):
                continue
            # =SUM(C6:K6) → estendi al nuovo ultimo mese; =K37 → ripunta all'ultimo mese
            import re
            v2 = re.sub(
                rf"SUM\((\$?[A-Z]+\$?)(\d+):\$?[A-Z]+\$?(\d+)\)",
                lambda m: f"SUM({m.group(1)}{m.group(2)}:{last_col_l}{m.group(3)})",
                v,
            )
            v2 = re.sub(rf"^=([A-Z]+)(\d+)$", f"={last_col_l}\\2", v2)
            if v2 != v:
                ws.cell(r, new_totali_col).value = v2
                changed.append(f"{ws.title}!{get_column_letter(new_totali_col)}{r} (TOTALI)")
    return changed


def extend_to(wb: Workbook, target_periodo: int) -> list[str]:
    """Estende ogni foglio con colonne-mese fino a target_periodo. In-place."""
    require_periodo(target_periodo, "target_periodo")
    changed: list[str] = []
    for name in wb.sheetnames:
        changed += _extend_sheet(wb[name], target_periodo)
    return changed
```

- [ ] **Step 4: Run → PASS.** Se `Translator` produce riferimenti inattesi su una formula del fixture, stampa la formula sorgente e quella tradotta nel messaggio di assert prima di sistemare — la traduzione deve essere verificabile a occhio.

- [ ] **Step 5: CLI subcommand** — in `cli_handler.py` aggiungi `build_pf_extend_parser()` con `--pf` (Path, required), `--to` (str `YYYY-MM`, required), `--out` (default `Path.cwd()/"pianfin-out"`); handler:

```python
def _handle_extend(args) -> int:
    import openpyxl
    from datetime import datetime
    from verticals.condges.pf_rotate.excel_model import periodo
    from verticals.condges.pf_rotate.extend import extend_to

    anno, mese = map(int, args.to.split("-"))
    wb = openpyxl.load_workbook(args.pf)
    changed = extend_to(wb, periodo(anno, mese))
    if not changed:
        print("Già coperto: nessuna colonna da aggiungere.")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M")
    out = args.out / f"{args.pf.stem}_extended_{args.to}_{ts}.xlsx"
    wb.save(out)
    print(f"Output: {out}\nColonne aggiunte/aggiornate: {len(changed)}")
    for c in changed[:20]:
        print(f"  + {c}")
    return 0
```

Registra il subcommand dove è registrato `pf-rotate` (trova con `grep -n "pf-rotate" cli.py verticals/condges/cli_commands.py`).

- [ ] **Step 6: Test CLI** in `tests/test_pf_rotate_cli_handler.py`: invoca l'handler con il fixture su tmp_path e verifica che il file `_extended_2027-06_` esista e che `find_month_periods` sul suo master arrivi a `periodo(2027, 6)`.

- [ ] **Step 7: ruff + Commit** — `git commit -m "feat(pf-rotate): pf-extend — estensione template a periodo target con traduzione formule"`

---

### Task 9: Estensione REALE dei due master → gate umano

**Files:** nessun codice — esecuzione + verifica.

- [ ] **Step 1: Run su entrambi i master**

```bash
python cli.py pf-extend --pf pianfin-in/ORTI_PF_2026-07.xlsx --to 2027-06 --out pianfin-out
python cli.py pf-extend --pf pianfin-in/INTUR_PF_2026-06.xlsx --to 2027-06 --out pianfin-out
```

- [ ] **Step 2: Verifica automatica** — su ciascun output: `find_month_periods` del master arriva a `(2027, 6)`; zero `#REF!` nel file (`grep` sulle formule via openpyxl); `find_layout(wb)` risolve ancora; rotation smoke sul file esteso (stessi comandi del Task 6 Step 9, col file esteso come `--pf`) → controlli attesi ORTI 13/0/x · INTUR 12/0/x (gli INDET possono cambiare per le colonne nuove: annota il numero, gli ERR devono restare 0).

- [ ] **Step 3: 🛑 STOP — gate umano.** I file estesi vanno aperti da Stefano/Rosa in Excel desktop con ricalcolo (⌘=): cascata saldo sui mesi 2027, formule dettaglio, TOTALI. **Non proseguire al Task 10 senza l'ok esplicito.** (Regola CLAUDE.md: il render con dati reali lo vede un umano prima di considerare buono il file.)

---

### Task 10: `--trim-before` — la potatura annuale

**Files:**
- Modify: `verticals/condges/pf_rotate/extend.py` · `cli_handler.py` (arg `--trim-before` su pf-extend)
- Test: `tests/test_pf_rotate_extend.py` (append)

**Interfaces:**
- Produces: `trim_before(wb: Workbook, wb_values: Workbook, cutoff_periodo: int) -> list[str]` — elimina le colonne-mese con `p < cutoff`, ri-ancora la prima colonna superstite. `wb_values` è il gemello `data_only=True` dello STESSO file (serve per congelare i valori calcolati). CLI: `--trim-before YYYY-MM` opzionale su `pf-extend`.

- [ ] **Step 1: Write failing tests**

```python
def test_trim_ri_ancora_la_prima_colonna(minimal_pf_orti_bytes, tmp_path):
    import openpyxl
    from verticals.condges.pf_rotate.extend import extend_to, trim_before
    from verticals.condges.pf_rotate.excel_model import find_month_periods, periodo

    p = tmp_path / "f.xlsx"
    wb0 = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes))
    extend_to(wb0, periodo(2027, 6))
    wb0.save(p)
    wb = openpyxl.load_workbook(p)
    wbv = openpyxl.load_workbook(p, data_only=True)

    trim_before(wb, wbv, periodo(2027, 1))
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    assert min(cols) == periodo(2027, 1)
    first = cols[periodo(2027, 1)]
    v = pf.cell(4, first).value          # saldo iniziale della prima superstite
    assert not (isinstance(v, str) and v.startswith("="))  # hardcoded, non formula


def test_trim_zero_ref_rotti(minimal_pf_orti_bytes, tmp_path):
    ...  # come sopra, poi:
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert not (isinstance(cell.value, str) and "#REF!" in cell.value), (
                    f"{ws.title}!{cell.coordinate}: {cell.value}"
                )
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement `trim_before`** — logica per foglio:
  1. `cols = find_month_periods(ws)`; colonne da eliminare = `[c for p, c in cols.items() if p < cutoff]`; se vuoto → skip.
  2. **Prima di eliminare**: per la prima colonna superstite `c_first`, per ogni riga con formula che referenzia colonne in eliminazione (regex sui ref A1 con lettera colonna < lettera di c_first — usa `_A1_REF_RE` di excel_model): sostituisci la formula col **valore cached** dalla cella omologa di `wb_values` (`wb_values[ws.title].cell(r, c)`). Se il valore cached è `None` e la formula non è vuota → `raise ValueError(f"{ws.title}!{ref}: valore calcolato assente — apri e salva il file in Excel prima del trim")`. Il caso tipico è `r4 = '=<col eliminata>37'` → diventa il saldo hardcoded (com'è oggi la colonna d'apertura, check C1 di step5 lo esige).
  3. `ws.delete_cols(first_del, n_del)` (le colonne mese sono contigue per costruzione).
  4. Il marker anno: se la prima superstite non ha l'anno in riga 1 (era su una colonna eliminata), scrivi `periodo_anno_mese(cutoff)[0]` in riga 1 della prima superstite.
  5. Scan finale `#REF!` sul foglio → se presente, `raise` (mai output silenziosamente rotto).

⚠️ `delete_cols` di openpyxl NON trasla le formule delle colonne a destra — dopo la cancellazione i riferimenti relativi puntano male. Per questo l'ordine è: **congela ANCHE le formule delle colonne superstiti che referenziano colonne eliminate** (punto 2 copre tutte le righe, non solo r4) e verifica col punto 5 + il test dello Step 1 che la cascata superstite (che referenzia solo colonne superstiti: `=<prev>37` con prev ≥ c_first) resti valida — quei ref si spostano TUTTI della stessa quantità... **NO: non si spostano da soli.** Strategia corretta e semplice: dopo `delete_cols`, ricostruisci la cascata delle colonne superstiti riscrivendo per ogni colonna-mese k>first: `r4 = '=<col k-1>37'` (pattern noto, layout-aware via `find_layout`), e per le righe-formula standard usa `Translator` dalla colonna omologa: riscrivi ogni colonna superstite traducendo dalla PRIMA colonna superstite (che è stata congelata a valori solo dove referenziava il passato). Il test `#REF!` + il golden-smoke chiudono il cerchio.

- [ ] **Step 4: Run → PASS** (entrambi i test). Poi rotation smoke su un file trimmed (fixture): `rotate(...)` con `periodo_chiuso=periodo(2027, 1)` non solleva e i controlli danno ERR=0.
- [ ] **Step 5: CLI** — aggiungi `--trim-before` a `pf-extend`; l'handler carica il gemello `data_only=True` e chiama `trim_before` dopo `extend_to`.
- [ ] **Step 6: ruff + Commit** — `git commit -m "feat(pf-rotate): pf-extend --trim-before — potatura annuale con ri-ancoraggio"`

---

### Task 11: Chiusura — suite, docs, STATUS

**Files:**
- Modify: `CLAUDE.md` (§Financial Data: una riga su pf-extend e chiave periodo) · `STATUS.md` (entry sessione)

- [ ] **Step 1:** `python -m pytest -q` → tutta verde (annota il numero finale) · `ruff check .` pulito.
- [ ] **Step 2:** In `CLAUDE.md` §Financial Data aggiungi: *"**Chiave periodo**: il motore ragiona in periodi ordinali (`anno*12+mese-1`, `excel_model.periodo`) — i mesi nudi 1-12 vivono solo ai bordi CLI/app. `hotelops pf-extend --to YYYY-MM [--trim-before YYYY-MM]` estende/pota il template (orizzonte = giugno anno+1, concept ORIZZONTE_DI_TRAVERSATA)."*
- [ ] **Step 3:** STATUS.md: 3 righe (chiave periodo shippata, pf-extend, esito gate umano Task 9).
- [ ] **Step 4:** Commit finale + push del branch. PR verso main con il summary dei task (la merge resta decisione di Stefano).

---

## Self-review (fatto in scrittura)

- **Copertura spec**: §1 chiave periodo → Task 1-6 · §2 allungamento → Task 8-9 · §3 trim → Task 10 · §4 test (golden 9-col Task 6; collisione Task 7; wrap Task 2; guardia Task 1; oltre-orizzonte Task 4; estensione Task 8; trim Task 10; INTUR e2e Task 6 Step 9 + Task 9 Step 2) · §7 ordine rispettato (Task 0 rebase; gate umano Task 9 prima del trim).
- **Domande aperte spec (§5)**: TOTALI → il piano implementa il default "estendi i SUM, ripunta 37/45 all'ultimo mese" (Task 8); nascondere/sdoppiare resta decisione di Stefano al gate del Task 9. Coda di mesi al trim → parametro `--trim-before` la rende banale (si passa un cutoff più vecchio).
- **Tipi coerenti**: `periodo_chiuso: int` ovunque nel motore; `bucket_periodi: list[int]`; tuple `(anno, mese)` solo in `parse_scadenze(primo_mese_aperto=...)` e nei bordi CLI/app.
- **Niente placeholder**: ogni step ha codice o comando concreto; i punti di incertezza reale (Translator su formule vere, cached values) hanno la strategia di verifica scritta nello step.
