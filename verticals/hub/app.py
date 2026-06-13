"""HotelOps Hub — layer di presentazione sopra i vertical (NON un vertical).

Lancio: streamlit run verticals/hub/app.py
Spec: docs/superpowers/specs/2026-06-12-hub-app-store-design.md
"""

import sys
from pathlib import Path

# `streamlit run` mette in sys.path la dir dello script, non il repo root:
# senza questo bootstrap `import verticals` fallisce (stesso problema di app_cdg).
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402

from verticals.hub import home  # noqa: E402
from verticals.hub.pages_ import fb, ingest, mutui, reviews  # noqa: E402
from verticals.hub.theme import inject_brand  # noqa: E402

st.set_page_config(page_title="HotelOps Hub", page_icon="🏨", layout="wide")
inject_brand()  # admin: chrome Streamlit visibile

pg = st.navigation(
    [
        st.Page(home.render, title="Home", icon="🏨", default=True, url_path="home"),
        st.Page(fb.render, title="F&B", icon="🍽", url_path="fb"),
        st.Page(reviews.render, title="Reviews", icon="⭐", url_path="reviews"),
        st.Page(mutui.render, title="Mutui", icon="🏦", url_path="mutui"),
        st.Page(ingest.render, title="Ingest", icon="📥", url_path="ingest"),
    ]
)
pg.run()
