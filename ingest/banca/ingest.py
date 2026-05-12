#!/usr/bin/env python3
"""
Bank transaction ingestion pipeline.

Reads raw bank files from datahub/homebanking/{ORTI,INTUR}/,
transforms them to 5D fact rows, appends to fatti/f_banche_movimenti.csv.

Supports: Sella CSV, MPS Excel, Intesa Excel.

Usage:
    python -m ingest.banca.ingest --datahub /path/to/datahub --all
    python -m ingest.banca.ingest --datahub /path/to/datahub --file FILENAME
    python -m ingest.banca.ingest --datahub /path/to/datahub --dry-run --all
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

from core.bq.client import get_client
from core.config import PROJECT
from core.contracts import SchemaViolationError, validate_columns
from ingest._logging import setup_logging as _setup_logging
from core.schemas import BancaMovimentoRow, validate_batch

try:
    import openpyxl  # noqa: F401 - presence check

    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

BQ_TABLE = f"{PROJECT}.hotelops.f_banche_movimenti"
BQ_SNAPSHOT_TABLE = f"{PROJECT}.hotelops.f_saldi_banca_snapshot"


# -- Config -------------------------------------------------------------------

SOCIETA_KEYWORDS = {"INTUR": "INTUR", "ORTI": "ORTI"}
# Longer keys first so MPS_KROSS is matched before MPS
# Longer keys first so MPS_KROSS is matched before MPS
BANCA_KEYWORDS = {
    "MPS_KROSS": "MPS_KROSS",
    "MPS KROSS": "MPS_KROSS",
    "KROSS": "MPS_KROSS",
    "INTESA": "INTESA",
    "SELLA": "SELLA",
    "BCP": "BCP",
    "MPS": "MPS",
}

EXCEL_EXTENSIONS = {".xls", ".xlsx"}

DEFAULT_FUNZIONE = "FINANZA"
DEFAULT_BU = "HQ"
DEFAULT_LOCATION = "N_A"

FOOTER_DESCRIPTIONS = {"totale (€)", "totale(€)", "totale"}
FOOTER_PREFIXES = ("saldo al",)

# Italian IBAN: IT + 2 check digits + 1 letter (CIN) + 5 ABI + 5 CAB + 12 conto = 27 chars
IBAN_REGEX = re.compile(r"IT\d{2}[A-Z]\d{22}")

# ABI → banca_id. Source: core/registry.yaml banche section.
_ABI_TO_BANCA = {
    "01030": "MPS",
    "03069": "INTESA",
    "03268": "SELLA",
    "05142": "BCP",
}

# ORTI has two MPS accounts; the Kross one (conto 1205058) is its own banca_id.
# Match on the 12-char conto suffix of the IBAN.
_MPS_KROSS_CONTI = {"000001205058"}


def is_footer_row(raw: dict) -> bool:
    desc = (raw.get("desc") or "").strip().lower()
    return desc in FOOTER_DESCRIPTIONS or any(
        desc.startswith(p) for p in FOOTER_PREFIXES
    )


FACT_HEADER = [
    "id_movimento",
    "societa_id",
    "business_unit_id",
    "funzione_id",
    "location_id",
    "oggetto_id",
    "banca_id",
    "data_operazione",
    "data_valuta",
    "descrizione",
    "divisa",
    "importo_debito",
    "importo_credito",
    "importo_netto",
    "categoria_raw",
    "sottocategoria_raw",
    "categoria_normalizzata",
    "sottocategoria_normalizzata",
    "tipo_movimento",
    "codice_identificativo_banca",
    "etichette",
    "note",
    "data_ingresso",
    "file_sorgente",
    "riga_sorgente",
    "hash_riga",
    "raw_object_id",
]


# -- Helpers ------------------------------------------------------------------


def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    return _setup_logging("ingest_banca", log_dir, verbose)


def _scan_xlsx_preamble_iban(filepath: Path, max_rows: int = 30) -> Optional[str]:
    """Scan the first ~30 rows of an XLSX cell-by-cell for an Italian IBAN.

    MPS Web Banking 2026 puts IBAN at R12; Intesa Sanpaolo Web Banking at R2.

    Caveat: openpyxl in read_only=True silently drops columns beyond the first
    on workbooks missing a default style (Intesa export hits this case). Use
    the normal load path — the preamble is ≤30 rows so memory is negligible.
    """
    try:
        import openpyxl

        wb = openpyxl.load_workbook(filepath, data_only=True)
        try:
            ws = wb.active
            for row_idx, row in enumerate(
                ws.iter_rows(values_only=True), start=1
            ):
                if row_idx > max_rows:
                    break
                for cell in row:
                    if cell is None:
                        continue
                    s = str(cell).replace(" ", "").replace("\t", "")
                    m = IBAN_REGEX.search(s)
                    if m:
                        return m.group(0)
        finally:
            wb.close()
    except Exception:
        pass
    return None


def _banca_from_iban(iban: str) -> Optional[str]:
    """Map an Italian IBAN to banca_id. Distinguishes MPS vs MPS_KROSS via conto."""
    if not iban or len(iban) < 27:
        return None
    abi = iban[5:10]
    banca = _ABI_TO_BANCA.get(abi)
    if banca == "MPS" and iban[15:27] in _MPS_KROSS_CONTI:
        return "MPS_KROSS"
    return banca


def _detect_banca_from_content(filepath: Path) -> Optional[str]:
    """Detect bank type by inspecting file content.

    Primary signal: IBAN regex on the first ~30 rows (deterministic via ABI
    lookup, robust to header offsets like MPS Web Banking 2026 where the data
    header sits at R19). Fallback: column-name matching on first 5 rows for
    legacy formats whose preamble doesn't carry an IBAN.
    """
    ext = filepath.suffix.lower()
    try:
        if ext in (".xls", ".xlsx"):
            # Primary: IBAN preamble. Works for any Italian bank statement.
            iban = _scan_xlsx_preamble_iban(filepath)
            if iban:
                banca = _banca_from_iban(iban)
                if banca:
                    return banca

            # Fallback: column-name matching on first 5 rows (legacy formats).
            df = pd.read_excel(filepath, nrows=5)
            cols_upper = {str(c).upper() for c in df.columns}
            # MPS classic: Data, Valuta, Dare, Avere, Descrizione operazioni
            if {"DATA", "VALUTA", "DARE", "AVERE"}.issubset(cols_upper):
                return "MPS"
            # MPS 2026: DATA CONT., DATA VAL., DESCRIZIONE, IMPORTO(€)
            if any("DATA CONT" in c for c in cols_upper):
                return "MPS"
            # Intesa: Data Contabile, Data Valuta
            if any("DATA CONTABILE" in c for c in cols_upper):
                return "INTESA"
            # Sella: Codice identificativo, Data operazione
            if any("CODICE IDENTIFICATIVO" in c for c in cols_upper):
                return "SELLA"
        elif ext == ".csv":
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                header = f.readline().upper()
            if "CODICE IDENTIFICATIVO" in header:
                return "SELLA"
    except Exception:
        pass
    return None


def infer_meta(filepath: Path) -> dict:
    """Infer societa and banca from keywords in filename, folder path, and file content."""
    name_upper = filepath.name.upper()
    path_upper = str(filepath).upper()
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", filepath.name)
    data_ingresso = (
        date_match.group(0) if date_match else datetime.now().strftime("%Y-%m-%d")
    )
    # Try filename first, then full path
    societa = next(
        (v for k, v in SOCIETA_KEYWORDS.items() if k in name_upper), None
    ) or next((v for k, v in SOCIETA_KEYWORDS.items() if k in path_upper), "UNKNOWN")
    banca = next(
        (v for k, v in BANCA_KEYWORDS.items() if k in name_upper), None
    ) or next((v for k, v in BANCA_KEYWORDS.items() if k in path_upper), None)
    # Fallback: detect banca from file content (headers/columns)
    if not banca:
        banca = _detect_banca_from_content(filepath) or "UNKNOWN"
    return {
        "data_ingresso": data_ingresso,
        "funzione": DEFAULT_FUNZIONE,
        "societa_banca": f"{societa}_{banca}",
        "ext": filepath.suffix.lstrip(".").lower(),
        "filename": filepath.name,
    }


def infer_ids(societa_banca: str) -> tuple[str, str]:
    societa = next(
        (v for k, v in SOCIETA_KEYWORDS.items() if k in societa_banca), "UNKNOWN"
    )
    banca = next(
        (v for k, v in BANCA_KEYWORDS.items() if k in societa_banca), "UNKNOWN"
    )
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
    "Codice identificativo",
    "Data operazione",
    "Data valuta",
    "Descrizione",
    "Divisa",
    "Debito",
    "Credito",
    "Categoria",
    "Sottocategoria",
    "Etichette",
    "Note",
}

MPS_REQUIRED_COLUMNS = {"Data", "Valuta", "Dare", "Avere", "Descrizione operazioni"}
MPS2026_REQUIRED_COLUMNS = {"DATA CONT.", "DATA VAL.", "DESCRIZIONE", "IMPORTO(€)"}

INTESA_REQUIRED_COLUMNS = {"Data Contabile", "Data Valuta", "Dare", "Avere"}

SELLA_XLS_REQUIRED_COLUMNS = {
    "Codice identificativo",
    "Data operazione",
    "Descrizione",
    "Debito",
}


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
            rows.append(
                {
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
                }
            )
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
        # Skip footer rows (RIEPILOGO, repeated headers, totals)
        raw_dare = r["Dare"]
        raw_avere = r["Avere"]
        try:
            dare = float(raw_dare) if pd.notna(raw_dare) else 0.0
            avere = float(raw_avere) if pd.notna(raw_avere) else 0.0
        except (ValueError, TypeError):
            continue
        if dare == 0 and avere == 0:
            continue
        d_op = (
            r["Data"].strftime("%d/%m/%y")
            if pd.notna(r["Data"]) and hasattr(r["Data"], "strftime")
            else str(r["Data"])
        )
        d_val = (
            r["Valuta"].strftime("%d/%m/%y")
            if pd.notna(r["Valuta"]) and hasattr(r["Valuta"], "strftime")
            else str(r["Valuta"])
        )
        causale = str(r.get("Causale", "")) if pd.notna(r.get("Causale")) else ""
        desc = (
            str(r.get("Descrizione operazioni", ""))
            if pd.notna(r.get("Descrizione operazioni"))
            else ""
        )
        rows.append(
            {
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
            }
        )
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
    for i, row in enumerate(
        ws.iter_rows(min_row=header_idx + 1, values_only=True), start=header_idx + 1
    ):
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
        for col_name in [
            "Descrizione Causale ABI/SWIFT",
            "Descrizioni Aggiuntive",
            "Descrizione Causale Banca",
        ]:
            if col_name in col:
                v = row[col[col_name]]
                if v:
                    desc_parts.append(str(v).strip())

        causale = (
            str(row[col["Causale ABI/Swift"]] or "").strip()
            if "Causale ABI/Swift" in col
            else ""
        )
        cro = (
            str(row[col["Rif. Banca (CRO)"]] or "").strip()
            if "Rif. Banca (CRO)" in col
            else ""
        )

        rows.append(
            {
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
            }
        )

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
        raise SchemaViolationError(
            f"MPS 2026 Excel {path.name}: cannot find header row"
        )

    validate_columns(
        found=[c for c in header_row if c],
        required=MPS2026_REQUIRED_COLUMNS,
        context=f"MPS 2026 Excel {path.name}",
    )

    col = {name: idx for idx, name in enumerate(header_row) if name}

    rows = []
    for i, row in enumerate(
        ws.iter_rows(min_row=header_idx + 1, values_only=True), start=header_idx + 1
    ):
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

        causale = (
            str(row[col.get("CAUSALE", 3)] or "").strip() if "CAUSALE" in col else ""
        )
        desc = str(row[col["DESCRIZIONE"]] or "").strip()

        rows.append(
            {
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
            }
        )

    logger.info(f"  {len(rows)} rows")
    return rows


def extract_saldo_mps2026(
    path: Path, meta: dict, logger: logging.Logger
) -> dict | None:
    """Extract Saldo Finale + date from MPS 2026 OOXML header rows (before DATA CONT.)."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(path.read_bytes()), data_only=True)
        ws = wb.active
        saldo_finale = None
        data_finale = None
        for row in ws.iter_rows(max_row=30, values_only=True):
            for i, cell in enumerate(row):
                if isinstance(cell, str) and "Saldo Finale" in cell:
                    for v in row[i + 1 :]:
                        if v is None:
                            continue
                        if hasattr(v, "year"):
                            # openpyxl datetime — extract date directly
                            data_finale = v.date() if hasattr(v, "date") else v
                        elif isinstance(v, str):
                            # Text date in header — parse with DD/MM priority
                            parsed = parse_date(v)
                            if parsed.year > 2000:
                                data_finale = (
                                    parsed.date() if hasattr(parsed, "date") else parsed
                                )
                        elif isinstance(v, (int, float)):
                            saldo_finale = float(v)
                    break
            if saldo_finale is not None:
                break
        if saldo_finale is None:
            return None
        societa, banca = infer_ids(meta["societa_banca"])
        from datetime import date as _date

        if data_finale is None:
            data_finale = _date.today()
            logger.warning(f"  data_finale not found in {path.name}, using today")
        elif data_finale > _date.today():
            logger.warning(
                f"  data_finale {data_finale} is in the future for {path.name}, using today"
            )
            data_finale = _date.today()
        snapshot = {
            "societa_id": societa,
            "banca_id": banca,
            "data_snapshot": data_finale.isoformat(),
            "saldo_finale": saldo_finale,
        }
        logger.info(
            f"  Saldo Finale {societa}/{banca}: {data_finale} = €{saldo_finale:,.2f}"
        )
        return snapshot
    except Exception as e:
        logger.warning(f"  extract_saldo_mps2026 {path.name}: {e}")
        return None


def upsert_saldo_snapshot(
    bq_client: bigquery.Client, snapshot: dict, dry_run: bool, logger: logging.Logger
):
    """Write saldo snapshot to f_saldi_banca_snapshot (upsert by societa+banca+data_snapshot)."""
    if dry_run:
        logger.info(
            f"  DRY RUN saldo: {snapshot['societa_id']}/{snapshot['banca_id']} {snapshot['data_snapshot']} = €{snapshot['saldo_finale']:,.2f}"
        )
        return
    from google.cloud import bigquery as bq_lib

    table_id = BQ_SNAPSHOT_TABLE
    try:
        bq_client.get_table(table_id)
    except Exception:
        schema = [
            bq_lib.SchemaField("societa_id", "STRING"),
            bq_lib.SchemaField("banca_id", "STRING"),
            bq_lib.SchemaField("data_snapshot", "DATE"),
            bq_lib.SchemaField("saldo_finale", "FLOAT"),
        ]
        bq_client.create_table(bq_lib.Table(table_id, schema=schema))
        logger.info(f"  Created {table_id}")
    try:
        bq_client.query(f"""
        DELETE FROM `{table_id}`
        WHERE societa_id = '{snapshot["societa_id"]}'
          AND banca_id = '{snapshot["banca_id"]}'
          AND data_snapshot = DATE('{snapshot["data_snapshot"]}')
        """).result()
    except Exception as e:
        # Streaming buffer conflict — rows just inserted can't be DELETEd yet.
        # Safe to skip: we'll just INSERT (may produce a dupe for today, next run cleans up).
        if "streaming buffer" in str(e).lower():
            logger.warning(
                f"  Saldo skip DELETE (streaming buffer): {snapshot['societa_id']}/{snapshot['banca_id']} — inserting anyway"
            )
        else:
            raise
    errors = bq_client.insert_rows_json(table_id, [snapshot])
    if errors:
        logger.error(f"  Snapshot errors: {errors[:2]}")
    else:
        logger.info(
            f"  ✓ Saldo snapshot saved: {snapshot['societa_id']}/{snapshot['banca_id']} {snapshot['data_snapshot']}"
        )


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
        data_val = (
            xldate(data_val_raw, i, "Data valuta")
            if data_val_raw not in ("", "-")
            else data_op
        )
        rows.append(
            {
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
            }
        )

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
            key = (
                row["sorgente_banca"],
                row.get("categoria_raw", ""),
                row.get("sottocategoria_raw", ""),
            )
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
        "hash_riga": md5(
            societa, banca, d_op.strftime("%Y-%m-%d"), d_val.strftime("%Y-%m-%d"), netto
        ),
    }


# -- Pipeline -----------------------------------------------------------------


def load_hashes(bq_client: bigquery.Client) -> set:
    """Load dedup hashes from BQ.

    Computes both legacy (desc-based) hashes and current (date_val-based)
    hashes so that cross-format duplicates are caught regardless of which
    export format was ingested first.
    """
    try:
        result = bq_client.query(
            f"""SELECT hash_riga, societa_id, banca_id,
                       FORMAT_DATE('%Y-%m-%d', data_operazione) AS d_op,
                       FORMAT_DATE('%Y-%m-%d', data_valuta) AS d_val,
                       importo_netto
                FROM `{BQ_TABLE}`"""
        ).result()
        hashes = set()
        for row in result:
            if row.hash_riga:
                hashes.add(row.hash_riga)  # legacy hash
            # current hash (format-agnostic)
            hashes.add(
                md5(
                    row.societa_id, row.banca_id, row.d_op, row.d_val, row.importo_netto
                )
            )
        return hashes
    except Exception as e:
        logging.getLogger("ingest_banca").warning(f"Could not load hashes from BQ: {e}")
        return set()


def process_file(
    filepath: Path,
    bq_client: bigquery.Client,
    mappings: dict,
    hashes: set,
    logger: logging.Logger,
    dry_run: bool = False,
    meta: dict = None,
    raw_object_id: Optional[str] = None,
) -> dict:
    stats = {"file": filepath.name, "total": 0, "written": 0, "dupes": 0, "errors": 0}

    if meta is None:
        meta = infer_meta(filepath)

    # Detect actual format from content (Rosa's files often have .xls but are xlsx)
    if meta["ext"] in ("xls", "xlsx"):
        with open(filepath, "rb") as f:
            meta["ext"] = "xlsx" if f.read(2) == b"PK" else "xls"

    # Read — choose reader by societa_banca, with content-based fallback
    content_format = _detect_banca_from_content(filepath)
    try:
        sb = meta["societa_banca"].upper()
        if meta["ext"] == "csv":
            raw_rows = read_sella_csv(filepath, logger)
        elif "INTESA" in sb and content_format != "SELLA":
            raw_rows = read_intesa_excel(filepath, logger)
        elif "SELLA" in sb or content_format == "SELLA":
            if meta["ext"] == "xls":
                raw_rows = read_sella_xls(filepath, logger)
            else:
                raise SchemaViolationError(
                    f"SELLA file with unexpected format: {meta['ext']} — expected xls"
                )
        elif "MPS" in sb and meta["ext"] == "xlsx":
            raw_rows = read_mps2026_excel(filepath, logger)
            snapshot = extract_saldo_mps2026(filepath, meta, logger)
            if snapshot:
                upsert_saldo_snapshot(bq_client, snapshot, dry_run, logger)
        else:
            raw_rows = read_mps_excel(filepath, logger)
    except SchemaViolationError as e:
        logger.error(f"Schema violation: {e}")
        stats["errors"] = 1
        return stats

    raw_rows = [r for r in raw_rows if not is_footer_row(r)]
    stats["total"] = len(raw_rows)
    new_rows = []

    for i, raw in enumerate(raw_rows, 1):
        raw = apply_mapping(raw, mappings, meta["societa_banca"])
        fact = transform(raw, meta, i)
        fact["raw_object_id"] = raw_object_id

        if fact["hash_riga"] in hashes:
            stats["dupes"] += 1
            continue

        hashes.add(fact["hash_riga"])
        new_rows.append(fact)

    if dry_run:
        logger.info(f"DRY RUN: would write {len(new_rows)} rows")
        stats["written"] = 0
    elif new_rows:
        validate_batch(
            new_rows, BancaMovimentoRow, f"f_banche_movimenti ({meta['societa_banca']})"
        )
        df = pd.DataFrame(new_rows, columns=FACT_HEADER)
        df["data_operazione"] = pd.to_datetime(df["data_operazione"])
        df["data_valuta"] = pd.to_datetime(df["data_valuta"])
        df["data_ingresso"] = pd.to_datetime(df["data_ingresso"])
        df["riga_sorgente"] = df["riga_sorgente"].astype(int)
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        bq_client.load_table_from_dataframe(
            df, BQ_TABLE, job_config=job_config
        ).result()
        stats["written"] = len(new_rows)
        logger.info(f"Wrote {len(new_rows)} rows → BigQuery")

    return stats


def collect_files(source: Path) -> list[Path]:
    """Recursively collect all bank files from staging folder."""
    files = []
    for ext in ("*.csv", "*.xls", "*.xlsx", "*.XLS", "*.XLSX"):
        files.extend(source.rglob(ext))
    return sorted(files)


def ingest_single_file(
    file_path: Path,
    raw_object_id: str,
    societa: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Single-file ingestion path used by promote_raw_object.

    Differs from main() batch mode: caller already resolved the file (downloaded
    from GCS to temp by promotion), no datahub folder needed for mappings (we
    use an empty mapping dict — promote contract assumes the parser tolerates
    no-mapping for unmapped descriptors). Caller passes raw_object_id which is
    stamped on every row.
    """
    bq_client = get_client()
    mappings: dict = {}  # promote contract: no datahub access
    hashes = load_hashes(bq_client)

    meta = infer_meta(file_path)
    if "UNKNOWN" in meta["societa_banca"] and societa:
        # Override inferred societa from CLI flag when fname doesn't carry it.
        meta["societa_banca"] = meta["societa_banca"].replace("UNKNOWN", societa)

    logger = logging.getLogger("ingest.banca.single_file")
    return process_file(
        file_path,
        bq_client,
        mappings,
        hashes,
        logger,
        dry_run,
        meta=meta,
        raw_object_id=raw_object_id,
    )


def main():
    parser = argparse.ArgumentParser(description="Bank transaction ingestion")
    # Batch mode (existing):
    parser.add_argument(
        "--datahub", help="Path to datahub root (batch mode — for mappings and logs)"
    )
    parser.add_argument(
        "--source", "-s", help="Staging folder from rclone sync (batch mode default)"
    )
    # Single-file mode (new — used by promote subprocess):
    parser.add_argument(
        "--file", help="Single file to ingest (used by promotion path)"
    )
    parser.add_argument(
        "--raw-object-id", help="Raw object ID to stamp on rows (single-file mode)"
    )
    parser.add_argument(
        "--societa", choices=["ORTI", "INTUR"],
        help="Societa override for single-file mode when filename doesn't carry it",
    )
    parser.add_argument("--project", default=PROJECT, help="GCP project")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Single-file mode (promotion path)
    if args.file:
        if not args.raw_object_id:
            print("ERROR: --file requires --raw-object-id", file=sys.stderr)
            sys.exit(2)
        stats = ingest_single_file(
            file_path=Path(args.file),
            raw_object_id=args.raw_object_id,
            societa=args.societa,
            dry_run=args.dry_run,
        )
        print(
            f"single-file: {stats.get('total', 0)} total, "
            f"{stats.get('written', 0)} written, {stats.get('dupes', 0)} dupes, "
            f"{stats.get('errors', 0)} errors"
        )
        # Non-zero exit if parser couldn't read the file (schema violation,
        # unknown bank, etc). Promotion interprets exit≠0 as VALIDATE_FAIL
        # → emits REJECTED instead of falsely flagging PROMOTED.
        if stats.get("errors", 0) > 0:
            sys.exit(1)
        return

    # Batch mode (existing — keep behavior unchanged)
    if not args.datahub:
        print("ERROR: batch mode requires --datahub", file=sys.stderr)
        sys.exit(2)

    datahub = Path(args.datahub)
    if not datahub.exists():
        print(f"Datahub not found: {datahub}")
        sys.exit(1)

    log_dir = datahub / "meta" / "pipeline" / "logs"
    logger = setup_logging(log_dir, args.verbose)
    logger.info("=" * 60)
    logger.info("Bank ingestion pipeline START")

    bq_client = (
        get_client()
        if args.project == PROJECT
        else bigquery.Client(project=args.project)
    )
    mappings = load_mappings(
        datahub / "dimensioni" / "mappature" / "dim_mapping_banca.csv", logger
    )
    hashes = load_hashes(bq_client)
    logger.info(f"Existing hashes: {len(hashes)}")

    source = (
        Path(args.source)
        if args.source
        else Path.home() / ".cache/hotelops/banche_staging"
    )
    if not source.exists():
        logger.error(f"Source not found: {source} — run fetch_drive.py first")
        sys.exit(1)

    files = collect_files(source)
    logger.info(f"Files found in staging: {len(files)}")

    for filepath in files:
        meta = infer_meta(filepath)
        if "UNKNOWN" in meta["societa_banca"]:
            logger.warning(
                f"SKIP — cannot infer societa/banca from filename or path: {filepath}"
            )
            continue
        stats = process_file(
            filepath, bq_client, mappings, hashes, logger, args.dry_run, meta=meta
        )
        logger.info(
            f"  {stats['file']}: {stats['total']} total, {stats['written']} written, {stats['dupes']} dupes, {stats['errors']} errors"
        )

    logger.info("Bank ingestion pipeline DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
