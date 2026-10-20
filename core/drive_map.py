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
    """Load a private map; malformed YAML or schema raises ValueError.

    Readers can report unavailable coverage; writers must stop before effects.
    """
    path = path or Path(os.environ.get("HOTELOPS_DRIVE_MAP", str(DRIVE_MAP_PATH)))
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"{path}: YAML della mappa Drive non valido") from error
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: la mappa Drive deve essere un mapping")  # noqa: TRY004 — invalid configuration value
    for section in ("roots", "folders"):
        entries = data.get(section, {})
        if not isinstance(entries, dict):
            raise ValueError(f"{path}: `{section}` deve essere un mapping")  # noqa: TRY004 — invalid configuration value
        for key, entry in entries.items():
            if (
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(entry, dict)
                or not isinstance(entry.get("id"), str)
                or not entry["id"].strip()
            ):
                raise ValueError(
                    f"{path}: `{section}` richiede chiavi e id testuali non vuoti"
                )
            if section == "roots" and (
                not isinstance(entry.get("label", key), str)
                or not isinstance(entry.get("inbox_only", False), bool)
            ):
                raise ValueError(
                    f"{path}: una radice richiede label testuale e inbox_only booleano"
                )
    if not isinstance(data.get("domain", ""), str):
        raise ValueError(f"{path}: `domain` deve essere testuale")  # noqa: TRY004 — invalid configuration value
    roots = {
        key: DriveRoot(
            key=key,
            id=v["id"],
            label=v.get("label", key),
            inbox_only=v.get("inbox_only", False),
        )
        for key, v in data.get("roots", {}).items()
    }
    if not roots:
        raise ValueError(
            f"{path}: nessuna radice in `roots`; configura HOTELOPS_DRIVE_MAP "
            "con un file locale privato prima di eseguire l'inventario"
        )
    folders = {k: v["id"] for k, v in data.get("folders", {}).items()}
    return DriveMap(roots=roots, folders=folders, domain=data.get("domain", ""))
