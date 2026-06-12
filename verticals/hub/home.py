"""Home-store: card per app con semaforo freshness (layout A, 2026-06-12)."""

import streamlit as st

from verticals.hub.freshness import carica_freshness, semaforo


@st.cache_data(ttl=300, show_spinner="Carico freshness…")
def _freshness():
    return carica_freshness()


def render():
    st.title("🏨 HotelOps Hub")
    try:
        fresh = _freshness()
    except Exception as e:  # BQ giù: dichiarare, mai cache silente
        st.error(f"Dati non disponibili (BigQuery): {e}")
        return

    peggiore = max(
        (v["giorni"] if v.get("giorni") is not None else 99)
        for v in fresh.values()
        if "giorni" in v
    )
    st.caption(f"Stato dati: {semaforo(peggiore)} · refresh ogni 5 min")

    col_fb, col_rev, col_ing = st.columns(3)
    with col_fb:
        g = fresh["fb"]["giorni"]
        st.subheader(f"🍽 F&B {semaforo(g)}")
        st.metric("Ultimo consumo", f"{g} gg fa" if g is not None else "n/d")
    with col_rev:
        g = fresh["reviews"]["giorni"]
        st.subheader(f"⭐ Reviews {semaforo(g, 7, 14)}")
        st.metric("Media mese", fresh["reviews"]["media_mese"] or "n/d")
    with col_ing:
        n = fresh["ingest"]["in_coda"]
        st.subheader(f"📥 Ingest {'🟢' if n == 0 else '🟡'}")
        st.metric("Raw objects in coda", n)

    st.caption(
        "💶 Cassa/PF arriva con la migrazione PF generazionale "
        "(in pausa: P1 lotteria budget, vedi STATUS.md)."
    )
