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
from verticals.hub.registry import pages_for  # noqa: E402
from verticals.hub.roles import current_apps  # noqa: E402
from verticals.hub.theme import inject_brand  # noqa: E402

# Favicon = icona app (monogramma P, design 1B) — stessa identità della home-screen.
_ICON = str(Path(__file__).parent / "assets" / "icon-192.png")

st.set_page_config(page_title="HotelOps Hub", page_icon=_ICON, layout="wide")
inject_brand()  # admin: chrome Streamlit visibile

allowed = current_apps()

# Una st.Page per ogni pagina CONCESSA; mappa id→Page per i link dalla Home.
_page_objs = {
    a.id: st.Page(a.target, title=a.title, icon=a.icon, url_path=a.id)
    for a in pages_for(allowed)
}

home_page = st.Page(
    lambda: home.render(_page_objs, allowed),
    title="Home",
    icon="🏨",
    default=True,
    url_path="home",
)

pg = st.navigation([home_page, *_page_objs.values()], position="top")
pg.run()
