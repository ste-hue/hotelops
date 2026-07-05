"""Registry app-store del hub: una sola fonte di verità per ogni superficie.

La Home (gateway) e la nav si costruiscono da ``APPS``. Aggiungere un'app = appendere
una riga qui. I **ruoli/multi-audience sono rimandati** (YAGNI): quando serviranno, si
aggiunge un campo ``roles`` + ``roles.py`` (spec 2026-06-14-hub-app-store-infrastructure).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from verticals.hub.pages_ import accodamenti, cashflow, fb, mutui, reviews, spiaggia

# Ordine dei gruppi nella Home gateway.
GROUPS = ["Finanza", "Operations", "Sistema"]

# URL esterni (bind).
_BANCHE_LOOKER = (
    "https://datastudio.google.com/u/0/reporting/"
    "2a7a4c25-56f2-44d4-986f-9a9cc27a03cd/page/TlJ0C"
)


@dataclass(frozen=True)
class HubApp:
    """Una superficie montata nel hub.

    kind:
      - "page"  → ``target`` è una ``render()`` Streamlit (montata in nav + tile)
      - "bind"  → ``target`` è un URL esterno (solo tile, link in nuova scheda)
      - "soon"  → placeholder "coming soon" (né nav né link)
    """

    id: str
    title: str
    icon: str
    group: str
    kind: str
    target: Callable | str | None = None
    subtitle: str = ""
    sensitive: bool = False  # scrive/muta stato/azioni irreversibili/dati riservati (S1)


APPS: list[HubApp] = [
    # ── Finanza ──────────────────────────────────────────────────────────────
    HubApp("cashflow", "Cashflow", "💸", "Finanza", "page", cashflow.render, "PF & proiezione cassa", sensitive=True),
    HubApp("accodamenti", "Accodamenti", "📒", "Finanza", "page", accodamenti.render, "raccolta cassa → Gaia", sensitive=True),
    HubApp("banche", "Banche", "🏛", "Finanza", "bind", _BANCHE_LOOKER, "movimenti & saldi (Looker)"),
    HubApp("mutui", "Mutui", "🏦", "Finanza", "page", mutui.render, "ammortamenti & simulatore"),
    # CdG spento 2026-07-05 (troppi dati, redesign "budget vs reale" in arrivo);
    # riaccendere = ripristinare kind=page + import (pages_/cdg.py resta nel codice).
    HubApp("cdg", "CdG", "📊", "Finanza", "soon", None, "controllo di gestione (in redesign)"),
    # ── Operations ───────────────────────────────────────────────────────────
    HubApp("fb", "Food & Beverage", "🍽", "Operations", "page", fb.render, "food cost & coperti"),
    HubApp("spiaggia", "Spiaggia", "🏖️", "Operations", "page", spiaggia.render, "ricavo stabilimento & quadratura"),
    HubApp("reviews", "Reviews", "⭐", "Operations", "page", reviews.render, "reputation & sentiment"),
    # ── Sistema ──────────────────────────────────────────────────────────────
    # L'ingest NON è una sezione trasversale: è una funzione di ciascun vertical
    # (accodamenti → condges/Finanza, F&B → Operations, …). La vecchia pagina
    # Ingest generica (intake→promote per qualsiasi file) è smontata dalla nav —
    # l'ingest "intelligente per tipi nuovi" vive nella chat (skill hotelops-ingest).
    # `verticals/hub/pages_/ingest.py` resta nel codice come tool di lineage.
]


def validate(apps: list[HubApp] = APPS) -> None:
    """Check a import-time: id unici, group noto, target coerente col kind."""
    seen = set()
    for a in apps:
        if a.id in seen:
            raise ValueError(f"registry: id duplicato {a.id!r}")
        seen.add(a.id)
        if a.group not in GROUPS:
            raise ValueError(f"registry: group sconosciuto {a.group!r} per {a.id!r}")
        if a.kind == "page" and not callable(a.target):
            raise ValueError(f"registry: {a.id!r} kind=page richiede target callable")
        if a.kind == "bind" and not isinstance(a.target, str):
            raise ValueError(f"registry: {a.id!r} kind=bind richiede URL str")
        if a.kind == "soon" and a.target is not None:
            raise ValueError(f"registry: {a.id!r} kind=soon non ha target")
        if a.kind not in ("page", "bind", "soon"):
            raise ValueError(f"registry: {a.id!r} kind sconosciuto {a.kind!r}")


def pages() -> list[HubApp]:
    """Le app montabili come pagina Streamlit (per la nav)."""
    return [a for a in APPS if a.kind == "page"]


def by_group() -> dict[str, list[HubApp]]:
    """Le app raggruppate per dominio, nell'ordine di ``GROUPS``."""
    return {g: [a for a in APPS if a.group == g] for g in GROUPS}


def pages_for(allowed: frozenset[str]) -> list[HubApp]:
    """Le pagine montabili (kind=page) concesse a ``allowed``."""
    return [a for a in pages() if a.id in allowed]


def by_group_for(allowed: frozenset[str]) -> dict[str, list[HubApp]]:
    """Le app per gruppo, filtrate su ``allowed`` (gruppi vuoti restano chiavi)."""
    return {g: [a for a in apps if a.id in allowed] for g, apps in by_group().items()}


validate()
