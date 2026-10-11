from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


def resolve_datahub_root() -> Path:
    """Return the local hotelops_datahub root with env override first."""
    env_path = _env_path("HOTELOPS_DATAHUB_ROOT")
    if env_path:
        return env_path

    home = Path.home()
    candidates = [
        home / "Library" / "CloudStorage" / "GoogleDrive" / "My Drive" / "00_hotelops_datahub",
        home / "Google Drive" / "My Drive" / "00_hotelops_datahub",
        home / "hotelops_datahub",
    ]
    cloud_storage = home / "Library" / "CloudStorage"
    if cloud_storage.exists():
        for drive_mount in sorted(cloud_storage.glob("GoogleDrive-*")):
            candidates.insert(
                0, drive_mount / "My Drive" / "00_hotelops_datahub"
            )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_artifacts_root() -> Path:
    """Return the default local artifacts folder with env override first."""
    env_path = _env_path("HOTELOPS_ARTIFACTS_ROOT")
    if env_path:
        return env_path
    return Path.home() / "Desktop" / "WORK" / "artifacts"


def resolve_drive_sa_key_path() -> Path:
    """Return the Drive service-account key path with env override first."""
    env_path = _env_path("HOTELOPS_DRIVE_SA_KEY")
    if env_path:
        return env_path
    return Path.home() / ".config" / "hotelops" / "drive-audit-key.json"
