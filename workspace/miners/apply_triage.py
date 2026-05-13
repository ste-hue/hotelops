"""Apply triage routing: rclone shortcuts from mining run thread folders to F*/ subfolders.

Reads the approved triage CSV (from `triage_capex.py` + user review), then for each
row with a routable f_code, creates a Drive shortcut from the thread folder in the
run dump to the canonical destination under 07_fornitori/F<NNN>/<subfolder>/.

Routing rules:
- F001..F033   → 07_fornitori/F<NNN>_<NAME>/<subfolder>/<thread_folder_name>
- SCARTATO_*   → 07_fornitori/_SCARTATI/<NAME>/<thread_folder_name>
- GENERIC_PROJECT → _PROGETTO_TRASVERSALE/<thread_folder_name>
- NOISE        → skip (leave in run dump only)

Dry-run by default; pass --apply to actually create shortcuts.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

RCLONE_REMOTE = "mywork"
PROJECT_DRIVE_PATH = "04_Progetti_Investimenti/Investimenti2026/HPAN25PIANO1_CamerePrimoPiano"


def list_f_folders() -> dict[str, str]:
    """Return mapping F-code → folder name (e.g. 'F001' → 'F001_AMCN')."""
    cmd = ["rclone", "lsf", f"{RCLONE_REMOTE}:{PROJECT_DRIVE_PATH}/07_fornitori/", "--dirs-only"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    mapping = {}
    for line in out.strip().splitlines():
        name = line.rstrip("/")
        if name.startswith("F") and "_" in name:
            code = name.split("_", 1)[0]
            mapping[code] = name
    return mapping


def compute_dest(f_code: str, subfolder: str, thread_folder_name: str, f_map: dict[str, str]) -> str | None:
    """Return destination relative path under PROJECT_DRIVE_PATH, or None if skip."""
    if f_code == "NOISE":
        return None
    if f_code == "GENERIC_PROJECT":
        return f"_PROGETTO_TRASVERSALE/{thread_folder_name}"
    if f_code.startswith("SCARTATO_"):
        name = f_code.replace("SCARTATO_", "")
        return f"07_fornitori/_SCARTATI/{name}/{thread_folder_name}"
    if f_code in f_map:
        return f"07_fornitori/{f_map[f_code]}/{subfolder}/{thread_folder_name}"
    return None


def rclone_shortcut(src_path: str, dest_path: str, dry_run: bool) -> tuple[bool, str]:
    """Create Drive shortcut. Returns (ok, message)."""
    cmd = [
        "rclone", "backend", "shortcut", f"{RCLONE_REMOTE}:",
        f"{PROJECT_DRIVE_PATH}/{src_path}",
        f"{PROJECT_DRIVE_PATH}/{dest_path}",
    ]
    if dry_run:
        return True, "dry-run"
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else "unknown err"
    return True, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path, help="triage_proposal.csv (approved)")
    ap.add_argument("--run-folder", required=True,
                    help="Run folder name under workspace-controller-test/ (e.g. HPAN25PIANO1__extract_20260512_113045)")
    ap.add_argument("--apply", action="store_true", help="Actually create shortcuts (default = dry-run)")
    ap.add_argument("--min-confidence", default="MED", choices=["HIGH", "MED", "LOW"],
                    help="Skip rows below this confidence (default MED → applies HIGH+MED)")
    args = ap.parse_args()

    f_map = list_f_folders()
    print(f"F-folder map: {len(f_map)} entries")

    rows_total = rows_skip_conf = rows_skip_noise = rows_route = rows_err = 0
    confidence_order = {"HIGH": 3, "MED": 2, "LOW": 1}
    threshold = confidence_order[args.min_confidence]

    by_dest: dict[str, list[dict]] = {}
    errors: list[tuple[str, str]] = []

    with args.csv.open() as f:
        for row in csv.DictReader(f):
            rows_total += 1
            conf = row.get("confidence", "LOW").upper()
            if confidence_order.get(conf, 0) < threshold:
                rows_skip_conf += 1
                continue

            f_code = row.get("f_code", "NOISE")
            subfolder = row.get("subfolder", "04_comunicazioni")
            drive_folder_rel = row.get("drive_folder", "")  # e.g. _Certo/<thread_folder>
            mailbox = row.get("mailbox", "")
            if not drive_folder_rel or not mailbox:
                rows_err += 1
                errors.append((row.get("thread_id", "?"), "missing drive_folder or mailbox"))
                continue

            thread_folder_name = Path(drive_folder_rel).name
            dest_rel = compute_dest(f_code, subfolder, thread_folder_name, f_map)
            if dest_rel is None:
                rows_skip_noise += 1
                continue

            src_rel = f"workspace-controller-test/{args.run_folder}/{mailbox}/{drive_folder_rel}"
            ok, msg = rclone_shortcut(src_rel, dest_rel, dry_run=not args.apply)
            if not ok:
                rows_err += 1
                errors.append((thread_folder_name, msg))
            else:
                rows_route += 1
                by_dest.setdefault(f_code, []).append(row)

    print(f"\n{'━' * 64}")
    print(f"{'DRY-RUN' if not args.apply else 'APPLIED'} — confidence ≥ {args.min_confidence}")
    print(f"{'━' * 64}")
    print(f"  Total rows in CSV:       {rows_total}")
    print(f"  Skipped (low confidence): {rows_skip_conf}")
    print(f"  Skipped (NOISE):          {rows_skip_noise}")
    print(f"  Routed:                   {rows_route}")
    print(f"  Errors:                   {rows_err}")
    print(f"\nBy destination (f_code → count):")
    for code in sorted(by_dest):
        print(f"  {code:24s} → {len(by_dest[code])}")
    if errors:
        print(f"\nErrors:")
        for tid, msg in errors[:10]:
            print(f"  {tid}: {msg}")

    if not args.apply:
        print(f"\nTo apply: re-run with --apply")


if __name__ == "__main__":
    main()
