#!/usr/bin/env python3
"""
Sync bank files from Google Drive to local staging using rclone.

Syncs homebanking/{ORTI,INTUR}/ from the datahub ingresso/ subtree
(see core.datahub_sync for the remote root).

Usage:
    python -m ingest.banca.fetch_drive --staging ~/.cache/hotelops/banche_staging
    python -m ingest.banca.fetch_drive --staging ~/.cache/hotelops/banche_staging --dry-run
"""

import argparse
import sys
from pathlib import Path

from core.datahub_sync import RcloneError, rclone_sync


def main():
    parser = argparse.ArgumentParser(description="Sync banche/ from Drive via rclone")
    parser.add_argument("--staging", required=True, help="Local staging directory")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    staging = Path(args.staging)

    print(f"Syncing ingresso/homebanking → {staging}")
    try:
        rclone_sync(
            "ingresso/homebanking",
            staging,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    except RcloneError as e:
        print(f"rclone sync failed: {e}")
        sys.exit(1)

    print("Sync complete")


if __name__ == "__main__":
    main()
