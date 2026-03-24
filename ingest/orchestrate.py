#!/usr/bin/env python3
"""
Unified pipeline orchestrator — one command to ingest everything.

Syncs from Google Drive, classifies files by type, calls the right parser,
logs every processed file to a manifest for auditability.

Usage:
    python -m ingest.orchestrate                    # Full run (sync + ingest all)
    python -m ingest.orchestrate --dry-run           # Parse + CSV, no BigQuery
    python -m ingest.orchestrate --no-sync           # Skip Drive sync
    python -m ingest.orchestrate --only banca        # Only bank group
    python -m ingest.orchestrate --only amministrativa
    python -m ingest.orchestrate --only dimensioni
    python -m ingest.orchestrate --pipeline gasparotto  # Single pipeline

Datahub structure (Google Drive):
    hotelops_datahub/
    ├── homebanking/{ORTI,INTUR}/            → ingest.banca.ingest (f_banche_movimenti)
    ├── movimenti_contabili/{ORTI,INTUR}/   → ingest.amministrativa.ingest_movimenti_contabili
    ├── registro_banca_esolver/{ORTI,INTUR}/ → ingest.amministrativa.ingest_scheda_contabile (f_saldi_banca_snapshot)
    ├── partite_fornitori/{ORTI,INTUR}/     → ingest.amministrativa.ingest_partite_aperte
    ├── accodamenti/ORTI/                   → ingest.banca.ingest_accodamenti (f_accodamenti)
    ├── economato/                          → ingest.amministrativa.ingest_consumi_economato
    ├── coperti/                            → ingest.amministrativa.ingest_coperti
    ├── bilancino/{ORTI,INTUR}/             → ingest.amministrativa.ingest_bilancino
    ├── gasparotto/                         → ingest.amministrativa.ingest_gasparotto
    └── piani_finanziari/{ORTI,INTUR}/      → ingest.amministrativa.ingest_piano_finanziario_xlsx
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Paths ────────────────────────────────────────────────────────────────────

HOTELOPS_ROOT = Path(__file__).resolve().parent.parent

# Google Drive datahub (macOS default — override with --datahub)
DEFAULT_DATAHUB = Path(
    os.path.expanduser(
        "~/Library/CloudStorage/GoogleDrive-stefano@panoramagroup.it"
        "/My Drive/hotelops_datahub"
    )
)

# Local staging dirs
STAGING_BASE = Path(os.path.expanduser("~/.cache/hotelops"))
STAGING = {
    "banche":       STAGING_BASE / "banche_staging",
    "accodamenti":  STAGING_BASE / "accodamenti_staging",
    "movimenti":    STAGING_BASE / "movimenti_staging",
}

# Manifest — tracks every file we've ever processed
MANIFEST_DIR = DEFAULT_DATAHUB / "meta" / "pipeline"


# ── Pipeline registry ────────────────────────────────────────────────────────

class Pipeline:
    """Definition of one ingest pipeline."""

    def __init__(
        self,
        name: str,
        group: str,
        module: str,
        args_fn,  # callable(ctx) → list[str]
        needs_sync: bool = False,
        sync_fn=None,  # callable(ctx) → None
        description: str = "",
    ):
        self.name = name
        self.group = group
        self.module = module
        self.args_fn = args_fn
        self.needs_sync = needs_sync
        self.sync_fn = sync_fn
        self.description = description


def _banca_args(ctx: dict) -> list[str]:
    args = ["--datahub", str(ctx["datahub"]), "--source", str(STAGING["banche"])]
    if ctx["dry_run"]:
        args.append("--dry-run")
    if ctx["verbose"]:
        args.append("--verbose")
    return args


def _accodamenti_args(ctx: dict) -> list[str]:
    args = [
        "--datahub", str(ctx["datahub"]),
        "--staging", str(STAGING["accodamenti"]),
    ]
    if ctx["no_sync"]:
        args.append("--no-sync")
    if ctx["dry_run"]:
        args.append("--dry-run")
    if ctx["verbose"]:
        args.append("--verbose")
    return args


def _movimenti_args(ctx: dict) -> list[str]:
    args = [
        "--datahub", str(ctx["datahub"]),
        "--staging", str(STAGING["movimenti"]),
    ]
    if ctx["no_sync"]:
        args.append("--no-sync")
    if ctx["dry_run"]:
        args.append("--dry-run")
    return args


def _economato_args(ctx: dict) -> list[str]:
    source = ctx["datahub"] / "economato"
    args = [
        "--source", str(source),
        "--datahub", str(ctx["datahub"]),
    ]
    if ctx["dry_run"]:
        args += ["--dry-run", "--output-dir", str(ctx["output_dir"])]
    return args


def _coperti_args(ctx: dict) -> list[str]:
    source = ctx["datahub"] / "coperti"
    args = [
        "--source", str(source),
        "--datahub", str(ctx["datahub"]),
    ]
    if ctx["dry_run"]:
        args.append("--dry-run")
    return args


def _bilancino_discover(ctx: dict) -> list[list[str]]:
    """Discover bilancino files in bilancino/{ORTI,INTUR}/."""
    import re
    bil_dir = ctx["datahub"] / "bilancino"
    if not bil_dir.exists():
        return []
    runs = []
    for societa_dir in ["ORTI", "INTUR"]:
        sdir = bil_dir / societa_dir
        if not sdir.exists():
            continue
        for f in sorted(sdir.glob("*.xls*")):
            if f.name.startswith("~$"):
                continue
            societa = societa_dir
            mese = None
            m = re.search(r"(\d{4}-\d{2})", f.name)
            if m:
                mese = m.group(1)
            if not mese:
                continue
            args = ["--file", str(f), "--societa", societa, "--mese", mese]
            if ctx["dry_run"]:
                args.append("--dry-run")
            runs.append(args)
    return runs


def _gasparotto_discover(ctx: dict) -> list[list[str]]:
    """Discover Gasparotto master files."""
    ingresso = ctx["datahub"] / "gasparotto"
    if not ingresso.exists():
        return []
    runs = []
    for f in sorted(ingresso.glob("*Gasparotto*xlsx")) + sorted(ingresso.glob("*Master*xlsx")):
        if f.name.startswith("~$"):
            continue
        name_upper = f.name.upper()
        societa = "ORTI" if "ORTI" in name_upper else "INTUR" if "INTUR" in name_upper else "ORTI"
        args = ["--file", str(f), "--societa", societa]
        if ctx["dry_run"]:
            args += ["--dry-run", "--output-dir", str(ctx["output_dir"])]
        runs.append(args)
    return runs


def _piano_fin_discover(ctx: dict) -> list[list[str]]:
    """Discover Piano Finanziario XLSX files."""
    pf_dir = ctx["datahub"] / "piani_finanziari"
    if not pf_dir.exists():
        return []
    args = ["--dir", str(pf_dir), "--latest-only"]
    if ctx["dry_run"]:
        args += ["--dry-run", "--output-dir", str(ctx["output_dir"])]
    # Search in ORTI/ and INTUR/ subfolders
    has_files = (
        list((pf_dir / "ORTI").glob("*.xlsx")) if (pf_dir / "ORTI").exists() else []
    ) + (
        list((pf_dir / "INTUR").glob("*.xlsx")) if (pf_dir / "INTUR").exists() else []
    )
    return [args] if has_files else []


def _dim_categorie_args(ctx: dict) -> list[str]:
    # Look for the canonical file
    candidates = [
        ctx["datahub"] / "gasparotto" / "Costi Ricavi 2025-2026 Budget.xlsx",
        ctx["datahub"] / "dimensioni" / "Costi Ricavi 2025-2026 Budget.xlsx",
    ]
    for c in candidates:
        if c.exists():
            args = ["--file", str(c)]
            if ctx["dry_run"]:
                args += ["--dry-run", "--output-dir", str(ctx["output_dir"])]
            return args
    return []  # File not found — skip


def _dim_piano_conti_args(ctx: dict) -> list[str]:
    # Same file, different sheet
    return _dim_categorie_args(ctx)


def _stagionalita_args(ctx: dict) -> list[str]:
    # Reads from BQ (not datahub files), sync irrelevant.
    # ORTI only — INTUR deferred until revenue data loaded.
    args = ["--societa", "ORTI"]
    if ctx["dry_run"]:
        args.append("--dry-run")
    return args


def _partite_discover(ctx: dict) -> list[list[str]]:
    """Discover partite fornitori files in partite_fornitori/{ORTI,INTUR}/."""
    pt_dir = ctx["datahub"] / "partite_fornitori"
    if not pt_dir.exists():
        return []
    runs = []
    for societa_dir in ["ORTI", "INTUR"]:
        sdir = pt_dir / societa_dir
        if not sdir.exists():
            continue
        files = sorted(sdir.glob("*.xlsx")) + sorted(sdir.glob("*.xls"))
        files = [f for f in files if not f.name.startswith("~$")]
        if not files:
            continue
        # SNAPSHOT: only latest file matters
        latest = files[-1]
        args = ["--file", str(latest), "--societa", societa_dir]
        if ctx["dry_run"]:
            args.append("--dry-run")
        runs.append(args)
    return runs


def _scheda_contabile_discover(ctx: dict) -> list[list[str]]:
    """Discover scheda contabile files in registro_banca_esolver/{ORTI,INTUR}/."""
    sc_dir = ctx["datahub"] / "registro_banca_esolver"
    if not sc_dir.exists():
        return []
    runs = []
    for societa_dir in ["ORTI", "INTUR"]:
        sdir = sc_dir / societa_dir
        if not sdir.exists():
            continue
        files = sorted(sdir.glob("*.xlsx")) + sorted(sdir.glob("*.xls")) + sorted(sdir.glob("*.csv")) + sorted(sdir.glob("*.CSV"))
        files = [f for f in files if not f.name.startswith("~$")]
        if files:
            args = ["--dir", str(sdir), "--societa", societa_dir]
            if ctx["dry_run"]:
                args.append("--dry-run")
            runs.append(args)
    return runs


def _sync_banca(ctx: dict) -> None:
    """Sync bank files from Drive."""
    subprocess.run(
        [sys.executable, "-m", "ingest.banca.fetch_drive",
         "--staging", str(STAGING["banche"])],
        cwd=str(HOTELOPS_ROOT),
        check=True,
    )


# ── Pipeline definitions ─────────────────────────────────────────────────────

PIPELINES = [
    # Banca group — auto-discovering
    Pipeline(
        name="banca",
        group="banca",
        module="ingest.banca.ingest",
        args_fn=_banca_args,
        needs_sync=True,
        sync_fn=_sync_banca,
        description="Bank transactions → f_banche_movimenti",
    ),
    Pipeline(
        name="accodamenti",
        group="banca",
        module="ingest.banca.ingest_accodamenti",
        args_fn=_accodamenti_args,
        description="Esolver PMS accodamenti → f_accodamenti",
    ),
    Pipeline(
        name="movimenti_contabili",
        group="amministrativa",
        module="ingest.amministrativa.ingest_movimenti_contabili",
        args_fn=_movimenti_args,
        description="Esolver journal entries → f_movimenti_contabili",
    ),

    # Amministrativa group — auto-discovering
    Pipeline(
        name="consumi_economato",
        group="amministrativa",
        module="ingest.amministrativa.ingest_consumi_economato",
        args_fn=_economato_args,
        description="Supply consumption → f_consumi_economato",
    ),
    Pipeline(
        name="coperti",
        group="amministrativa",
        module="ingest.amministrativa.ingest_coperti",
        args_fn=_coperti_args,
        description="Meal covers → f_coperti_giornalieri",
    ),

    # Dimension tables — one-shot
    Pipeline(
        name="categorie",
        group="dimensioni",
        module="ingest.amministrativa.ingest_categorie",
        args_fn=_dim_categorie_args,
        description="Cost categories → d_categorie_conti",
    ),
    Pipeline(
        name="piano_conti",
        group="dimensioni",
        module="ingest.amministrativa.ingest_piano_conti_nuovo",
        args_fn=_dim_piano_conti_args,
        description="Chart of accounts 2026 → d_piano_conti",
    ),
    Pipeline(
        name="stagionalita",
        group="dimensioni",
        module="ingest.amministrativa.ingest_coefficienti_stagionalita",
        args_fn=_stagionalita_args,
        description="Seasonality coefficients → d_coefficienti_stagionalita",
    ),
]

# Multi-file pipelines (discover N files, run N times)
MULTI_PIPELINES = [
    ("bilancino", "amministrativa",
     "ingest.amministrativa.ingest_bilancino",
     _bilancino_discover,
     "Trial balance → f_bilancino"),
    ("gasparotto", "amministrativa",
     "ingest.amministrativa.ingest_gasparotto",
     _gasparotto_discover,
     "Gasparotto budget → f_budget_mensile"),
    ("piano_finanziario", "amministrativa",
     "ingest.amministrativa.ingest_piano_finanziario_xlsx",
     _piano_fin_discover,
     "Piano finanziario → f_piano_finanziario_input"),
    ("scheda_contabile", "amministrativa",
     "ingest.amministrativa.ingest_scheda_contabile",
     _scheda_contabile_discover,
     "Scheda contabile Esolver → f_saldi_banca_snapshot"),
    ("partite_fornitori", "amministrativa",
     "ingest.amministrativa.ingest_partite_aperte",
     _partite_discover,
     "Partite aperte fornitori → f_partite_aperte_fornitori"),
]


# ── Manifest ─────────────────────────────────────────────────────────────────

MANIFEST_FIELDS = [
    "timestamp", "pipeline", "status", "rows_before", "rows_after",
    "duration_s", "error",
]


def _file_hash(path: Path) -> str:
    """Quick hash of file for change detection."""
    h = hashlib.md5()
    h.update(str(path).encode())
    if path.exists():
        h.update(str(path.stat().st_mtime).encode())
        h.update(str(path.stat().st_size).encode())
    return h.hexdigest()[:12]


class Manifest:
    """Append-only log of pipeline runs."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.log_file = base_dir / "runs" / "orchestrate_runs.csv"

    def ensure_dirs(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log_run(self, pipeline: str, status: str, duration_s: float,
                error: str = ""):
        self.ensure_dirs()
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "timestamp": now,
            "pipeline": pipeline,
            "status": status,
            "rows_before": "",
            "rows_after": "",
            "duration_s": f"{duration_s:.1f}",
            "error": error[:200] if error else "",
        }
        write_header = not self.log_file.exists()
        with open(self.log_file, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if write_header:
                w.writeheader()
            w.writerow(row)


# ── Runner ───────────────────────────────────────────────────────────────────

def setup_logger(verbose: bool) -> logging.Logger:
    log = logging.getLogger("orchestrate")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-5s  %(message)s",
            datefmt="%H:%M:%S",
        ))
        log.addHandler(h)
    return log


def run_pipeline(
    module: str,
    args: list[str],
    logger: logging.Logger,
    manifest: Manifest,
    pipeline_name: str,
    dry_run: bool = False,
) -> bool:
    """Run a pipeline as a subprocess. Returns True on success."""
    import time

    cmd = [sys.executable, "-m", module] + args
    logger.info(f"  → {module} {' '.join(args[:6])}{'...' if len(args) > 6 else ''}")

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(HOTELOPS_ROOT),
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max per pipeline
        )
        duration = time.time() - t0

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                logger.info(f"    {line}")

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else f"exit code {result.returncode}"
            logger.error(f"  ✗ {pipeline_name} FAILED ({duration:.1f}s): {error_msg}")
            manifest.log_run(pipeline_name, "FAILED", duration, error_msg)
            return False

        logger.info(f"  ✓ {pipeline_name} OK ({duration:.1f}s)")
        manifest.log_run(pipeline_name, "OK", duration)
        return True

    except subprocess.TimeoutExpired:
        duration = time.time() - t0
        logger.error(f"  ✗ {pipeline_name} TIMEOUT after {duration:.0f}s")
        manifest.log_run(pipeline_name, "TIMEOUT", duration, "exceeded 600s")
        return False
    except Exception as e:
        duration = time.time() - t0
        logger.error(f"  ✗ {pipeline_name} ERROR: {e}")
        manifest.log_run(pipeline_name, "ERROR", duration, str(e))
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified hotelops pipeline orchestrator"
    )
    parser.add_argument("--datahub", default=str(DEFAULT_DATAHUB),
                        help="Path to hotelops_datahub root")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + CSV, no BigQuery writes")
    parser.add_argument("--no-sync", action="store_true",
                        help="Skip Drive sync (use local staging)")
    parser.add_argument("--only", choices=["banca", "amministrativa", "dimensioni"],
                        help="Run only this pipeline group")
    parser.add_argument("--pipeline", type=str,
                        help="Run only this specific pipeline by name")
    parser.add_argument("--output-dir", default="output",
                        help="CSV output dir for dry-run mode")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logger = setup_logger(args.verbose)
    datahub = Path(args.datahub)

    logger.info("=" * 60)
    logger.info("  HOTELOPS ORCHESTRATOR")
    logger.info("=" * 60)
    logger.info(f"  Datahub:  {datahub}")
    logger.info(f"  Dry-run:  {args.dry_run}")
    logger.info(f"  Sync:     {not args.no_sync}")
    if args.only:
        logger.info(f"  Filter:   group={args.only}")
    if args.pipeline:
        logger.info(f"  Filter:   pipeline={args.pipeline}")
    logger.info("=" * 60)

    ctx = {
        "datahub": datahub,
        "dry_run": args.dry_run,
        "no_sync": args.no_sync,
        "verbose": args.verbose,
        "output_dir": args.output_dir,
    }

    manifest = Manifest(datahub / "meta" / "pipeline")

    # Ensure staging dirs exist
    for s in STAGING.values():
        s.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}  # pipeline → OK/FAILED/SKIPPED

    # ── Step 1: Drive sync (if not --no-sync) ────────────────────────────
    if not args.no_sync and not args.dry_run:
        logger.info("")
        logger.info("── SYNC ─────────────────────────────────────────")
        for p in PIPELINES:
            if p.needs_sync and p.sync_fn:
                if args.only and p.group != args.only:
                    continue
                if args.pipeline and p.name != args.pipeline:
                    continue
                logger.info(f"  Syncing for {p.name}...")
                try:
                    p.sync_fn(ctx)
                    logger.info("  ✓ Sync OK")
                except Exception as e:
                    logger.error(f"  ✗ Sync failed: {e}")

    # ── Step 2: Run single-invocation pipelines ──────────────────────────
    logger.info("")
    logger.info("── PIPELINES ────────────────────────────────────")

    for p in PIPELINES:
        if args.only and p.group != args.only:
            results[p.name] = "SKIPPED"
            continue
        if args.pipeline and p.name != args.pipeline:
            results[p.name] = "SKIPPED"
            continue

        logger.info(f"\n[{p.name}] {p.description}")
        pipeline_args = p.args_fn(ctx)
        if not pipeline_args:
            logger.info("  ⊘ Nessun file trovato — skip")
            results[p.name] = "NO_FILES"
            continue

        ok = run_pipeline(
            p.module, pipeline_args, logger, manifest,
            p.name, args.dry_run,
        )
        results[p.name] = "OK" if ok else "FAILED"

    # ── Step 3: Run multi-file pipelines ─────────────────────────────────
    for name, group, module, discover_fn, desc in MULTI_PIPELINES:
        if args.only and group != args.only:
            results[name] = "SKIPPED"
            continue
        if args.pipeline and name != args.pipeline:
            results[name] = "SKIPPED"
            continue

        logger.info(f"\n[{name}] {desc}")
        try:
            arg_lists = discover_fn(ctx)
        except Exception as e:
            logger.error(f"  Discovery failed: {e}")
            results[name] = "FAILED"
            continue

        if not arg_lists:
            logger.info("  ⊘ Nessun file trovato — skip")
            results[name] = "NO_FILES"
            continue

        all_ok = True
        for i, pipeline_args in enumerate(arg_lists):
            sub_name = f"{name}[{i}]"
            ok = run_pipeline(
                module, pipeline_args, logger, manifest,
                sub_name, args.dry_run,
            )
            if not ok:
                all_ok = False

        results[name] = "OK" if all_ok else "PARTIAL"

    # ── Summary ──────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("  SUMMARY")
    logger.info("=" * 60)

    ok_count = sum(1 for s in results.values() if s == "OK")
    fail_count = sum(1 for s in results.values() if s in ("FAILED", "PARTIAL"))
    skip_count = sum(1 for s in results.values() if s in ("SKIPPED", "NO_FILES"))

    for name, status in results.items():
        icon = {"OK": "✓", "FAILED": "✗", "PARTIAL": "⚠", "SKIPPED": "⊘", "NO_FILES": "⊘"}
        logger.info(f"  {icon.get(status, '?')} {name:<25s} {status}")

    logger.info(f"\n  Total: {ok_count} OK, {fail_count} failed, {skip_count} skipped")
    logger.info("=" * 60)

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
