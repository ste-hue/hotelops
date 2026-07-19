"""Home gateway: unico punto d'ingresso per tutto il frontend HotelOps.

Si costruisce dal registry (``APPS``), raggruppata per dominio. Launcher puro: ogni
tile = icona + titolo + sottotitolo + azione, e linka dentro la pagina (``page``),
all'URL esterno (``bind``) o segna "coming soon" (``soon``). Niente numeri sul
front-door — i dati si guardano dentro le app, col loro contesto.
"""

import streamlit as st

from verticals.hub.registry import HubApp, by_group_for
from verticals.hub.theme import brand_header


def render(
    page_objs: dict | None = None, allowed: frozenset[str] | None = None
) -> None:
    """page_objs = {app_id: st.Page} montate; allowed = app concesse all'utente."""
    page_objs = page_objs or {}
    allowed = frozenset() if allowed is None else allowed
    brand_header("HotelOps", "Amalfi Coast · Maiori")

    groups = by_group_for(allowed)
    if not any(groups.values()):
        st.warning(
            "Non hai ancora accesso a nessuna sezione. "
            "Contatta l'amministratore per i permessi."
        )
        return

    st.caption("Punto d'ingresso · apri un'app per i dati col loro contesto")
    for group, apps in groups.items():
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
        elif app.kind == "bind" and isinstance(app.route, str):
            st.link_button("Apri ↗", app.route)
        elif app.kind == "soon":
            st.caption("🔜 coming soon")
        if app.owner:
            st.caption(f"Owner: {app.owner}")
