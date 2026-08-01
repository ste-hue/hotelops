"""Watermark UID per casella PEC, su GCS.

È una OTTIMIZZAZIONE, non la garanzia di correttezza: evita di riscaricare
buste già viste. La correttezza sta nel content-hash all'intake. Se un
watermark si perde, il giro riscarica e l'hash impedisce i duplicati.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_PREFIX = "pec/_watermark"


def _blob(bucket: str, entity_id: str, client=None):
    if client is None:
        from google.cloud import storage

        client = storage.Client()
    return client.bucket(bucket).blob(f"{_PREFIX}/{entity_id}.json")


def read_watermark(bucket: str, entity_id: str, client=None) -> int:
    blob = _blob(bucket, entity_id, client)
    if not blob.exists():
        log.info("Nessun watermark per %s: si parte da 0", entity_id)
        return 0
    return int(json.loads(blob.download_as_text())["last_uid"])


def write_watermark(bucket: str, entity_id: str, uid: int, client=None) -> None:
    blob = _blob(bucket, entity_id, client)
    blob.upload_from_string(
        json.dumps({"last_uid": int(uid)}), content_type="application/json"
    )
    log.info("Watermark %s → %d", entity_id, uid)
