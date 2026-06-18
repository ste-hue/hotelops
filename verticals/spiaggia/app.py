"""Streamlit — vertical Spiaggia (Panorama Beach): soldi totali per giorno.

Vista interattiva e read-only del RICAVO TOTALE dello stabilimento:
`stabilimento_totale` = banco INTUR (corrispettivi) + alloggiati ORTI (PMS),
con la quadratura cassa Moolty. Filtri: anno, periodo, solo-giorni-col-registro.

Standalone: `streamlit run verticals/spiaggia/app.py`
Hub: `from verticals.spiaggia.app import render` → `st.Page(render, ...)`
     (render() NON chiama set_page_config — lo fa l'hub una volta sola).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bq.client import get_client
from core.config import DATASET, PROJECT

_BRAND_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&family=Jost:wght@300;400;500&display=swap');
html, body, [class*="css"] { font-family: 'Jost', sans-serif; }
.stApp { background-color: #fbf9f5; }
h1, h2, h3 { font-family: 'Cinzel', serif; color: #003764; }
.pb-sub { font-family: 'Cormorant Garamond', serif; color: #57c1e8; font-size: 1.2rem; }
[data-testid="stMetricValue"] { color: #003764; font-family: 'Cinzel', serif; }
</style>
"""

_NUM = ["spiaggia_intur", "bar_intur", "spiaggia_orti",
        "stabilimento_totale", "pos_moolty", "scost_cassa"]


def _q(sql: str) -> pd.DataFrame:
    return get_client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_giornaliero() -> pd.DataFrame:
    g = _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_giornaliero` ORDER BY data")
    for c in _NUM:
        if c in g:
            g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    if "data" in g:
        g["data"] = pd.to_datetime(g["data"]).dt.date
    return g


def _eur(v) -> str:
    try:
        return "€ " + f"{float(v):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def render() -> None:
    """Panorama Beach — soldi totali per giorno, interattiva. Montabile nell'hub."""
    st.markdown(_BRAND_CSS, unsafe_allow_html=True)
    st.title("Panorama Beach")
    st.markdown('<div class="pb-sub">Soldi totali spiaggia · per giorno</div>',
                unsafe_allow_html=True)

    g = load_giornaliero()
    if g.empty:
        st.info("Nessun dato disponibile.")
        return

    # ---------------- Filtri (sidebar) ----------------
    st.sidebar.header("Filtri")
    anni = sorted(g["anno"].dropna().unique().tolist(), reverse=True)
    # Default sull'ultimo anno con Moolty (non sull'anno in corso semi-vuoto).
    anni_full = [a for a in anni if g.loc[g["anno"] == a, "pos_moolty"].sum() > 0]
    default_idx = anni.index(anni_full[0]) if anni_full else 0
    anno = st.sidebar.selectbox("Anno", anni, index=default_idx) if anni else None

    gy = g[g["anno"] == anno].copy() if anno is not None else g.copy()
    if not gy.empty:
        dmin, dmax = gy["data"].min(), gy["data"].max()
        periodo = st.sidebar.date_input("Periodo", (dmin, dmax),
                                        min_value=dmin, max_value=dmax)
        if isinstance(periodo, (list, tuple)) and len(periodo) == 2:
            gy = gy[(gy["data"] >= periodo[0]) & (gy["data"] <= periodo[1])]

    if st.sidebar.checkbox("Solo giorni col registro compilato", value=False):
        gy = gy[~gy["flag_manca_corrispettivi"]]

    if gy.empty:
        st.warning("Nessun dato nel periodo/filtro selezionato.")
        return

    gy["banco"] = gy["spiaggia_intur"] + gy["bar_intur"]

    # ---------------- KPI (reattivi ai filtri) ----------------
    st.metric("💰 Soldi totali spiaggia", _eur(gy["stabilimento_totale"].sum()))
    c1, c2, c3 = st.columns(3)
    c1.metric("Banco diretto (INTUR)", _eur(gy["banco"].sum()))
    c2.metric("Ospiti hotel (ORTI)", _eur(gy["spiaggia_orti"].sum()))
    c3.metric("Moolty (cassa POS)", _eur(gy["pos_moolty"].sum()))

    # ---------------- Grafico (totale = banco + ospiti impilati) ----------------
    st.subheader("Per giorno")
    st.bar_chart(gy.set_index("data")[["banco", "spiaggia_orti"]])

    # ---------------- Tabella interattiva (ordinabile) ----------------
    show = gy[["data", "stabilimento_totale", "spiaggia_intur", "bar_intur",
               "spiaggia_orti", "pos_moolty", "scost_cassa",
               "flag_manca_corrispettivi"]].sort_values("data")
    show = show.rename(columns={
        "stabilimento_totale": "TOTALE",
        "spiaggia_intur": "spiaggia (INTUR)",
        "bar_intur": "bar (INTUR)",
        "spiaggia_orti": "ospiti hotel (ORTI)",
        "pos_moolty": "Moolty (cassa)",
        "scost_cassa": "scost. cassa",
        "flag_manca_corrispettivi": "⚠ no registro",
    })
    st.dataframe(show, use_container_width=True, height=460, hide_index=True)
    st.caption("Colonne ordinabili (clic sull'intestazione). scost. cassa = banco − Moolty. "
               "⚠ no registro = giorno con Moolty ma corrispettivo non ancora compilato.")


if __name__ == "__main__":
    st.set_page_config(page_title="Panorama Beach", page_icon="🏖️", layout="wide")
    render()
