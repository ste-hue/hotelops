#!/usr/bin/env python3
"""
Lista movimenti contabili Esolver ingestion pipeline.

Reads XLS exports from Esolver (Lista movimenti contabili) → BigQuery f_movimenti_contabili.
Idempotent via MD5 hash on (societa_id, id_documento, num_progr_riga).

Sources (Drive):
    hotelops_datahub/movimenti_contabili/ORTI/
    hotelops_datahub/movimenti_contabili/INTUR/

Usage:
    # Full run: sync from Drive + ingest
    python -m ingest.flussi.ingest_movimenti_contabili --datahub /path/to/datahub

    # Ingest only (already synced)
    python -m ingest.flussi.ingest_movimenti_contabili --datahub /path/to/datahub --no-sync

    # Single file
    python -m ingest.flussi.ingest_movimenti_contabili --file /path/to/ORTI_LISTAMOVCONT.XLS --societa ORTI

    # Dry run
    python -m ingest.flussi.ingest_movimenti_contabili --file /path/to/ORTI_LISTAMOVCONT.XLS --societa ORTI --dry-run
"""

import argparse
import csv
import hashlib
import logging
import sys
from pathlib import Path

try:
    import xlrd

    HAS_XLRD = True
except ImportError:
    HAS_XLRD = False

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.bq.client import get_client
from core.config import PROJECT
from core.datahub_sync import RcloneError, rclone_sync

BQ_TABLE = f"{PROJECT}.hotelops.f_movimenti_contabili"

STAGING_DEFAULT = Path.home() / ".cache/hotelops/movimenti_staging"

FACT_HEADER = [
    "hash_riga",
    "societa_id",
    "id_documento",
    "num_progr_riga",
    "gruppo_doc",
    "anno",
    "mese",
    "data_registrazione",
    "sigla_doc",
    "rif_registrazione",
    "num_doc_originale",
    "data_originale",
    "tipo_documento",
    "cod_conto",
    "cod_partitario",
    "rag_sociale",
    "causale_contabile",
    "imp_dare",
    "imp_avere",
    "cod_divisione",
    "file_sorgente",
    "data_ingresso",
    "raw_object_id",
]

BQ_SCHEMA = (
    [
        bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("id_documento", "INTEGER"),
        bigquery.SchemaField("num_progr_riga", "INTEGER"),
        bigquery.SchemaField("gruppo_doc", "STRING"),
        bigquery.SchemaField("anno", "INTEGER"),
        bigquery.SchemaField("mese", "INTEGER"),
        bigquery.SchemaField("data_registrazione", "DATE"),
        bigquery.SchemaField("sigla_doc", "STRING"),
        bigquery.SchemaField("rif_registrazione", "STRING"),
        bigquery.SchemaField("num_doc_originale", "STRING"),
        bigquery.SchemaField("data_originale", "DATE"),
        bigquery.SchemaField("tipo_documento", "STRING"),
        bigquery.SchemaField("cod_conto", "STRING"),
        bigquery.SchemaField("cod_partitario", "STRING"),
        bigquery.SchemaField("rag_sociale", "STRING"),
        bigquery.SchemaField("causale_contabile", "STRING"),
        bigquery.SchemaField("imp_dare", "FLOAT64"),
        bigquery.SchemaField("imp_avere", "FLOAT64"),
        bigquery.SchemaField("cod_divisione", "STRING"),
        bigquery.SchemaField("file_sorgente", "STRING"),
        bigquery.SchemaField("data_ingresso", "DATE"),
        bigquery.SchemaField("raw_object_id", "STRING"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_movimenti_contabili")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def xl_date(v) -> str | None:
    if isinstance(v, float) and v > 0:
        return xlrd.xldate_as_datetime(v, 0).date().isoformat()
    return None


def make_hash(societa_id: str, id_documento: int, num_progr_riga: int) -> str:
    key = f"{societa_id}|{id_documento}|{num_progr_riga}"
    return hashlib.md5(key.encode()).hexdigest()


def make_hash_content(
    societa_id: str,
    data_reg_iso: str | None,
    cod_conto: str | None,
    imp_dare: float | None,
    imp_avere: float | None,
    causale: str | None,
) -> str:
    """Content-based stable hash across XLS legacy and XLSX report formats.

    The same logical accounting row produces the same hash regardless of the
    Esolver report format used to extract it. Must stay in sync with the SQL
    expression used by the migration in core/bq/migrations/2026_05_08_movimenti_content_hash.py.

    Note: rag_sociale is intentionally excluded — XLSX populates it with the
    account description for bank/cash rows (e.g. 190101 → 'Banca c/c MPS')
    while legacy XLS leaves it NULL. The causale already carries the
    distinguishing info (counterparty name, document ref, etc.).
    """
    if not data_reg_iso:
        raise ValueError("data_reg_iso is required for hash stability")

    key = "|".join(
        [
            societa_id,
            data_reg_iso,
            (cod_conto or "").strip(),
            f"{(imp_dare or 0.0):.2f}",
            f"{(imp_avere or 0.0):.2f}",
            (causale or "").strip(),
        ]
    )
    return hashlib.md5(key.encode()).hexdigest()


def infer_societa(filepath: Path) -> str | None:
    name = filepath.stem.upper()
    if "INTUR" in name:
        return "INTUR"
    if "ORTI" in name:
        return "ORTI"
    return None


def parse_file(filepath: Path, societa_id: str, logger: logging.Logger) -> list[dict]:
    if not HAS_XLRD:
        logger.error("xlrd non installato. Run: pip install xlrd")
        sys.exit(1)

    from datetime import date

    today = date.today().isoformat()
    file_sorgente = filepath.name

    wb = xlrd.open_workbook(str(filepath))
    ws = wb.sheets()[0]
    logger.info(f"  {file_sorgente}: {ws.nrows - 1} righe")

    rows = []
    for r in range(1, ws.nrows):
        row = ws.row_values(r)

        id_doc = int(row[0]) if isinstance(row[0], float) else None
        id_mov = int(row[1]) if isinstance(row[1], float) else None
        num_progr = int(row[2]) if isinstance(row[2], float) else None
        gruppo_doc = str(row[3]).strip() if row[3] else None
        anno = int(row[4]) if isinstance(row[4], float) else None
        mese = int(row[5]) if isinstance(row[5], float) else None
        data_reg = xl_date(row[6])
        sigla_doc = str(row[7]).strip() if row[7] else None
        rif_reg = str(row[8]).strip() if row[8] else None
        num_doc_orig = str(row[9]).strip() if row[9] else None
        data_orig = xl_date(row[10])
        tipo_doc = str(row[11]).strip() if row[11] else None
        cod_conto = str(row[12]).strip() if row[12] else None
        cod_partitario = str(row[13]).strip() if row[13] else None
        rag_sociale = str(row[15]).strip() if row[15] else None
        causale = str(row[18]).strip() if row[18] else None
        imp_dare = float(row[20]) if isinstance(row[20], float) else 0.0
        imp_avere = float(row[21]) if isinstance(row[21], float) else 0.0
        cod_divisione = str(row[25]).strip() if row[25] else None

        if id_doc is None or num_progr is None or data_reg is None:
            continue

        hash_riga = make_hash_content(
            societa_id, data_reg, cod_conto, imp_dare, imp_avere, causale
        )

        rows.append(
            {
                "hash_riga": hash_riga,
                "societa_id": societa_id,
                "id_documento": id_doc,
                "num_progr_riga": num_progr,
                "gruppo_doc": gruppo_doc,
                "anno": anno,
                "mese": mese,
                "data_registrazione": data_reg,
                "sigla_doc": sigla_doc,
                "rif_registrazione": rif_reg,
                "num_doc_originale": num_doc_orig,
                "data_originale": data_orig,
                "tipo_documento": tipo_doc,
                "cod_conto": cod_conto,
                "cod_partitario": cod_partitario,
                "rag_sociale": rag_sociale,
                "causale_contabile": causale,
                "imp_dare": imp_dare,
                "imp_avere": imp_avere,
                "cod_divisione": cod_divisione,
                "file_sorgente": file_sorgente,
                "data_ingresso": today,
                "raw_object_id": None,
            }
        )

    return rows


def parse_file_xlsx(
    filepath: Path, societa_id: str, logger: logging.Logger
) -> list[dict]:
    """Parse Esolver 'report-style' XLSX movimenti contabili.

    Column layout (26 cols):
        0=logo, 1=societa, 2=timestamp, 3=unused, 4=operatore,
        5=data_registrazione, 6=sigla_doc (e.g. "PNC 1"), 7=data_originale,
        8=tipo_documento, 9=cod_conto, 10=cod_partitario, 11=rag_sociale,
        12=causale_contabile, 13=imp_dare, 14=imp_avere, 15-25=running totals
    """
    import re
    from datetime import date, datetime

    import openpyxl

    today = date.today().isoformat()
    file_sorgente = filepath.name

    wb = openpyxl.load_workbook(str(filepath), read_only=True)
    ws = wb.active
    logger.info(f"  {file_sorgente}: {ws.max_row} righe (xlsx)")

    rows = []
    # Track row index within each (date, pnc_num) group for num_progr_riga
    group_counters: dict[tuple, int] = {}

    for raw_row in ws.iter_rows(values_only=True):
        # Extract date — col 5 can be datetime or string "YYYY-MM-DD"
        raw_date = raw_row[5]
        if isinstance(raw_date, datetime):
            data_reg = raw_date.date()
        elif isinstance(raw_date, date):
            data_reg = raw_date
        elif isinstance(raw_date, str):
            try:
                data_reg = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                continue  # skip non-data rows (headers, totals)
        else:
            continue

        # Extract PNC number from col 6 (e.g. "PNC 1" -> sigla="PNC", num=1)
        sigla_raw = str(raw_row[6]).strip() if raw_row[6] else ""
        match = re.match(r"([A-Z]+)\s+(\d+)", sigla_raw)
        if not match:
            continue
        sigla_doc = match.group(1)
        pnc_num = int(match.group(2))

        # num_progr_riga: sequential within (date, pnc_num)
        group_key = (data_reg.isoformat(), pnc_num)
        idx = group_counters.get(group_key, 0)
        group_counters[group_key] = idx + 1

        cod_conto = str(raw_row[9]).strip() if raw_row[9] else None
        if not cod_conto:
            continue

        cod_part_raw = raw_row[10]
        cod_partitario = (
            str(int(cod_part_raw))
            if isinstance(cod_part_raw, (int, float)) and cod_part_raw
            else None
        )

        imp_dare = float(raw_row[13]) if isinstance(raw_row[13], (int, float)) else 0.0
        imp_avere = float(raw_row[14]) if isinstance(raw_row[14], (int, float)) else 0.0

        # Parse data_originale from col 7 (often " DD/MM/YY" or None)
        data_orig = None
        if raw_row[7] and str(raw_row[7]).strip():
            try:
                data_orig = (
                    datetime.strptime(str(raw_row[7]).strip(), "%d/%m/%y")
                    .date()
                    .isoformat()
                )
            except ValueError:
                pass

        rag_sociale = str(raw_row[11]).strip() if raw_row[11] else None
        causale = str(raw_row[12]).strip() if raw_row[12] else None

        hash_riga = make_hash_content(
            societa_id,
            data_reg.isoformat(),
            cod_conto,
            imp_dare,
            imp_avere,
            causale,
        )

        rows.append(
            {
                "hash_riga": hash_riga,
                "societa_id": societa_id,
                "id_documento": None,
                "num_progr_riga": idx + 1,
                "gruppo_doc": sigla_raw,
                "anno": data_reg.year,
                "mese": data_reg.month,
                "data_registrazione": data_reg.isoformat(),
                "sigla_doc": sigla_doc,
                "rif_registrazione": None,
                "num_doc_originale": None,
                "data_originale": data_orig,
                "tipo_documento": str(raw_row[8]).strip() if raw_row[8] else None,
                "cod_conto": cod_conto,
                "cod_partitario": cod_partitario,
                "rag_sociale": rag_sociale,
                "causale_contabile": causale,
                "imp_dare": imp_dare,
                "imp_avere": imp_avere,
                "cod_divisione": None,
                "file_sorgente": file_sorgente,
                "data_ingresso": today,
                "raw_object_id": None,
            }
        )

    wb.close()
    return rows


def sync_from_drive(staging: Path, logger: logging.Logger):
    staging.mkdir(parents=True, exist_ok=True)
    for societa in ["INTUR", "ORTI"]:
        dest = staging / societa
        logger.info(f"rclone sync ingresso/movimenti_contabili/{societa} → {dest}")
        try:
            rclone_sync(f"ingresso/movimenti_contabili/{societa}", dest)
            logger.info(f"  {societa}: sync OK")
        except RcloneError as e:
            logger.error(f"rclone error: {e}")


def load_hashes_bq(bq_client, societa_id: str, logger: logging.Logger) -> set:
    try:
        result = bq_client.query(
            f"SELECT hash_riga FROM `{BQ_TABLE}` WHERE societa_id = '{societa_id}'"
        ).result()
        hashes = {row.hash_riga for row in result}
        logger.info(f"  Hashes BQ esistenti {societa_id}: {len(hashes)}")
        return hashes
    except Exception as e:
        logger.warning(f"  Impossibile caricare hashes BQ ({societa_id}): {e}")
        return set()


def write_to_bq(rows: list[dict], bq_client, logger: logging.Logger):
    if not rows:
        return
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = bq_client.load_table_from_json(rows, BQ_TABLE, job_config=job_config)
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
    else:
        logger.info(f"  BQ: {len(rows)} righe → {BQ_TABLE}")


def write_to_csv(rows: list[dict], csv_path: Path, logger: logging.Logger):
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if csv_path.exists():
        with open(csv_path, newline="") as f:
            existing = {r["hash_riga"] for r in csv.DictReader(f)}
    new_rows = [r for r in rows if r["hash_riga"] not in existing]
    if not new_rows:
        logger.info("  CSV: nessuna nuova riga")
        return
    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FACT_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    logger.info(f"  CSV: {len(new_rows)} righe → {csv_path.name}")


def delete_period_bq(
    bq_client, societa_id: str, min_date: str, max_date: str, logger: logging.Logger
) -> int:
    """DELETE rows for (societa, date range). Returns number of rows deleted."""
    q = f"""
    DELETE FROM `{BQ_TABLE}`
    WHERE societa_id = @societa
      AND data_registrazione BETWEEN @min_d AND @max_d
    """
    job = bq_client.query(
        q,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa_id),
                bigquery.ScalarQueryParameter("min_d", "DATE", min_date),
                bigquery.ScalarQueryParameter("max_d", "DATE", max_date),
            ]
        ),
    )
    job.result()
    deleted = job.num_dml_affected_rows or 0
    logger.info(
        f"  DELETE {societa_id} [{min_date}..{max_date}]: {deleted} righe rimosse"
    )
    return deleted


def process_societa(
    societa_id: str,
    files: list[Path],
    datahub: Path | None,
    bq_client,
    dry_run: bool,
    replace: bool,
    raw_object_id: str | None,
    logger: logging.Logger,
):
    """Parse files for one societa and write to f_movimenti_contabili.

    raw_object_id contract (lineage FK):
      - None        → legacy/manual ingest, raw_object_id stays NULL on every row.
      - <id>        → stamped on every row (set after parse, before write/dedup),
                      lands in f_movimenti_contabili.raw_object_id and links
                      back to f_raw_objects (provenance verifiable end-to-end).
    """
    if raw_object_id:
        logger.info(
            f"  lineage raw_object_id: {raw_object_id} (will be stamped on each row)"
        )
    all_rows = []
    for f in files:
        if f.suffix.lower() == ".xlsx":
            rows = parse_file_xlsx(f, societa_id, logger)
        else:
            rows = parse_file(f, societa_id, logger)
        all_rows.extend(rows)

    if not all_rows:
        logger.info(f"  {societa_id}: nessuna riga")
        return

    if raw_object_id:
        for row in all_rows:
            row["raw_object_id"] = raw_object_id

    logger.info(f"  {societa_id}: {len(all_rows)} righe totali")

    if dry_run:
        return

    if replace:
        # SNAPSHOT-by-period semantics: delete the date range covered by the file,
        # then insert all rows. Idempotent regardless of parser/hash scheme.
        dates = [r["data_registrazione"] for r in all_rows if r["data_registrazione"]]
        min_date, max_date = min(dates), max(dates)
        logger.info(f"  {societa_id}: replace mode, range {min_date}..{max_date}")
        delete_period_bq(bq_client, societa_id, min_date, max_date, logger)
        new_rows = all_rows
    else:
        existing = load_hashes_bq(bq_client, societa_id, logger)
        new_rows = [r for r in all_rows if r["hash_riga"] not in existing]
        logger.info(
            f"  {societa_id}: {len(new_rows)} nuove, {len(all_rows) - len(new_rows)} già presenti"
        )

    write_to_bq(new_rows, bq_client, logger)

    if datahub:
        csv_path = datahub / "fatti" / "f_movimenti_contabili.csv"
        write_to_csv(new_rows, csv_path, logger)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Lista movimenti contabili Esolver → f_movimenti_contabili"
    )
    parser.add_argument("--datahub", help="Path to datahub root")
    parser.add_argument(
        "--staging",
        help="Local staging dir (default: ~/.cache/hotelops/movimenti_staging)",
    )
    parser.add_argument("--file", help="Single XLS or XLSX file to ingest")
    parser.add_argument(
        "--societa", choices=["INTUR", "ORTI"], help="Società (required with --file)"
    )
    parser.add_argument("--no-sync", action="store_true", help="Skip rclone sync")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="SNAPSHOT mode: DELETE rows in the file's date range before insert (true idempotency)",
    )
    parser.add_argument(
        "--raw-object-id",
        help="Lineage raw_object_id (from promote subprocess contract). "
        "When provided, stamped on every row written to "
        "f_movimenti_contabili.raw_object_id (FK to f_raw_objects).",
    )
    args = parser.parse_args()

    logger = setup_logger()

    if args.raw_object_id and not args.file:
        logger.error("--raw-object-id supportato solo con --file")
        sys.exit(1)

    # Single file mode
    if args.file:
        if not args.societa:
            filepath = Path(args.file)
            args.societa = infer_societa(filepath)
            if not args.societa:
                logger.error("--societa richiesto (INTUR o ORTI)")
                sys.exit(1)
        files_by_societa = {args.societa: [Path(args.file)]}
    else:
        # Multi-file mode: sync + process staging
        staging = Path(args.staging) if args.staging else STAGING_DEFAULT
        if not args.no_sync:
            sync_from_drive(staging, logger)
        files_by_societa = {}
        for societa in ["INTUR", "ORTI"]:
            societa_dir = staging / societa
            if societa_dir.exists():
                xls_files = (
                    list(societa_dir.glob("*.XLS"))
                    + list(societa_dir.glob("*.xls"))
                    + list(societa_dir.glob("*.XLSX"))
                    + list(societa_dir.glob("*.xlsx"))
                )
                if xls_files:
                    files_by_societa[societa] = xls_files

    if not files_by_societa:
        logger.warning("Nessun file trovato")
        return

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        bq_client = None
    else:
        if not HAS_BQ:
            logger.error("google-cloud-bigquery non installato")
            sys.exit(1)
        bq_client = get_client()

    datahub = Path(args.datahub) if args.datahub else None

    for societa_id, files in files_by_societa.items():
        logger.info(f"=== {societa_id} ===")
        process_societa(
            societa_id,
            files,
            datahub,
            bq_client,
            args.dry_run,
            args.replace,
            args.raw_object_id,
            logger,
        )

    logger.info("DONE")


if __name__ == "__main__":
    main()
