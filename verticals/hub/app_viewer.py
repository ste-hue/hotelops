"""HotelOps Hub — superficie VIEWER per la direzione (sola lettura, brandizzata).

Differenze dall'app admin (`app.py`):
  - niente pagina Ingest né Cassa (nessuna superficie di scrittura/interna)
  - chrome Streamlit nascosta (look pulito per il direttore)
  - dietro Cloudflare Access (gating per email) quando pubblicata su Cloud Run

Lancio locale: streamlit run verticals/hub/app_viewer.py
Spec: docs/superpowers/specs/2026-06-12-hub-app-store-design.md
"""

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402

from verticals.hub import home  # noqa: E402
from verticals.hub.pages_ import fb, mutui, reviews  # noqa: E402
from verticals.hub.theme import inject_brand  # noqa: E402

st.set_page_config(page_title="Panorama · HotelOps", page_icon="🏨", layout="wide")
inject_brand(hide_chrome=True)  # viewer: chrome Streamlit nascosta


def _home_viewer():
    home.render(audience="viewer")


pg = st.navigation(
    [
        st.Page(_home_viewer, title="Home", icon="🏨", default=True, url_path="home"),
        st.Page(fb.render, title="F&B", icon="🍽", url_path="fb"),
        st.Page(reviews.render, title="Reviews", icon="⭐", url_path="reviews"),
        st.Page(mutui.render, title="Mutui", icon="🏦", url_path="mutui"),
    ]
)
pg.run()
