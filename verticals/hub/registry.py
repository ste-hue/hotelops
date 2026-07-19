"""Registry app-store del hub: sola metadata, zero import di implementazione."""

from __future__ import annotations

from dataclasses import dataclass

# Ordine dei gruppi nella Home gateway.
GROUPS = ["Finanza", "Operations", "Sistema"]

# URL esterni (bind).
_BANCHE_LOOKER = (
    "https://datastudio.google.com/u/0/reporting/"
    "2a7a4c25-56f2-44d4-986f-9a9cc27a03cd/page/TlJ0C"
)


def _is_https_route(route: str | None) -> bool:
    return isinstance(route, str) and route.startswith("https://")


@dataclass(frozen=True)
class HubApp:
    """Contratto di una superficie.

    Il registry dichiara *cosa* esiste; la risoluzione tecnica del render vive in
    ``verticals.hub.resolver``.
    """

    id: str
    title: str
    icon: str
    group: str
    kind: str
    route: str | None = None
    subtitle: str = ""
    sensitive: bool = False  # scrive/muta stato/azioni irreversibili/dati riservati (S1)
    capabilities: tuple[str, ...] = ()
    owner: str = ""
    context_requirements: tuple[str, ...] = ()
    delivery_mode: str = "streamlit"


APPS: list[HubApp] = [
    # ── Finanza ──────────────────────────────────────────────────────────────
    HubApp(
        "cashflow",
        "Cashflow",
        "💸",
        "Finanza",
        "page",
        "cashflow",
        "PF & proiezione cassa",
        sensitive=True,
        capabilities=("write", "export_xlsx", "audit"),
        owner="Rosa",
        context_requirements=("societa", "mese", "scenario"),
        delivery_mode="streamlit",
    ),
    HubApp(
        "cassa-consuntivo",
        "Cassa consuntivo",
        "💰",
        "Finanza",
        "page",
        "cassa-consuntivo",
        "Il vero cashflow: banca vs certificati",
        sensitive=True,
        capabilities=("audit", "drilldown"),
        owner="Rosa",
        context_requirements=("societa", "mese", "scenario"),
        delivery_mode="streamlit",
    ),
    HubApp(
        "bilancini",
        "Bilancini",
        "📗",
        "Finanza",
        "page",
        "bilancini",
        "bilancio di verifica: YTD, progressione, navigatore",
        sensitive=True,
        capabilities=("export_csv", "search", "drilldown", "audit"),
        owner="Rosa",
        context_requirements=("societa", "mese", "scenario"),
        delivery_mode="edge",
    ),
    HubApp(
        "accodamenti",
        "Accodamenti",
        "📒",
        "Finanza",
        "page",
        "accodamenti",
        "raccolta cassa → Gaia",
        sensitive=True,
        capabilities=("write", "audit"),
        owner="Rosa",
        context_requirements=("societa", "mese"),
        delivery_mode="streamlit",
    ),
    HubApp(
        "banche",
        "Banche",
        "🏛",
        "Finanza",
        "bind",
        _BANCHE_LOOKER,
        "movimenti & saldi (Looker)",
        capabilities=("search", "audit"),
        owner="Rosa",
        context_requirements=("societa", "mese"),
        delivery_mode="external",
    ),
    HubApp(
        "mutui",
        "Mutui",
        "🏦",
        "Finanza",
        "page",
        "mutui",
        "ammortamenti & simulatore",
        capabilities=("scenario", "export_csv"),
        owner="Stefano",
        context_requirements=("scenario",),
        delivery_mode="edge",
    ),
    HubApp(
        "revenue",
        "Revenue",
        "📈",
        "Finanza",
        "page",
        "revenue",
        "booking curve & pace",
        sensitive=True,
        capabilities=("upload", "audit"),
        owner="Antonio Russo",
        context_requirements=("mese", "scenario"),
        delivery_mode="streamlit",
    ),
    # CdG spento 2026-07-05 (troppi dati, redesign "budget vs reale" in arrivo);
    # riaccendere = ripristinare kind=page + import (pages_/cdg.py resta nel codice).
    HubApp(
        "cdg",
        "CdG",
        "📊",
        "Finanza",
        "soon",
        None,
        "controllo di gestione (in redesign)",
        capabilities=("planned",),
        owner="Rosa / Romita",
        context_requirements=("societa", "mese", "scenario"),
        delivery_mode="planned",
    ),
    # ── Operations ───────────────────────────────────────────────────────────
    HubApp(
        "fb",
        "Food & Beverage",
        "🍽",
        "Operations",
        "page",
        "fb",
        "food cost & coperti",
        capabilities=("search", "audit"),
        owner="Mario",
        context_requirements=("mese",),
        delivery_mode="streamlit",
    ),
    HubApp(
        "spiaggia",
        "Spiaggia",
        "🏖️",
        "Operations",
        "page",
        "spiaggia",
        "ricavo stabilimento & quadratura",
        capabilities=("audit",),
        owner="Mario",
        context_requirements=("mese",),
        delivery_mode="streamlit",
    ),
    HubApp(
        "reviews",
        "Reviews",
        "⭐",
        "Operations",
        "page",
        "reviews",
        "reputation & sentiment",
        capabilities=("search", "audit"),
        owner="Antonio Russo",
        context_requirements=("scenario",),
        delivery_mode="streamlit",
    ),
    # ── Sistema ──────────────────────────────────────────────────────────────
    # L'ingest NON è una sezione trasversale: è una funzione di ciascun vertical
    # (accodamenti → condges/Finanza, F&B → Operations, …). La vecchia pagina
    # Ingest generica (intake→promote per qualsiasi file) è smontata dalla nav —
    # l'ingest "intelligente per tipi nuovi" vive nella chat (skill hotelops-ingest).
    # `verticals/hub/pages_/ingest.py` resta nel codice come tool di lineage.
]


def validate(apps: list[HubApp] = APPS) -> None:
    """Check a import-time: id unici, group noto, route coerente col kind."""
    seen = set()
    for a in apps:
        if a.id in seen:
            raise ValueError(f"registry: id duplicato {a.id!r}")
        seen.add(a.id)
        if a.group not in GROUPS:
            raise ValueError(f"registry: group sconosciuto {a.group!r} per {a.id!r}")
        if a.kind == "page" and not isinstance(a.route, str):
            raise ValueError(f"registry: {a.id!r} kind=page richiede route str")
        if a.kind == "bind" and not _is_https_route(a.route):
            raise ValueError(f"registry: {a.id!r} kind=bind richiede URL https")
        if a.kind == "soon" and a.route is not None:
            raise ValueError(f"registry: {a.id!r} kind=soon non ha route")
        if a.kind not in ("page", "bind", "soon"):
            raise ValueError(f"registry: {a.id!r} kind sconosciuto {a.kind!r}")
        if not isinstance(a.capabilities, tuple):
            raise ValueError(f"registry: {a.id!r} capabilities deve essere tuple")
        if not isinstance(a.context_requirements, tuple):
            raise ValueError(
                f"registry: {a.id!r} context_requirements deve essere tuple"
            )


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
