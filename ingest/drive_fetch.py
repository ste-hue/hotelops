"""Drive auto-sync: fetch live Google Drive files, then intake + promote.

Usage:
    python -m ingest.drive_fetch --source-name RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT
    python -m ingest.drive_fetch --source-name <SOURCE> --no-promote
    python -m ingest.drive_fetch --all            # tutte le sorgenti Drive del registry
    python -m ingest.drive_fetch --all --dry-run  # elenca cosa entrerebbe, nessuna scrittura

Un solo scrittore (spec 2026-10-17 drive-agent-friendly): i file delle sorgenti
con drive_file_id/drive_folder_id entrano in f_raw_objects solo da qui, con
actor "drive_sync". L'MD5 arriva dal metadato `md5Checksum` dell'API: il
download avviene solo per gli hash assenti da f_raw_objects.

Auth: service account key at HOTELOPS_DRIVE_SA_KEY (env) or
~/.config/hotelops/drive-audit-key.json; keyless con l'identità del runtime.
Requires: google-api-python-client (pip install -e ".[drive]").
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import tempfile
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from core.local_paths import resolve_drive_sa_key_path

log = logging.getLogger(__name__)

DEFAULT_KEY = str(resolve_drive_sa_key_path())
_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_SYNC_ACTOR = "drive_sync"
FOLDER_MIME = "application/vnd.google-apps.folder"
_FILE_FIELDS = "id, name, mimeType, md5Checksum, modifiedTime"


def _drive_service(key_path: str = DEFAULT_KEY):
    from googleapiclient.discovery import build

    if os.path.exists(key_path):
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            key_path, scopes=_SCOPES
        )
    else:
        # Keyless: usa l'identità del runtime (es. Cloud Run Job che gira come
        # drive-audit@). Nessun file-chiave necessario.
        import google.auth

        creds, _ = google.auth.default(scopes=_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _download(svc, file_id: str, dest: Path, export_mime: str | None = None) -> Path:
    from googleapiclient.http import MediaIoBaseDownload

    req = (
        svc.files().export_media(fileId=file_id, mimeType=export_mime)
        if export_mime
        else svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    )
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest.write_bytes(buf.getvalue())
    return dest


def _local_destination(dest_dir: Path, name: str) -> Path:
    """Drive names are metadata, never a local relative or absolute path."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Drive filename is not a single safe path component")
    return Path(dest_dir) / name


def fetch_drive_file(file_id: str, dest_dir: Path, key_path: str = DEFAULT_KEY) -> Path:
    """Download a Drive file (by id) to dest_dir/<original name>. Returns the path."""
    svc = _drive_service(key_path)
    meta = (
        svc.files().get(fileId=file_id, fields="name", supportsAllDrives=True).execute()
    )
    dest = _download(svc, file_id, _local_destination(dest_dir, meta["name"]))
    log.info(
        "Fetched Drive file %r → %s (%d bytes)", meta["name"], dest, dest.stat().st_size
    )
    return dest


# ── Elenco candidati (puro rispetto a BigQuery: solo API Drive) ──────────────


@dataclass
class DriveCandidate:
    file_id: str
    name: str
    mime_type: str
    md5: str | None  # None per i file nativi Google
    export_mime: str | None = None


def list_candidates(svc, source_def) -> list[DriveCandidate]:
    """I file che la sorgente osserva: uno (drive_file_id) o il contenuto piatto
    della cartella di atterraggio (drive_folder_id), sottocartelle escluse."""
    out: list[DriveCandidate] = []
    if source_def.drive_file_id:
        m = (
            svc.files()
            .get(
                fileId=source_def.drive_file_id,
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            )
            .execute()
        )
        metas = [m]
    else:
        metas = []
        token = None
        while True:
            resp = (
                svc.files()
                .list(
                    q=f"'{source_def.drive_folder_id}' in parents and trashed = false",
                    fields=f"nextPageToken, files({_FILE_FIELDS})",
                    pageSize=200,
                    pageToken=token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            metas.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                break
    for m in metas:
        if m.get("mimeType") == FOLDER_MIME:
            continue
        native = m.get("md5Checksum") is None
        out.append(
            DriveCandidate(
                file_id=m["id"],
                name=m["name"],
                mime_type=m.get("mimeType", ""),
                md5=m.get("md5Checksum"),
                export_mime=source_def.drive_export_mime if native else None,
            )
        )
    return out


# ── Sync di una sorgente ─────────────────────────────────────────────────────


@dataclass
class SyncReport:
    source_name: str
    seen: int = 0
    skipped_known: int = 0
    skipped_native: int = 0
    ingested: list[str] = field(default_factory=list)  # raw_object_id
    promoted: int = 0
    errors: list[str] = field(default_factory=list)


def sync_source(
    source_def,
    svc,
    *,
    hash_exists: Callable[[str], bool],
    intake: Callable[[Path, str], object],
    promote: Callable[[str], object] | None,
    tmp_dir: Path,
    dry_run: bool = False,
) -> SyncReport:
    """Un giro su una sorgente: elenca, salta gli hash noti, scarica e fa intake
    dei nuovi, promuove se richiesto. Le dipendenze da BigQuery sono iniettate
    così il giro si prova senza rete."""
    rep = SyncReport(source_name=source_def.source_name)
    for c in list_candidates(svc, source_def):
        rep.seen += 1
        if c.md5 is None and c.export_mime is None:
            rep.skipped_native += 1
            log.info(
                "%s: %r nativo Google senza drive_export_mime, solo inventario",
                rep.source_name,
                c.name,
            )
            continue
        if c.md5 is not None and hash_exists(c.md5):
            rep.skipped_known += 1
            continue
        if dry_run:
            log.info(
                "%s: [DRY-RUN] entrerebbe %r (md5 %s)",
                rep.source_name,
                c.name,
                (c.md5 or "export")[:12],
            )
            rep.ingested.append(f"dry-run:{c.file_id}")
            continue
        try:
            local = _download(
                svc,
                c.file_id,
                _local_destination(tmp_dir, c.name),
                export_mime=c.export_mime,
            )
            result = intake(local, source_def.source_name)
            rid = getattr(result, "raw_object_id", None)
            if not rid:
                rep.errors.append(
                    f"{c.name}: intake senza raw_object_id (lineage gate disabilitato?)"
                )
                continue
            if getattr(result, "deduped", False):
                rep.skipped_known += 1
                continue
            rep.ingested.append(rid)
            if promote is not None:
                pr = promote(rid)
                if getattr(pr, "status", None) != "PROMOTED":
                    rep.errors.append(
                        f"{c.name}: promotion not completed "
                        f"({getattr(pr, 'status', 'UNKNOWN')}; "
                        f"{getattr(pr, 'reason', None) or 'no reason'})"
                    )
                    continue
                rep.promoted += 1
                log.info(
                    "%s: %r → %s promote=%s",
                    rep.source_name,
                    c.name,
                    rid,
                    getattr(pr, "status", "?"),
                )
        except Exception as e:  # un file rotto non ferma la cartella
            log.exception("%s: errore su %r", rep.source_name, c.name)
            rep.errors.append(f"{c.name}: {e}")
    return rep


def _bq_hash_exists(md5: str) -> bool:
    from core.lineage.raw_manifest import _lookup_existing_by_hash

    return _lookup_existing_by_hash(md5) is not None


def _intake(path: Path, source_name: str):
    from ingest.intake import intake_file

    return intake_file(path, source_name=source_name, actor=DRIVE_SYNC_ACTOR)


def _promote(raw_object_id: str):
    from ingest.promotion import promote_raw_object

    return promote_raw_object(raw_object_id, actor=DRIVE_SYNC_ACTOR)


def run_sources(
    source_defs,
    *,
    key_path: str,
    do_promote: bool,
    dry_run: bool,
    auto_only: bool = False,
) -> list[SyncReport]:
    from core.pipeline_run import PipelineRun

    svc = _drive_service(key_path)
    reports: list[SyncReport] = []
    for sd in source_defs:
        # A dry run must not manufacture a successful execution receipt.
        context = (
            nullcontext(None)
            if dry_run
            else PipelineRun(f"drive_fetch:{sd.source_name}", societa_id=sd.societa)
        )
        with (
            context as run,
            tempfile.TemporaryDirectory() as tmp,
        ):
            rep = sync_source(
                sd,
                svc,
                hash_exists=_bq_hash_exists,
                intake=_intake,
                promote=(
                    _promote
                    if do_promote and (not auto_only or sd.promotion_policy == "AUTO")
                    else None
                ),
                tmp_dir=Path(tmp),
                dry_run=dry_run,
            )
            if run is not None:
                run.rows_found = rep.seen
                run.rows_new = len(rep.ingested)
                if rep.errors:
                    run.status = "FAIL"
                    run.error_message = "; ".join(rep.errors)[:500]
            reports.append(rep)
            print(
                f"{rep.source_name}: visti={rep.seen} noti={rep.skipped_known} "
                f"nativi={rep.skipped_native} nuovi={len(rep.ingested)} "
                f"promossi={rep.promoted} errori={len(rep.errors)}"
            )
            for e in rep.errors:
                print(f"  ERRORE {e}", file=sys.stderr)
    return reports


def main() -> None:
    p = argparse.ArgumentParser(
        prog="ingest.drive_fetch",
        description="Fetch live Drive files, then run lineage intake + promote.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--source-name", help="Registry source name")
    g.add_argument(
        "--all",
        action="store_true",
        help="Tutte le sorgenti con drive_file_id/drive_folder_id",
    )
    p.add_argument(
        "--file-id",
        default=None,
        help="Override Drive file ID (solo con --source-name)",
    )
    p.add_argument(
        "--no-promote", action="store_true", help="Skip promote after intake"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Elenca i file nuovi, nessuna scrittura"
    )
    p.add_argument("--key", default=DEFAULT_KEY, help="Path to SA key JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    if args.all:
        if args.file_id:
            raise SystemExit("ERROR: --file-id non ha senso con --all")
        sources = [sd for sd in reg.sources.values() if sd.is_drive_source]
    else:
        sd = reg.get(args.source_name)
        if sd is None:
            raise SystemExit(
                f"ERROR: source_name not in registry: {args.source_name!r}"
            )
        if args.file_id:
            sd = sd.model_copy(
                update={"drive_file_id": args.file_id, "drive_folder_id": None}
            )
        if not sd.is_drive_source:
            raise SystemExit(
                f"ERROR: source {args.source_name!r} has no drive_file_id/drive_folder_id "
                "in registry and --file-id not provided"
            )
        sources = [sd]

    reports = run_sources(
        sources,
        key_path=args.key,
        do_promote=not args.no_promote,
        dry_run=args.dry_run,
        auto_only=args.all,
    )
    if any(r.errors for r in reports):
        sys.exit(1)


if __name__ == "__main__":
    main()
