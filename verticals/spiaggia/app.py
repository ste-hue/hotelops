"""Streamlit — vertical Spiaggia (Panorama Beach): soldi totali per giorno.

Vista semplice, read-only, del RICAVO TOTALE dello stabilimento:
`stabilimento_totale` = banco INTUR (corrispettivi) + alloggiati ORTI (PMS),
con la quadratura cassa Moolty. Niente prenotazioni / occupazione.

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
</style>
"""

_NUM = ["spiaggia_intur", "bar_intur", "spiaggia_orti",
        "stabilimento_totale", "pos_moolty", "scost_cassa"]


def _q(sql: str) -> pd.DataFrame:
    return get_client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_giornaliero() -> pd.DataFrame:
    return _q(f"SELECT * FROM `{PROJECT}.{DATASET}.v_spiaggia_giornaliero` ORDER BY data")


def _eur(v) -> str:
    try:
        return "€ " + f"{float(v):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def render() -> None:
    """Panorama Beach — soldi totali per giorno. Montabile nell'hub."""
    st.markdown(_BRAND_CSS, unsafe_allow_html=True)
    st.title("Panorama Beach")
    st.markdown('<div class="pb-sub">Soldi totali spiaggia · per giorno</div>',
                unsafe_allow_html=True)

    g = load_giornaliero()
    if g.empty:
        st.info("Nessun dato disponibile.")
        return

    for c in _NUM:
        if c in g:
            g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)

    anni = sorted(g["anno"].dropna().unique().tolist(), reverse=True)
    # Default sull'ultimo anno con dati completi (Moolty presente), non sull'anno
    # in corso semi-vuoto (es. 2026 senza export Moolty/PMS ancora caricati).
    anni_full = [a for a in anni if g.loc[g["anno"] == a, "pos_moolty"].sum() > 0]
    default_idx = anni.index(anni_full[0]) if anni_full else 0
    anno = st.sidebar.selectbox("Anno", anni, index=default_idx) if anni else None
    gy = g[g["anno"] == anno].copy() if anno is not None else g.copy()

    gy["banco"] = gy["spiaggia_intur"] + gy["bar_intur"]
    totale = gy["stabilimento_totale"].sum()
    banco = gy["banco"].sum()
    alloggiati = gy["spiaggia_orti"].sum()

    # --- Headline: SOLDI TOTALI (INTUR banco + ORTI alloggiati) ---
    st.metric("💰 Soldi totali spiaggia", _eur(totale))
    c1, c2 = st.columns(2)
    c1.metric("di cui banco diretto (INTUR)", _eur(banco))
    c2.metric("di cui ospiti hotel (ORTI)", _eur(alloggiati))
    if alloggiati == 0 and banco > 0:
        st.caption("⚠️ Alloggiati ORTI a 0 per quest'anno: manca l'export PMS — il totale è ancora solo il banco.")

    # --- Andamento mensile: totale (banco + alloggiati impilati) ---
    st.subheader("Per mese")
    monthly = (gy.groupby("mese")
               .agg(Banco=("banco", "sum"), **{"Ospiti hotel": ("spiaggia_orti", "sum")}))
    st.bar_chart(monthly)  # barre impilate → l'altezza è il totale spiaggia

    # --- Dettaglio giornaliero ---
    st.subheader("Per giorno")
    show = gy[["data", "stabilimento_totale", "spiaggia_intur", "bar_intur",
               "spiaggia_orti", "pos_moolty", "scost_cassa"]].sort_values("data")
    show = show.rename(columns={
        "stabilimento_totale": "TOTALE",
        "spiaggia_intur": "spiaggia (INTUR)",
        "bar_intur": "bar (INTUR)",
        "spiaggia_orti": "ospiti hotel (ORTI)",
        "pos_moolty": "Moolty (cassa)",
        "scost_cassa": "scost. cassa",
    })
    st.dataframe(show, use_container_width=True, height=460, hide_index=True)
    st.caption("scost. cassa = banco registro − Moolty (vicino a 0 = la cassa del banco quadra).")


if __name__ == "__main__":
    st.set_page_config(page_title="Panorama Beach", page_icon="🏖️", layout="wide")
    render()
