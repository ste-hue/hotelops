"""Pagina Cashflow — monta verticals.condges.app_cashflow.render()."""

from __future__ import annotations

import streamlit as st

from verticals.hub.surface_context import SurfaceContext


def render(ctx: SurfaceContext | None = None):
    from verticals.hub.roles import current_apps

    if "cashflow" not in current_apps():
        st.error("Non hai accesso a questa sezione.")
        st.stop()
    try:
        from verticals.condges.app_cashflow import render as _render
    except ImportError:
        st.title("💸 Cashflow")
        st.info(
            "App Cashflow non disponibile: `verticals/condges/app_cashflow.py` mancante."
        )
        return
    _render()
