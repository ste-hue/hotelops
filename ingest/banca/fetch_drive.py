#!/usr/bin/env python3
"""
Sync bank files from Google Drive to local staging using rclone.

Syncs homebanking/{ORTI,INTUR}/ from 00_hotelops_datahub/ingresso/.

Usage:
    python -m ingest.banca.fetch_drive --staging ~/.cache/hotelops/banche_staging
    python -m ingest.banca.fetch_drive --staging ~/.cache/hotelops/banche_staging --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

REMOTE = "mywork:00_hotelops_datahub/ingresso/homebanking"


def main():
    parser = argparse.ArgumentParser(description="Sync banche/ from Drive via rclone")
    parser.add_argument("--staging", required=True, help="Local staging directory")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)

    cmd = ["rclone", "sync", REMOTE, str(staging)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("-v")

    print(f"Syncing {REMOTE} → {staging}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("rclone sync failed")
        sys.exit(1)

    print("Sync complete")


if __name__ == "__main__":
    main()
