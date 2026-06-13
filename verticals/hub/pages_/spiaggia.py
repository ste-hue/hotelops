"""Pagina Spiaggia — monta verticals.spiaggia.app.render() (Panorama Beach)."""

import streamlit as st


def render():
    try:
        from verticals.spiaggia.app import render as _render
    except ImportError:
        st.title("🏖️ Spiaggia")
        st.info("Vertical Spiaggia non disponibile: `verticals/spiaggia` non importabile.")
        return
    _render()
