"""Home gateway: unico punto d'ingresso per tutto il frontend HotelOps.

Si costruisce dal registry (``APPS``), raggruppata per dominio. Launcher puro: ogni
tile = icona + titolo + sottotitolo + azione, e linka dentro la pagina (``page``),
all'URL esterno (``bind``) o segna "coming soon" (``soon``). Niente numeri sul
front-door — i dati si guardano dentro le app, col loro contesto.
"""

import html

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

    st.markdown(lista_html(groups, page_objs), unsafe_allow_html=True)


def _href(app: HubApp, page_obj) -> tuple[str, str, bool] | None:
    """(href, etichetta, esterno) per il bottone della riga; None = «presto»."""
    if app.kind == "page" and page_obj is not None:
        return f"/{getattr(page_obj, 'url_path', app.id)}", "Apri", False
    if app.kind == "bind" and isinstance(app.target, str):
        return app.target, "Apri ↗", True
    return None


def lista_html(groups: dict[str, list[HubApp]], page_objs: dict) -> str:
    """La home come lista: un'etichetta per gruppo, una riga per app.

    Riga = logo piccolo (l'icona dell'app in un tondo), nome, una frase, un bottone solo.
    Niente numeri e niente griglia: il front-door elenca e apre, i dati stanno dentro.
    Funzione pura: HTML da registry e pagine montate, testabile senza Streamlit.
    """
    parti = []
    for group, apps in groups.items():
        if not apps:
            continue
        righe = []
        for app in apps:
            h = _href(app, page_objs.get(app.id))
            if h is None:
                bottone = '<span class="pg-apri pg-presto">presto</span>'
            else:
                href, etichetta, esterno = h
                extra = ' target="_blank" rel="noopener"' if esterno else ""
                bottone = f'<a class="pg-apri" href="{html.escape(href, quote=True)}"{extra}>{etichetta}</a>'
            sotto = (
                f'<div class="pg-sotto">{html.escape(app.subtitle)}</div>'
                if app.subtitle
                else ""
            )
            righe.append(
                f'<li class="pg-riga">'
                f'<span class="pg-badge" aria-hidden="true">{html.escape(app.icon)}</span>'
                f'<div class="pg-testo"><div class="pg-nome">{html.escape(app.title)}</div>{sotto}</div>'
                f"{bottone}</li>"
            )
        parti.append(
            f'<section class="pg-gruppo"><div class="pg-eyebrow">{html.escape(group)}</div>'
            f'<ul class="pg-lista">{"".join(righe)}</ul></section>'
        )
    return "".join(parti)
