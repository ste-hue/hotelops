"""Home gateway: unico punto d'ingresso per tutto il frontend HotelOps.

Si costruisce dal registry (``APPS``), raggruppata per dominio. Launcher puro: ogni
tile = icona + titolo + sottotitolo + azione, e linka dentro la pagina (``page``),
all'URL esterno (``bind``) o segna "coming soon" (``soon``). Niente numeri sul
front-door — i dati si guardano dentro le app, col loro contesto.
"""

import streamlit as st

from verticals.hub.registry import HubApp, by_group
from verticals.hub.theme import brand_header


def render(page_objs: dict | None = None) -> None:
    """page_objs = {app_id: st.Page} delle pagine montate, per i link in-app."""
    page_objs = page_objs or {}
    brand_header("HotelOps", "Amalfi Coast · Maiori")
    st.caption("Punto d'ingresso · apri un'app per i dati col loro contesto")

    for group, apps in by_group().items():
        if not apps:
            continue
        st.subheader(group)
        cols = st.columns(3)
        for i, app in enumerate(apps):
            with cols[i % 3]:
                _tile(app, page_objs.get(app.id))


def _tile(app: HubApp, page_obj) -> None:
    with st.container(border=True):
        st.markdown(f"### {app.icon} {app.title}")
        if app.subtitle:
            st.caption(app.subtitle)

        if app.kind == "page" and page_obj is not None:
            st.page_link(page_obj, label="Apri →")
        elif app.kind == "bind" and isinstance(app.target, str):
            st.link_button("Apri ↗", app.target)
        elif app.kind == "soon":
            st.caption("🔜 coming soon")
