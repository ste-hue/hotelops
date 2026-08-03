"""Client IMAP in sola lettura per caselle PEC.

Modulo autonomo: non importa nulla di hotelops. Non invia (nessun SMTP) e
non scrive sulla casella (nessun flag, nessun \\Seen): sono caselle con
valore probatorio e un processo automatico non le tocca.
"""

from __future__ import annotations

import imaplib
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)


def _connect(cfg: ImapConfig, folder: str = "INBOX"):
    conn = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    conn.login(cfg.user, cfg.password)
    conn.select(folder, readonly=True)  # <- la garanzia di sola lettura
    return conn


def _search(conn, criterion: str) -> set[int]:
    typ, data = conn.uid("search", None, criterion)
    if typ != "OK":
        raise RuntimeError(f"IMAP search fallita ({criterion}): {typ}")
    if not data or not data[0]:
        return set()
    return {int(u) for u in data[0].split()}


def fetch_since(
    cfg: ImapConfig,
    since_uid: int,
    folder: str = "INBOX",
    since_date: str | None = None,
    conn_factory=None,
) -> list[tuple[int, bytes]]:
    """Buste con UID > since_uid, più quelle da since_date (formato "01-Jul-2026").

    `folder` seleziona la cartella IMAP (es. "INBOX.Inviata"); la sola
    lettura resta garantita anche lì (`select(folder, readonly=True)`).
    """
    conn = (conn_factory or _connect)(cfg, folder)
    try:
        # "UID N:*" torna sempre anche l'ultimo messaggio, pure se il suo UID
        # è < N. Senza questo filtro lo si rilavora a ogni giro, per sempre.
        # Il filtro va applicato SOLO qui: se lo si applica anche all'unione
        # con SINCE sotto, la finestra di sicurezza diventa un no-op, perché
        # esiste apposta per recuperare UID bassi con data recente.
        uids = {u for u in _search(conn, f"UID {since_uid + 1}:*") if u > since_uid}
        if since_date:
            uids |= _search(conn, f"SINCE {since_date}")

        out: list[tuple[int, bytes]] = []
        for uid in sorted(uids):
            typ, msg = conn.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg or msg[0] is None:
                log.warning("UID %d: fetch fallita, salto", uid)
                continue
            out.append((uid, msg[0][1]))
        return out
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 — logout best-effort
            log.debug("logout fallito", exc_info=True)
