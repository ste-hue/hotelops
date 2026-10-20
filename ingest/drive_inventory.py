"""Inventario Drive: una fotografia al giorno dell'albero in f_drive_inventory.

Usage:
    python -m ingest.drive_inventory              # tutte le radici di core/drive_map.yaml
    python -m ingest.drive_inventory --root investimenti --dry-run
    python -m ingest.drive_inventory --dry-run    # conta e stampa, nessuna scrittura

Spec 2026-10-17 drive-agent-friendly. Only metadata is read from Drive;
exact API responses are retained by the existing GCS intake. Publication is a
complete DATE-partition snapshot, including each configured root itself.
Partial --root scans are inspection-only (--dry-run). File content raw IDs
and metadata-observation raw IDs are distinct provenance links.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from core.drive_map import DriveMap, DriveRoot, load_drive_map
from core.schemas import DriveInventoryRow

log = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
_META_FIELDS = (
    "id, name, mimeType, size, md5Checksum, sha256Checksum, "
    "modifiedTime, createdTime, owners(emailAddress), parents, "
    "shortcutDetails(targetId), permissions(type, emailAddress, domain)"
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


def _permissions_observed(meta: dict, domain: str) -> bool:
    permissions = meta.get("permissions")
    if not isinstance(permissions, list):
        return False
    # A returned permission whose identity is hidden cannot establish absence
    # of external access. This is visibility, never an authorization decision.
    for permission in permissions:
        kind = permission.get("type")
        if kind in {"user", "group"}:
            if not permission.get("emailAddress") or not domain:
                return False
        elif kind == "domain":
            if not permission.get("domain") or not domain:
                return False
        elif kind != "anyone":
            return False
    return True


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
        permissions_observed=_permissions_observed(meta, domain),
        perm_anyone=anyone,
        perm_outside_domain=outside,
    )


def list_children(
    svc, folder_id: str, *, observations: list | None = None
) -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        resp = (
            svc.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=f"nextPageToken, incompleteSearch, files({_META_FIELDS})",
                pageSize=200,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        if observations is not None:
            observations.append(
                {
                    "method": "files.list",
                    "folder_id": folder_id,
                    "page_token": token,
                    "response": resp,
                }
            )
        if resp.get("incompleteSearch"):
            raise ValueError(f"incomplete Drive search for {folder_id}")
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
    from core.lineage.raw_manifest import F_RAW_OBJECTS

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


INVENTORY_SOURCE = "DRIVE_INVENTORY_GROUP_SNAPSHOT"


def capture_observation(payload: dict) -> str:
    """Retain exact API observations through the existing intake/GCS boundary.

    The document is an observation of the principal-visible tree, not the
    contents of the listed business files. Its FK is separate from their hash bridge.
    """
    from core.lineage.source_resolver import load_registry
    from ingest.intake import intake_file
    from ingest.promotion import _fetch_raw_object

    source = load_registry().get(INVENTORY_SOURCE)
    if (
        source is None
        or source.raw_storage is None
        or source.raw_storage.backend != "gcs"
    ):
        raise ValueError("inventory observations require registered GCS raw storage")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "drive-inventory.json"
        path.write_text(
            json.dumps(payload, sort_keys=True, ensure_ascii=False), encoding="utf-8"
        )
        result = intake_file(
            path, source_name=INVENTORY_SOURCE, actor="drive_inventory"
        )
    rid = getattr(result, "raw_object_id", None)
    if not rid:
        raise ValueError("inventory intake returned no raw object")
    raw = _fetch_raw_object(rid)
    prefix = f"gs://{source.raw_storage.bucket or 'hotelops-raw'}/{INVENTORY_SOURCE}/"
    if (
        raw.source_name != INVENTORY_SOURCE
        or raw.raw_backend != "gcs"
        or not raw.raw_uri.startswith(prefix)
        or raw.gcs_generation is None
    ):
        raise ValueError("inventory raw object is not in its canonical GCS path")
    return rid


def run(
    svc,
    dmap: DriveMap,
    *,
    roots: list[str] | None = None,
    snapshot_date=None,
    dry_run: bool = False,
    lookup: Callable[[list[str]], dict[str, str]] = _bq_lookup,
    capture: Callable[[dict], str] | None = None,
) -> list[DriveInventoryRow]:
    from core.freshness import today_rome

    snapshot_date = snapshot_date or today_rome()
    selected = sorted(set(roots if roots is not None else dmap.roots))
    if not selected or any(k not in dmap.roots for k in selected):
        raise ValueError("select at least one configured root")
    if not dry_run and set(selected) != set(dmap.roots):
        raise ValueError(
            "partial --root scans are dry-run only; publish all configured roots"
        )
    observed_at = datetime.now(UTC)
    observations = []
    observer = None
    try:
        about = svc.about().get(fields="user(emailAddress,permissionId)").execute()
        observations.append({"method": "about.get", "response": about})
        observer = about.get("user", {}).get("emailAddress")
        if not observer:
            raise ValueError("Drive principal was not observed")
    except Exception:
        if not dry_run:
            raise
        log.warning("dry-run: Drive principal unavailable; no publishable coverage")

    by_id: dict[str, DriveInventoryRow] = {}
    inbox_ids = set()
    for key in selected:
        root = dmap.roots[key]
        root_row = None
        effective_id = root.id
        try:
            meta = (
                svc.files()
                .get(fileId=root.id, fields=_META_FIELDS, supportsAllDrives=True)
                .execute()
            )
            observations.append(
                {
                    "method": "files.get",
                    "requested_root": root.id,
                    "root_key": key,
                    "response": meta,
                }
            )
            if meta.get("mimeType") != FOLDER_MIME:
                raise ValueError(f"configured root {key} is not an observed folder")
            effective_id = meta["id"]
            root_row = build_row(
                meta,
                snapshot_date=snapshot_date,
                path=root.label,
                root_key=key,
                domain=dmap.domain,
            )
            root_row.inventory_root_keys = [key]
        except Exception:
            if not dry_run:
                raise
            log.warning("dry-run: root %s metadata unavailable; coverage unknown", key)
        if root.inbox_only:
            inbox_ids.add(effective_id)
        got = walk_root(
            svc,
            DriveRoot(key, effective_id, root.label, root.inbox_only),
            snapshot_date=snapshot_date,
            domain=dmap.domain,
            list_fn=lambda service, fid: list_children(
                service, fid, observations=observations
            ),
        )
        if root_row is not None:
            got.append(
                root_row
            )  # A root is an observed object even with zero children.
        for row in got:
            previous = by_id.get(row.file_id)
            if previous is None:
                row.root_keys = [key]
                by_id[row.file_id] = row
            else:
                previous.root_keys = sorted(set(previous.root_keys) | {key})
                previous.inventory_root_keys = sorted(
                    set(previous.inventory_root_keys) | set(row.inventory_root_keys)
                )
                # files.get observes the root itself, including its permissions.
                if row.inventory_root_keys:
                    previous.permissions_observed = row.permissions_observed
                    previous.perm_anyone = row.perm_anyone
                    previous.perm_outside_domain = row.perm_outside_domain
        log.info("root %s: %d observed entries", key, len(got))
    rows = list(by_id.values())
    for row in rows:
        row.configured_roots = selected
        row.observer_email = observer
        row.observed_at = observed_at
        row.in_inbox_root = row.parent_id in inbox_ids
    attach_raw_object_ids(rows, lookup)
    print(
        f"inventario {snapshot_date}: {len(rows)} oggetti, radici={','.join(selected)}"
    )
    if dry_run:
        return rows
    covered = {key for row in rows for key in row.inventory_root_keys}
    if covered != set(selected):
        raise ValueError("incomplete root coverage; inventory not published")
    payload = {
        "schema_version": 1,
        "snapshot_date": str(snapshot_date),
        "observed_at": observed_at.isoformat(),
        "observer_email": observer,
        "roots": [
            {
                "key": key,
                "requested_id": dmap.roots[key].id,
                "label": dmap.roots[key].label,
                "inbox_only": dmap.roots[key].inbox_only,
            }
            for key in selected
        ],
        "domain": dmap.domain,
        "observations": observations,
    }
    rid = (capture or capture_observation)(payload)
    if not rid:
        raise ValueError("metadata raw provenance missing; inventory not published")
    for row in rows:
        row.observation_raw_object_id = rid
    from core.bq.write import bq_write_validated
    from core.config import F_DRIVE_INVENTORY

    bq_write_validated(
        F_DRIVE_INVENTORY,
        rows,
        mode="snapshot",
        natural_key=["snapshot_date"],
        snapshot_partition=snapshot_date,
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
    context = (
        nullcontext(None)
        if args.dry_run
        else PipelineRun("drive_inventory", societa_id="GROUP")
    )
    with context as prun:
        rows = run(svc, dmap, roots=args.root, dry_run=args.dry_run)
        if prun is not None:
            prun.rows_new = len(rows)
    if not rows:
        print(
            "nessun oggetto: le radici sono condivise con l'identità che esegue il job?",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
