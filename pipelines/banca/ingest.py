#!/usr/bin/env python3
"""
Bank transaction ingestion pipeline.

Reads raw bank files from datahub ingresso/banca/banca_grezza/,
transforms them to 5D fact rows, appends to fatti/f_banche_movimenti.csv.

Supports: Sella CSV, MPS Excel.

Usage:
    python -m pipelines.banca.ingest --datahub /path/to/datahub --all
    python -m pipelines.banca.ingest --datahub /path/to/datahub --file FILENAME
    python -m pipelines.banca.ingest --datahub /path/to/datahub --dry-run --all
"""

import argparse
import csv
import hashlib
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import openpyxl  # noqa: F401 - presence check
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False


# -- Config -------------------------------------------------------------------

FILENAME_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2})__([A-Z_]+)__([A-Z_]+)__(.+)\.(csv|xls|xlsx)$"
)

SOCIETA_MAP = {"INTUR": "INTUR", "ORTI": "ORTI", "MPS": "ORTI"}
BANCA_MAP = {"INTUR_SELLA": "SELLA", "SELLA": "SELLA", "MPS": "MPS"}

DEFAULT_FUNZIONE = "FINANZA"
DEFAULT_BU = "HQ"
DEFAULT_LOCATION = "N_A"

FACT_HEADER = [
    "id_movimento", "societa_id", "business_unit_id", "funzione_id",
    "location_id", "oggetto_id", "banca_id", "data_operazione", "data_valuta",
    "descrizione", "divisa", "importo_debito", "importo_credito", "importo_netto",
    "categoria_raw", "sottocategoria_raw", "categoria_normalizzata",
    "sottocategoria_normalizzata", "tipo_movimento", "codice_identificativo_banca",
    "etichette", "note", "data_ingresso", "file_sorgente", "riga_sorgente",
    "hash_riga",
]


# -- Helpers ------------------------------------------------------------------

def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = logging.getLogger("ingest_banca")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh = logging.FileHandler(log_dir / f"ingest_banca_{ts}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def parse_filename(name: str) -> Optional[dict]:
    m = FILENAME_PATTERN.match(name)
    if not m:
        return None
    return {
        "data_ingresso": m.group(1),
        "funzione": m.group(2),
        "societa_banca": m.group(3),
        "dettaglio": m.group(4),
        "ext": m.group(5),
    }


def infer_ids(societa_banca: str) -> tuple[str, str]:
    societa = next((v for k, v in SOCIETA_MAP.items() if k in societa_banca), "UNKNOWN")
    banca = next((v for k, v in BANCA_MAP.items() if k in societa_banca), "UNKNOWN")
    return societa, banca


def euro(val: str) -> float:
    if not val:
        return 0.0
    val = val.strip().strip('"')
    neg = val.startswith("-")
    val = val.replace("-", "").replace("+", "").replace(",", ".")
    try:
        r = float(val)
        return -r if neg else r
    except ValueError:
        return 0.0


def md5(*args) -> str:
    return hashlib.md5("|".join(str(a) for a in args).encode()).hexdigest()


def parse_date(s: str) -> datetime:
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return datetime.now()


# -- Readers ------------------------------------------------------------------

def read_sella_csv(path: Path, logger: logging.Logger) -> list[dict]:
    logger.info(f"Reading Sella CSV: {path.name}")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            rows.append({
                "riga": i,
                "codice": row.get("Codice identificativo", ""),
                "data_op": row.get("Data operazione", ""),
                "data_val": row.get("Data valuta", ""),
                "desc": row.get("Descrizione", ""),
                "divisa": row.get("Divisa", "EUR"),
                "debito": euro(row.get("Debito", "")),
                "credito": euro(row.get("Credito", "")),
                "cat": row.get("Categoria", ""),
                "subcat": row.get("Sottocategoria", ""),
                "tipo": row.get("Etichette", ""),
                "note": row.get("Note", ""),
            })
    logger.info(f"  {len(rows)} rows")
    return rows


def read_mps_excel(path: Path, logger: logging.Logger) -> list[dict]:
    if not HAS_EXCEL:
        logger.error("openpyxl not installed, cannot read Excel")
        return []
    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas not installed, cannot read Excel")
        return []

    logger.info(f"Reading MPS Excel: {path.name}")
    df = pd.read_excel(path)
    required = ["Data", "Valuta", "Dare", "Avere", "Descrizione operazioni"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.error(f"Missing columns: {missing}")
        return []

    rows = []
    for i, r in df.iterrows():
        dare = r["Dare"] if pd.notna(r["Dare"]) else 0.0
        avere = r["Avere"] if pd.notna(r["Avere"]) else 0.0
        if dare == 0 and avere == 0:
            continue
        d_op = r["Data"].strftime("%d/%m/%y") if pd.notna(r["Data"]) and hasattr(r["Data"], "strftime") else str(r["Data"])
        d_val = r["Valuta"].strftime("%d/%m/%y") if pd.notna(r["Valuta"]) and hasattr(r["Valuta"], "strftime") else str(r["Valuta"])
        causale = str(r.get("Causale", "")) if pd.notna(r.get("Causale")) else ""
        desc = str(r.get("Descrizione operazioni", "")) if pd.notna(r.get("Descrizione operazioni")) else ""
        rows.append({
            "riga": i + 2,
            "codice": "",
            "data_op": d_op,
            "data_val": d_val,
            "desc": f"{causale} {desc}".strip(),
            "divisa": "EUR",
            "debito": abs(dare) if dare != 0 else 0.0,
            "credito": abs(avere) if avere != 0 else 0.0,
            "cat": causale,
            "subcat": "",
            "tipo": causale,
            "note": "",
        })
    logger.info(f"  {len(rows)} rows")
    return rows


# -- Mappings -----------------------------------------------------------------

def load_mappings(path: Path, logger: logging.Logger) -> dict:
    mappings = {}
    if not path.exists():
        logger.warning(f"No mapping table: {path}")
        return mappings
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("attivo", "TRUE").upper() != "TRUE":
                continue
            key = (row["sorgente_banca"], row.get("categoria_raw", ""), row.get("sottocategoria_raw", ""))
            mappings[key] = {
                "cat_norm": row["categoria_normalizzata"],
                "subcat_norm": row["sottocategoria_normalizzata"],
            }
    logger.info(f"  {len(mappings)} mapping rules")
    return mappings


def apply_mapping(row: dict, mappings: dict, sorgente: str) -> dict:
    for key in [
        (sorgente, row["cat"], row["subcat"]),
        (sorgente, row["cat"], ""),
        ("DEFAULT", "", ""),
    ]:
        if key in mappings:
            row["cat_norm"] = mappings[key]["cat_norm"]
            row["subcat_norm"] = mappings[key]["subcat_norm"]
            return row
    row["cat_norm"] = "NON_CLASSIFICATO"
    row["subcat_norm"] = "NON_CLASSIFICATO"
    return row


# -- Transform ----------------------------------------------------------------

def transform(raw: dict, meta: dict, counter: int) -> dict:
    societa, banca = infer_ids(meta["societa_banca"])
    d_op = parse_date(raw["data_op"])
    d_val = parse_date(raw["data_val"])
    netto = raw["credito"] - abs(raw["debito"])
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    return {
        "id_movimento": f"MOV_{societa}_{banca}_{d_op.strftime('%Y%m%d')}_{counter:06d}_{ts}",
        "societa_id": societa,
        "business_unit_id": DEFAULT_BU,
        "funzione_id": DEFAULT_FUNZIONE,
        "location_id": DEFAULT_LOCATION,
        "oggetto_id": f"CONTO_{societa}_{banca}",
        "banca_id": banca,
        "data_operazione": d_op.strftime("%Y-%m-%d"),
        "data_valuta": d_val.strftime("%Y-%m-%d"),
        "descrizione": raw["desc"],
        "divisa": raw["divisa"],
        "importo_debito": raw["debito"],
        "importo_credito": raw["credito"],
        "importo_netto": netto,
        "categoria_raw": raw["cat"],
        "sottocategoria_raw": raw["subcat"],
        "categoria_normalizzata": raw.get("cat_norm", "NON_CLASSIFICATO"),
        "sottocategoria_normalizzata": raw.get("subcat_norm", "NON_CLASSIFICATO"),
        "tipo_movimento": raw["tipo"],
        "codice_identificativo_banca": raw["codice"],
        "etichette": raw["tipo"],
        "note": raw["note"],
        "data_ingresso": meta["data_ingresso"],
        "file_sorgente": meta["filename"],
        "riga_sorgente": raw["riga"],
        "hash_riga": md5(societa, banca, d_op.strftime("%Y-%m-%d"), netto, raw["desc"]),
    }


# -- Pipeline -----------------------------------------------------------------

def load_hashes(fact_table: Path) -> set:
    if not fact_table.exists():
        return set()
    with open(fact_table, "r", encoding="utf-8") as f:
        return {row["hash_riga"] for row in csv.DictReader(f) if row.get("hash_riga")}


def process_file(filepath: Path, datahub: Path, mappings: dict, hashes: set,
                 logger: logging.Logger, dry_run: bool = False) -> dict:
    stats = {"file": filepath.name, "total": 0, "written": 0, "dupes": 0, "errors": 0}

    meta = parse_filename(filepath.name)
    if not meta:
        logger.error(f"Bad filename: {filepath.name}")
        stats["errors"] = 1
        return stats
    meta["filename"] = filepath.name

    # Read
    if meta["ext"] == "csv":
        raw_rows = read_sella_csv(filepath, logger)
    else:
        raw_rows = read_mps_excel(filepath, logger)

    stats["total"] = len(raw_rows)
    fact_table = datahub / "fatti" / "f_banche_movimenti.csv"
    new_rows = []

    for i, raw in enumerate(raw_rows, 1):
        raw = apply_mapping(raw, mappings, meta["societa_banca"])
        fact = transform(raw, meta, i)

        if fact["hash_riga"] in hashes:
            stats["dupes"] += 1
            continue

        hashes.add(fact["hash_riga"])
        new_rows.append(fact)

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


def main():
    parser = argparse.ArgumentParser(description="Bank transaction ingestion")
    parser.add_argument("--datahub", required=True, help="Path to datahub root")
    parser.add_argument("--file", "-f", help="Process specific file in ingresso/banca/banca_grezza/")
    parser.add_argument("--all", "-a", action="store_true", help="Process all files")
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
    logger.info("Bank ingestion pipeline START")

    mappings = load_mappings(datahub / "dimensioni" / "mappature" / "dim_mapping_banca.csv", logger)
    hashes = load_hashes(datahub / "fatti" / "f_banche_movimenti.csv")
    logger.info(f"Existing hashes: {len(hashes)}")

    ingresso = datahub / "ingresso" / "banca" / "banca_grezza"
    files = []
    if args.file:
        p = ingresso / args.file
        if not p.exists():
            logger.error(f"File not found: {p}")
            sys.exit(1)
        files = [p]
    elif args.all:
        files = sorted(ingresso.glob("*.csv")) + sorted(ingresso.glob("*.xls*"))
    else:
        parser.print_help()
        sys.exit(1)

    logger.info(f"Files to process: {len(files)}")

    for f in files:
        stats = process_file(f, datahub, mappings, hashes, logger, args.dry_run)
        logger.info(f"  {stats['file']}: {stats['total']} total, {stats['written']} written, {stats['dupes']} dupes, {stats['errors']} errors")

    logger.info("Bank ingestion pipeline DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
