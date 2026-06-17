"""Streamlit — vertical Spiaggia (Panorama Beach), interna/direzione.

Ricerca prenotazioni + KPI cassa/occupazione. Read-only su viste v_spiaggia_*.

Standalone: `streamlit run verticals/spiaggia/app.py`
Hub: `from verticals.spiaggia.app import render` → `st.Page(render, ...)`
     (render() NON chiama set_page_config — lo fa l'hub una volta sola).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bq.client import get_client
from core.config import DATASET, PROJECT

# Brand Panorama Beach (approssimazione CSS, non il Design System web).
_BRAND_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&family=Jost:wght@300;400;500&display=swap');
html, body, [class*="css"] { font-family: 'Jost', sans-serif; }
.stApp { background-color: #fbf9f5; }
h1, h2, h3 { font-family: 'Cinzel', serif; color: #003764; }
.pb-sub { font-family: 'Cormorant Garamond', serif; color: #57c1e8; font-size: 1.2rem; }
[data-testid="stMetricValue"] { color: #003764; font-family: 'Cinzel', serif; }
.stButton>button { background-color: #57c1e8; color: #003764; border: none; }
</style>
"""


def _q(sql: str) -> pd.DataFrame:
    return get_client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_kpi() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_kpi` ORDER BY anno, mese")


@st.cache_data(ttl=300)
def load_prenotazioni() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_prenotazioni`")


@st.cache_data(ttl=300)
def load_cassa() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_cassa`")


@st.cache_data(ttl=300)
def load_occupazione() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_occupazione` ORDER BY giorno")


@st.cache_data(ttl=300)
def load_giornaliero() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_giornaliero` ORDER BY data")


def render() -> None:
    """Render la pagina Panorama Beach. Montabile nell'hub (no set_page_config)."""
    st.markdown(_BRAND_CSS, unsafe_allow_html=True)
    st.title("Panorama Beach")
    st.markdown('<div class="pb-sub">Prenotazioni · Cassa · Occupazione</div>', unsafe_allow_html=True)

    kpi = load_kpi()
    anni = sorted(kpi["anno"].dropna().unique().tolist(), reverse=True) if not kpi.empty else []
    # Default sull'ultimo anno con incasso: evita di aprire su un anno futuro ancora vuoto.
    anni_cassa = sorted(kpi[kpi["incassato"].fillna(0) > 0]["anno"].unique().tolist(), reverse=True)
    default_idx = anni.index(anni_cassa[0]) if anni_cassa else 0
    anno_sel = st.sidebar.selectbox("Anno", anni, index=default_idx) if anni else None

    # --- Header KPI (anno selezionato) ---
    if anno_sel is not None:
        k = kpi[kpi["anno"] == anno_sel]
        n_pren = int(k["n_prenotazioni"].sum())
        incassato = k["incassato"].fillna(0).sum()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Prenotazioni", n_pren)
        c2.metric("Incassato", f"€ {incassato:,.0f}")
        c3.metric("Incasso medio/pren.", f"€ {incassato / n_pren:,.0f}" if n_pren else "—")
        online_pct = (k["quota_online"] * k["n_prenotazioni"]).sum() / k["n_prenotazioni"].sum() if n_pren else 0
        hotel_pct = (k["quota_hotel"] * k["n_prenotazioni"]).sum() / k["n_prenotazioni"].sum() if n_pren else 0
        c4.metric("Online %", f"{online_pct*100:,.0f}%")
        c5.metric("Hotel-linked %", f"{hotel_pct*100:,.0f}%")

    # --- Ricerca prenotazioni ---
    st.header("Cerca prenotazioni")
    pren = load_prenotazioni()
    fc1, fc2, fc3 = st.columns(3)
    q_cliente = fc1.text_input("Cliente / email / telefono")
    q_ombrellone = fc2.text_input("Ombrellone (spot_name)")
    q_anno = fc3.selectbox("Anno prenotazione", ["(tutti)"] + [str(a) for a in anni]) if anni else "(tutti)"

    view = pren.copy()
    if q_anno not in ("(tutti)", "") and "anno" in view:
        view = view[view["anno"] == int(q_anno)]
    if q_ombrellone:
        view = view[view["spot_name"].fillna("").str.contains(q_ombrellone, case=False)]
    if q_cliente:
        mask = (
            view["first_name"].fillna("").str.contains(q_cliente, case=False)
            | view["last_name"].fillna("").str.contains(q_cliente, case=False)
            | view["email"].fillna("").str.contains(q_cliente, case=False)
            | view["phone"].fillna("").str.contains(q_cliente, case=False)
        )
        view = view[mask]

    st.caption(f"{len(view)} prenotazioni")
    st.dataframe(
        view[[
            "id", "start_date", "end_date", "spot_name", "first_name", "last_name",
            "email", "phone", "beds", "chairs", "gross_booking_value", "channel",
            "online", "hotel_linked",
        ]],
        use_container_width=True,
        height=400,
    )

    # --- Grafici ---
    st.header("Andamenti")
    g1, g2 = st.columns(2)
    occ = load_occupazione()
    if not occ.empty and anno_sel is not None:
        occ_y = occ[occ["anno"] == anno_sel]
        g1.subheader("Occupazione ombrelloni")
        g1.line_chart(occ_y.set_index("giorno")["occupazione_pct"])
    cassa = load_cassa()
    if not cassa.empty and anno_sel is not None:
        cassa_y = cassa[cassa["anno"] == anno_sel]
        per_metodo = cassa_y.groupby("method_label")["importo_netto"].sum()
        g2.subheader("Cassa per metodo")
        g2.bar_chart(per_metodo)

    # --- Ricavo giornaliero ---
    st.header("Ricavo giornaliero (corrispettivi + alloggiati)")
    g = load_giornaliero()
    if not g.empty:
        if anno_sel is not None and "anno" in g:
            g = g[g["anno"] == anno_sel]
        st.dataframe(
            g[[
                "data", "spiaggia_intur", "spiaggia_orti", "bar_intur",
                "bar_orti", "spiaggia_totale", "bar_totale", "stabilimento_totale",
                "flag_manca_pms",
            ]],
            use_container_width=True,
            height=400,
        )
        st.bar_chart(g.set_index("data")[["spiaggia_totale", "bar_totale"]])


if __name__ == "__main__":
    st.set_page_config(page_title="Panorama Beach", page_icon="🏖️", layout="wide")
    render()
