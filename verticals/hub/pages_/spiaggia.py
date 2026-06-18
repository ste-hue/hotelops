"""Pagina Spiaggia — monta verticals.spiaggia.app.render()."""

import streamlit as st


def render():
    try:
        from verticals.spiaggia.app import render as _render
    except ImportError:
        st.title("🏖️ Spiaggia")
        st.info(
            "Dashboard Spiaggia in arrivo: `verticals/spiaggia/app.py` "
            "non è ancora disponibile."
        )
        return
    _render()
