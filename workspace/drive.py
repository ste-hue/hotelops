from __future__ import annotations

import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from .auth import drive_read_credentials, drive_write_credentials


def get_drive_writer(subject: str):
    """Drive service for writing output (impersonating subject who owns quota)."""
    return build(
        "drive",
        "v3",
        credentials=drive_write_credentials(subject),
        cache_discovery=False,
    )


def get_drive_reader(subject: str):
    """Drive service for reading user's Drive (impersonated, drive.readonly scope)."""
    return build(
        "drive",
        "v3",
        credentials=drive_read_credentials(subject),
        cache_discovery=False,
    )


def ensure_subfolder(service, parent_id: str, name: str) -> str:
    """Return id of subfolder named `name` under `parent_id`, creating if missing."""
    safe_name = name.replace("'", "\\'")
    q = (
        f"'{parent_id}' in parents and name = '{safe_name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resp = (
        service.files()
        .list(
            q=q,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    found = resp.get("files", [])
    if found:
        return found[0]["id"]
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = (
        service.files()
        .create(body=body, fields="id", supportsAllDrives=True)
        .execute()
    )
    return folder["id"]


def upload_bytes(
    service, parent_id: str, name: str, data: bytes, mime_type: str
) -> str:
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    body = {"name": name, "parents": [parent_id]}
    f = (
        service.files()
        .create(body=body, media_body=media, fields="id", supportsAllDrives=True)
        .execute()
    )
    return f["id"]
