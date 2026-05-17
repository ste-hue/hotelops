"""Populate 07_fornitori/F<NNN>/{01_preventivi,03_fatture}/ with rclone shortcuts.

Walks 3 canonical sources on Drive and maps each PDF to F-code via filename fuzzy match:
- FATTURE_LAVORI_HOTEL/*.pdf       → F<NNN>/03_fatture/
- Preventivi_Lavori_Hotel/*.pdf    → F<NNN>/01_preventivi/
- offerta_santelia*.pdf at root    → F<NNN>/01_preventivi/

Idempotent: skips destinations that already exist.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

RCLONE_REMOTE = "mywork"
PROJECT = "04_Progetti_Investimenti/Investimenti2026/HPAN25PIANO1_CamerePrimoPiano"
SUPPLIERS_YAML = Path(__file__).parent / "suppliers.yaml"


def normalize(s: str) -> str:
    s = (s or "").upper()
    s = s.replace("&", "AND")  # preserve B&T → BAND T (then BAND matches as token)
    s = re.sub(r"\b(S\.?\s*R\.?\s*L\.?|S\.?\s*P\.?\s*A\.?|SOCIO\s*UNICO|AZIONISTA\s*UNICO|SRL|SPA|SAS|SNC|GROUP)\b", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


EXPLICIT_ALIASES = {
    # F-code → list of filename tokens that should match (short / branded names)
    "F001": ["AMCN", "A.M.C.N", "AMCN BONIFICO"],
    "F005": ["B&T", "B & T", "DORELAN"],
    "F009": ["CSC", "IL CENTRO CSC", "CENTRO CSC"],
    "F011": ["CUOMO", "RINO CUOMO"],
    "F014": ["ILLUXIT"],
    "F015": ["INDELB", "INDEL B"],
    "F016": ["ITX", "ZARA"],
    "F017": ["LAUDATO"],
    "F018": ["MARIGLIANO", "ARCHISAVIO"],
    "F019": ["MARINO"],
    "F022": ["OLIVA"],
    "F023": ["PORTEDI", "DIERRE"],
    "F024": ["ROMANO"],
    "F025": ["STE", "S.T.E"],
    "F026": ["SALA", "SALA SERRAMENTI", "SALA INFISSI", "SALA GIANPIERO"],
    "F027": ["SANTELIA"],
    "F028": ["VDA", "VDA GROUP"],
    "F029": ["METAL 2000", "METAL2000"],
    "F031": ["SKLUM"],
    "F033": ["ELECTRA"],
}


def build_fuzzy_map() -> dict[str, str]:
    cfg = yaml.safe_load(SUPPLIERS_YAML.read_text())
    out: dict[str, str] = {}
    for s in cfg["suppliers"]:
        cod = s["code"]
        rs = normalize(s["ragione_sociale"])
        out[rs] = cod
        compact = re.sub(r"\s+", "", rs)
        if compact:
            out.setdefault(compact, cod)
        for tok in rs.split():
            if len(tok) >= 4 and tok not in {"SRL", "SPA", "SAS", "GROUP", "COSTRUZIONI", "TAPPEZZERIA", "GIUSEPPE", "ITALIA", "PIASTRELLISTI", "FIGLI"}:
                out.setdefault(tok, cod)
    # Add explicit aliases (overrides for short/brand names)
    for cod, aliases in EXPLICIT_ALIASES.items():
        for a in aliases:
            n = normalize(a)
            if n:
                out.setdefault(n, cod)
            c = re.sub(r"\s+", "", n)
            if c:
                out.setdefault(c, cod)
    return out


def match_filename_to_fcode(filename: str, fmap: dict[str, str]) -> str | None:
    norm = normalize(filename)
    if not norm:
        return None
    compact = re.sub(r"\s+", "", norm)
    if norm in fmap:
        return fmap[norm]
    if compact in fmap:
        return fmap[compact]
    # Token-level exact match (handles short brand names like VDA, CSC, STE)
    tokens = norm.split()
    for tok in tokens:
        if len(tok) >= 3 and tok in fmap:
            return fmap[tok]
    # Substring match for longer keys
    for known, cod in fmap.items():
        if len(known) < 4:
            continue
        if known in norm or known in compact:
            return cod
    return None


def list_fornitori_folders() -> dict[str, str]:
    """F-code → folder name (e.g., F001 → F001_AMCN)."""
    r = subprocess.run(
        ["rclone", "lsf", f"{RCLONE_REMOTE}:{PROJECT}/07_fornitori/", "--dirs-only"],
        capture_output=True, text=True, check=True,
    )
    out = {}
    for line in r.stdout.strip().splitlines():
        n = line.rstrip("/")
        if n.startswith("F") and "_" in n:
            out[n.split("_", 1)[0]] = n
    return out


def list_files(folder: str) -> list[str]:
    r = subprocess.run(
        ["rclone", "lsf", f"{RCLONE_REMOTE}:{PROJECT}/{folder}", "--files-only"],
        capture_output=True, text=True, check=True,
    )
    return [l for l in r.stdout.strip().splitlines() if l]


def list_dest_files(folder: str) -> set[str]:
    """Existing files in destination folder, for idempotency check."""
    try:
        r = subprocess.run(
            ["rclone", "lsf", f"{RCLONE_REMOTE}:{PROJECT}/{folder}", "--files-only"],
            capture_output=True, text=True, check=True,
        )
        return {l for l in r.stdout.strip().splitlines() if l}
    except subprocess.CalledProcessError:
        return set()


def make_shortcut(src_path: str, dest_path: str, dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        return True, "dry-run"
    cmd = [
        "rclone", "backend", "shortcut", f"{RCLONE_REMOTE}:",
        f"{PROJECT}/{src_path}",
        f"{PROJECT}/{dest_path}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else "unknown"
        return False, err[:120]
    return True, "ok"


def process_source(src_folder: str, dest_subfolder: str, fmap: dict[str, str],
                   f_folders: dict[str, str], dry_run: bool) -> dict:
    files = list_files(src_folder)
    print(f"\n── {src_folder} ({len(files)} files) → */{dest_subfolder}/")
    routed = skipped_unmatched = skipped_existing = errors = 0
    err_samples = []

    for fn in files:
        if not fn.lower().endswith((".pdf", ".PDF")):
            continue
        cod = match_filename_to_fcode(fn, fmap)
        if not cod or cod not in f_folders:
            skipped_unmatched += 1
            continue
        dest_folder = f"07_fornitori/{f_folders[cod]}/{dest_subfolder}"
        existing = list_dest_files(dest_folder)
        if fn in existing:
            skipped_existing += 1
            continue
        ok, msg = make_shortcut(f"{src_folder}/{fn}", f"{dest_folder}/{fn}", dry_run)
        if ok:
            routed += 1
        else:
            errors += 1
            if len(err_samples) < 3:
                err_samples.append((fn, msg))

    print(f"  routed:           {routed}")
    print(f"  skipped (no F):   {skipped_unmatched}")
    print(f"  skipped (exists): {skipped_existing}")
    print(f"  errors:           {errors}")
    for fn, msg in err_samples:
        print(f"    ERR {fn[:50]}: {msg}")
    return {"routed": routed, "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Default = apply. --dry-run to preview")
    args = ap.parse_args()

    fmap = build_fuzzy_map()
    f_folders = list_fornitori_folders()
    print(f"F-folders: {len(f_folders)}")
    print(f"Fuzzy map: {len(fmap)} keys")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")

    tot_routed = tot_errors = 0
    for r in [
        process_source("FATTURE_LAVORI_HOTEL", "03_fatture", fmap, f_folders, args.dry_run),
        process_source("Preventivi_Lavori_Hotel", "01_preventivi", fmap, f_folders, args.dry_run),
    ]:
        tot_routed += r["routed"]
        tot_errors += r["errors"]

    # Handle offerta_santelia at root (single known preventivo)
    r = subprocess.run(
        ["rclone", "lsf", f"{RCLONE_REMOTE}:{PROJECT}/", "--files-only", "--max-depth", "1"],
        capture_output=True, text=True,
    )
    root_files = [l for l in r.stdout.splitlines() if l]
    root_preventivi = [f for f in root_files if "offerta" in f.lower() or "preventivo" in f.lower()]
    if root_preventivi:
        print(f"\n── root preventivi ({len(root_preventivi)}) → */01_preventivi/")
        for fn in root_preventivi:
            cod = match_filename_to_fcode(fn, fmap)
            if cod and cod in f_folders:
                dest = f"07_fornitori/{f_folders[cod]}/01_preventivi"
                existing = list_dest_files(dest)
                if fn in existing:
                    print(f"  skip exists: {fn[:50]}")
                    continue
                ok, msg = make_shortcut(fn, f"{dest}/{fn}", args.dry_run)
                print(f"  {'✓' if ok else '✗'} {fn[:50]} → {cod}: {msg}")
                if ok:
                    tot_routed += 1
                else:
                    tot_errors += 1

    print(f"\n{'━' * 60}")
    print(f"TOTAL — routed: {tot_routed}, errors: {tot_errors}")


if __name__ == "__main__":
    main()
