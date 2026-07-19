"""Pagina Spiaggia — monta verticals.spiaggia.app.render().

L'uploader Moolty (write-path) è per-utente: la pagina resta in sola lettura
per il gruppo Operations, il drop compare solo agli uploader autorizzati.
"""

from __future__ import annotations

import streamlit as st

from verticals.hub.surface_context import SurfaceContext

# Chi può caricare l'export Moolty dalla pagina (write-path via lineage).
_MOOLTY_UPLOADERS = frozenset(
    {
        "stefano@panoramagroup.it",
        "ste.dellapietra@gmail.com",
    }
)


def render(ctx: SurfaceContext | None = None):
    try:
        from verticals.spiaggia.app import render as _render
    except ImportError:
        st.title("🏖️ Spiaggia")
        st.info(
            "Dashboard Spiaggia in arrivo: `verticals/spiaggia/app.py` "
            "non è ancora disponibile."
        )
        return

    from verticals.hub.roles import current_email

    email = ctx.user_email if ctx is not None else current_email()
    _render(can_upload=email in _MOOLTY_UPLOADERS)
