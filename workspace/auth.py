from __future__ import annotations

from google.oauth2 import service_account

from .config import SA_KEY_PATH, SCOPE_DRIVE_FILE, SCOPE_GMAIL_READ


def gmail_credentials(subject: str):
    """Delegated credentials impersonating mailbox owner."""
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=[SCOPE_GMAIL_READ],
    )
    return creds.with_subject(subject)


def drive_credentials():
    """SA's own credentials for Drive uploads (no impersonation).

    Destination folders must be shared with the SA email as Editor for drive.file
    scope to allow file creation under them.
    """
    return service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=[SCOPE_DRIVE_FILE],
    )
