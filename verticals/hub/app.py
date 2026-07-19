"""HotelOps Hub — layer di presentazione sopra i vertical (NON un vertical).

Home gateway + nav si costruiscono dal registry (`verticals/hub/registry.py`):
aggiungere un'app = una riga lì, non una modifica qui.

Lancio: streamlit run verticals/hub/app.py
Spec: docs/superpowers/specs/2026-06-20-hub-gateway-presentation-design.md
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
from verticals.hub.resolver import mounted_pages  # noqa: E402
from verticals.hub.roles import current_apps, current_email  # noqa: E402
from verticals.hub.surface_context import render_sidebar_context  # noqa: E402
from verticals.hub.theme import inject_brand  # noqa: E402

st.set_page_config(page_title="HotelOps Hub", page_icon="🏨", layout="wide")
inject_brand()  # admin: chrome Streamlit visibile

allowed = current_apps()
ctx = render_sidebar_context(user_email=current_email(), allowed_apps=allowed)

# Una st.Page per ogni pagina CONCESSA; mappa id→Page per i link dalla Home.
_page_objs = mounted_pages(allowed, ctx)

home_page = st.Page(
    lambda: home.render(_page_objs, allowed),
    title="Home",
    icon="🏨",
    default=True,
    url_path="home",
)

pg = st.navigation([home_page, *_page_objs.values()], position="top")
pg.run()
