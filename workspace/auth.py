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


def drive_write_credentials(subject: str):
    """Delegated credentials for writing files, impersonating a user with Drive quota.

    Service accounts have zero Drive storage quota in Workspace — uploads fail with
    403 "Service Accounts do not have storage quota". Impersonating a real user
    (e.g. stefano@panoramagroup.it) makes the uploaded files owned by that user.
    """
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=[SCOPE_DRIVE_FILE],
    )
    return creds.with_subject(subject)
