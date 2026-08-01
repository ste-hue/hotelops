"""PEC auto-sync: fetch IMAP read-only, poi intake + promote.

Usage:
    python -m ingest.pec_fetch --all
    python -m ingest.pec_fetch --source-name PEC_MAILBOX_VIGNA_APPEND
    python -m ingest.pec_fetch --source-name PEC_MAILBOX_ORTI_APPEND --no-promote

Sostituisce lo scarico manuale dell'mbox dalla webmail. Tutto ciò che sta a
valle (parser, classificazione, pannello, digest) è invariato.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    entity_id: str
    fetched: int = 0
    ingested: int = 0
    deduped: int = 0
    last_uid: int = 0
    status: str = "OK"
    error: Optional[str] = None


@dataclass
class Deps:
    """Confini iniettabili — i test non toccano rete, GCS o BQ."""

    fetch_since: Callable
    read_watermark: Callable
    write_watermark: Callable
    intake_file: Callable
    promote_raw_object: Callable
    get_password: Callable


def _default_deps() -> Deps:
    from ingest.intake import intake_file
    from ingest.pec_imap import fetch_since
    from ingest.pec_watermark import read_watermark, write_watermark
    from ingest.promotion import promote_raw_object

    return Deps(
        fetch_since=fetch_since,
        read_watermark=read_watermark,
        write_watermark=write_watermark,
        intake_file=intake_file,
        promote_raw_object=promote_raw_object,
        get_password=lambda env: os.environ[env],
    )


def fetch_mailbox(
    source_name: str,
    since_days: int = 7,
    promote: bool = True,
    deps: Deps | None = None,
) -> FetchResult:
    from core.lineage.source_resolver import load_registry

    from ingest.pec_imap import ImapConfig

    d = deps or _default_deps()
    sd = load_registry().get(source_name)
    if sd is None:
        raise ValueError(f"source {source_name!r} non nel registry")
    if sd.imap is None:
        raise ValueError(f"source {source_name!r} senza blocco imap")

    entity = sd.entity_id
    bucket = sd.raw_storage.bucket
    res = FetchResult(entity_id=entity)

    cfg = ImapConfig(
        host=sd.imap.host,
        port=sd.imap.port,
        user=sd.casella,  # l'utente IMAP è la casella del registry
        password=d.get_password(sd.imap.password_env),
    )

    watermark = d.read_watermark(bucket, entity)
    since_date = (
        (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
        if since_days
        else None
    )

    try:
        messages = d.fetch_since(cfg, watermark, since_date=since_date)
    except Exception as exc:  # noqa: BLE001 — una casella giù non ferma le altre
        log.error("%s: fetch fallita: %s", entity, exc)
        res.status, res.error = "FAILED", str(exc)
        return res

    res.fetched = len(messages)
    highest = watermark

    with tempfile.TemporaryDirectory() as tmp:
        for uid, raw in messages:
            path = Path(tmp) / f"{entity}_{uid}.eml"
            path.write_bytes(raw)
            out = d.intake_file(path, source_name=source_name, actor="pec_fetch")
            if out.deduped:
                res.deduped += 1
            else:
                res.ingested += 1
                if promote and out.raw_object_id:
                    d.promote_raw_object(out.raw_object_id, actor="pec_fetch")
            highest = max(highest, uid)

    if highest > watermark:
        d.write_watermark(bucket, entity, highest)
    res.last_uid = highest
    return res


def main() -> None:
    p = argparse.ArgumentParser(
        prog="ingest.pec_fetch",
        description="Fetch IMAP read-only delle caselle PEC, poi intake + promote.",
    )
    p.add_argument("--source-name", default=None)
    p.add_argument("--all", action="store_true", help="Tutte le caselle PEC con blocco imap")
    p.add_argument("--since-days", type=int, default=7,
                   help="Finestra di sicurezza oltre al watermark (0 = solo watermark)")
    p.add_argument("--no-promote", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    from core.lineage.source_resolver import load_registry

    if args.all:
        names = sorted(
            sd.source_name
            for sd in load_registry().find_all_by_detector_category("pec_mbox")
            if sd.imap is not None
        )
    elif args.source_name:
        names = [args.source_name]
    else:
        raise SystemExit("ERROR: serve --source-name oppure --all")

    failed = []
    for name in names:
        r = fetch_mailbox(name, since_days=args.since_days, promote=not args.no_promote)
        print(
            f"{r.entity_id}: status={r.status} fetched={r.fetched} "
            f"ingested={r.ingested} deduped={r.deduped} last_uid={r.last_uid}"
            + (f" error={r.error}" if r.error else "")
        )
        if r.status == "FAILED":
            failed.append(r.entity_id)

    if failed:
        print(f"PARZIALE: caselle non raggiunte: {', '.join(failed)}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
