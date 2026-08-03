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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    entity_id: str
    fetched: int = 0
    ingested: int = 0
    deduped: int = 0
    promoted: int = 0
    rejected: int = 0
    status: str = "OK"
    error: Optional[str] = None
    per_folder: dict[str, int] = field(default_factory=dict)


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

    since_date = (
        (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
        if since_days
        else None
    )

    errors: list[str] = []
    for folder in sd.imap.folders:
        res.per_folder.setdefault(folder, 0)
        try:
            wm = d.read_watermark(bucket, entity, folder=folder)
            highest: int | None = None
            blocks = d.fetch_since(
                cfg,
                wm.last_uid,
                folder=folder,
                since_date=since_date,
                uidvalidity=wm.uidvalidity,
            )
            # Un blocco alla volta: si scarica, si ingerisce e si salva il
            # watermark. Un guasto a metà cartella non butta via il lavoro
            # già fatto — gli UID sono crescenti, quindi il progresso è
            # monotono e la cartella si completa in più notti.
            for blk in blocks:
                if highest is None:
                    highest = blk.base_uid
                res.per_folder[folder] += len(blk.messages)
                res.fetched += len(blk.messages)
                _ingest_block(blk, res, entity, source_name, promote, d)
                highest = max([highest, *(uid for uid, _ in blk.messages)])
                d.write_watermark(
                    bucket, entity, highest, folder=folder, uidvalidity=blk.uidvalidity
                )
        except Exception as exc:  # noqa: BLE001 — una cartella giù non ferma le altre
            log.error("%s/%s: fetch fallita: %s", entity, folder, exc)
            errors.append(f"{folder}: {exc}")
            # il watermark resta all'ultimo blocco andato a buon fine: il
            # content-hash protegge dai duplicati al giro dopo

    if errors:
        res.status, res.error = "FAILED", "; ".join(errors)
    if res.rejected:
        res.status = "FAILED"
        rej = f"{res.rejected} buste rifiutate dal promote"
        res.error = f"{res.error}; {rej}" if res.error else rej
    return res


def _ingest_block(
    blk, res: FetchResult, entity: str, source_name: str, promote: bool, d: Deps
) -> None:
    """Intake (+promote) di un blocco. L'.eml sparisce appena caricato: su
    Cloud Run la temp dir è tmpfs, cioè RAM."""
    with tempfile.TemporaryDirectory() as tmp:
        for uid, raw in blk.messages:
            path = Path(tmp) / f"{entity}_{uid}.eml"
            path.write_bytes(raw)
            try:
                out = d.intake_file(path, source_name=source_name, actor="pec_fetch")
            finally:
                path.unlink(missing_ok=True)
            if out.deduped:
                res.deduped += 1
                continue
            res.ingested += 1
            if not promote:
                continue
            if not out.raw_object_id:
                # Senza raw_object_id il promote non parte e la busta resta
                # solo su GCS: silenzio inaccettabile, si alza.
                raise RuntimeError(
                    f"UID {uid}: intake senza raw_object_id "
                    "(lineage gate disabilitato?) — promote impossibile"
                )
            pr = d.promote_raw_object(out.raw_object_id, actor="pec_fetch")
            # promote_raw_object NON solleva: torna REJECTED con la ragione.
            # Se non la si guarda, una busta mai atterrata in f_pec_messages
            # passa per ingerita.
            if pr.status == "PROMOTED":
                res.promoted += 1
            else:
                res.rejected += 1
                log.error(
                    "%s UID %d: promote %s (%s), raw_object_id=%s",
                    entity, uid, pr.status, pr.reason, out.raw_object_id,
                )


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
        if not names:
            # Senza guardia il job notturno diventerebbe un no-op verde alla
            # prima modifica sbagliata del registry.
            raise SystemExit(
                "ERROR: --all non ha trovato nessuna casella PEC con blocco imap nel registry"
            )
    elif args.source_name:
        names = [args.source_name]
    else:
        raise SystemExit("ERROR: serve --source-name oppure --all")

    failed = []
    for name in names:
        try:
            r = fetch_mailbox(name, since_days=args.since_days, promote=not args.no_promote)
        except Exception as exc:  # noqa: BLE001 — una casella guasta non blocca le altre
            log.error("%s: errore inatteso: %s", name, exc)
            r = FetchResult(entity_id=name, status="FAILED", error=str(exc))
        # per_folder è la compensazione a status, che collassa a FAILED anche
        # se è caduta una cartella su due: dice quale ha lavorato e quanto.
        folders = " ".join(f"{f}={n}" for f, n in r.per_folder.items()) or "-"
        print(
            f"{r.entity_id}: status={r.status} fetched={r.fetched} "
            f"ingested={r.ingested} deduped={r.deduped} "
            f"promoted={r.promoted} rejected={r.rejected} folders[{folders}]"
            + (f" error={r.error}" if r.error else "")
        )
        if r.status == "FAILED":
            failed.append(r.entity_id)

    if failed:
        print(f"PARZIALE: caselle non raggiunte: {', '.join(failed)}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
