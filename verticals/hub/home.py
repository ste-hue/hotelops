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

    g_fb = fresh["fb"]["giorni"]
    g_rev = fresh["reviews"]["giorni"]
    n_coda = fresh["ingest"]["in_coda"]
    # ogni fonte ha la sua scala (mensile/settimanale): il semaforo di testata
    # è il peggiore dei semafori per-card, non dei giorni grezzi
    s_fb = semaforo(g_fb, soglia_attenzione=35, soglia_allarme=70)
    s_rev = semaforo(g_rev, 7, 14)
    s_ing = "🟢" if n_coda == 0 else "🟡"
    semafori = [s_fb, s_rev, s_ing]
    peggiore = "🔴" if "🔴" in semafori else ("🟡" if "🟡" in semafori else "🟢")
    st.caption(f"Stato dati: {peggiore} · refresh ogni 5 min")

    col_fb, col_rev, col_ing = st.columns(3)
    with col_fb:
        st.subheader(f"🍽 F&B {s_fb}")
        st.metric("Ultimo mese coperto", f"{g_fb} gg fa" if g_fb is not None else "n/d")
    with col_rev:
        st.subheader(f"⭐ Reviews {s_rev}")
        st.metric("Media mese", fresh["reviews"]["media_mese"] or "n/d")
    with col_ing:
        st.subheader(f"📥 Ingest {s_ing}")
        st.metric("Raw objects in coda", n_coda)

    st.caption(
        "💶 Cassa/PF arriva con la migrazione PF generazionale "
        "(in pausa: P1 lotteria budget, vedi STATUS.md)."
    )
