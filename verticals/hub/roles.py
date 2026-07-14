"""Risoluzione identità → app concesse per il hub.

L'auth "chi entra" è all'edge (IAP). Qui si legge l'email autenticata e si
risolve il set di app-id concesse. Le app SENSIBILI (scrittura/stato) non
ereditano dalle costanti-gruppo: vanno concesse a mano (Invariante S1).
Il bypass dev è SOLO esplicito (HUB_DEV_ALLOW_ALL=1); default fail-closed (S2).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import streamlit as st

from verticals.hub.registry import APPS

# Header con cui l'edge espone l'email autenticata (IAP oggi; Cloudflare Access domani).
_EDGE_HEADERS = (
    "X-Goog-Authenticated-User-Email",
    "Cf-Access-Authenticated-User-Email",
)
_DEV_BYPASS_ENV = "HUB_DEV_ALLOW_ALL"


def _group_safe(group: str) -> frozenset[str]:
    """App del gruppo NON sensibili — le sensibili non si ereditano (S1).

    I placeholder ``soon`` sono esclusi: non sono superfici concedibili
    (es. cdg spento 2026-07-05 non deve rientrare in FINANZA dal gruppo).
    """
    return frozenset(
        a.id for a in APPS if a.group == group and not a.sensitive and a.kind != "soon"
    )


# {banche, mutui} — cashflow e cdg esclusi (sensitive: scrivono su BQ).
FINANZA = _group_safe("Finanza")
OPERATIONS = _group_safe("Operations")  # {fb, spiaggia, reviews}
ALL = frozenset(a.id for a in APPS)  # admin: tutto, sensibili incluse

# Tripwire S1: le costanti-gruppo non devono contenere app sensibili.
# Eseguito a import-time: se qualcuno bypassa _group_safe o marca un'app
# sensibile senza escluderla, il modulo esplode subito (fail loudly).
_SENSITIVE_IDS = frozenset(a.id for a in APPS if a.sensitive)


def _assert_s1(name: str, const: frozenset[str]) -> frozenset[str]:
    """Tripwire S1: una costante-gruppo non può contenere app sensibili.

    Difende dal caso in cui qualcuno hardcodi una costante bypassando
    _group_safe, o marchi un'app sensibile senza escluderla dal gruppo.
    """
    leaked = const & _SENSITIVE_IDS
    if leaked:
        raise AssertionError(f"S1 violata: app sensibili in {name}: {sorted(leaked)}")
    return const


_assert_s1("FINANZA", FINANZA)
_assert_s1("OPERATIONS", OPERATIONS)

# Mappa email → app concesse. Versionata in git; sensibili nominate a mano (S1).
_GRANTS: dict[str, frozenset[str]] = {
    "stefano@panoramagroup.it": ALL,  # Stefano (Workspace/IAP) — admin
    "ste.dellapietra@gmail.com": ALL,  # Stefano (gmail) — ridondanza
    "amministrazione@panoramagroup.it": FINANZA | {"cashflow", "accodamenti", "spiaggia", "bilancini"},  # Rosa
    "fom@panoramagroup.it": OPERATIONS,  # Anna (room division)
    "fb@panoramagroup.it": OPERATIONS,  # Stefano Amato (F&B)
    "gm@panoramagroup.it": FINANZA
    | OPERATIONS
    | {"cashflow", "cdg", "bilancini"},  # Antonio Russo (direttore)
    "stedepi@gmail.com": frozenset({"reviews", "mutui"}),  # padre
    "magazzino@panoramagroup.it": frozenset({"fb", "spiaggia"}),  # Mario (economato)
}


def _parse_email(raw: str | None) -> str | None:
    """`accounts.google.com:foo@bar` → `foo@bar`; None/'' → None."""
    if not raw:
        return None
    return raw.split(":", 1)[1] if ":" in raw else raw


def _email_from_headers(headers: Mapping | None) -> str | None:
    if not headers:
        return None
    lower = {str(k).lower(): v for k, v in dict(headers).items()}
    for h in _EDGE_HEADERS:
        if h.lower() in lower:
            return _parse_email(lower[h.lower()])
    return None


def _resolve(email: str | None, allow_all: bool) -> frozenset[str]:
    if email is not None:
        return _GRANTS.get(email, frozenset())  # nota → grant; ignota → deny
    # Nessuna identità: l'assenza di header NON prova "dev" → fail-closed (S2).
    return ALL if allow_all else frozenset()


def current_email() -> str | None:
    """Email autenticata dall'edge per il run corrente (None se assente)."""
    try:
        headers = st.context.headers
    except Exception:
        headers = None
    return _email_from_headers(headers)


def current_apps() -> frozenset[str]:
    """App-id concesse all'utente del run corrente. Non eccepisce mai."""
    email = current_email()
    allow_all = os.environ.get(_DEV_BYPASS_ENV) == "1"
    return _resolve(email, allow_all)
