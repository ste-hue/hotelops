# F&B Dashboard Streamlit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dashboard Streamlit di monitoraggio operativo F&B (sostituisce i dashboard Looker mai aggiornati), hub-ready: logica in funzioni importabili, entry point sottile.

**Architecture:** 3 file nuovi in `verticals/condges/` — `fb_data.py` (data layer puro: query BQ + helper testabili, zero Streamlit), `fb_dashboard.py` (presentazione: `render()` con 3 tab, cache `st.cache_data` qui), `app_fb.py` (entry standalone ~10 righe). Il hub futuro importerà `render()`. Più 5 costanti nuove in `core/config.py`.

**Tech Stack:** Python 3.11, pandas, google-cloud-bigquery (via `core.bq.client.get_client()`), Streamlit, Plotly, pytest.

**Spec:** `docs/superpowers/specs/2026-06-12-fb-dashboard-streamlit-design.md`

**Ordine vincolato:** il tab "Stagione in corso" (Task 4) è il primo deliverable usabile — Stefano lo testa con giugno in corso. KPI e Dettaglio seguono.

**Convenzione commit:** ogni commit termina con la riga `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Stagiare SOLO i file indicati per nome (mai `git add .`).

---

## Contratti dati (riferimento, già verificati su BQ)

- `v_fb_kpi` (mensile): `anno, mese, periodo(DATE), costo_breakfast, costo_ristorante, costo_bar, costo_fb_totale, pax_breakfast, pax_lunch, pax_dinner, coperti_hotel, ricavi_breakfast, ricavi_food, ricavi_beverage, ricavi_fb_totali, ricavi_room_totali, food_cost_pct_breakfast, costo_per_pax_breakfast, ricavo_per_pax_breakfast, food_cost_pct_ristorante, costo_per_pax_ristorante, food_cost_pct_bar, food_cost_pct, euro_per_pasto, costo_fb_totale_ap, coperti_hotel_ap, ricavi_fb_totali_ap, ricavi_room_totali_ap`.
  ⚠️ Non esistono colonne `_ap` per i pct per bucket: i delta YoY sulle metric card si mostrano solo dove calcolabili (€/pasto via `costo_fb_totale_ap/coperti_hotel_ap`).
  ⚠️ Mese in corso (es. giugno 2026): `coperti_hotel > 0` ma `costo_fb_totale == 0` perché consumi/ricavi mensili arrivano a fine mese → regola n/d.
- `v_fb_consumi` (anno×mese×reparto×codice_prodotto): `anno, mese, periodo, reparto_id, is_fb_reparto(BOOL), is_anomalia(BOOL), classe, categoria_prodotto, codice_prodotto, descrizione, quantita, costo, prezzo_unitario, costo_ap, quantita_ap, prezzo_unitario_ap, delta_costo, effetto_prezzo, effetto_volume, costo_yoy_pct`.
- `v_fb_ricavi` (societa×BU×anno×mese×codice): `..., codice, descrizione, classe, tipo_pasto, categoria_fb, netto, lordo, coperti_bu, ricavo_netto_per_coperto, netto_ap, netto_yoy_pct`. Filtrare `classe='02FB'` per l'F&B.
- `v_fb_pasti` (anno×mese×societa×BU×tipo_pasto×tipo_ospite): `..., is_staff(BOOL), n_coperti, n_coperti_ap, coperti_yoy_pct`.
- `f_produzione_pms` (giornaliera): `societa_id, business_unit_id, data(DATE), anno, mese, classe, importo_imponibile(NUMERIC)`. F&B = `classe='02FB'`.
- `f_vendite_fb` (giornaliera): `..., data_servizio(DATE), sala, codice_articolo, descrizione, tipo_piatto, quantita, importo_netto, segmento_cliente`.
- `f_coperti_giornalieri`: `societa_id, anno, mese, data_servizio(DATE), tipo_pasto, tipo_ospite, business_unit_id, n_coperti`.
- `f_consumi_economato` / `f_ricavi_fb`: mensili (`anno`, `mese`), usate solo per freshness qui.

---

### Task 1: Costanti config F&B

**Files:**
- Modify: `core/config.py`

- [ ] **Step 1: Aggiungi le costanti**

In `core/config.py`, dopo la riga `F_RISTOCUBE_ORDERS          = _t("f_ristocube_orders")` aggiungi:

```python
F_VENDITE_FB                = _t("f_vendite_fb")
```

In fondo alla sezione `# Looker Studio views` (dopo `V_BUDGET`) aggiungi:

```python
V_FB_KPI                     = _t("v_fb_kpi")
V_FB_CONSUMI                 = _t("v_fb_consumi")
V_FB_RICAVI                  = _t("v_fb_ricavi")
V_FB_PASTI                   = _t("v_fb_pasti")
```

- [ ] **Step 2: Verifica import**

Run: `python -c "from core.config import F_VENDITE_FB, V_FB_KPI, V_FB_CONSUMI, V_FB_RICAVI, V_FB_PASTI; print(V_FB_KPI)"`
Expected: `hotelops-suite.hotelops.v_fb_kpi`

- [ ] **Step 3: Commit**

```bash
git add core/config.py
git commit -m "feat(config): costanti F_VENDITE_FB + viste v_fb_* per dashboard F&B

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Helper puri in `fb_data` (TDD)

**Files:**
- Create: `verticals/condges/fb_data.py`
- Test: `tests/test_fb_dashboard.py`

- [ ] **Step 1: Scrivi i test (falliranno)**

Crea `tests/test_fb_dashboard.py`:

```python
"""Test funzioni pure dashboard F&B — nessuna chiamata BQ."""
from datetime import date

import pandas as pd

from verticals.condges import fb_data


class TestAlignYoyDaily:
    def test_same_day_match(self):
        df = pd.DataFrame([
            {"data": date(2025, 6, 10), "ricavi": 100.0},
            {"data": date(2026, 6, 10), "ricavi": 150.0},
        ])
        out = fb_data.align_yoy_daily(df)
        r = out[out["data"] == date(2026, 6, 10)].iloc[0]
        assert r["ricavi_ap"] == 100.0

    def test_no_prior_year(self):
        df = pd.DataFrame([{"data": date(2026, 6, 10), "ricavi": 150.0}])
        out = fb_data.align_yoy_daily(df)
        assert pd.isna(out.iloc[0]["ricavi_ap"])

    def test_leap_day_dropped(self):
        # 29/02/2024 non ha corrispondente nel 2025: non deve matchare né esplodere
        df = pd.DataFrame([
            {"data": date(2024, 2, 29), "ricavi": 80.0},
            {"data": date(2025, 2, 28), "ricavi": 90.0},
        ])
        out = fb_data.align_yoy_daily(df)
        r = out[out["data"] == date(2025, 2, 28)].iloc[0]
        assert pd.isna(r["ricavi_ap"])

    def test_preserva_righe_correnti(self):
        df = pd.DataFrame([
            {"data": date(2025, 6, 1), "ricavi": 1.0},
            {"data": date(2026, 6, 1), "ricavi": 2.0},
            {"data": date(2026, 6, 2), "ricavi": 3.0},
        ])
        out = fb_data.align_yoy_daily(df)
        assert len(out) == len(df)


class TestFreshnessBadge:
    OGGI = date(2026, 6, 12)

    def test_giornaliera_fresca(self):
        assert fb_data.freshness_badge("giornaliera", "2026-06-12", self.OGGI) == "✅"

    def test_giornaliera_3gg_ancora_ok(self):
        assert fb_data.freshness_badge("giornaliera", "2026-06-09", self.OGGI) == "✅"

    def test_giornaliera_stale(self):
        assert fb_data.freshness_badge("giornaliera", "2026-06-08", self.OGGI) == "⚠️"

    def test_mensile_mese_chiuso_presente(self):
        assert fb_data.freshness_badge("mensile", "2026-05", self.OGGI) == "✅"

    def test_mensile_stale(self):
        assert fb_data.freshness_badge("mensile", "2026-04", self.OGGI) == "⚠️"

    def test_mensile_gia_al_mese_corrente(self):
        assert fb_data.freshness_badge("mensile", "2026-06", self.OGGI) == "✅"


class TestKpiOrNd:
    def test_normale(self):
        assert fb_data.kpi_or_nd(0.261, 24572.9, 4377) == "26.1%"

    def test_consumi_mensili_mancanti(self):
        # giugno in corso: coperti ci sono, consumi no -> n/d, mai 0%
        assert fb_data.kpi_or_nd(None, 0.0, 1896) == "n/d"

    def test_mese_vuoto(self):
        assert fb_data.kpi_or_nd(None, 0.0, 0) == "—"

    def test_pct_null_con_costi(self):
        assert fb_data.kpi_or_nd(None, 100.0, 10) == "n/d"
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_fb_dashboard.py -v`
Expected: errore di import `fb_data` / `ModuleNotFoundError` o `AttributeError`.

- [ ] **Step 3: Implementa gli helper**

Crea `verticals/condges/fb_data.py`:

```python
"""Data layer dashboard F&B — query BQ + helper puri. Zero Streamlit.

Importabile dal futuro hub (verticals/hub/) e da fb_dashboard.render().
Spec: docs/superpowers/specs/2026-06-12-fb-dashboard-streamlit-design.md
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def align_yoy_daily(df: pd.DataFrame, date_col: str = "data") -> pd.DataFrame:
    """Aggiunge colonne ``<col>_ap`` allineate allo stesso giorno-calendario
    dell'anno precedente. Il 29/02 non ha corrispondente nell'anno non
    bisestile e viene scartato dal lato anno-precedente.
    """

    def _plus_one_year(d: date) -> date | None:
        try:
            return d.replace(year=d.year + 1)
        except ValueError:  # 29/02 -> anno successivo non bisestile
            return None

    prev = df.copy()
    prev[date_col] = prev[date_col].map(_plus_one_year)
    prev = prev.dropna(subset=[date_col])
    value_cols = [c for c in df.columns if c != date_col]
    prev = prev.rename(columns={c: f"{c}_ap" for c in value_cols})
    return df.merge(prev, on=date_col, how="left")


def freshness_badge(granularita: str, ultimo_dato: str, oggi: date) -> str:
    """⚠️ se la fonte è indietro: giornaliera >3 giorni, mensile se manca
    l'ultimo mese chiuso. ``ultimo_dato``: 'YYYY-MM-DD' o 'YYYY-MM'."""
    if granularita == "giornaliera":
        ritardo = (oggi - date.fromisoformat(ultimo_dato)).days
        return "⚠️" if ritardo > 3 else "✅"
    anno, mese = (int(p) for p in ultimo_dato.split("-"))
    ultimo_chiuso = oggi.replace(day=1) - timedelta(days=1)
    indietro = (anno, mese) < (ultimo_chiuso.year, ultimo_chiuso.month)
    return "⚠️" if indietro else "✅"


def kpi_or_nd(pct: float | None, costo_totale: float, coperti: int) -> str:
    """Formatta un KPI %: 'n/d' se i consumi mensili non sono ancora caricati
    (costo 0 ma coperti presenti), '—' se il mese è proprio vuoto."""
    if not costo_totale:
        return "n/d" if coperti else "—"
    if pct is None or pd.isna(pct):
        return "n/d"
    return f"{pct * 100:.1f}%"
```

- [ ] **Step 4: Verifica che passino**

Run: `pytest tests/test_fb_dashboard.py -v`
Expected: 14 PASS.

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/fb_data.py tests/test_fb_dashboard.py
git commit -m "feat(fb): helper puri dashboard F&B (YoY same-day, freshness badge, regola n/d)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Query functions in `fb_data`

**Files:**
- Modify: `verticals/condges/fb_data.py`

Le query sono SELECT sottili su viste/tabelle già testate a livello BQ: niente unit test (la suite non chiama BQ), verifica manuale a fine task.

- [ ] **Step 1: Aggiungi import e runner query**

In cima a `fb_data.py`, sotto gli import esistenti, aggiungi:

```python
from core.bq.client import get_client
from core.config import (
    F_CONSUMI_ECONOMATO,
    F_COPERTI_GIORNALIERI,
    F_PRODUZIONE_PMS,
    F_RICAVI_FB,
    F_RISTOCUBE_ORDERS,
    F_VENDITE_FB,
    V_FB_CONSUMI,
    V_FB_KPI,
    V_FB_PASTI,
    V_FB_RICAVI,
)


def _q(sql: str) -> pd.DataFrame:
    return get_client().query(sql).to_dataframe()
```

- [ ] **Step 2: Aggiungi le query mensili (4 viste)**

In fondo a `fb_data.py`:

```python
def kpi_mensili(anno: int) -> pd.DataFrame:
    """KPI F&B mensili da v_fb_kpi (3 bucket onesti + colonne _ap)."""
    return _q(f"SELECT * FROM `{V_FB_KPI}` WHERE anno = {int(anno)} ORDER BY mese")


def consumi(anno: int, solo_fb: bool = True) -> pd.DataFrame:
    """Costo merce per prodotto da v_fb_consumi.

    Default: solo reparti F&B e senza righe anomale (storni UoM mag-2025).
    """
    where = f"anno = {int(anno)}"
    if solo_fb:
        where += " AND is_fb_reparto AND NOT is_anomalia"
    return _q(
        f"SELECT * FROM `{V_FB_CONSUMI}` WHERE {where} ORDER BY mese, costo DESC"
    )


def ricavi_codici(anno: int) -> pd.DataFrame:
    """Ricavi produzione netta per codice da v_fb_ricavi (tutte le classi)."""
    return _q(
        f"SELECT * FROM `{V_FB_RICAVI}` WHERE anno = {int(anno)} "
        "ORDER BY mese, netto DESC"
    )


def pasti(anno: int) -> pd.DataFrame:
    """Coperti pasto mensili da v_fb_pasti (is_staff esposto, non sommato)."""
    return _q(f"SELECT * FROM `{V_FB_PASTI}` WHERE anno = {int(anno)} ORDER BY mese")
```

- [ ] **Step 3: Aggiungi le query giornaliere e freshness**

Sempre in fondo a `fb_data.py`:

```python
def stagione_giornaliera(anno: int) -> pd.DataFrame:
    """Una riga per giorno dell'anno: ricavi F&B PMS (classe 02FB), vendite
    POS, coperti. Colonne ``*_ap`` = stesso giorno-calendario anno precedente
    (allineamento in pandas via align_yoy_daily)."""
    sql = f"""
    WITH prod AS (
      SELECT data, SUM(importo_imponibile) AS ricavi_fb_pms
      FROM `{F_PRODUZIONE_PMS}`
      WHERE classe = '02FB'
      GROUP BY data
    ), pos AS (
      SELECT data_servizio AS data, SUM(importo_netto) AS vendite_pos
      FROM `{F_VENDITE_FB}`
      GROUP BY 1
    ), cop AS (
      SELECT data_servizio AS data, SUM(n_coperti) AS coperti
      FROM `{F_COPERTI_GIORNALIERI}`
      GROUP BY 1
    ), giorni AS (
      SELECT data FROM prod
      UNION DISTINCT SELECT data FROM pos
      UNION DISTINCT SELECT data FROM cop
    )
    SELECT g.data, p.ricavi_fb_pms, v.vendite_pos, c.coperti
    FROM giorni g
    LEFT JOIN prod p USING (data)
    LEFT JOIN pos v USING (data)
    LEFT JOIN cop c USING (data)
    WHERE EXTRACT(YEAR FROM g.data) IN ({int(anno)}, {int(anno) - 1})
    ORDER BY g.data
    """
    df = _q(sql)
    df["data"] = pd.to_datetime(df["data"]).dt.date
    for col in ("ricavi_fb_pms", "vendite_pos", "coperti"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    aligned = align_yoy_daily(df, "data")
    correnti = aligned["data"].map(lambda d: d.year) == int(anno)
    return aligned[correnti].reset_index(drop=True)


def coperti_giornalieri(anno: int) -> pd.DataFrame:
    """Coperti per giorno × tipo_pasto (anno corrente)."""
    return _q(f"""
    SELECT data_servizio AS data, tipo_pasto, SUM(n_coperti) AS coperti
    FROM `{F_COPERTI_GIORNALIERI}`
    WHERE anno = {int(anno)}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """)


def vendite_per_sala(anno: int, ultimi_giorni: int = 30) -> pd.DataFrame:
    """Vendite POS giorno × sala, ultimi N giorni con dati."""
    return _q(f"""
    SELECT data_servizio AS data, sala, SUM(importo_netto) AS netto
    FROM `{F_VENDITE_FB}`
    WHERE anno = {int(anno)}
      AND data_servizio >= DATE_SUB(
        (SELECT MAX(data_servizio) FROM `{F_VENDITE_FB}` WHERE anno = {int(anno)}),
        INTERVAL {int(ultimi_giorni)} DAY)
    GROUP BY 1, 2
    ORDER BY 1, 2
    """)


def freshness() -> pd.DataFrame:
    """Ultima data disponibile per fonte F&B.

    Colonne: tabella, granularita ('giornaliera'|'mensile'), ultimo_dato
    ('YYYY-MM-DD' o 'YYYY-MM') — formato consumato da freshness_badge.
    """
    return _q(f"""
    SELECT 'coperti giornalieri' AS tabella, 'giornaliera' AS granularita,
           CAST(MAX(data_servizio) AS STRING) AS ultimo_dato
    FROM `{F_COPERTI_GIORNALIERI}`
    UNION ALL
    SELECT 'vendite POS', 'giornaliera', CAST(MAX(data_servizio) AS STRING)
    FROM `{F_VENDITE_FB}`
    UNION ALL
    SELECT 'comande RistoCube', 'giornaliera', CAST(MAX(data) AS STRING)
    FROM `{F_RISTOCUBE_ORDERS}`
    UNION ALL
    SELECT 'produzione PMS', 'giornaliera', CAST(MAX(data) AS STRING)
    FROM `{F_PRODUZIONE_PMS}`
    UNION ALL
    SELECT 'consumi economato', 'mensile',
           FORMAT('%d-%02d', MAX(anno), MAX_BY(mese, anno * 100 + mese))
    FROM `{F_CONSUMI_ECONOMATO}`
    UNION ALL
    SELECT 'ricavi F&B mensili', 'mensile',
           FORMAT('%d-%02d', MAX(anno), MAX_BY(mese, anno * 100 + mese))
    FROM `{F_RICAVI_FB}`
    ORDER BY granularita, tabella
    """)
```

- [ ] **Step 4: Verifica suite ancora verde**

Run: `pytest tests/test_fb_dashboard.py -v`
Expected: 14 PASS (gli helper non sono cambiati; l'import del modulo non deve rompersi).

- [ ] **Step 5: Verifica manuale contro BQ**

Run:

```bash
python -c "
from verticals.condges import fb_data
f = fb_data.freshness()
print(f.to_string(index=False))
df = fb_data.stagione_giornaliera(2026)
print(df.tail(8).to_string(index=False))
print('giorni 2026:', len(df), '| coperti tot:', df['coperti'].sum())
"
```

Expected (al 2026-06-12): freshness con 6 righe — coperti `2026-06-12`, vendite POS `2026-06-08`, produzione PMS `2026-06-04`, consumi/ricavi `2026-05`; stagione con ultime righe a giugno 2026, colonne `ricavi_fb_pms_ap`/`coperti_ap` popolate per i giorni con corrispondente 2025.

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/fb_data.py
git commit -m "feat(fb): query layer dashboard F&B (4 viste mensili + giornaliere + freshness)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Tab "Stagione in corso" + scheletro `render()` + `app_fb.py`

**Files:**
- Create: `verticals/condges/fb_dashboard.py`
- Create: `verticals/condges/app_fb.py`
- Test: `tests/test_fb_dashboard.py` (sezione figure)

**Primo deliverable usabile** — al termine Stefano può lanciare l'app e seguire giugno.

- [ ] **Step 1: Scrivi i test delle figure (falliranno)**

In cima a `tests/test_fb_dashboard.py`, sotto gli import esistenti, aggiungi (così ruff non segnala E402; `importorskip` salta i test figure se streamlit non è installato):

```python
import plotly.graph_objects as go
import pytest

fb_dashboard = pytest.importorskip("verticals.condges.fb_dashboard")
```

Poi appendi in fondo al file:

```python
def _df_stagione() -> pd.DataFrame:
    return pd.DataFrame({
        "data": [date(2026, 6, 1), date(2026, 6, 2)],
        "ricavi_fb_pms": [100.0, 200.0],
        "vendite_pos": [50.0, 60.0],
        "coperti": [10.0, 20.0],
        "ricavi_fb_pms_ap": [90.0, None],
        "vendite_pos_ap": [40.0, None],
        "coperti_ap": [8.0, None],
    })


class TestFigStagione:
    def test_fig_ricavi_giornalieri(self):
        fig = fb_dashboard.fig_ricavi_giornalieri(_df_stagione())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2  # anno corrente + anno precedente

    def test_fig_cumulato(self):
        fig = fb_dashboard.fig_cumulato(_df_stagione())
        assert isinstance(fig, go.Figure)
        # il cumulato corrente all'ultimo giorno = somma dei ricavi
        assert fig.data[0].y[-1] == 300.0

    def test_fig_coperti_tipo_pasto(self):
        df = pd.DataFrame({
            "data": [date(2026, 6, 1), date(2026, 6, 1)],
            "tipo_pasto": ["COLAZIONE", "CENA"],
            "coperti": [50, 30],
        })
        fig = fb_dashboard.fig_coperti_tipo_pasto(df)
        assert isinstance(fig, go.Figure)

    def test_fig_vendite_sala(self):
        df = pd.DataFrame({
            "data": [date(2026, 6, 1)],
            "sala": ["RISTORANTE"],
            "netto": [500.0],
        })
        fig = fb_dashboard.fig_vendite_sala(df)
        assert isinstance(fig, go.Figure)

    def test_fig_su_df_vuoto_non_esplode(self):
        vuoto = _df_stagione().iloc[0:0]
        assert isinstance(fb_dashboard.fig_ricavi_giornalieri(vuoto), go.Figure)
        assert isinstance(fb_dashboard.fig_cumulato(vuoto), go.Figure)
```

- [ ] **Step 2: Verifica che non passino ancora**

Run: `pytest tests/test_fb_dashboard.py -v`
Expected: i 14 test helper PASS, i 5 nuovi **SKIPPED** (`importorskip`: il modulo `fb_dashboard` non esiste ancora). Dopo lo Step 3 dovranno risultare PASS — se restano SKIPPED qualcosa è rotto nell'import.

- [ ] **Step 3: Implementa `fb_dashboard.py`**

Crea `verticals/condges/fb_dashboard.py`:

```python
"""Dashboard F&B — presentazione Streamlit. Logica dati in fb_data.

Il hub importa: ``from verticals.condges.fb_dashboard import render``.
render() NON chiama st.set_page_config (lo fa solo app_fb.py).
Run standalone: streamlit run verticals/condges/app_fb.py
Spec: docs/superpowers/specs/2026-06-12-fb-dashboard-streamlit-design.md
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from verticals.condges import fb_data

# --- cache layer (vive qui: fb_data resta importabile senza Streamlit) ----


@st.cache_data(ttl=300)
def _stagione(anno: int) -> pd.DataFrame:
    return fb_data.stagione_giornaliera(anno)


@st.cache_data(ttl=300)
def _coperti_giorno(anno: int) -> pd.DataFrame:
    return fb_data.coperti_giornalieri(anno)


@st.cache_data(ttl=300)
def _vendite_sala(anno: int) -> pd.DataFrame:
    return fb_data.vendite_per_sala(anno)


@st.cache_data(ttl=300)
def _freshness() -> pd.DataFrame:
    return fb_data.freshness()


# --- figure pure (testabili senza Streamlit) -------------------------------


def fig_ricavi_giornalieri(df: pd.DataFrame) -> go.Figure:
    """Ricavi F&B PMS (classe 02FB) giorno per giorno, vs anno precedente."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["data"], y=df["ricavi_fb_pms"], name="anno corrente", mode="lines"))
    fig.add_trace(go.Scatter(
        x=df["data"], y=df["ricavi_fb_pms_ap"], name="anno precedente",
        mode="lines", line={"dash": "dot"}))
    fig.update_layout(title="Ricavi F&B giornalieri (PMS 02FB)",
                      yaxis_tickformat=",.0f")
    return fig


def fig_cumulato(df: pd.DataFrame) -> go.Figure:
    """Ricavi F&B cumulati, confronto a parità di giorni col dato AP."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["data"], y=df["ricavi_fb_pms"].fillna(0).cumsum(),
        name="cumulato anno corrente", mode="lines"))
    fig.add_trace(go.Scatter(
        x=df["data"], y=df["ricavi_fb_pms_ap"].fillna(0).cumsum(),
        name="cumulato anno precedente", mode="lines", line={"dash": "dot"}))
    fig.update_layout(title="Ricavi F&B cumulati", yaxis_tickformat=",.0f")
    return fig


def fig_coperti_tipo_pasto(df: pd.DataFrame) -> go.Figure:
    return px.bar(df, x="data", y="coperti", color="tipo_pasto",
                  title="Coperti giornalieri per tipo pasto")


def fig_vendite_sala(df: pd.DataFrame) -> go.Figure:
    fig = px.bar(df, x="data", y="netto", color="sala",
                 title="Vendite POS per sala — ultimi 30 giorni")
    fig.update_layout(yaxis_tickformat=",.0f")
    return fig


# --- sezioni ---------------------------------------------------------------


def render_stagione(anno: int, oggi: date) -> None:
    fresh = _freshness()
    cols = st.columns(len(fresh))
    for col, row in zip(cols, fresh.itertuples(index=False)):
        badge = fb_data.freshness_badge(row.granularita, row.ultimo_dato, oggi)
        col.metric(f"{badge} {row.tabella}", row.ultimo_dato)
    st.caption(
        "⚠️ giornaliera = indietro di più di 3 giorni (serve nuovo export); "
        "mensile = manca l'ultimo mese chiuso."
    )

    df = _stagione(anno)
    if df.empty:
        st.info(f"Nessun dato giornaliero per il {anno}.")
        return
    st.plotly_chart(fig_ricavi_giornalieri(df), use_container_width=True)
    st.plotly_chart(fig_cumulato(df), use_container_width=True)
    c1, c2 = st.columns(2)
    c1.plotly_chart(fig_coperti_tipo_pasto(_coperti_giorno(anno)),
                    use_container_width=True)
    c2.plotly_chart(fig_vendite_sala(_vendite_sala(anno)),
                    use_container_width=True)


def render_kpi(anno: int) -> None:
    st.info("KPI mensili — in arrivo (Task 5).")


def render_dettaglio(anno: int) -> None:
    st.info("Dettaglio mensile — in arrivo (Task 6).")


# --- entry -----------------------------------------------------------------


def render() -> None:
    """Entry importabile dal hub. Nessun set_page_config qui."""
    st.title("🍽️ F&B — monitoraggio operativo")
    oggi = date.today()
    anno = int(st.selectbox(
        "Anno", list(range(oggi.year, 2024, -1)), index=0, key="fb_anno"))
    tab_stagione, tab_kpi, tab_dettaglio = st.tabs(
        ["🌊 Stagione in corso", "📊 KPI mensili", "🔍 Dettaglio mensile"])
    with tab_stagione:
        render_stagione(anno, oggi)
    with tab_kpi:
        render_kpi(anno)
    with tab_dettaglio:
        render_dettaglio(anno)
```

- [ ] **Step 4: Implementa `app_fb.py`**

Crea `verticals/condges/app_fb.py`:

```python
"""Entry standalone dashboard F&B.

Run: streamlit run verticals/condges/app_fb.py
Il hub (verticals/hub/) NON usa questo file: importa fb_dashboard.render.
"""
import streamlit as st

from verticals.condges.fb_dashboard import render

st.set_page_config(page_title="F&B — Hotel Panorama", page_icon="🍽️",
                   layout="wide")
render()
```

- [ ] **Step 5: Verifica test**

Run: `pytest tests/test_fb_dashboard.py -v`
Expected: tutti PASS (14 helper + 5 figure).

- [ ] **Step 6: Smoke run dell'app**

Run: `timeout 60 streamlit run verticals/condges/app_fb.py --server.headless true & sleep 25 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8501 && kill %1`
Expected: `200`, nessun traceback nel log Streamlit. Poi verifica visiva: `streamlit run verticals/condges/app_fb.py` — banner freshness con 6 fonti, ricavi giornalieri giugno con linea 2025 tratteggiata, coperti fino a oggi.

- [ ] **Step 7: Commit**

```bash
git add verticals/condges/fb_dashboard.py verticals/condges/app_fb.py tests/test_fb_dashboard.py
git commit -m "feat(fb): dashboard Streamlit — tab Stagione in corso + banner freshness + entry hub-ready

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Tab "KPI mensili"

**Files:**
- Modify: `verticals/condges/fb_dashboard.py` (sostituisce il placeholder `render_kpi`)
- Test: `tests/test_fb_dashboard.py`

- [ ] **Step 1: Scrivi i test delle figure KPI (falliranno)**

Appendi a `tests/test_fb_dashboard.py`:

```python
def _df_kpi() -> pd.DataFrame:
    return pd.DataFrame({
        "anno": [2026, 2026],
        "mese": [5, 6],
        "periodo": [date(2026, 5, 1), date(2026, 6, 1)],
        "costo_fb_totale": [24572.9, 0.0],
        "coperti_hotel": [4377, 1896],
        "ricavi_breakfast": [38836.4, 0.0],
        "ricavi_food": [23042.7, 0.0],
        "ricavi_beverage": [20981.5, 0.0],
        "food_cost_pct_breakfast": [0.387, None],
        "food_cost_pct_ristorante": [0.261, None],
        "food_cost_pct_bar": [0.168, None],
        "euro_per_pasto": [5.61, 0.0],
        "costo_fb_totale_ap": [25812.9, 27285.2],
        "coperti_hotel_ap": [3271, 4461],
    })


class TestFigKpi:
    def test_fig_food_cost_mensile(self):
        fig = fb_dashboard.fig_food_cost_mensile(_df_kpi())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # breakfast / ristorante / bar

    def test_food_cost_maschera_mesi_senza_consumi(self):
        # giugno: costo_fb_totale 0 -> il punto deve essere None, non 0%
        fig = fb_dashboard.fig_food_cost_mensile(_df_kpi())
        for trace in fig.data:
            assert trace.y[-1] is None or pd.isna(trace.y[-1])

    def test_fig_ricavi_split(self):
        fig = fb_dashboard.fig_ricavi_split(_df_kpi())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # breakfast / food / beverage

    def test_fig_coperti_mensili(self):
        fig = fb_dashboard.fig_coperti_mensili(_df_kpi())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2  # anno corrente + precedente
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_fb_dashboard.py -v -k Kpi`
Expected: FAIL con `AttributeError: fig_food_cost_mensile`.

- [ ] **Step 3: Implementa figure + render_kpi**

In `fb_dashboard.py`, nella sezione figure, aggiungi:

```python
_BUCKETS_FC = {
    "food_cost_pct_breakfast": "Breakfast",
    "food_cost_pct_ristorante": "Ristorante",
    "food_cost_pct_bar": "Bar",
}


def fig_food_cost_mensile(df: pd.DataFrame) -> go.Figure:
    """Food cost % per bucket. Mesi senza consumi caricati -> buco, mai 0%."""
    plot = df.copy()
    senza_consumi = plot["costo_fb_totale"] == 0
    for col in _BUCKETS_FC:
        plot.loc[senza_consumi, col] = None
    fig = go.Figure()
    for col, label in _BUCKETS_FC.items():
        fig.add_trace(go.Scatter(x=plot["periodo"], y=plot[col], name=label,
                                 mode="lines+markers"))
    fig.update_layout(title="Food cost % per bucket", yaxis_tickformat=".0%")
    return fig


def fig_ricavi_split(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col, label in [("ricavi_breakfast", "Breakfast"),
                       ("ricavi_food", "Food"),
                       ("ricavi_beverage", "Beverage")]:
        fig.add_trace(go.Bar(x=df["periodo"], y=df[col], name=label))
    fig.update_layout(barmode="stack", title="Ricavi F&B per componente",
                      yaxis_tickformat=",.0f")
    return fig


def fig_coperti_mensili(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["periodo"], y=df["coperti_hotel"],
                         name="anno corrente"))
    fig.add_trace(go.Bar(x=df["periodo"], y=df["coperti_hotel_ap"],
                         name="anno precedente"))
    fig.update_layout(barmode="group", title="Coperti hotel per mese")
    return fig
```

Aggiungi il wrapper cache accanto agli altri:

```python
@st.cache_data(ttl=300)
def _kpi(anno: int) -> pd.DataFrame:
    return fb_data.kpi_mensili(anno)
```

Sostituisci il placeholder `render_kpi` con:

```python
def render_kpi(anno: int) -> None:
    df = _kpi(anno)
    if df.empty:
        st.info(f"Nessun KPI mensile per il {anno}.")
        return
    mesi = df["mese"].tolist()
    mese = st.selectbox("Mese", mesi, index=len(mesi) - 1, key="fb_kpi_mese")
    r = df[df["mese"] == mese].iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Food cost ristorante", fb_data.kpi_or_nd(
        r["food_cost_pct_ristorante"], r["costo_fb_totale"], r["coperti_hotel"]))
    c2.metric("Food cost bar", fb_data.kpi_or_nd(
        r["food_cost_pct_bar"], r["costo_fb_totale"], r["coperti_hotel"]))
    c3.metric("Food cost breakfast", fb_data.kpi_or_nd(
        r["food_cost_pct_breakfast"], r["costo_fb_totale"], r["coperti_hotel"]))

    # delta €/pasto vs AP: unico delta calcolabile dalle colonne _ap della vista
    delta_pasto = None
    if r["costo_fb_totale"] and r["coperti_hotel_ap"] and r["costo_fb_totale_ap"]:
        pasto_ap = r["costo_fb_totale_ap"] / r["coperti_hotel_ap"]
        delta_pasto = f"{r['euro_per_pasto'] - pasto_ap:+.2f} € vs AP"
    c4.metric(
        "€ / pasto",
        "n/d" if not r["costo_fb_totale"] else f"{r['euro_per_pasto']:.2f} €",
        delta=delta_pasto, delta_color="inverse")

    st.plotly_chart(fig_food_cost_mensile(df), use_container_width=True)
    col1, col2 = st.columns(2)
    col1.plotly_chart(fig_ricavi_split(df), use_container_width=True)
    col2.plotly_chart(fig_coperti_mensili(df), use_container_width=True)
```

- [ ] **Step 4: Verifica test**

Run: `pytest tests/test_fb_dashboard.py -v`
Expected: tutti PASS (helper + figure stagione + 4 figure KPI).

- [ ] **Step 5: Verifica visiva**

Run: `streamlit run verticals/condges/app_fb.py` → tab KPI mensili: maggio 2026 deve mostrare ristorante 26.1%, bar 16.8%, breakfast 38.7%; giugno deve mostrare "n/d", non 0%.

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/fb_dashboard.py tests/test_fb_dashboard.py
git commit -m "feat(fb): tab KPI mensili (metric card n/d-aware + serie food cost/ricavi/coperti)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Tab "Dettaglio mensile"

**Files:**
- Modify: `verticals/condges/fb_dashboard.py` (sostituisce il placeholder `render_dettaglio`)
- Test: `tests/test_fb_dashboard.py`

- [ ] **Step 1: Scrivi i test delle figure dettaglio (falliranno)**

Appendi a `tests/test_fb_dashboard.py`:

```python
class TestFigDettaglio:
    def test_fig_consumi_reparto(self):
        df = pd.DataFrame({
            "reparto_id": ["CUCINA", "CUCINA", "CANTINA"],
            "costo": [100.0, 50.0, 30.0],
        })
        fig = fb_dashboard.fig_consumi_reparto(df)
        assert isinstance(fig, go.Figure)

    def test_fig_ricavi_tipo_pasto(self):
        df = pd.DataFrame({
            "tipo_pasto": ["CENA", "BAR"],
            "categoria_fb": ["FOOD", "BEVERAGE"],
            "netto": [1000.0, 400.0],
        })
        fig = fb_dashboard.fig_ricavi_tipo_pasto(df)
        assert isinstance(fig, go.Figure)

    def test_fig_pasti_mensili(self):
        df = pd.DataFrame({
            "periodo": [date(2026, 5, 1), date(2026, 5, 1)],
            "tipo_pasto": ["COLAZIONE", "CENA"],
            "n_coperti": [3000, 400],
        })
        fig = fb_dashboard.fig_pasti_mensili(df)
        assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_fb_dashboard.py -v -k Dettaglio`
Expected: FAIL con `AttributeError: fig_consumi_reparto`.

- [ ] **Step 3: Implementa figure + render_dettaglio**

In `fb_dashboard.py`, sezione figure:

```python
def fig_consumi_reparto(df: pd.DataFrame) -> go.Figure:
    agg = df.groupby("reparto_id", as_index=False)["costo"].sum()
    fig = px.bar(agg, x="reparto_id", y="costo", title="Costo merce per reparto")
    fig.update_layout(yaxis_tickformat=",.0f")
    return fig


def fig_ricavi_tipo_pasto(df: pd.DataFrame) -> go.Figure:
    agg = df.groupby(["tipo_pasto", "categoria_fb"], as_index=False)["netto"].sum()
    fig = px.bar(agg, x="tipo_pasto", y="netto", color="categoria_fb",
                 title="Ricavi per tipo pasto (food vs beverage)")
    fig.update_layout(yaxis_tickformat=",.0f")
    return fig


def fig_pasti_mensili(df: pd.DataFrame) -> go.Figure:
    agg = df.groupby(["periodo", "tipo_pasto"], as_index=False)["n_coperti"].sum()
    return px.bar(agg, x="periodo", y="n_coperti", color="tipo_pasto",
                  title="Coperti mensili per tipo pasto")
```

Wrapper cache accanto agli altri:

```python
@st.cache_data(ttl=300)
def _consumi(anno: int) -> pd.DataFrame:
    return fb_data.consumi(anno)


@st.cache_data(ttl=300)
def _ricavi(anno: int) -> pd.DataFrame:
    return fb_data.ricavi_codici(anno)


@st.cache_data(ttl=300)
def _pasti(anno: int) -> pd.DataFrame:
    return fb_data.pasti(anno)
```

Sostituisci il placeholder `render_dettaglio` con:

```python
def render_dettaglio(anno: int) -> None:
    t_cons, t_ric, t_pasti = st.tabs(
        ["🥩 Consumi", "💶 Ricavi per codice", "🍽️ Pasti"])

    with t_cons:
        df = _consumi(anno)
        if df.empty:
            st.info(f"Nessun consumo F&B per il {anno}.")
        else:
            mesi = sorted(df["mese"].unique().tolist())
            mese = st.selectbox("Mese", mesi, index=len(mesi) - 1,
                                key="fb_cons_mese")
            dfm = df[df["mese"] == mese]
            st.plotly_chart(fig_consumi_reparto(dfm), use_container_width=True)
            st.markdown("**Top 20 prodotti per costo** — scomposizione "
                        "Δ = effetto prezzo + effetto volume")
            top = dfm.nlargest(20, "costo")[
                ["reparto_id", "codice_prodotto", "descrizione", "costo",
                 "delta_costo", "effetto_prezzo", "effetto_volume",
                 "costo_yoy_pct"]]
            st.dataframe(top, use_container_width=True, hide_index=True)

    with t_ric:
        df = _ricavi(anno)
        df = df[df["classe"] == "02FB"]
        if df.empty:
            st.info(f"Nessun ricavo F&B per il {anno}.")
        else:
            mesi = sorted(df["mese"].unique().tolist())
            mese = st.selectbox("Mese", mesi, index=len(mesi) - 1,
                                key="fb_ric_mese")
            dfm = df[df["mese"] == mese]
            st.plotly_chart(fig_ricavi_tipo_pasto(dfm), use_container_width=True)
            st.dataframe(
                dfm[["codice", "descrizione", "tipo_pasto", "categoria_fb",
                     "netto", "ricavo_netto_per_coperto", "netto_yoy_pct"]]
                .sort_values("netto", ascending=False),
                use_container_width=True, hide_index=True)

    with t_pasti:
        df = _pasti(anno)
        if df.empty:
            st.info(f"Nessun coperto registrato per il {anno}.")
        else:
            staff = st.toggle("Includi staff (HQ)", value=False,
                              key="fb_pasti_staff")
            if not staff:
                df = df[~df["is_staff"]]
            st.plotly_chart(fig_pasti_mensili(df), use_container_width=True)
            pivot = df.pivot_table(index=["business_unit_id", "tipo_ospite"],
                                   columns="mese", values="n_coperti",
                                   aggfunc="sum", fill_value=0)
            st.dataframe(pivot, use_container_width=True)
```

- [ ] **Step 4: Verifica test**

Run: `pytest tests/test_fb_dashboard.py -v`
Expected: tutti PASS.

- [ ] **Step 5: Verifica visiva**

Run: `streamlit run verticals/condges/app_fb.py` → tab Dettaglio: consumi maggio con top prodotti e effetto prezzo/volume; ricavi per codice pasto; pasti con toggle staff.

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/fb_dashboard.py tests/test_fb_dashboard.py
git commit -m "feat(fb): tab Dettaglio mensile (consumi prezzo/volume, ricavi per codice, pasti)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Verifica finale + STATUS.md

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: Suite completa + lint**

Run: `pytest && ruff check . && ruff format --check .`
Expected: tutti i test PASS (625 baseline + ~26 nuovi), ruff pulito. Se `ruff format --check` segnala i file nuovi, esegui `ruff format verticals/condges/fb_data.py verticals/condges/fb_dashboard.py verticals/condges/app_fb.py tests/test_fb_dashboard.py` e ri-verifica i test.

- [ ] **Step 2: Aggiorna STATUS.md**

Nella sezione "Prossimi passi", sostituisci la riga sul Looker:

```
- **Aggiornare dashboard Looker F&B** al nuovo contratto colonne `v_fb_kpi` (...)
```

con:

```
- ~~Aggiornare dashboard Looker F&B~~ → **superato**: dashboard Streamlit F&B (`verticals/condges/app_fb.py`, hub-ready via `fb_dashboard.render()`) — spec `docs/superpowers/specs/2026-06-12-fb-dashboard-streamlit-design.md`. Looker abbandonato per l'F&B.
```

Nella sezione "In corso" aggiorna la riga F&B Looker pipeline sostituendo "Pendente: aggiornare dashboard Looker F&B al nuovo contratto colonne." con "Dashboard: Streamlit `app_fb.py` (2026-06-12, sostituisce Looker)."

- [ ] **Step 3: Commit**

```bash
git add STATUS.md
git commit -m "docs(status): dashboard F&B in Streamlit, Looker superato

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Smoke finale end-to-end**

Run: `streamlit run verticals/condges/app_fb.py`
Criterio di successo (verify-before-claiming-done): banner freshness coerente con BQ (coperti = oggi, vendite/comande 06-08, produzione 06-04, mensili 2026-05), maggio KPI = 26.1/16.8/38.7%, giugno = n/d, nessun traceback in console su tutti e 3 i tab.
