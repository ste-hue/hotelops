"""Watermark UID per casella+cartella PEC, su GCS.

È una OTTIMIZZAZIONE, non la garanzia di correttezza: evita di riscaricare
buste già viste. La correttezza sta nel content-hash all'intake. Se un
watermark si perde, il giro riscarica e l'hash impedisce i duplicati.

Gli UID IMAP sono per-cartella: INBOX e INBOX.Inviata hanno numerazioni
indipendenti, quindi il watermark è a chiave doppia (entity, folder).
Path: pec/_watermark/<ENTITY>/<folder>.json, con il "." di "INBOX.Inviata"
sostituito da "_" (niente sottocartelle involontarie su GCS).
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_PREFIX = "pec/_watermark"


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
) -> int:
    blob, client = _blob(bucket, entity_id, folder, client)
    if folder == "INBOX":
        _migrate_legacy_if_needed(bucket, entity_id, blob, client)
    if not blob.exists():
        log.info("Nessun watermark per %s/%s: si parte da 0", entity_id, folder)
        return 0
    return int(json.loads(blob.download_as_text())["last_uid"])


def write_watermark(
    bucket: str, entity_id: str, uid: int, folder: str = "INBOX", client=None
) -> None:
    blob, _ = _blob(bucket, entity_id, folder, client)
    blob.upload_from_string(
        json.dumps({"last_uid": int(uid)}), content_type="application/json"
    )
    log.info("Watermark %s/%s → %d", entity_id, folder, uid)
