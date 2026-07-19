"""Contesto condiviso del hub per le superfici che leggono il dominio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import streamlit as st

_CTX_PREFIX = "hub_ctx_"
_MESI = (
    "gen",
    "feb",
    "mar",
    "apr",
    "mag",
    "giu",
    "lug",
    "ago",
    "set",
    "ott",
    "nov",
    "dic",
)


@dataclass(frozen=True)
class SurfaceContext:
    societa: str
    anno: int
    mese: int
    scenario: str
    user_email: str | None = None
    allowed_apps: frozenset[str] = frozenset()


def _default_period() -> tuple[int, int]:
    today = date.today()
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def _state_key(name: str) -> str:
    return f"{_CTX_PREFIX}{name}"


def current_context(
    *, user_email: str | None = None, allowed_apps: frozenset[str] | None = None
) -> SurfaceContext:
    """Legge il contesto corrente dallo session state."""
    default_anno, default_mese = _default_period()
    return SurfaceContext(
        societa=st.session_state.get(_state_key("societa"), "ORTI"),
        anno=int(st.session_state.get(_state_key("anno"), default_anno)),
        mese=int(st.session_state.get(_state_key("mese"), default_mese)),
        scenario=st.session_state.get(_state_key("scenario"), "Actual"),
        user_email=user_email,
        allowed_apps=frozenset() if allowed_apps is None else allowed_apps,
    )


def render_sidebar_context(
    *, user_email: str | None = None, allowed_apps: frozenset[str] | None = None
) -> SurfaceContext:
    """Renderizza il contesto globale una volta e lo restituisce alle superfici."""
    default_anno, default_mese = _default_period()
    with st.sidebar:
        st.markdown("### Contesto")
        st.selectbox(
            "Società",
            ["ORTI", "INTUR"],
            key=_state_key("societa"),
        )
        st.number_input(
            "Anno",
            min_value=2020,
            max_value=2100,
            value=default_anno,
            step=1,
            key=_state_key("anno"),
        )
        st.selectbox(
            "Mese",
            list(range(1, 13)),
            index=default_mese - 1,
            format_func=lambda m: f"{m:02d} · {_MESI[m - 1]}",
            key=_state_key("mese"),
        )
        st.selectbox(
            "Scenario",
            ["Actual"],
            key=_state_key("scenario"),
        )
        if user_email:
            st.caption(f"Utente: {user_email}")
    return current_context(user_email=user_email, allowed_apps=allowed_apps)
