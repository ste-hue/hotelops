#!/usr/bin/env python3
"""
Bank transaction ingestion pipeline.

Reads raw bank files from datahub ingresso/banca/estratti/,
transforms them to 5D fact rows, appends to fatti/f_banche_movimenti.csv.

Supports: Sella CSV, MPS Excel, Intesa Excel.

Usage:
    python -m pipelines.banca.ingest --datahub /path/to/datahub --all
    python -m pipelines.banca.ingest --datahub /path/to/datahub --file FILENAME
    python -m pipelines.banca.ingest --datahub /path/to/datahub --dry-run --all
"""

import argparse
import csv
import hashlib
import io
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from google.cloud import bigquery

from lib.contracts import SchemaViolationError, validate_columns

try:
    import openpyxl  # noqa: F401 - presence check
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

BQ_PROJECT = "hotelops-suite"
BQ_TABLE = "hotelops-suite.hotelops.f_banche_movimenti"


# -- Config -------------------------------------------------------------------

FILENAME_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2})__([A-Z_]+)__([A-Z_]+)__(.+)\.(csv|xls|xlsx)$"
)

SOCIETA_MAP = {"INTUR": "INTUR", "ORTI": "ORTI", "MPS": "ORTI"}
BANCA_MAP = {"INTUR_SELLA": "SELLA", "SELLA": "SELLA", "MPS": "MPS", "INTESA": "INTESA"}

# For path-based inference (staging traversal)
SOCIETA_KEYWORDS = {"INTUR": "INTUR", "ORTI": "ORTI"}
BANCA_KEYWORDS = {"MPS KROSS": "MPS_KROSS", "INTESA": "INTESA", "SELLA": "SELLA", "MPS": "MPS"}

EXCEL_EXTENSIONS = {".xls", ".xlsx"}

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


def meta_from_path(filepath: Path) -> Optional[dict]:
    """Infer metadata from staging folder path (e.g. MOVIMENTI BANCARI ESTRATTI/ORTI/ORTI-MPS/file.xls)."""
    path_str = " / ".join(filepath.parts).upper()
    societa = next((v for k, v in SOCIETA_KEYWORDS.items() if k in path_str), "UNKNOWN")
    banca = next((v for k, v in BANCA_KEYWORDS.items() if k in path_str), "UNKNOWN")
    ext = filepath.suffix.lstrip(".").lower()
    return {
        "data_ingresso": datetime.now().strftime("%Y-%m-%d"),
        "funzione": "FINANZA",
        "societa_banca": f"{societa}_{banca}",
        "ext": ext,
        "filename": filepath.name,
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
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return datetime.now()


# -- Readers ------------------------------------------------------------------

SELLA_REQUIRED_COLUMNS = {
    "Codice identificativo", "Data operazione", "Data valuta",
    "Descrizione", "Divisa", "Debito", "Credito",
    "Categoria", "Sottocategoria", "Etichette", "Note",
}

MPS_REQUIRED_COLUMNS = {"Data", "Valuta", "Dare", "Avere", "Descrizione operazioni"}
MPS2026_REQUIRED_COLUMNS = {"DATA CONT.", "DATA VAL.", "DESCRIZIONE", "IMPORTO(€)"}

INTESA_REQUIRED_COLUMNS = {"Data Contabile", "Data Valuta", "Dare", "Avere"}

SELLA_XLS_REQUIRED_COLUMNS = {"Codice identificativo", "Data operazione", "Descrizione", "Debito"}


def read_sella_csv(path: Path, logger: logging.Logger) -> list[dict]:
    logger.info(f"Reading Sella CSV: {path.name}")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_columns(
            found=reader.fieldnames or [],
            required=SELLA_REQUIRED_COLUMNS,
            context=f"Sella CSV {path.name}",
        )
        for i, row in enumerate(reader, start=2):
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
    validate_columns(
        found=list(df.columns),
        required=MPS_REQUIRED_COLUMNS,
        context=f"MPS Excel {path.name}",
    )

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


def read_intesa_excel(path: Path, logger: logging.Logger) -> list[dict]:
    if not HAS_EXCEL:
        logger.error("openpyxl not installed, cannot read Excel")
        return []

    logger.info(f"Reading Intesa Excel: {path.name}")
    wb = openpyxl.load_workbook(io.BytesIO(path.read_bytes()), data_only=True)
    ws = wb.active

    # Find header row dynamically (look for "Data Contabile" in first column)
    header_idx = None
    header_row = None
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row[0] == "Data Contabile":
            header_idx = i
            header_row = row
            break

    if header_idx is None:
        raise SchemaViolationError(f"Intesa Excel {path.name}: cannot find header row")

    validate_columns(
        found=[c for c in header_row if c],
        required=INTESA_REQUIRED_COLUMNS,
        context=f"Intesa Excel {path.name}",
    )

    col = {name: idx for idx, name in enumerate(header_row) if name}

    rows = []
    for i, row in enumerate(ws.iter_rows(min_row=header_idx + 1, values_only=True), start=header_idx + 1):
        dare_val = row[col["Dare"]]
        avere_val = row[col["Avere"]]
        if dare_val is None and avere_val is None:
            continue

        dare = abs(float(dare_val)) if dare_val is not None else 0.0
        avere = abs(float(avere_val)) if avere_val is not None else 0.0

        def fmt_date(v):
            if v is None:
                return ""
            if hasattr(v, "strftime"):
                return v.strftime("%d/%m/%Y")
            return str(v)

        desc_parts = []
        for col_name in ["Descrizione Causale ABI/SWIFT", "Descrizioni Aggiuntive", "Descrizione Causale Banca"]:
            if col_name in col:
                v = row[col[col_name]]
                if v:
                    desc_parts.append(str(v).strip())

        causale = str(row[col["Causale ABI/Swift"]] or "").strip() if "Causale ABI/Swift" in col else ""
        cro = str(row[col["Rif. Banca (CRO)"]] or "").strip() if "Rif. Banca (CRO)" in col else ""

        rows.append({
            "riga": i,
            "codice": cro,
            "data_op": fmt_date(row[col["Data Contabile"]]),
            "data_val": fmt_date(row[col["Data Valuta"]]),
            "desc": " | ".join(p for p in desc_parts if p),
            "divisa": "EUR",
            "debito": dare,
            "credito": avere,
            "cat": causale,
            "subcat": "",
            "tipo": causale,
            "note": "",
        })

    logger.info(f"  {len(rows)} rows")
    return rows


def read_mps2026_excel(path: Path, logger: logging.Logger) -> list[dict]:
    if not HAS_EXCEL:
        logger.error("openpyxl not installed, cannot read Excel")
        return []

    logger.info(f"Reading MPS 2026 Excel: {path.name}")
    wb = openpyxl.load_workbook(io.BytesIO(path.read_bytes()), data_only=True)
    ws = wb.active

    # Find header row by looking for "DATA CONT." in column B (index 1)
    header_idx = None
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row[1] == "DATA CONT.":
            header_idx = i
            header_row = row
            break

    if header_idx is None:
        raise SchemaViolationError(f"MPS 2026 Excel {path.name}: cannot find header row")

    validate_columns(
        found=[c for c in header_row if c],
        required=MPS2026_REQUIRED_COLUMNS,
        context=f"MPS 2026 Excel {path.name}",
    )

    col = {name: idx for idx, name in enumerate(header_row) if name}

    rows = []
    for i, row in enumerate(ws.iter_rows(min_row=header_idx + 1, values_only=True), start=header_idx + 1):
        importo = row[col["IMPORTO(€)"]]
        if importo is None:
            continue

        importo = float(importo)
        dare = abs(importo) if importo < 0 else 0.0
        avere = importo if importo > 0 else 0.0

        def fmt_date(v):
            if v is None:
                return ""
            if hasattr(v, "strftime"):
                return v.strftime("%d/%m/%Y")
            return str(v)

        causale = str(row[col.get("CAUSALE", 3)] or "").strip() if "CAUSALE" in col else ""
        desc = str(row[col["DESCRIZIONE"]] or "").strip()

        rows.append({
            "riga": i,
            "codice": "",
            "data_op": fmt_date(row[col["DATA CONT."]]),
            "data_val": fmt_date(row[col["DATA VAL."]]),
            "desc": f"{causale} {desc}".strip() if causale else desc,
            "divisa": "EUR",
            "debito": dare,
            "credito": avere,
            "cat": causale,
            "subcat": "",
            "tipo": causale,
            "note": "",
        })

    logger.info(f"  {len(rows)} rows")
    return rows


def read_sella_xls(path: Path, logger: logging.Logger) -> list[dict]:
    try:
        import xlrd
    except ImportError:
        logger.error("xlrd not installed, cannot read XLS")
        return []

    logger.info(f"Reading Sella XLS: {path.name}")
    wb = xlrd.open_workbook(str(path))
    ws = wb.sheet_by_index(0)

    header = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)]
    validate_columns(
        found=header,
        required=SELLA_XLS_REQUIRED_COLUMNS,
        context=f"Sella XLS {path.name}",
    )
    col = {name: idx for idx, name in enumerate(header)}

    def cell(row_idx, col_name):
        return ws.cell_value(row_idx, col[col_name]) if col_name in col else ""

    def num(v):
        try:
            return abs(float(v)) if v not in (None, "", ".") else 0.0
        except (ValueError, TypeError):
            return 0.0

    def xldate(v, row_idx, col_name):
        cell_obj = ws.cell(row_idx, col[col_name]) if col_name in col else None
        if cell_obj and cell_obj.ctype == xlrd.XL_CELL_DATE:
            t = xlrd.xldate_as_tuple(v, wb.datemode)
            from datetime import date
            return date(*t[:3]).strftime("%d/%m/%Y")
        return str(v).split(".")[0] if v else ""

    rows = []
    for i in range(1, ws.nrows):
        debito = num(cell(i, "Debito"))
        credito = num(cell(i, "Credito"))
        if debito == 0 and credito == 0:
            continue
        data_op = xldate(cell(i, "Data operazione"), i, "Data operazione")
        data_val_raw = cell(i, "Data valuta") if "Data valuta" in col else ""
        data_val = xldate(data_val_raw, i, "Data valuta") if data_val_raw not in ("", "-") else data_op
        rows.append({
            "riga": i + 1,
            "codice": str(cell(i, "Codice identificativo") or ""),
            "data_op": data_op,
            "data_val": data_val,
            "desc": str(cell(i, "Descrizione") or ""),
            "divisa": str(cell(i, "Divisa") or "EUR") or "EUR",
            "debito": debito,
            "credito": credito,
            "cat": str(cell(i, "Categoria") or ""),
            "subcat": str(cell(i, "Sottocategoria") or ""),
            "tipo": str(cell(i, "Etichette") or ""),
            "note": str(cell(i, "Note") or ""),
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

def load_hashes(bq_client: bigquery.Client) -> set:
    try:
        result = bq_client.query(
            f"SELECT hash_riga FROM `{BQ_TABLE}` WHERE hash_riga IS NOT NULL"
        ).result()
        return {row.hash_riga for row in result}
    except Exception as e:
        logging.getLogger("ingest_banca").warning(f"Could not load hashes from BQ: {e}")
        return set()


def process_file(filepath: Path, bq_client: bigquery.Client, mappings: dict, hashes: set,
                 logger: logging.Logger, dry_run: bool = False, meta: dict = None) -> dict:
    stats = {"file": filepath.name, "total": 0, "written": 0, "dupes": 0, "errors": 0}

    if meta is None:
        meta = parse_filename(filepath.name)
        if not meta:
            logger.error(f"Bad filename: {filepath.name}")
            stats["errors"] = 1
            return stats
        meta["filename"] = filepath.name

    # Detect actual format from content (Rosa's files often have .xls but are xlsx)
    if meta["ext"] in ("xls", "xlsx"):
        with open(filepath, "rb") as f:
            meta["ext"] = "xlsx" if f.read(2) == b"PK" else "xls"

    # Read
    try:
        sb = meta["societa_banca"].upper()
        if meta["ext"] == "csv":
            raw_rows = read_sella_csv(filepath, logger)
        elif "INTESA" in sb:
            raw_rows = read_intesa_excel(filepath, logger)
        elif "SELLA" in sb and meta["ext"] == "xls":
            raw_rows = read_sella_xls(filepath, logger)
        elif "MPS" in sb and meta["ext"] == "xlsx":
            raw_rows = read_mps2026_excel(filepath, logger)
        else:
            raw_rows = read_mps_excel(filepath, logger)
    except SchemaViolationError as e:
        logger.error(f"Schema violation: {e}")
        stats["errors"] = 1
        return stats

    stats["total"] = len(raw_rows)
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
        df = pd.DataFrame(new_rows, columns=FACT_HEADER)
        df["data_operazione"] = pd.to_datetime(df["data_operazione"])
        df["data_valuta"] = pd.to_datetime(df["data_valuta"])
        df["riga_sorgente"] = df["riga_sorgente"].astype(int)
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        bq_client.load_table_from_dataframe(df, BQ_TABLE, job_config=job_config).result()
        stats["written"] = len(new_rows)
        logger.info(f"Wrote {len(new_rows)} rows → BigQuery")

    return stats


def collect_files(source: Path) -> list[Path]:
    """Recursively collect all bank files from staging folder."""
    files = []
    for ext in ("*.csv", "*.xls", "*.xlsx", "*.XLS", "*.XLSX"):
        files.extend(source.rglob(ext))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="Bank transaction ingestion")
    parser.add_argument("--datahub", required=True, help="Path to datahub root (for mappings and logs)")
    parser.add_argument("--source", "-s", help="Staging folder from rclone sync (default: auto)")
    parser.add_argument("--project", default=BQ_PROJECT, help="GCP project")
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

    bq_client = bigquery.Client(project=args.project)
    mappings = load_mappings(datahub / "dimensioni" / "mappature" / "dim_mapping_banca.csv", logger)
    hashes = load_hashes(bq_client)
    logger.info(f"Existing hashes: {len(hashes)}")

    source = Path(args.source) if args.source else Path.home() / ".cache/hotelops/tesoreria_staging"
    if not source.exists():
        logger.error(f"Source not found: {source} — run fetch_drive.py first")
        sys.exit(1)

    files = collect_files(source)
    logger.info(f"Files found in staging: {len(files)}")

    for filepath in files:
        meta = parse_filename(filepath.name) or meta_from_path(filepath)
        if not meta:
            logger.warning(f"Cannot infer metadata: {filepath.name}, skipping")
            continue
        meta["filename"] = filepath.name
        stats = process_file(filepath, bq_client, mappings, hashes, logger, args.dry_run, meta=meta)
        logger.info(f"  {stats['file']}: {stats['total']} total, {stats['written']} written, {stats['dupes']} dupes, {stats['errors']} errors")

    logger.info("Bank ingestion pipeline DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
