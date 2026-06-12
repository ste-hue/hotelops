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
