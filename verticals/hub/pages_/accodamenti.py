"""Pagina Accodamenti — ingestore dedicato del vertical condges (cassa → Gaia).

Superficie di SCRITTURA (aggiorna `f_accodamenti`) → re-check del grant (S1).
"""

import streamlit as st


def render():
    from verticals.hub.roles import current_apps

    if "accodamenti" not in current_apps():
        st.error("Non hai accesso a questa sezione.")
        st.stop()
    try:
        from verticals.condges.app_accodamenti import render as _render
    except ImportError:
        st.title("📒 Accodamenti")
        st.info(
            "App Accodamenti non disponibile: "
            "`verticals/condges/app_accodamenti.py` mancante."
        )
        return
    _render()
