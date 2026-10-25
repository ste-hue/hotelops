"""Raccordi di navigazione per progetto, non una seconda anagrafica business.

Gli ID riusano i codici dei progetti esistenti. Nessun budget, stato o
avanzamento viene copiato dalle app in questo catalogo.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectSurface:
    progetto_id: str
    title: str
    app_url: str
    regia_node_id: str
    description: str

    @property
    def regia_url(self) -> str:
        return f"https://regia.panorama-host.com/?node={self.regia_node_id}"


PROJECTS = (
    ProjectSurface(
        progetto_id="HPAN26SOFT",
        title="Soft restyling camere",
        app_url="https://soft.panorama-host.com",
        regia_node_id="68079b85",
        description="Rilievi, interventi e piano delle camere esistenti.",
    ),
    ProjectSurface(
        progetto_id="HPAN26PIANO3",
        title="Terzo piano — cantiere 2026–27",
        app_url="https://hpan26.panorama-host.com",
        regia_node_id="ea45459f",
        description="Cronoprogramma e forniture del terzo piano.",
    ),
)
