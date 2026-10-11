"""Drive auto-sync: fetch a live Google Drive file, then intake + promote.

Usage:
    python -m ingest.drive_fetch --source-name RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT
    python -m ingest.drive_fetch --source-name RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT --no-promote
    python -m ingest.drive_fetch --source-name RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT --key /path/sa-key.json

Auth: service account key at HOTELOPS_DRIVE_SA_KEY (env) or ~/.config/hotelops/drive-audit-key.json.
Requires: google-api-python-client (pip install -e ".[drive]").
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import tempfile
from pathlib import Path

from core.local_paths import resolve_drive_sa_key_path

log = logging.getLogger(__name__)

DEFAULT_KEY = str(resolve_drive_sa_key_path())
_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


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


def fetch_drive_file(file_id: str, dest_dir: Path, key_path: str = DEFAULT_KEY) -> Path:
    """Download a Drive file (by id) to dest_dir/<original name>. Returns the path."""
    from googleapiclient.http import MediaIoBaseDownload

    svc = _drive_service(key_path)
    meta = svc.files().get(fileId=file_id, fields="name", supportsAllDrives=True).execute()
    dest = Path(dest_dir) / meta["name"]
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest.write_bytes(buf.getvalue())
    log.info("Fetched Drive file %r → %s (%d bytes)", meta["name"], dest, dest.stat().st_size)
    return dest


def main() -> None:
    p = argparse.ArgumentParser(
        prog="ingest.drive_fetch",
        description="Fetch a live Drive file, then run lineage intake + promote.",
    )
    p.add_argument("--source-name", required=True, help="Registry source name")
    p.add_argument("--file-id", default=None,
                   help="Override Drive file ID (bypasses registry drive_file_id)")
    p.add_argument("--no-promote", action="store_true", help="Skip promote after intake")
    p.add_argument("--key", default=DEFAULT_KEY, help="Path to SA key JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    source_def = reg.get(args.source_name)
    if source_def is None:
        raise SystemExit(f"ERROR: source_name not in registry: {args.source_name!r}")

    file_id = args.file_id or source_def.drive_file_id
    if not file_id:
        raise SystemExit(
            f"ERROR: source {args.source_name!r} has no drive_file_id in registry and --file-id not provided"
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        log.info("Fetching Drive file_id=%s for source %s", file_id, args.source_name)
        local_file = fetch_drive_file(file_id, dest_dir=tmp_path, key_path=args.key)

        from ingest.intake import intake_file

        result = intake_file(local_file, source_name=args.source_name, actor="drive_sync")
        print(f"raw_object_id={result.raw_object_id}")
        print(f"content_hash={result.content_hash}")
        print(f"deduped={result.deduped}")

        if not args.no_promote:
            from ingest.promotion import promote_raw_object

            if not result.raw_object_id:
                print(
                    "ERROR: intake returned no raw_object_id (lineage gate disabled?) — promote skipped",
                    file=sys.stderr,
                )
                sys.exit(1)
            pr = promote_raw_object(result.raw_object_id, actor="drive_sync")
            print(f"promote_status={pr.status} reason={pr.reason or '-'} noop={pr.noop}")


if __name__ == "__main__":
    main()
