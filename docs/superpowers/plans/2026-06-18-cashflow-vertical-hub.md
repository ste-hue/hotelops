# Cashflow Vertical (hub app) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Montare un vertical "Cashflow" nel hub: guscio Streamlit sottile che wrappa il motore canonico `pf_rotate.rotate()` per generare il PF del mese successivo (upload PF+scadenziario, saldi pre-fill BQ editabili, policy fornitori), con run-log idempotente su BigQuery per la memoria mese×mese.

**Architecture:** La surface (`app_cashflow.render()`) raccoglie input e mostra risultati; delega il calcolo a `rotate()` (render adapter, invariato) e l'unico write BQ a `cash_pf_service.log_cash_projection_run()` → gate I1 `bq_write_validated`. La pagina hub (`pages_/cashflow.py`) monta `render()`; `app_scadenzario`/`tesoreria` (path divergenti) vengono deprecati.

**Tech Stack:** Python 3.11+, Streamlit, Pydantic v2, pandas, openpyxl, `google-cloud-bigquery`, pytest, ruff. Branch: `feat/cash-pf-engine`. Worktree: `.worktrees/cash-pf-engine` (test sempre con `python -m pytest` da dentro il worktree).

**Spec:** `docs/superpowers/specs/2026-06-18-cashflow-vertical-hub-design.md`

## Global Constraints

- **Unico writer BQ** della slice = `cash_pf_service.log_cash_projection_run` via `bq_write_validated`. Nessun `load_table_from_json`/`bq.query(DELETE/INSERT)` nella surface.
- **`rotate()` e gli step `pf_rotate` restano invariati** internamente (è il render adapter). NON toccare `step5_controlli` in questa slice (control fix = task separato).
- **Stateless**: PF + scadenziario + saldi caricati a ogni run. Nessuna statefulness/GCS/auto-load.
- **Policy fornitori default = `skip`** (procede con warning).
- Run-log **snapshot** idempotente, `natural_key=["societa_id","anno","mese_chiuso"]`.
- File deprecati (`app_scadenzario`, `tesoreria`) **non si cancellano** — solo banner.
- Test dal worktree: `python -m pytest` (cwd in testa a `sys.path`). Mai `pip install -e` da qui.

**Verified primitives (do not re-derive):**
- Engine: `from verticals.condges.pf_rotate.rotate import rotate, RotateResult` — `rotate(*, pf_path: Path, scad_df: pd.DataFrame, bucket_months: list[int], societa: str, mese_chiuso: int, data_saldo: date, saldi: dict[str,float] | None = None, fornitori_csv: Path, out_dir: Path, unmapped_policy=UnmappedPolicy.FAIL, allow_partial_saldi=False, extra_excluded=None) -> RotateResult`. `RotateResult` fields: `out_path: Path, n_controlli_ok: int, n_controlli_err: int, n_controlli_indet: int`.
- Policy: `from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy` (`.SKIP`, `.FAIL`, `.INTERACTIVE`).
- Scadenze: `from verticals.condges.scadenze_parse import parse_scadenze` — `parse_scadenze(fobj: BytesIO, primo_mese_aperto: tuple[int,int]|None) -> (df, bucket_months)`. df columns: `codice_fornitore, nome, totale, scaduto, mese_<N>…`.
- Saldi: `from verticals.condges.pf_rotate.step1_saldi import fetch_saldi_da_bq` — `fetch_saldi_da_bq(societa: str, data_saldo: date) -> dict[str,float]`.
- Gate: `from core.bq.write import bq_write_validated` — `(table, rows: list[BaseModel], mode, natural_key)`; `mode="snapshot"` = DELETE+INSERT per natural_key.
- Config pattern: `core/config.py` usa `_t("table_name")`; `F_*` ids in cima al file.
- Schemas: `core/schemas.py` — `SocietaId = Literal["ORTI","INTUR"]`; Pydantic v2 `field_validator`. `data_caricamento` = ISO string required.
- Service: `from verticals.condges.services import cash_pf_service`; intents in `verticals/condges/services/intents.py`; `SaveResult(table, rows_written, natural_key)`.
- Hub mount pattern: `verticals/hub/pages_/spiaggia.py` (render→`verticals.spiaggia.app.render`); nav in `verticals/hub/app.py` (`st.Page(<page>.render, title=…, icon=…, url_path=…)`).

---

## Task 1: BQ run-log foundation (config + schema + intent + service)

Tutto ciò che serve a persistere un run. Testabile con gate mockato.

**Files:**
- Modify: `core/config.py` (aggiungi `F_CASH_PROJECTION_RUNS`)
- Modify: `core/schemas.py` (aggiungi `CashProjectionRunRow`)
- Modify: `verticals/condges/services/intents.py` (aggiungi `LogCashRunIntent`)
- Modify: `verticals/condges/services/cash_pf_service.py` (aggiungi `log_cash_projection_run`)
- Test: `tests/test_cash_pf_service.py` (append)

**Interfaces:**
- Produces: `cash_pf_service.log_cash_projection_run(intent: LogCashRunIntent) -> SaveResult`; `LogCashRunIntent` (vedi Step 4); `CashProjectionRunRow`; `cfg.F_CASH_PROJECTION_RUNS`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cash_pf_service.py  (append)
from core.schemas import CashProjectionRunRow
from verticals.condges.services.intents import LogCashRunIntent


def test_log_cash_projection_run_calls_gate_snapshot():
    intent = LogCashRunIntent(
        societa_id="ORTI", anno=2026, mese_chiuso=4, data_saldo="2026-04-30",
        saldo_cutover=332611.44, scaduto_totale=-180442.12,
        totale_partite_aperte=-573556.67, forward_buckets={5: -23470.84, 6: -347596.64},
        n_controlli_ok=22, n_controlli_err=1, n_controlli_indet=0,
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        result = cash_pf_service.log_cash_projection_run(intent)

    gate.assert_called_once()
    args, kwargs = gate.call_args
    table, rows = args[0], args[1]
    assert table.endswith("f_cash_projection_runs")
    assert kwargs["mode"] == "snapshot"
    assert kwargs["natural_key"] == ["societa_id", "anno", "mese_chiuso"]
    assert len(rows) == 1 and isinstance(rows[0], CashProjectionRunRow)
    row = rows[0]
    assert row.fonte == "APP_CASHFLOW"
    assert row.data_caricamento
    # forward_buckets serializzato come JSON string {mese: importo}
    import json
    assert json.loads(row.forward_buckets_json) == {"5": -23470.84, "6": -347596.64}
    assert result.rows_written == 1


def test_cash_projection_run_rejects_bad_mese():
    import pytest
    bad = LogCashRunIntent(
        societa_id="ORTI", anno=2026, mese_chiuso=13, data_saldo="2026-04-30",
        saldo_cutover=0.0, scaduto_totale=0.0, totale_partite_aperte=0.0,
        forward_buckets={}, n_controlli_ok=0, n_controlli_err=0, n_controlli_indet=0,
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        with pytest.raises(Exception):
            cash_pf_service.log_cash_projection_run(bad)
        gate.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cash_pf_service.py::test_log_cash_projection_run_calls_gate_snapshot -v`
Expected: FAIL — `ImportError: cannot import name 'CashProjectionRunRow'` / `LogCashRunIntent`.

- [ ] **Step 3: Add config table id**

In `core/config.py`, dopo `F_FATTURE_RIGHE = _t("f_fatture_righe")` (riga ~29):

```python
F_CASH_PROJECTION_RUNS      = _t("f_cash_projection_runs")
```

- [ ] **Step 4: Add the intent dataclass**

In `verticals/condges/services/intents.py`, dopo `SavePrevisioneIntent`:

```python
@dataclass(frozen=True)
class LogCashRunIntent:
    societa_id: str
    anno: int
    mese_chiuso: int
    data_saldo: str  # ISO date
    saldo_cutover: float
    scaduto_totale: float
    totale_partite_aperte: float
    forward_buckets: dict[int, float]
    n_controlli_ok: int
    n_controlli_err: int
    n_controlli_indet: int
    saldo_proiettato_finale: float | None = None
    fonte: str = "APP_CASHFLOW"
```

- [ ] **Step 5: Add the Pydantic schema**

In `core/schemas.py`, dopo `PianoFinanziarioInputRow` (riga ~102):

```python
# ── f_cash_projection_runs ───────────────────────────────────────────────────


class CashProjectionRunRow(BaseModel):
    """Schema for f_cash_projection_runs rows (run-log proiezione cassa)."""

    societa_id: SocietaId
    anno: int
    mese_chiuso: int
    data_saldo: str  # ISO date del cutover
    saldo_cutover: float
    scaduto_totale: float
    totale_partite_aperte: float
    forward_buckets_json: str  # JSON {mese: importo}
    saldo_proiettato_finale: Optional[float] = None
    n_controlli_ok: int
    n_controlli_err: int
    n_controlli_indet: int
    fonte: str = "APP_CASHFLOW"
    data_caricamento: str  # ISO timestamp
    raw_object_id: Optional[str] = None

    @field_validator("mese_chiuso")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese_chiuso fuori range: {v}")
        return v
```

- [ ] **Step 6: Implement the service function**

In `verticals/condges/services/cash_pf_service.py`, aggiorna gli import in cima:

```python
import json
```

aggiungi a `from core.config import ...`: `F_CASH_PROJECTION_RUNS`;
aggiungi a `from core.schemas import ...`: `CashProjectionRunRow`;
aggiungi a `from verticals.condges.services.intents import ...`: `LogCashRunIntent`.

Poi, in fondo al file:

```python
_CASH_RUN_NATURAL_KEY = ["societa_id", "anno", "mese_chiuso"]


def log_cash_projection_run(intent: LogCashRunIntent) -> SaveResult:
    """Logga un run di proiezione cassa — snapshot idempotente per (societa, anno, mese_chiuso)."""
    row = CashProjectionRunRow(
        societa_id=intent.societa_id,
        anno=intent.anno,
        mese_chiuso=intent.mese_chiuso,
        data_saldo=intent.data_saldo,
        saldo_cutover=round(float(intent.saldo_cutover), 2),
        scaduto_totale=round(float(intent.scaduto_totale), 2),
        totale_partite_aperte=round(float(intent.totale_partite_aperte), 2),
        forward_buckets_json=json.dumps(
            {str(m): round(float(v), 2) for m, v in intent.forward_buckets.items()},
            ensure_ascii=False,
        ),
        saldo_proiettato_finale=intent.saldo_proiettato_finale,
        n_controlli_ok=intent.n_controlli_ok,
        n_controlli_err=intent.n_controlli_err,
        n_controlli_indet=intent.n_controlli_indet,
        fonte=intent.fonte,
        data_caricamento=datetime.now(timezone.utc).isoformat(),
    )
    bq_write_validated(
        str(F_CASH_PROJECTION_RUNS), [row], mode="snapshot",
        natural_key=_CASH_RUN_NATURAL_KEY,
    )
    return SaveResult(str(F_CASH_PROJECTION_RUNS), 1, _CASH_RUN_NATURAL_KEY)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_cash_pf_service.py -v -k "cash_projection or cash_run"`
Expected: PASS (entrambi i nuovi test).

- [ ] **Step 8: Commit**

```bash
git add core/config.py core/schemas.py verticals/condges/services/intents.py verticals/condges/services/cash_pf_service.py tests/test_cash_pf_service.py
git commit -m "feat(condges): run-log proiezione cassa (f_cash_projection_runs) via gate I1"
```

---

## Task 2: `app_cashflow` surface (pure helper + render)

La pura logica di costruzione del run-log è testabile; la `render()` è wiring Streamlit (smoke parse).

**Files:**
- Create: `verticals/condges/app_cashflow.py`
- Test: `tests/test_app_cashflow.py`

**Interfaces:**
- Consumes: `rotate`, `RotateResult`, `parse_scadenze`, `fetch_saldi_da_bq`, `UnmappedPolicy`, `cash_pf_service.log_cash_projection_run`, `LogCashRunIntent`.
- Produces: `build_cash_run_intent(*, societa_id, anno, mese_chiuso, data_saldo, saldi, scad_df, bucket_months, result) -> LogCashRunIntent`; `render() -> None`.

- [ ] **Step 1: Write the failing test (pure helper)**

```python
# tests/test_app_cashflow.py
import pandas as pd

from verticals.condges.app_cashflow import build_cash_run_intent


class _FakeResult:
    n_controlli_ok = 22
    n_controlli_err = 1
    n_controlli_indet = 0


def test_build_cash_run_intent_computes_figures():
    df = pd.DataFrame(
        {
            "codice_fornitore": [1, 2],
            "nome": ["A", "B"],
            "totale": [-100.0, -50.0],
            "scaduto": [-80.0, 0.0],
            "mese_5": [-20.0, -10.0],
            "mese_6": [0.0, -40.0],
        }
    )
    intent = build_cash_run_intent(
        societa_id="ORTI", anno=2026, mese_chiuso=4, data_saldo="2026-04-30",
        saldi={"MPS": 245171.52, "INTESA": 87439.92}, scad_df=df,
        bucket_months=[5, 6], result=_FakeResult(),
    )
    assert intent.societa_id == "ORTI"
    assert intent.mese_chiuso == 4
    assert round(intent.saldo_cutover, 2) == 332611.44
    assert round(intent.scaduto_totale, 2) == -80.0
    assert round(intent.totale_partite_aperte, 2) == -150.0
    assert intent.forward_buckets == {5: -30.0, 6: -40.0}
    assert intent.n_controlli_err == 1
    assert intent.fonte == "APP_CASHFLOW"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_app_cashflow.py::test_build_cash_run_intent_computes_figures -v`
Expected: FAIL — `ModuleNotFoundError: verticals.condges.app_cashflow`.

- [ ] **Step 3: Create `app_cashflow.py` with the pure helper + render**

```python
#!/usr/bin/env python3
"""Cashflow vertical — guscio Streamlit sul motore canonico pf-rotate.

Monta `render()` nel hub. Stateless: upload PF + scadenziario + saldi → genera il
PF del mese successivo (rotation completa) + logga il run su BQ (memoria mese×mese).
L'authority è BigQuery + l'engine pf_rotate; questa è solo la surface.
"""

from __future__ import annotations

import tempfile
from calendar import monthrange
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from verticals.condges.pf_rotate.rotate import RotateResult, rotate
from verticals.condges.pf_rotate.step1_saldi import fetch_saldi_da_bq
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy
from verticals.condges.scadenze_parse import parse_scadenze
from verticals.condges.services import cash_pf_service
from verticals.condges.services.intents import LogCashRunIntent

FORNITORI_CSV = Path("core/bq/dimensioni/d_fornitori.csv")
MESI = {
    1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
    7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre",
}


def build_cash_run_intent(
    *,
    societa_id: str,
    anno: int,
    mese_chiuso: int,
    data_saldo: str,
    saldi: dict[str, float],
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    result: RotateResult,
) -> LogCashRunIntent:
    """Estrae le cifre del run dal scad_df + saldi + RotateResult (funzione pura)."""
    scaduto = float(scad_df["scaduto"].sum()) if "scaduto" in scad_df.columns else 0.0
    totale = float(scad_df["totale"].sum()) if "totale" in scad_df.columns else 0.0
    buckets = {
        m: float(scad_df[f"mese_{m}"].sum())
        for m in bucket_months
        if f"mese_{m}" in scad_df.columns
    }
    return LogCashRunIntent(
        societa_id=societa_id,
        anno=anno,
        mese_chiuso=mese_chiuso,
        data_saldo=data_saldo,
        saldo_cutover=float(sum(saldi.values())) if saldi else 0.0,
        scaduto_totale=scaduto,
        totale_partite_aperte=totale,
        forward_buckets=buckets,
        n_controlli_ok=result.n_controlli_ok,
        n_controlli_err=result.n_controlli_err,
        n_controlli_indet=result.n_controlli_indet,
    )


def render() -> None:
    st.title("💸 Cashflow — Piano Finanziario")
    st.caption(
        "Previsione di cassa: carica il PF del mese da chiudere + lo scadenziario, "
        "conferma i saldi, genera il PF del mese successivo."
    )

    societa = st.selectbox("Società", ["ORTI", "INTUR"])
    col1, col2 = st.columns(2)
    with col1:
        up_pf = st.file_uploader("PF del mese da chiudere (.xlsx)", type=["xlsx"], key="pf")
    with col2:
        up_scad = st.file_uploader(
            "Scadenziario fornitori (.xlsx)", type=["xlsx"], key="scad"
        )

    today = date.today()
    mese_chiuso = int(
        st.number_input(
            "Mese da chiudere", min_value=1, max_value=12, value=max(1, today.month - 1)
        )
    )
    anno = int(st.number_input("Anno", min_value=2020, max_value=2100, value=today.year))

    if not up_pf or not up_scad:
        st.info("Carica PF e scadenziario per continuare.")
        return

    # cutover = ultimo giorno del mese chiuso; primo mese aperto = mese successivo
    data_saldo = date(anno, mese_chiuso, monthrange(anno, mese_chiuso)[1])
    primo_aperto = (anno + 1, 1) if mese_chiuso == 12 else (anno, mese_chiuso + 1)

    scad_df, bucket_months = parse_scadenze(
        BytesIO(up_scad.getvalue()), primo_mese_aperto=primo_aperto
    )
    st.subheader("Scadenziario")
    st.write(
        f"{len(scad_df)} fornitori · mesi forward: "
        f"{', '.join(MESI[m] for m in bucket_months)}"
    )

    # Saldi: pre-fill da BQ, editabili
    try:
        bq_saldi = fetch_saldi_da_bq(societa, data_saldo)
    except Exception as e:  # noqa: BLE001 — BQ assente in dev/cloud è non-fatale
        bq_saldi = {}
        st.warning(f"Saldi BQ non disponibili ({e}); inseriscili a mano.")
    st.subheader("Saldi banca al cutover")
    st.caption(f"Cutover: {data_saldo.isoformat()} (pre-compilati da BQ se disponibili)")
    default_banche = list(bq_saldi.keys()) or (
        ["MPS", "Intesa", "MPS_KROSS"]
        if societa == "ORTI"
        else ["MPS", "Intesa", "Sella", "BCP"]
    )
    saldi: dict[str, float] = {}
    for banca in default_banche:
        saldi[banca] = float(
            st.number_input(
                f"Saldo {banca}",
                value=float(bq_saldi.get(banca, 0.0)),
                step=1000.0,
                format="%.2f",
                key=f"saldo_{banca}",
            )
        )

    policy_label = st.radio(
        "Fornitori non mappati", ["skip (procedi con warning)", "fail (blocca)"]
    )
    policy = UnmappedPolicy.SKIP if policy_label.startswith("skip") else UnmappedPolicy.FAIL

    if not st.button("Genera PF mese successivo", type="primary"):
        return

    with tempfile.TemporaryDirectory() as tmp:
        pf_path = Path(tmp) / up_pf.name
        pf_path.write_bytes(up_pf.getvalue())
        try:
            result = rotate(
                pf_path=pf_path,
                scad_df=scad_df,
                bucket_months=bucket_months,
                societa=societa,
                mese_chiuso=mese_chiuso,
                data_saldo=data_saldo,
                saldi={k: v for k, v in saldi.items() if v != 0} or None,
                fornitori_csv=FORNITORI_CSV,
                out_dir=Path(tmp),
                unmapped_policy=policy,
            )
        except Exception as e:  # noqa: BLE001 — surfacing engine error to UI
            st.error(f"Rotation fallita: {e}")
            return

        out_bytes = result.out_path.read_bytes()

    # Esiti
    if result.n_controlli_err:
        st.error(
            f"Controlli: {result.n_controlli_ok} OK · {result.n_controlli_err} ERR · "
            f"{result.n_controlli_indet} INDET — ERR sotto investigazione (vedi spec §4)."
        )
    else:
        st.success(
            f"Controlli: {result.n_controlli_ok} OK · 0 ERR · "
            f"{result.n_controlli_indet} INDET"
        )

    intent = build_cash_run_intent(
        societa_id=societa,
        anno=int(anno),
        mese_chiuso=int(mese_chiuso),
        data_saldo=data_saldo.isoformat(),
        saldi=saldi,
        scad_df=scad_df,
        bucket_months=bucket_months,
        result=result,
    )
    st.metric("Scaduto (roll-forward)", f"€ {intent.scaduto_totale:,.2f}")
    st.metric("Totale partite aperte", f"€ {intent.totale_partite_aperte:,.2f}")
    if intent.forward_buckets:
        st.write("Progressivo forward:")
        st.table(
            {MESI[m]: f"€ {v:,.2f}" for m, v in sorted(intent.forward_buckets.items())}
        )

    try:
        cash_pf_service.log_cash_projection_run(intent)
        st.caption("Run loggato su BigQuery (f_cash_projection_runs).")
    except Exception as e:  # noqa: BLE001 — log non deve bloccare il download
        st.warning(f"Run-log BQ non riuscito ({e}); download comunque disponibile.")

    st.download_button(
        "⬇️ Scarica nuovo PF",
        data=out_bytes,
        file_name=result.out_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
```

- [ ] **Step 4: Run the pure-helper test to verify it passes**

Run: `python -m pytest tests/test_app_cashflow.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the module parses cleanly**

Run: `python -c "import ast; ast.parse(open('verticals/condges/app_cashflow.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/app_cashflow.py tests/test_app_cashflow.py
git commit -m "feat(condges): app_cashflow surface (render + build_cash_run_intent) su rotate()"
```

---

## Task 3: Hub mount (pagina + nav)

**Files:**
- Create: `verticals/hub/pages_/cashflow.py`
- Modify: `verticals/hub/app.py` (import + `st.Page`)
- Test: `tests/test_hub_cashflow_mount.py`

**Interfaces:**
- Consumes: `verticals.condges.app_cashflow.render`.
- Produces: `verticals.hub.pages_.cashflow.render`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_cashflow_mount.py
import ast
from pathlib import Path


def test_cashflow_page_exists_and_callable():
    from verticals.hub.pages_ import cashflow

    assert callable(cashflow.render)


def test_hub_app_registers_cashflow():
    src = Path("verticals/hub/app.py").read_text()
    assert "cashflow" in src, "hub/app.py deve importare e registrare la pagina cashflow"
    # parse-only sanity
    ast.parse(src)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hub_cashflow_mount.py -v`
Expected: FAIL — `ImportError: cannot import name 'cashflow'` e/o assert su app.py.

- [ ] **Step 3: Create the hub page**

```python
# verticals/hub/pages_/cashflow.py
"""Pagina Cashflow — monta verticals.condges.app_cashflow.render()."""

import streamlit as st


def render():
    try:
        from verticals.condges.app_cashflow import render as _render
    except ImportError:
        st.title("💸 Cashflow")
        st.info("App Cashflow non disponibile: `verticals/condges/app_cashflow.py` mancante.")
        return
    _render()
```

- [ ] **Step 4: Register the page in the hub nav**

In `verticals/hub/app.py`, riga ~19, estendi l'import:

```python
from verticals.hub.pages_ import cashflow, fb, ingest, mutui, reviews, spiaggia  # noqa: E402
```

In `verticals/hub/app.py`, dentro `st.navigation([...])` (dopo la riga `st.Page(mutui.render, ...)`):

```python
        st.Page(cashflow.render, title="Cashflow", icon="💸", url_path="cashflow"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_hub_cashflow_mount.py -v`
Expected: PASS.

- [ ] **Step 6: Verify hub app still parses**

Run: `python -c "import ast; ast.parse(open('verticals/hub/app.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add verticals/hub/pages_/cashflow.py verticals/hub/app.py tests/test_hub_cashflow_mount.py
git commit -m "feat(hub): monta la pagina Cashflow nel viewer"
```

---

## Task 4: Deprecazione `app_scadenzario` + `tesoreria`

Banner di deprecazione che puntano alla nuova app. **Nessuna cancellazione.**

**Files:**
- Modify: `verticals/condges/app_scadenzario.py` (docstring + `st.warning` in `main()`)
- Modify: `verticals/condges/tesoreria.py` (docstring + `st.warning` nel render/main)
- Test: `tests/test_deprecations.py`

**Interfaces:**
- Produces: marker testuale `DEPRECATO` nei due file (verificabile).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deprecations.py
from pathlib import Path


def test_app_scadenzario_deprecated():
    src = Path("verticals/condges/app_scadenzario.py").read_text()
    assert "DEPRECATO" in src and "app_cashflow" in src


def test_tesoreria_deprecated():
    src = Path("verticals/condges/tesoreria.py").read_text()
    assert "DEPRECATO" in src and "app_cashflow" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_deprecations.py -v`
Expected: FAIL — marker assente.

- [ ] **Step 3: Add deprecation banner to `app_scadenzario.py`**

Prependi al docstring di modulo (prima riga dopo `#!/usr/bin/env python3`), trasformando la riga `"""Scadenzario -> PF Updater (Streamlit).` in:

```python
"""DEPRECATO — usare il vertical Cashflow (verticals/condges/app_cashflow.py, hub).

Questo path scrive le scadenze nel PF senza la rotation completa (no azzeramento
mese chiuso, no controlli). Sostituito da app_cashflow che wrappa pf_rotate.rotate().

Scadenzario -> PF Updater (Streamlit).
```

E in `main()` (subito dopo `st.title(...)`, riga ~471), inserisci:

```python
    st.warning(
        "⚠️ App DEPRECATA — usa il vertical **Cashflow** nel hub "
        "(`app_cashflow`, rotation completa con controlli)."
    )
```

- [ ] **Step 4: Add deprecation banner to `tesoreria.py`**

Prependi al docstring di modulo la riga:

```python
"""DEPRECATO — usare il vertical Cashflow (verticals/condges/app_cashflow.py, hub).
```

(mantenendo il resto del docstring esistente sotto). Poi, subito dopo il primo
`st.title(...)` o `st.header(...)` dell'app (cerca con `grep -n "st.title\|st.header" verticals/condges/tesoreria.py` e usa la prima occorrenza), inserisci:

```python
    st.warning("⚠️ App DEPRECATA — usa il vertical **Cashflow** nel hub.")
```

Se `tesoreria.py` non ha un `st.title/header` in cima, inserisci lo `st.warning` come prima chiamata Streamlit del flusso principale.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_deprecations.py -v`
Expected: PASS.

- [ ] **Step 6: Verify both parse**

Run: `python -c "import ast; [ast.parse(open(f).read()) for f in ['verticals/condges/app_scadenzario.py','verticals/condges/tesoreria.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add verticals/condges/app_scadenzario.py verticals/condges/tesoreria.py tests/test_deprecations.py
git commit -m "chore(condges): deprecazione app_scadenzario + tesoreria → vertical Cashflow"
```

---

## Task 5: Green finale (lint + suite) + smoke manuale documentato

**Files:** nessuno nuovo.

- [ ] **Step 1: Ruff format + check SOLO sui file della slice**

Run (un path per argomento; zsh non fa word-splitting):
```bash
ruff format core/config.py core/schemas.py verticals/condges/services/intents.py verticals/condges/services/cash_pf_service.py verticals/condges/app_cashflow.py verticals/hub/pages_/cashflow.py verticals/hub/app.py verticals/condges/app_scadenzario.py verticals/condges/tesoreria.py tests/test_cash_pf_service.py tests/test_app_cashflow.py tests/test_hub_cashflow_mount.py tests/test_deprecations.py
ruff check core/config.py core/schemas.py verticals/condges/services/ verticals/condges/app_cashflow.py verticals/hub/pages_/cashflow.py verticals/hub/app.py tests/test_cash_pf_service.py tests/test_app_cashflow.py tests/test_hub_cashflow_mount.py tests/test_deprecations.py
```
Expected: format tocca solo questi file; `ruff check` → All checks passed. **NON** lanciare `ruff format .` (riformatta 95 file pre-esistenti — vedi slice precedente).

- [ ] **Step 2: Full suite**

Run: `python -m pytest -q`
Expected: tutti verdi (inclusi i 4 nuovi file di test; `pf_rotate` invariato).

- [ ] **Step 3: Smoke import delle surface**

Run: `python -c "import ast; [ast.parse(open(f).read()) for f in ['verticals/condges/app_cashflow.py','verticals/hub/pages_/cashflow.py','verticals/hub/app.py']]; print('surfaces parse OK')"`
Expected: `surfaces parse OK`

- [ ] **Step 4: Commit (se ruff ha riformattato)**

```bash
git add core/config.py core/schemas.py verticals/condges/services/intents.py verticals/condges/services/cash_pf_service.py verticals/condges/app_cashflow.py verticals/hub/pages_/cashflow.py verticals/condges/app_scadenzario.py verticals/condges/tesoreria.py tests/test_cash_pf_service.py tests/test_app_cashflow.py tests/test_hub_cashflow_mount.py tests/test_deprecations.py
git commit -m "chore(condges): ruff format cashflow vertical slice" || echo "nothing to commit"
```

---

## Smoke manuale (fuori dal piano automatico)

Richiede i file reali (Desktop) + auth BQ; non automatizzabile in CI.

1. **Engine su dati reali**: con i file `ORTI_PF_2026_04.xlsx` + `ORTI_situazionepartitefornitori.xlsx`, esegui `hotelops pf-rotate --pf … --scad … --societa ORTI --mese-chiuso 4 --unmapped-policy skip` → verifica che generi un `_post-rotate_` e riporti i controlli (atteso ~22 OK, 1 ERR sotto investigazione).
2. **App hub**: `streamlit run verticals/hub/app.py` → pagina **Cashflow** → carica PF+scadenziario, conferma saldi, genera → scarica il PF, verifica scaduto/progressivo mostrati e la riga in `f_cash_projection_runs` (`bq query "SELECT * FROM hotelops.f_cash_projection_runs ORDER BY data_caricamento DESC LIMIT 5"`).

## Definition of Done

- App `Cashflow` montata nel hub (pagina + nav), `render()` gira.
- Genera il PF del mese successivo via `rotate()` canonico (upload PF+scadenziario, saldi pre-fill BQ editabili, policy default skip), con download.
- Ogni run riuscito logga `f_cash_projection_runs` via gate I1 (snapshot idempotente).
- Controlli mostrati come riportati da `rotate()` (no fix `step5` in questa slice).
- `app_scadenzario`/`tesoreria` deprecati (banner), non cancellati.
- `python -m pytest -q` e `ruff check` (file slice) verdi.

## Out of scope (follow-up, NON in questo piano)

- Control discrepancy J/cutover (systematic-debugging) + riconciliazione conteggio + label header stale.
- Statefulness/auto-load ultimo PF, vista storica mese×mese, supplier-mapping UX in-UI, storage GCS, card vetrina, BQ authority (Metà B completa).
