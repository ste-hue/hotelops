"""Risoluzione tecnica delle superfici hub.

Il registry dichiara la superficie; qui si decide come montarla davvero.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from verticals.hub.pages_ import (
    accodamenti,
    bilancini,
    cashflow,
    cassa_consuntivo,
    fb,
    mutui,
    revenue,
    reviews,
    spiaggia,
)
from verticals.hub.registry import APPS, HubApp, pages_for
from verticals.hub.surface_context import SurfaceContext

_PAGE_RENDERERS: dict[str, Callable[[SurfaceContext | None], None]] = {
    "cashflow": cashflow.render,
    "cassa-consuntivo": cassa_consuntivo.render,
    "bilancini": bilancini.render,
    "accodamenti": accodamenti.render,
    "mutui": mutui.render,
    "revenue": revenue.render,
    "fb": fb.render,
    "spiaggia": spiaggia.render,
    "reviews": reviews.render,
}


def _make_renderer(
    render: Callable[[SurfaceContext | None], None], ctx: SurfaceContext
) -> Callable[[], None]:
    return lambda: render(ctx)


def validate_resolution(apps: list[HubApp] = APPS) -> None:
    """Ogni page del registry deve avere un renderer risolvibile."""
    for app in apps:
        if app.kind == "page" and app.id not in _PAGE_RENDERERS:
            raise ValueError(f"resolver: renderer mancante per {app.id!r}")


def mounted_pages(
    allowed: frozenset[str], ctx: SurfaceContext
) -> dict[str, st.Page]:
    """Costruisce le `st.Page` dalle superfici concesse."""
    out: dict[str, st.Page] = {}
    for app in pages_for(allowed):
        render = _PAGE_RENDERERS[app.id]
        out[app.id] = st.Page(
            _make_renderer(render, ctx),
            title=app.title,
            icon=app.icon,
            url_path=app.route,
        )
    return out


validate_resolution()
