"""Pagina CdG — Controllo di Gestione del vertical condges (CE, BvA, Tesoreria, KPI).

Superficie di SCRITTURA (bottone "Salva in BQ" fonte=APP_BUDGET) → re-check del grant (S1).
"""

import streamlit as st


def render():
    from verticals.hub.roles import current_apps

    if "cdg" not in current_apps():
        st.error("Non hai accesso a questa sezione.")
        st.stop()
    try:
        from verticals.condges.app_cdg import render as _render
    except ImportError:
        st.title("📊 CdG")
        st.info("App CdG non disponibile: `verticals/condges/app_cdg.py` mancante.")
        return
    _render()
