"""Bonifica one-shot delle copie PEC caricate a mano il 2026-07-16.

Prefissi manuali: gs://orti-raw/pec/** e gs://stefano-raw/pec/** (VIGNA solo
dopo che sarà ingerita dal nuovo flusso). Rimozione SOLO se, per ogni file:
promote SUCCESS + oggetto canonico presente + hash combaciante + lineage in
BQ (spec 2026-07-17 §bonifica). Default: report-only. --esegui per rimuovere.

Nomi tabelle verificati (2026-07-17) su core/lineage/raw_manifest.py:
F_RAW_OBJECTS = f"{PROJECT}.{DATASET}.f_raw_objects", F_LINEAGE_EVENTS =
f"{PROJECT}.{DATASET}.f_lineage_events" con PROJECT="hotelops-suite" e
DATASET="hotelops" — non esposti da core.config, quindi qui si ricostruisce
lo stesso path con core.config.PROJECT + literal "hotelops" (identico).
RawObjectStatus (core/lineage/schemas.py) include "PROMOTED": la query sotto
è corretta così com'è, nessun adeguamento necessario.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import logging

from core.config import PROJECT

log = logging.getLogger("scripts.bonifica_pec")

PREFISSI_MANUALI = [("orti-raw", "pec/"), ("stefano-raw", "pec/")]
# I path canonici delle sorgenti PEC (raw_storage.path_template) NON stanno
# sotto pec/ ma sotto pec/mailbox/<ENTITY>/... tramite intake: qui si
# escludono per non toccare mai il canonico.
PREFISSI_CANONICI = ("pec/mailbox/",)


def puo_rimuovere(promoted: bool, canonico_esiste: bool,
                  hash_combacia: bool, lineage_persistita: bool) -> bool:
    return promoted and canonico_esiste and hash_combacia and lineage_persistita


def _md5_hex(blob) -> str:
    return binascii.hexlify(base64.b64decode(blob.md5_hash)).decode()


def _stato_lineage(client, content_hash: str) -> tuple[bool, bool, str | None]:
    """(promoted, lineage_persistita, raw_uri_canonico) per content_hash."""
    sql = f"""
    SELECT r.raw_object_id, r.raw_uri,
      (SELECT ARRAY_AGG(e.to_status IGNORE NULLS ORDER BY e.event_at DESC LIMIT 1)[OFFSET(0)]
       FROM `{PROJECT}.hotelops.f_lineage_events` e
       WHERE e.raw_object_id = r.raw_object_id) AS stato
    FROM `{PROJECT}.hotelops.f_raw_objects` r
    WHERE r.content_hash = @h
    """
    from google.cloud import bigquery

    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("h", "STRING", content_hash)]
    )).result())
    if not rows:
        return False, False, None
    r = rows[0]
    return (r.stato == "PROMOTED"), True, r.raw_uri


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esegui", action="store_true",
                    help="rimuove davvero (default: solo report)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from google.cloud import storage

    from core.bq.client import get_client

    gcs = storage.Client(project=PROJECT)
    bq = get_client()
    rimossi, bloccati = [], []

    for bucket_name, prefisso in PREFISSI_MANUALI:
        bucket = gcs.bucket(bucket_name)
        for blob in bucket.list_blobs(prefix=prefisso):
            if blob.name.startswith(PREFISSI_CANONICI):
                continue
            h = _md5_hex(blob)
            promoted, lineage, raw_uri = _stato_lineage(bq, h)
            canonico, combacia = False, False
            if raw_uri and raw_uri.startswith("gs://"):
                b2, _, p2 = raw_uri.removeprefix("gs://").partition("/")
                can = gcs.bucket(b2).get_blob(p2)
                canonico = can is not None
                combacia = canonico and _md5_hex(can) == h
            verdetto = puo_rimuovere(promoted, canonico, combacia, lineage)
            riga = (f"gs://{bucket_name}/{blob.name} → promoted={promoted} "
                    f"canonico={canonico} hash_ok={combacia} lineage={lineage}")
            if verdetto:
                rimossi.append(riga)
                if args.esegui:
                    blob.delete()
            else:
                bloccati.append(riga)

    azione = "RIMOSSO" if args.esegui else "RIMOVIBILE"
    for r in rimossi:
        log.info("%s: %s", azione, r)
    for r in bloccati:
        log.warning("BLOCCATO: %s", r)
    log.info("totale: %d %s, %d bloccati", len(rimossi), azione.lower(), len(bloccati))


if __name__ == "__main__":
    main()
