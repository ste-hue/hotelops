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


@st.cache_data(ttl=300)
def _kpi(anno: int) -> pd.DataFrame:
    return fb_data.kpi_mensili(anno)


@st.cache_data(ttl=300)
def _consumi(anno: int) -> pd.DataFrame:
    return fb_data.consumi(anno)


@st.cache_data(ttl=300)
def _ricavi(anno: int) -> pd.DataFrame:
    return fb_data.ricavi_codici(anno)


@st.cache_data(ttl=300)
def _pasti(anno: int) -> pd.DataFrame:
    return fb_data.pasti(anno)


# --- figure pure (testabili senza Streamlit) -------------------------------


def fig_ricavi_giornalieri(df: pd.DataFrame) -> go.Figure:
    """Ricavi F&B PMS (classe 02FB) giorno per giorno, vs anno precedente."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["data"], y=df["ricavi_fb_pms"], name="anno corrente", mode="lines"
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["data"],
            y=df["ricavi_fb_pms_ap"],
            name="anno precedente",
            mode="lines",
            line={"dash": "dot"},
        )
    )
    fig.update_layout(
        title="Ricavi F&B giornalieri (PMS 02FB)", yaxis_tickformat=",.0f"
    )
    return fig


def fig_cumulato(df: pd.DataFrame) -> go.Figure:
    """Ricavi F&B cumulati, confronto a parità di giorni col dato AP."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["data"],
            y=df["ricavi_fb_pms"].fillna(0).cumsum(),
            name="cumulato anno corrente",
            mode="lines",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["data"],
            y=df["ricavi_fb_pms_ap"].fillna(0).cumsum(),
            name="cumulato anno precedente",
            mode="lines",
            line={"dash": "dot"},
        )
    )
    fig.update_layout(title="Ricavi F&B cumulati", yaxis_tickformat=",.0f")
    return fig


def fig_coperti_tipo_pasto(df: pd.DataFrame) -> go.Figure:
    return px.bar(
        df,
        x="data",
        y="coperti",
        color="tipo_pasto",
        title="Coperti giornalieri per tipo pasto",
    )


def fig_vendite_sala(df: pd.DataFrame) -> go.Figure:
    fig = px.bar(
        df,
        x="data",
        y="netto",
        color="sala",
        title="Vendite POS per sala — ultimi 30 giorni",
    )
    fig.update_layout(yaxis_tickformat=",.0f")
    return fig


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
        fig.add_trace(
            go.Scatter(x=plot["periodo"], y=plot[col], name=label, mode="lines+markers")
        )
    fig.update_layout(title="Food & beverage cost % per bucket", yaxis_tickformat=".0%")
    return fig


def fig_ricavi_split(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col, label in [
        ("ricavi_breakfast", "Breakfast"),
        ("ricavi_food", "Food"),
        ("ricavi_beverage", "Beverage"),
    ]:
        fig.add_trace(go.Bar(x=df["periodo"], y=df[col], name=label))
    fig.update_layout(
        barmode="stack", title="Ricavi F&B per componente", yaxis_tickformat=",.0f"
    )
    return fig


def fig_coperti_mensili(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["periodo"], y=df["coperti_hotel"], name="anno corrente"))
    fig.add_trace(
        go.Bar(x=df["periodo"], y=df["coperti_hotel_ap"], name="anno precedente")
    )
    fig.update_layout(barmode="group", title="Coperti hotel per mese")
    return fig


def fig_consumi_reparto(df: pd.DataFrame) -> go.Figure:
    agg = df.groupby("reparto_id", as_index=False)["costo"].sum()
    fig = px.bar(agg, x="reparto_id", y="costo", title="Costo merce per reparto")
    fig.update_layout(yaxis_tickformat=",.0f")
    return fig


def fig_ricavi_tipo_pasto(df: pd.DataFrame) -> go.Figure:
    agg = df.groupby(["tipo_pasto", "categoria_fb"], as_index=False)["netto"].sum()
    fig = px.bar(
        agg,
        x="tipo_pasto",
        y="netto",
        color="categoria_fb",
        title="Ricavi per tipo pasto (food vs beverage)",
    )
    fig.update_layout(yaxis_tickformat=",.0f")
    return fig


def fig_pasti_mensili(df: pd.DataFrame) -> go.Figure:
    agg = df.groupby(["periodo", "tipo_pasto"], as_index=False)["n_coperti"].sum()
    return px.bar(
        agg,
        x="periodo",
        y="n_coperti",
        color="tipo_pasto",
        title="Coperti mensili per tipo pasto",
    )


# --- helpers puri ----------------------------------------------------------


def delta_euro_pasto(r: pd.Series) -> str | None:
    """Delta €/pasto vs anno precedente, None se non calcolabile (es. _ap NaN)."""
    if not r["costo_fb_totale"]:
        return None
    if pd.isna(r["coperti_hotel_ap"]) or pd.isna(r["costo_fb_totale_ap"]):
        return None
    if not r["coperti_hotel_ap"]:
        return None
    pasto_ap = r["costo_fb_totale_ap"] / r["coperti_hotel_ap"]
    return f"{r['euro_per_pasto'] - pasto_ap:+.2f} € vs AP"


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
    c1.plotly_chart(
        fig_coperti_tipo_pasto(_coperti_giorno(anno)), use_container_width=True
    )
    c2.plotly_chart(fig_vendite_sala(_vendite_sala(anno)), use_container_width=True)


def render_kpi(anno: int) -> None:
    df = _kpi(anno)
    if df.empty:
        st.info(f"Nessun KPI mensile per il {anno}.")
        return
    mesi = df["mese"].tolist()
    mese = st.selectbox("Mese", mesi, index=len(mesi) - 1, key="fb_kpi_mese")
    r = df[df["mese"] == mese].iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Food cost ristorante",
        fb_data.kpi_or_nd(
            r["food_cost_pct_ristorante"], r["costo_fb_totale"], r["coperti_hotel"]
        ),
    )
    c2.metric(
        "Beverage cost bar",
        fb_data.kpi_or_nd(
            r["food_cost_pct_bar"], r["costo_fb_totale"], r["coperti_hotel"]
        ),
    )
    c3.metric(
        "Food cost breakfast",
        fb_data.kpi_or_nd(
            r["food_cost_pct_breakfast"], r["costo_fb_totale"], r["coperti_hotel"]
        ),
    )

    # delta €/pasto vs AP: unico delta calcolabile dalle colonne _ap della vista
    delta_pasto = delta_euro_pasto(r)
    c4.metric(
        "€ / pasto",
        "n/d" if not r["costo_fb_totale"] else f"{r['euro_per_pasto']:.2f} €",
        delta=delta_pasto,
        delta_color="inverse",
    )

    st.plotly_chart(fig_food_cost_mensile(df), use_container_width=True)
    col1, col2 = st.columns(2)
    col1.plotly_chart(fig_ricavi_split(df), use_container_width=True)
    col2.plotly_chart(fig_coperti_mensili(df), use_container_width=True)


def render_dettaglio(anno: int) -> None:
    t_cons, t_ric, t_pasti = st.tabs(["🥩 Consumi", "💶 Ricavi per codice", "🍽️ Pasti"])

    with t_cons:
        df = _consumi(anno)
        if df.empty:
            st.info(f"Nessun consumo F&B per il {anno}.")
        else:
            mesi = sorted(df["mese"].unique().tolist())
            mese = st.selectbox("Mese", mesi, index=len(mesi) - 1, key="fb_cons_mese")
            dfm = df[df["mese"] == mese]
            st.plotly_chart(fig_consumi_reparto(dfm), use_container_width=True)
            st.markdown(
                "**Top 20 prodotti per costo** — scomposizione "
                "Δ = effetto prezzo + effetto volume"
            )
            top = dfm.nlargest(20, "costo")[
                [
                    "reparto_id",
                    "codice_prodotto",
                    "descrizione",
                    "costo",
                    "delta_costo",
                    "effetto_prezzo",
                    "effetto_volume",
                    "costo_yoy_pct",
                ]
            ]
            st.dataframe(top, use_container_width=True, hide_index=True)

    with t_ric:
        df = _ricavi(anno)
        df = df[df["classe"] == "02FB"]
        if df.empty:
            st.info(f"Nessun ricavo F&B per il {anno}.")
        else:
            mesi = sorted(df["mese"].unique().tolist())
            mese = st.selectbox("Mese", mesi, index=len(mesi) - 1, key="fb_ric_mese")
            dfm = df[df["mese"] == mese]
            st.plotly_chart(fig_ricavi_tipo_pasto(dfm), use_container_width=True)
            st.dataframe(
                dfm[
                    [
                        "codice",
                        "descrizione",
                        "tipo_pasto",
                        "categoria_fb",
                        "netto",
                        "ricavo_netto_per_coperto",
                        "netto_yoy_pct",
                    ]
                ].sort_values("netto", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

    with t_pasti:
        df = _pasti(anno)
        if df.empty:
            st.info(f"Nessun coperto registrato per il {anno}.")
        else:
            staff = st.toggle("Includi staff (HQ)", value=False, key="fb_pasti_staff")
            if not staff:
                df = df[~df["is_staff"]]
            st.plotly_chart(fig_pasti_mensili(df), use_container_width=True)
            pivot = df.pivot_table(
                index=["business_unit_id", "tipo_ospite"],
                columns="mese",
                values="n_coperti",
                aggfunc="sum",
                fill_value=0,
            )
            st.dataframe(pivot, use_container_width=True)


# --- entry -----------------------------------------------------------------


def render() -> None:
    """Entry importabile dal hub. Nessun set_page_config qui."""
    st.title("🍽️ F&B — monitoraggio operativo")
    oggi = date.today()
    anno = int(
        st.selectbox("Anno", list(range(oggi.year, 2024, -1)), index=0, key="fb_anno")
    )
    tab_stagione, tab_kpi, tab_dettaglio = st.tabs(
        ["🌊 Stagione in corso", "📊 KPI mensili", "🔍 Dettaglio mensile"]
    )
    with tab_stagione:
        render_stagione(anno, oggi)
    with tab_kpi:
        render_kpi(anno)
    with tab_dettaglio:
        render_dettaglio(anno)
