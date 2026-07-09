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


def ensure_shared_with(owner_or_holder: str, file_id: str, grantee: str) -> bool:
    """Concede a `grantee` accesso reader su `file_id`, impersonando un utente
    che possiede/detiene il file (DWD), senza email di notifica. Ritorna True
    se ora e' condiviso (o lo era gia'), False se non e' stato possibile (es.
    proprietario esterno al dominio non impersonabile)."""
    from googleapiclient.errors import HttpError

    try:
        svc = get_drive_writer(owner_or_holder)
        svc.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": "reader", "emailAddress": grantee},
            sendNotificationEmail=False,
            supportsAllDrives=True,
            fields="id",
        ).execute()
        return True
    except HttpError as e:
        content = e.content if isinstance(e.content, bytes) else str(e.content).encode()
        if e.resp.status in (400, 409) and (
            b"already" in content.lower() or b"duplicate" in content.lower()
        ):
            return True
        return False
    except Exception:
        # es. credenziali non ottenibili per un subject esterno al dominio
        return False


def create_shortcut(service, parent_id: str, name: str, target_id: str) -> str:
    """Crea una scorciatoia Drive a `target_id` dentro `parent_id`; ritorna l'id."""
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.shortcut",
        "parents": [parent_id],
        "shortcutDetails": {"targetId": target_id},
    }
    created = (
        service.files()
        .create(body=body, fields="id", supportsAllDrives=True)
        .execute()
    )
    return created["id"]


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
