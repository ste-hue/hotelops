"""Pagina Reviews — monta verticals.reviews.app.render()."""

from __future__ import annotations

from verticals.hub.surface_context import SurfaceContext


def render(ctx: SurfaceContext | None = None):
    from verticals.reviews.app import render as reviews_render

    reviews_render()
