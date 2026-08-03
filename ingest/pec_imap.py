"""Client IMAP in sola lettura per caselle PEC.

Modulo autonomo: non importa nulla di hotelops. Non invia (nessun SMTP) e
non scrive sulla casella (nessun flag, nessun \\Seen): sono caselle con
valore probatorio e un processo automatico non le tocca.
"""

from __future__ import annotations

import imaplib
import logging
from dataclasses import dataclass, field
from typing import Iterator, NamedTuple

log = logging.getLogger(__name__)

CHUNK_SIZE = 50


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)


class Block(NamedTuple):
    """Un blocco di buste, con il contesto che serve a scrivere il watermark.

    `base_uid` è il watermark da cui la cartella è effettivamente ripartita:
    0 se `uidvalidity` è cambiata (cartella ricreata lato server → gli UID
    vecchi non valgono più), altrimenti il watermark passato dal chiamante.
    """

    uidvalidity: int | None
    base_uid: int
    messages: list[tuple[int, bytes]]


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


def _uidvalidity(conn) -> int | None:
    """UIDVALIDITY della cartella appena selezionata (untagged response)."""
    try:
        _, data = conn.response("UIDVALIDITY")
    except Exception:  # noqa: BLE001 — server che non la espone: si degrada, non si rompe
        log.debug("UIDVALIDITY non leggibile", exc_info=True)
        return None
    if not data or not data[0]:
        return None
    return int(data[0])


def fetch_since(
    cfg: ImapConfig,
    since_uid: int,
    folder: str = "INBOX",
    since_date: str | None = None,
    conn_factory=None,
    uidvalidity: int | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> Iterator[Block]:
    """Buste con UID > since_uid, più quelle da since_date (formato "01-Jul-2026").

    Generatore: produce **blocchi** di `chunk_size` buste in UID crescente,
    così il chiamante può salvare il watermark man mano invece che a fine
    cartella. Una cartella da migliaia di messaggi avanza di quanto riesce
    anche se la connessione cade a metà (ed evita di tenere in RAM l'intero
    archivio).

    `folder` seleziona la cartella IMAP (es. "INBOX.Inviata"); la sola
    lettura resta garantita anche lì (`select(folder, readonly=True)`).

    `uidvalidity` è quella registrata nel watermark: se il server ne espone
    una diversa la cartella è stata ricreata/migrata, gli UID sono ripartiti
    e si riscarica da 0 (il content-hash all'intake deduplica).
    """
    conn = (conn_factory or _connect)(cfg, folder)
    try:
        current_uv = _uidvalidity(conn)
        base_uid = since_uid
        if (
            uidvalidity is not None
            and current_uv is not None
            and current_uv != uidvalidity
        ):
            log.warning(
                "%s: UIDVALIDITY cambiata (%d → %d): watermark azzerato, si riscarica tutto",
                folder,
                uidvalidity,
                current_uv,
            )
            base_uid = 0

        # "UID N:*" torna sempre anche l'ultimo messaggio, pure se il suo UID
        # è < N. Senza questo filtro lo si rilavora a ogni giro, per sempre.
        # Il filtro va applicato SOLO qui: se lo si applica anche all'unione
        # con SINCE sotto, la finestra di sicurezza diventa un no-op, perché
        # esiste apposta per recuperare UID bassi con data recente.
        uids = {u for u in _search(conn, f"UID {base_uid + 1}:*") if u > base_uid}
        if since_date:
            uids |= _search(conn, f"SINCE {since_date}")

        ordered = sorted(uids)
        for start in range(0, len(ordered), chunk_size):
            block: list[tuple[int, bytes]] = []
            for uid in ordered[start : start + chunk_size]:
                # BODY.PEEK[] e non RFC822: quest'ultimo setta \Seen, e la
                # sola lettura non deve dipendere dal fatto che la sessione
                # sia readonly.
                typ, msg = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
                if typ != "OK" or not msg or msg[0] is None:
                    # Mai saltare: il watermark avanzerebbe oltre una busta
                    # mai scaricata, e su un archivio probatorio sarebbe una
                    # perdita silenziosa e definitiva. Si alza: la cartella
                    # riparte al giro dopo, l'hash deduplica il già fatto.
                    raise RuntimeError(f"UID {uid}: fetch fallita ({typ}) su {folder}")
                block.append((uid, msg[0][1]))
            yield Block(uidvalidity=current_uv, base_uid=base_uid, messages=block)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 — logout best-effort
            log.debug("logout fallito", exc_info=True)
