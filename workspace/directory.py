"""Enumerazione utenti del dominio via Admin SDK Directory API."""

from __future__ import annotations

from googleapiclient.discovery import build

from .auth import directory_credentials
from .config import DOMAIN


def users_from_response(resp: dict) -> list[dict]:
    """Mappa la risposta users().list in dict piatti (puro, testabile)."""
    out = []
    for u in resp.get("users", []) or []:
        out.append({
            "email": u.get("primaryEmail", ""),
            "full_name": (u.get("name") or {}).get("fullName", ""),
            "suspended": bool(u.get("suspended", False)),
            "is_admin": bool(u.get("isAdmin", False)),
        })
    return out


def enumerate_domain_users(subject: str, include_suspended: bool = True) -> list[dict]:
    svc = build("admin", "directory_v1",
                credentials=directory_credentials(subject), cache_discovery=False)
    users: list[dict] = []
    token = None
    while True:
        resp = svc.users().list(
            domain=DOMAIN, orderBy="email", maxResults=100, pageToken=token,
        ).execute()
        users.extend(users_from_response(resp))
        token = resp.get("nextPageToken")
        if not token:
            break
    if not include_suspended:
        users = [u for u in users if not u["suspended"]]
    return users
