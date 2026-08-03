"""Watermark UID per casella+cartella PEC, su GCS.

È una OTTIMIZZAZIONE, non la garanzia di correttezza: evita di riscaricare
buste già viste. La correttezza sta nel content-hash all'intake. Se un
watermark si perde, il giro riscarica e l'hash impedisce i duplicati.

Gli UID IMAP sono per-cartella: INBOX e INBOX.Inviata hanno numerazioni
indipendenti, quindi il watermark è a chiave doppia (entity, folder).
Path: pec/_watermark/<ENTITY>/<folder>.json, con il "." di "INBOX.Inviata"
sostituito da "_" (niente sottocartelle involontarie su GCS).

Payload: {"last_uid": N, "uidvalidity": V}. Gli UID sono unici solo a parità
di UIDVALIDITY: se il server ricrea/migra la cartella ripartono da 1 e un
watermark alto sopprimerebbe tutto in silenzio. I file scritti prima che il
campo esistesse restano validi: senza `uidvalidity` non si azzera nulla.
"""

from __future__ import annotations

import json
import logging
from typing import NamedTuple

log = logging.getLogger(__name__)

_PREFIX = "pec/_watermark"


class Watermark(NamedTuple):
    """UID massimo visto, più la UIDVALIDITY della cartella in cui vale.

    `uidvalidity` è None sui watermark scritti prima che il campo esistesse:
    senza riferimento non si può dire che la cartella sia cambiata, quindi
    non si azzera nulla (il campo si popola alla prima scrittura utile).
    """

    last_uid: int
    uidvalidity: int | None = None


def _folder_key(folder: str) -> str:
    return folder.replace(".", "_")


def _legacy_blob(bucket: str, entity_id: str, client):
    return client.bucket(bucket).blob(f"{_PREFIX}/{entity_id}.json")


def _blob(bucket: str, entity_id: str, folder: str, client=None):
    if client is None:
        from google.cloud import storage

        client = storage.Client()
    blob = client.bucket(bucket).blob(
        f"{_PREFIX}/{entity_id}/{_folder_key(folder)}.json"
    )
    return blob, client


def _migrate_legacy_if_needed(bucket: str, entity_id: str, blob, client) -> None:
    """Il vecchio path per-casella (pre-cartelle) diventa il watermark di INBOX."""
    if blob.exists():
        return
    legacy = _legacy_blob(bucket, entity_id, client)
    if not legacy.exists():
        return
    log.info("Migro watermark legacy di %s a INBOX", entity_id)
    blob.upload_from_string(legacy.download_as_text(), content_type="application/json")


def read_watermark(
    bucket: str, entity_id: str, folder: str = "INBOX", client=None
) -> Watermark:
    blob, client = _blob(bucket, entity_id, folder, client)
    if folder == "INBOX":
        _migrate_legacy_if_needed(bucket, entity_id, blob, client)
    if not blob.exists():
        log.info("Nessun watermark per %s/%s: si parte da 0", entity_id, folder)
        return Watermark(0)
    payload = json.loads(blob.download_as_text())
    uidvalidity = payload.get("uidvalidity")
    return Watermark(
        int(payload["last_uid"]),
        int(uidvalidity) if uidvalidity is not None else None,
    )


def write_watermark(
    bucket: str,
    entity_id: str,
    uid: int,
    folder: str = "INBOX",
    client=None,
    uidvalidity: int | None = None,
) -> None:
    blob, _ = _blob(bucket, entity_id, folder, client)
    payload: dict[str, int] = {"last_uid": int(uid)}
    if uidvalidity is not None:
        payload["uidvalidity"] = int(uidvalidity)
    blob.upload_from_string(json.dumps(payload), content_type="application/json")
    log.info(
        "Watermark %s/%s → %d (uidvalidity=%s)", entity_id, folder, uid, uidvalidity
    )
