from __future__ import annotations

from google.oauth2 import service_account

from .config import (
    SA_KEY_PATH,
    SCOPE_DRIVE_FILE,
    SCOPE_DRIVE_READ,
    SCOPE_GMAIL_READ,
)


def gmail_credentials(subject: str):
    """Delegated credentials impersonating mailbox owner (read Gmail)."""
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=[SCOPE_GMAIL_READ],
    )
    return creds.with_subject(subject)


def drive_read_credentials(subject: str):
    """Delegated credentials impersonating user (read their Drive content)."""
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=[SCOPE_DRIVE_READ],
    )
    return creds.with_subject(subject)


def drive_write_credentials():
    """SA's own credentials for writing output files (no impersonation).

    Destination folder must be shared with the SA email as Editor.
    drive.file scope = SA can only act on files it created (or in shared folders).
    """
    return service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=[SCOPE_DRIVE_FILE],
    )
