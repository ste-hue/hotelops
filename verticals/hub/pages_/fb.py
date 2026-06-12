"""Pagina F&B — monta verticals.condges.fb_dashboard.render() (worktree fb-looker)."""

import streamlit as st


def render():
    try:
        from verticals.condges.fb_dashboard import render as fb_render
    except ImportError:
        st.title("🍽 F&B")
        st.info(
            "Dashboard F&B in arrivo: `verticals/condges/fb_dashboard.py` "
            "non è ancora su main (in costruzione nel worktree fb-looker)."
        )
        return
    fb_render()
