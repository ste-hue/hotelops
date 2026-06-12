"""HotelOps Hub — layer di presentazione sopra i vertical (NON un vertical).

Lancio: streamlit run verticals/hub/app.py
Spec: docs/superpowers/specs/2026-06-12-hub-app-store-design.md
"""

import streamlit as st

from verticals.hub import home
from verticals.hub.pages_ import fb, ingest, reviews

st.set_page_config(page_title="HotelOps Hub", page_icon="🏨", layout="wide")

pg = st.navigation(
    [
        st.Page(home.render, title="Home", icon="🏨", default=True),
        st.Page(fb.render, title="F&B", icon="🍽"),
        st.Page(reviews.render, title="Reviews", icon="⭐"),
        st.Page(ingest.render, title="Ingest", icon="📥"),
    ]
)
pg.run()
