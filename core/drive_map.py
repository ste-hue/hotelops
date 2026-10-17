"""core/drive_map.yaml: le radici Drive che il job inventario percorre e le
cartelle canoniche per concetto. Spec 2026-10-17 drive-agent-friendly (P8 minima).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DRIVE_MAP_PATH = Path(__file__).resolve().parent / "drive_map.yaml"


@dataclass(frozen=True)
class DriveRoot:
    key: str
    id: str
    label: str
    inbox_only: bool = False


@dataclass(frozen=True)
class DriveMap:
    roots: dict[str, DriveRoot]
    folders: dict[str, str]
    domain: str


def load_drive_map(path: Path | None = None) -> DriveMap:
    path = path or Path(os.environ.get("HOTELOPS_DRIVE_MAP", str(DRIVE_MAP_PATH)))
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    roots = {
        key: DriveRoot(
            key=key,
            id=str(v["id"]),
            label=str(v.get("label", key)),
            inbox_only=bool(v.get("inbox_only", False)),
        )
        for key, v in (data.get("roots") or {}).items()
    }
    if not roots:
        raise ValueError(
            f"{path}: nessuna radice in `roots`; configura HOTELOPS_DRIVE_MAP "
            "con un file locale privato prima di eseguire l'inventario"
        )
    folders = {k: str(v["id"]) for k, v in (data.get("folders") or {}).items()}
    return DriveMap(roots=roots, folders=folders, domain=str(data.get("domain", "")))
