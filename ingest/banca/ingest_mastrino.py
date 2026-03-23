#!/usr/bin/env python3
"""
Mastrino (ERP accounting ledger) ingestion pipeline.

Reads raw mastrino Excel files from datahub/homebanking/ subfolders,
transforms them to 5D fact rows, appends to fatti/f_ledger_movimenti.csv.

Usage:
    python -m ingest.banca.ingest_mastrino --datahub /path/to/datahub --all
    python -m ingest.banca.ingest_mastrino --datahub /path/to/datahub --file FILENAME
    python -m ingest.banca.ingest_mastrino --datahub /path/to/datahub --dry-run --all
"""

import argparse
import csv
import hashlib
import logging
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

from core.contracts import SchemaViolationError, validate_columns


# -- Config -------------------------------------------------------------------

# Mastrino column names expected from ERP export
MASTRINO_REQUIRED_COLUMNS = {
    "Data registrazione", "Causale contabile", "Dare in UdC", "Avere in UdC",
}

# Descriptions that indicate balance rows, not real transactions
SKIP_DESCRIPTIONS = {"Riporto saldi", "Ripresa saldi"}

DEFAULT_FUNZIONE = "FINANZA"
DEFAULT_BU = "HQ"
DEFAULT_LOCATION = "N_A"

FACT_HEADER = [
    "id_registrazione", "societa_id", "business_unit_id", "funzione_id",
    "location_id", "oggetto_id", "banca_id", "data_registrazione",
    "descrizione", "importo", "importo_dare", "importo_avere", "divisa",
    "riferimento_registrazione", "documento", "riferimenti_iva",
    "centro_imputazione", "data_ingresso", "file_sorgente", "riga_sorgente",
    "hash_riga",
]


# -- Helpers ------------------------------------------------------------------

def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = logging.getLogger("ingest_mastrino")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh = logging.FileHandler(log_dir / f"ingest_mastrino_{ts}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def parse_euro(val) -> float:
    """Parse euro values — handles strings with comma decimal and numeric types."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(val) -> str | None:
    """Parse date from datetime object or string. Returns ISO format or None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def md5(*args) -> str:
    return hashlib.md5("|".join(str(a) for a in args).encode()).hexdigest()


# -- Reader -------------------------------------------------------------------

def read_mastrino_excel(
    path: Path, societa: str, banca: str, logger: logging.Logger,
) -> list[dict]:
    """Read a mastrino Excel file and return normalized rows."""
    logger.info(f"Reading mastrino: {path.name}")

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active

    # Read header from first row
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    headers = [str(h).strip() if h else "" for h in header_row]

    validate_columns(
        found=headers,
        required=MASTRINO_REQUIRED_COLUMNS,
        context=f"Mastrino {path.name}",
    )

    oggetto_id = f"CONTO_{societa}_{banca}"
    rows = []

    for i, row_vals in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        row = dict(zip(headers, row_vals))

        desc = str(row.get("Causale contabile", "") or "").strip()
        if desc in SKIP_DESCRIPTIONS:
            continue

        date_str = parse_date(row.get("Data registrazione"))
        if not date_str:
            continue

        dare = parse_euro(row.get("Dare in UdC"))
        avere = parse_euro(row.get("Avere in UdC"))
        if dare == 0.0 and avere == 0.0:
            continue

        importo = dare - avere  # positive = money in, negative = money out

        rif = str(row.get("Rif. registrazione", "") or "").strip()
        ts = datetime.now().strftime("%Y%m%d%H%M%S")

        rows.append({
            "id_registrazione": f"REG_{societa}_{banca}_{date_str.replace('-', '')}_{i:06d}_{ts}",
            "societa_id": societa,
            "business_unit_id": DEFAULT_BU,
            "funzione_id": DEFAULT_FUNZIONE,
            "location_id": DEFAULT_LOCATION,
            "oggetto_id": oggetto_id,
            "banca_id": banca,
            "data_registrazione": date_str,
            "descrizione": desc,
            "importo": importo,
            "importo_dare": dare,
            "importo_avere": avere,
            "divisa": str(row.get("Val.", "") or "EUR").strip() or "EUR",
            "riferimento_registrazione": rif,
            "documento": str(row.get("Documento", "") or "").strip(),
            "riferimenti_iva": str(row.get("Riferimenti IVA", "") or "").strip(),
            "centro_imputazione": str(row.get("Centro imputazione", "") or "").strip(),
            "data_ingresso": datetime.now().strftime("%Y-%m-%d"),
            "file_sorgente": path.name,
            "riga_sorgente": i,
            "hash_riga": md5(societa, banca, date_str, importo, desc),
        })

    wb.close()
    logger.info(f"  {len(rows)} rows (after filtering)")
    return rows


# -- Pipeline -----------------------------------------------------------------

def load_hashes(fact_table: Path) -> set:
    if not fact_table.exists():
        return set()
    with open(fact_table, "r", encoding="utf-8") as f:
        return {row["hash_riga"] for row in csv.DictReader(f) if row.get("hash_riga")}


def process_file(
    filepath: Path, datahub: Path, societa: str, banca: str,
    hashes: set, logger: logging.Logger, dry_run: bool = False,
) -> dict:
    stats = {"file": filepath.name, "total": 0, "written": 0, "dupes": 0, "errors": 0}

    try:
        raw_rows = read_mastrino_excel(filepath, societa, banca, logger)
    except SchemaViolationError as e:
        logger.error(f"Schema violation: {e}")
        stats["errors"] = 1
        return stats

    stats["total"] = len(raw_rows)
    fact_table = datahub / "fatti" / "f_ledger_movimenti.csv"
    new_rows = []

    for row in raw_rows:
        if row["hash_riga"] in hashes:
            stats["dupes"] += 1
            continue
        hashes.add(row["hash_riga"])
        new_rows.append(row)

    if dry_run:
        logger.info(f"DRY RUN: would write {len(new_rows)} rows")
        stats["written"] = 0
    elif new_rows:
        exists = fact_table.exists()
        with open(fact_table, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FACT_HEADER)
            if not exists:
                w.writeheader()
            w.writerows(new_rows)
        stats["written"] = len(new_rows)
        logger.info(f"Wrote {len(new_rows)} rows")

    return stats


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Mastrino (ERP ledger) ingestion")
    parser.add_argument("--datahub", required=True, help="Path to datahub root")
    parser.add_argument("--file", "-f", help="Process specific file in banche/{SOCIETA}/")
    parser.add_argument("--all", "-a", action="store_true", help="Process all files")
    parser.add_argument("--societa", required=True, help="Societa ID (e.g. ORTI)")
    parser.add_argument("--banca", required=True, help="Banca ID (e.g. MPS)")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    datahub = Path(args.datahub)
    if not datahub.exists():
        print(f"Datahub not found: {datahub}")
        sys.exit(1)

    log_dir = datahub / "meta" / "pipeline" / "logs"
    logger = setup_logging(log_dir, args.verbose)
    logger.info("=" * 60)
    logger.info("Mastrino ingestion pipeline START")

    hashes = load_hashes(datahub / "fatti" / "f_ledger_movimenti.csv")
    logger.info(f"Existing hashes: {len(hashes)}")

    banche_dir = datahub / "banche"
    files = []
    if args.file:
        p = banche_dir / args.file
        if not p.exists():
            logger.error(f"File not found: {p}")
            sys.exit(1)
        files = [p]
    elif args.all:
        files = sorted(banche_dir.glob("**/*.xls*"))
    else:
        parser.print_help()
        sys.exit(1)

    logger.info(f"Files to process: {len(files)}")

    for f in files:
        stats = process_file(f, datahub, args.societa, args.banca, hashes, logger, args.dry_run)
        logger.info(
            f"  {stats['file']}: {stats['total']} total, "
            f"{stats['written']} written, {stats['dupes']} dupes, "
            f"{stats['errors']} errors"
        )

    logger.info("Mastrino ingestion pipeline DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
