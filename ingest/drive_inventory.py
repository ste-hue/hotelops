"""Inventario Drive: una fotografia al giorno dell'albero in f_drive_inventory.

Usage:
    python -m ingest.drive_inventory              # tutte le radici di core/drive_map.yaml
    python -m ingest.drive_inventory --root investimenti
    python -m ingest.drive_inventory --dry-run    # conta e stampa, nessuna scrittura

Spec 2026-10-17 drive-agent-friendly (P4, P7). Il job non scarica nulla: legge
metadati, hash (md5Checksum/sha256Checksum) e permessi dall'API Drive v3, poi
unisce per MD5 a f_raw_objects.content_hash per sapere cosa è già tracciato.
Scrittura SNAPSHOT via bq_write_validated con natural_key (snapshot_date, file_id):
il giro di oggi sostituisce il giro di oggi, mai quelli passati.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Iterable
from datetime import datetime

from core.drive_map import DriveMap, DriveRoot, load_drive_map
from core.schemas import DriveInventoryRow

log = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
_FIELDS = (
    "nextPageToken, files(id, name, mimeType, size, md5Checksum, sha256Checksum, "
    "modifiedTime, createdTime, owners(emailAddress), parents, "
    "shortcutDetails(targetId), permissions(type, emailAddress, domain))"
)


def _parse_ts(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v)


def _perms(meta: dict, domain: str) -> tuple[bool, list[str]]:
    anyone = False
    outside: list[str] = []
    for p in meta.get("permissions") or []:
        t = p.get("type")
        if t == "anyone":
            anyone = True
        elif t == "user" or t == "group":
            email = (p.get("emailAddress") or "").lower()
            if email and domain and not email.endswith("@" + domain):
                outside.append(email)
        elif t == "domain" and domain and p.get("domain") != domain:
            outside.append(f"domain:{p.get('domain')}")
    return anyone, sorted(set(outside))


def build_row(
    meta: dict, *, snapshot_date, path: str, root_key: str, domain: str
) -> DriveInventoryRow:
    anyone, outside = _perms(meta, domain)
    owners = meta.get("owners") or []
    parents = meta.get("parents") or []
    size = meta.get("size")
    return DriveInventoryRow(
        snapshot_date=snapshot_date,
        file_id=meta["id"],
        name=meta["name"],
        mime_type=meta.get("mimeType", ""),
        size_bytes=int(size) if size is not None else None,
        md5=meta.get("md5Checksum"),
        sha256=meta.get("sha256Checksum"),
        modified_time=_parse_ts(meta.get("modifiedTime")),
        created_time=_parse_ts(meta.get("createdTime")),
        owner_email=(owners[0].get("emailAddress") if owners else None),
        parent_id=parents[0] if parents else None,
        path=path,
        root_key=root_key,
        is_folder=meta.get("mimeType") == FOLDER_MIME,
        is_shortcut=meta.get("mimeType") == SHORTCUT_MIME,
        shortcut_target_id=(meta.get("shortcutDetails") or {}).get("targetId"),
        perm_anyone=anyone,
        perm_outside_domain=outside,
    )


def list_children(svc, folder_id: str) -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        resp = (
            svc.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=_FIELDS,
                pageSize=200,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        out.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return out


def walk_root(
    svc,
    root: DriveRoot,
    *,
    snapshot_date,
    domain: str,
    list_fn: Callable[[object, str], list[dict]] = list_children,
) -> list[DriveInventoryRow]:
    """Percorre la radice in profondità. Le scorciatoie non si seguono (sono
    righe, con il target), così un albero con un collegamento circolare finisce."""
    rows: list[DriveInventoryRow] = []
    stack: list[tuple[str, str]] = [(root.id, root.label)]
    seen: set[str] = set()
    while stack:
        folder_id, prefix = stack.pop()
        if folder_id in seen:
            continue
        seen.add(folder_id)
        for meta in list_fn(svc, folder_id):
            path = f"{prefix}/{meta['name']}"
            rows.append(
                build_row(
                    meta,
                    snapshot_date=snapshot_date,
                    path=path,
                    root_key=root.key,
                    domain=domain,
                )
            )
            if meta.get("mimeType") == FOLDER_MIME:
                stack.append((meta["id"], path))
    return rows


def attach_raw_object_ids(
    rows: Iterable[DriveInventoryRow], lookup: Callable[[list[str]], dict[str, str]]
) -> None:
    rows = list(rows)
    hashes = sorted({r.md5 for r in rows if r.md5})
    found = lookup(hashes) if hashes else {}
    for r in rows:
        if r.md5 and r.md5 in found:
            r.raw_object_id = found[r.md5]


def _bq_lookup(hashes: list[str]) -> dict[str, str]:
    from google.cloud import bigquery

    from core.bq.client import get_client
    from core.config import F_RAW_OBJECTS

    sql = f"""
    SELECT content_hash, ANY_VALUE(raw_object_id) AS raw_object_id
    FROM `{F_RAW_OBJECTS}` WHERE content_hash IN UNNEST(@h) GROUP BY content_hash
    """
    job = get_client().query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("h", "STRING", hashes)]
        ),
    )
    return {r.content_hash: r.raw_object_id for r in job.result()}


def run(
    svc,
    dmap: DriveMap,
    *,
    roots: list[str] | None = None,
    snapshot_date=None,
    dry_run: bool = False,
    lookup: Callable[[list[str]], dict[str, str]] = _bq_lookup,
) -> list[DriveInventoryRow]:
    from core.freshness import today_rome

    snapshot_date = snapshot_date or today_rome()
    chosen = [dmap.roots[k] for k in (roots or list(dmap.roots))]
    rows: list[DriveInventoryRow] = []
    for root in chosen:
        got = walk_root(svc, root, snapshot_date=snapshot_date, domain=dmap.domain)
        log.info("radice %s: %d oggetti", root.key, len(got))
        rows.extend(got)
    attach_raw_object_ids(rows, lookup)
    n_pub = sum(r.perm_anyone for r in rows)
    n_tracked = sum(r.raw_object_id is not None for r in rows)
    print(
        f"inventario {snapshot_date}: {len(rows)} oggetti, {n_pub} pubblici, "
        f"{n_tracked} tracciati in lineage, radici={','.join(r.key for r in chosen)}"
    )
    if dry_run or not rows:
        return rows
    from core.bq.write import bq_write_validated
    from core.config import F_DRIVE_INVENTORY

    bq_write_validated(
        F_DRIVE_INVENTORY,
        rows,
        mode="snapshot",
        natural_key=["snapshot_date", "file_id"],
    )
    return rows


def main() -> None:
    p = argparse.ArgumentParser(
        prog="ingest.drive_inventory", description=__doc__.splitlines()[0]
    )
    p.add_argument(
        "--root", action="append", help="Chiave di core/drive_map.yaml (ripetibile)"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--key",
        default=None,
        help="Path to SA key JSON (default: HOTELOPS_DRIVE_SA_KEY o keyless)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    from core.pipeline_run import PipelineRun
    from ingest.drive_fetch import DEFAULT_KEY, _drive_service

    dmap = load_drive_map()
    unknown = [k for k in (args.root or []) if k not in dmap.roots]
    if unknown:
        raise SystemExit(
            f"ERROR: radici sconosciute {unknown}; note: {sorted(dmap.roots)}"
        )
    svc = _drive_service(args.key or DEFAULT_KEY)
    with PipelineRun("drive_inventory", societa_id="GROUP") as prun:
        rows = run(svc, dmap, roots=args.root, dry_run=args.dry_run)
        prun.rows_new = 0 if args.dry_run else len(rows)
    if not rows:
        print(
            "nessun oggetto: le radici sono condivise con l'identità che esegue il job?",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
