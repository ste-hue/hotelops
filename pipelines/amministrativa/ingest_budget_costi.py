#!/usr/bin/env python3
"""
Budget costi fissi + personale loader.

Reads MAPPATURA DEI COSTI xlsx → BigQuery:
  - d_budget_costi_fissi  (budget_F_INTUR + budget_F_ORTI sheets)
  - d_personale_mensile   (Personale sheet)

NOTE: covers only COSTI FISSI (Tipo='F'). Variable costs (materie prime, OTA
commissions, laundry, etc.) are not in this file — they vary with occupancy
and come from corrispettivi + supplier invoices.

Usage:
    python -m pipelines.amministrativa.ingest_budget_costi \\
        --file "/path/to/MAPPATURA DEI COSTI_v_2.xlsx" \\
        --dry-run
    python -m pipelines.amministrativa.ingest_budget_costi \\
        --file "/path/to/MAPPATURA DEI COSTI_v_2.xlsx"
"""

import argparse
import logging
import sys
from pathlib import Path

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from google.cloud import bigquery
    HAS_BQ = True
except ImportError:
    HAS_BQ = False

BQ_PROJECT = "hotelops-suite"
BQ_BUDGET_TABLE = f"{BQ_PROJECT}.hotelops.d_budget_costi_fissi"
BQ_PERSONALE_TABLE = f"{BQ_PROJECT}.hotelops.d_personale_mensile"

DEFAULT_SOURCE = Path(
    "/Users/stefanodellapietra/Desktop/WORK/artifacts/MAPPATURA DEI COSTI_v_2.xlsx"
)

MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]

BQ_SCHEMA_BUDGET = [
    bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("codice_conto", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("descrizione", "STRING"),
    bigquery.SchemaField("tipo", "STRING"),           # F=fisso
    bigquery.SchemaField("actuals_2025", "FLOAT64"),
    bigquery.SchemaField("budget_2026", "FLOAT64"),
    bigquery.SchemaField("hotel", "FLOAT64"),
    bigquery.SchemaField("residence", "FLOAT64"),
    bigquery.SchemaField("cvm", "FLOAT64"),
    bigquery.SchemaField("spiaggia", "FLOAT64"),
    bigquery.SchemaField("hq", "FLOAT64"),
] if HAS_BQ else []

BQ_SCHEMA_PERSONALE = [
    bigquery.SchemaField("divisione", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("anno", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("mese", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("mese_num", "INTEGER"),
    bigquery.SchemaField("importo", "FLOAT64"),
] if HAS_BQ else []


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_budget_costi")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def v(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    return 0.0


def parse_budget_sheet(ws, societa_id: str, logger: logging.Logger) -> list[dict]:
    """Parse budget_F_INTUR or budget_F_ORTI sheet."""
    rows = []
    headers = None

    for row in ws.iter_rows(values_only=True):
        if headers is None:
            headers = [str(c).strip().upper() if c else "" for c in row]
            continue

        cod = row[0]
        if not cod or not isinstance(cod, str) or "." not in cod:
            continue  # skip header groups and subtotals

        descrizione = str(row[1]).strip() if row[1] else ""
        tipo = str(row[3]).strip() if row[3] else "F"
        actuals_2025 = v(row[2])
        budget_2026 = v(row[4])

        # BU columns: HOTEL, RESIDENCE, CASA VACANZA, SPIAGGIA, [PM], HQ
        # Position varies by sheet — find by header name
        col_idx = {h: i for i, h in enumerate(headers)}

        hotel = v(row[col_idx.get("HOTEL", 5)])
        residence = v(row[col_idx.get("RESIDENCE", 6)])
        cvm = v(row[col_idx.get("CASA VACANZA", 7)])
        spiaggia = v(row[col_idx.get("SPIAGGIA", 8)])
        hq = v(row[col_idx.get("HQ", 9)])

        rows.append({
            "societa_id": societa_id,
            "codice_conto": cod.strip(),
            "descrizione": descrizione,
            "tipo": tipo,
            "actuals_2025": actuals_2025,
            "budget_2026": budget_2026,
            "hotel": hotel,
            "residence": residence,
            "cvm": cvm,
            "spiaggia": spiaggia,
            "hq": hq,
        })

    logger.info(f"  {societa_id}: {len(rows)} righe budget")
    return rows


def parse_personale_sheet(ws, anno: int, logger: logging.Logger) -> list[dict]:
    """Parse Personale sheet → one row per divisione per mese."""
    rows = []
    headers_found = False

    for row in ws.iter_rows(values_only=True):
        if not any(v is not None for v in row):
            continue
        if str(row[0] or "").strip() == "Division":
            headers_found = True
            continue
        if not headers_found:
            continue

        divisione = str(row[0]).strip()
        if not divisione or divisione.startswith("TOTALE"):
            continue

        for m_idx, mese in enumerate(MESI):
            val = row[m_idx + 1]
            if isinstance(val, (int, float)):
                rows.append({
                    "divisione": divisione,
                    "anno": anno,
                    "mese": f"{anno}-{m_idx+1:02d}",
                    "mese_num": m_idx + 1,
                    "importo": float(val),
                })

    logger.info(f"  Personale: {len(rows)} righe ({anno})")
    return rows


def load_to_bq(rows: list[dict], table_id: str, schema, bq_client, logger: logging.Logger):
    if not rows:
        logger.warning(f"Nessuna riga da caricare in {table_id}")
        return

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = bq_client.load_table_from_json(rows, table_id, job_config=job_config)
    job.result()

    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
        sys.exit(1)

    logger.info(f"  {table_id}: {len(rows)} righe caricate (WRITE_TRUNCATE)")


def main():
    parser = argparse.ArgumentParser(description="Load budget costi fissi + personale → BigQuery")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_SOURCE),
        help=f"Path to MAPPATURA DEI COSTI xlsx (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument("--anno-personale", type=int, default=2026,
                        help="Anno budget personale (default: 2026)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logger = setup_logger()
    filepath = Path(args.file)
    if not filepath.exists():
        logger.error(f"File non trovato: {filepath}")
        sys.exit(1)

    if not HAS_OPENPYXL:
        logger.error("openpyxl non installato")
        sys.exit(1)

    wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)

    # Parse budget sheets
    budget_rows = []
    budget_rows += parse_budget_sheet(wb["budget_F_INTUR"], "INTUR", logger)
    budget_rows += parse_budget_sheet(wb["budget_F_ORTI"], "ORTI", logger)

    # Parse personale
    personale_rows = parse_personale_sheet(wb["Personale"], args.anno_personale, logger)

    wb.close()

    # Summary
    tot_intur = sum(r["actuals_2025"] for r in budget_rows if r["societa_id"] == "INTUR")
    tot_orti = sum(r["actuals_2025"] for r in budget_rows if r["societa_id"] == "ORTI")
    tot_personale = sum(r["importo"] for r in personale_rows)
    logger.info(f"Budget fissi 2025: INTUR={tot_intur:,.0f}€  ORTI={tot_orti:,.0f}€")
    logger.info(f"Personale {args.anno_personale} totale annuo: {tot_personale:,.0f}€")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = bigquery.Client(project=BQ_PROJECT)
    load_to_bq(budget_rows, BQ_BUDGET_TABLE, BQ_SCHEMA_BUDGET, bq_client, logger)
    load_to_bq(personale_rows, BQ_PERSONALE_TABLE, BQ_SCHEMA_PERSONALE, bq_client, logger)

    logger.info("DONE")


if __name__ == "__main__":
    main()
