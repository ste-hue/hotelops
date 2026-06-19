"""Pagina Cashflow — monta verticals.condges.app_cashflow.render()."""

import streamlit as st


def render():
    try:
        from verticals.condges.app_cashflow import render as _render
    except ImportError:
        st.title("💸 Cashflow")
        st.info(
            "App Cashflow non disponibile: `verticals/condges/app_cashflow.py` mancante."
        )
        return
    _render()
