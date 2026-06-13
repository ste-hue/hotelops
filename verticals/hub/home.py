"""Home-store: card per app con semaforo freshness (layout A, 2026-06-12)."""

import streamlit as st

from verticals.hub.freshness import carica_freshness, semaforo
from verticals.hub.theme import brand_header


@st.cache_data(ttl=300, show_spinner="Carico freshness…")
def _freshness():
    return carica_freshness()


def render(audience: str = "admin"):
    """audience='admin' (tu, tutte le card) | 'viewer' (direttore, no superfici interne)."""
    brand_header("HotelOps", "Amalfi Coast · Maiori")
    try:
        fresh = _freshness()
    except Exception as e:  # BQ giù: dichiarare, mai cache silente
        st.error(f"Dati non disponibili (BigQuery): {e}")
        return

    g_fb = fresh["fb"]["giorni"]
    g_rev = fresh["reviews"]["giorni"]
    s_fb = semaforo(g_fb, soglia_attenzione=35, soglia_allarme=70)
    s_rev = semaforo(g_rev, 7, 14)
    is_admin = audience == "admin"

    # semaforo di testata = peggiore dei semafori per-card (scale diverse per fonte)
    semafori = [s_fb, s_rev]
    if is_admin:
        n_coda = fresh["ingest"]["in_coda"]
        semafori.append("🟢" if n_coda == 0 else "🟡")
    peggiore = "🔴" if "🔴" in semafori else ("🟡" if "🟡" in semafori else "🟢")
    st.caption(f"Stato dati: {peggiore} · aggiornato ogni 5 min")

    cols = st.columns(3 if is_admin else 2)
    with cols[0]:
        st.subheader(f"🍽 F&B {s_fb}")
        st.metric("Ultimo mese coperto", f"{g_fb} gg fa" if g_fb is not None else "n/d")
    with cols[1]:
        st.subheader(f"⭐ Reviews {s_rev}")
        st.metric("Media mese", fresh["reviews"]["media_mese"] or "n/d")
    if is_admin:
        with cols[2]:
            st.subheader(f"📥 Ingest {'🟢' if n_coda == 0 else '🟡'}")
            st.metric("Raw objects in coda", n_coda)
        st.caption(
            "💶 Cassa/PF arriva con la migrazione PF generazionale "
            "(in pausa: P1 lotteria budget, vedi STATUS.md)."
        )
