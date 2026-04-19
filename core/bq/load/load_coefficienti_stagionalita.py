#!/usr/bin/env python3
"""
Seasonality coefficient computation pipeline.

Reads historical revenue data from BigQuery (f_ricavi_storici), computes
monthly seasonality coefficients per business unit, and writes them to
d_coefficienti_stagionalita (WRITE_TRUNCATE — full refresh each run).

The coefficient for a given BU × month is:
    avg_revenue(BU, month) / (annual_total(BU) / 12)

So coefficiente = 1.0 for an average month, >1 for peak, <1 for off-season.
The sum of 12 coefficients per BU is always 12.0.

Company-wide (HQ) coefficients are the revenue-weighted average across all BUs.

Usage:
    python -m core.bq.load.load_coefficienti_stagionalita
    python -m core.bq.load.load_coefficienti_stagionalita --societa ORTI
    python -m core.bq.load.load_coefficienti_stagionalita --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.bq.client import get_client
from core.config import D_COEFFICIENTI_STAGIONALITA, PROJECT
from core.schemas import CoefficienteStagionalitaRow, make_hash, validate_batch

# Source table for historical revenue
F_RICAVI_STORICI = f"{PROJECT}.hotelops.f_ricavi_storici"

BQ_SCHEMA = (
    [
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("business_unit_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("mese", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("coefficiente", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("fonte", "STRING"),
        bigquery.SchemaField("hash_riga", "STRING"),
        bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_coefficienti_stagionalita")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        log.addHandler(h)
    return log


# ── Pure computation ────────────────────────────────────────────────────────


def compute_coefficients(
    ricavi: list[dict],
    societa_id: str,
    fonte: str,
) -> list[dict]:
    """Compute seasonality coefficients from historical revenue data.

    Args:
        ricavi: list of dicts with keys: societa_id, business_unit_id,
                anno, mese, importo_entrate
        societa_id: company to label output rows with
        fonte: provenance tag (e.g. "RICAVI_STORICI")

    Returns:
        list of row dicts ready for BQ upload, one per BU x month (+ HQ).
    """
    now = datetime.now(timezone.utc).isoformat()

    # Accumulate per BU per month across years
    # bu_month_totals[bu][mese] = list of importo values (one per year)
    bu_years: dict[str, set[int]] = defaultdict(set)
    bu_month_totals: dict[str, dict[int, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    for r in ricavi:
        bu = r["business_unit_id"]
        if bu == "HQ":
            continue  # Skip HQ rows — we compute HQ as weighted average
        mese = int(r["mese"])
        anno = int(r["anno"])
        importo = float(r["importo_entrate"])
        bu_month_totals[bu][mese] += importo
        bu_years[bu].add(anno)

    rows: list[dict] = []

    # Per-BU coefficients
    bu_annual_totals: dict[str, float] = {}  # for HQ weighting
    bu_monthly_avg: dict[str, dict[int, float]] = {}  # for HQ weighting

    for bu in sorted(bu_month_totals.keys()):
        n_years = len(bu_years[bu]) if bu_years[bu] else 1
        monthly_avg: dict[int, float] = {}
        for m in range(1, 13):
            monthly_avg[m] = bu_month_totals[bu].get(m, 0.0) / n_years

        annual_total = sum(monthly_avg.values())
        bu_annual_totals[bu] = annual_total
        bu_monthly_avg[bu] = monthly_avg
        grand_monthly_avg = annual_total / 12.0

        for m in range(1, 13):
            if grand_monthly_avg == 0:
                coeff = 1.0  # flat if zero revenue
            else:
                coeff = monthly_avg[m] / grand_monthly_avg

            rows.append(
                {
                    "societa_id": societa_id,
                    "business_unit_id": bu,
                    "mese": m,
                    "coefficiente": round(coeff, 6),
                    "fonte": fonte,
                    "hash_riga": make_hash(societa_id, bu, str(m)),
                    "data_caricamento": now,
                }
            )

    # Company-wide (HQ) coefficients: revenue-weighted average across BUs
    total_revenue = sum(bu_annual_totals.values())
    for m in range(1, 13):
        if total_revenue == 0 or not bu_monthly_avg:
            coeff = 1.0
        else:
            weighted_sum = 0.0
            for bu, annual in bu_annual_totals.items():
                weight = annual / total_revenue
                bu_grand_avg = annual / 12.0
                if bu_grand_avg == 0:
                    bu_coeff = 1.0
                else:
                    bu_coeff = bu_monthly_avg[bu][m] / bu_grand_avg
                weighted_sum += weight * bu_coeff
            coeff = weighted_sum

        rows.append(
            {
                "societa_id": societa_id,
                "business_unit_id": "HQ",
                "mese": m,
                "coefficiente": round(coeff, 6),
                "fonte": fonte,
                "hash_riga": make_hash(societa_id, "HQ", str(m)),
                "data_caricamento": now,
            }
        )

    return rows


# ── BQ fetch ────────────────────────────────────────────────────────────────


def fetch_ricavi_from_bq(client: "bigquery.Client") -> list[dict]:
    """Fetch historical revenue data from f_ricavi_storici."""
    query = f"""
        SELECT societa_id, business_unit_id, anno, mese, importo_entrate
        FROM `{F_RICAVI_STORICI}`
    """
    result = client.query(query).result()
    return [dict(row) for row in result]


def fetch_seasonality_coefficients(
    societa_id: str = "ORTI",
    business_unit_id: str = "HQ",
) -> dict[int, float]:
    """Fetch coefficients from BQ. Returns {mese: coefficiente}.

    Falls back to flat 1.0 for all months if table is missing or empty.
    """
    flat = {m: 1.0 for m in range(1, 13)}

    if not HAS_BQ:
        return flat

    try:
        client = get_client()
        query = f"""
            SELECT mese, coefficiente
            FROM `{D_COEFFICIENTI_STAGIONALITA}`
            WHERE societa_id = @societa_id
              AND business_unit_id = @business_unit_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa_id", "STRING", societa_id),
                bigquery.ScalarQueryParameter(
                    "business_unit_id", "STRING", business_unit_id
                ),
            ]
        )
        result = client.query(query, job_config=job_config).result()
        coeffs = {int(row.mese): float(row.coefficiente) for row in result}
        return coeffs if coeffs else flat
    except Exception:
        return flat


# ── Quality summary ─────────────────────────────────────────────────────────


def print_coefficient_table(rows: list[dict], logger: logging.Logger) -> None:
    """Print a summary table of BU x month coefficients."""
    # Group by BU
    bu_coeffs: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rows:
        bu_coeffs[r["business_unit_id"]][r["mese"]] = r["coefficiente"]

    # Header
    header = (
        f"{'BU':<12s}"
        + "".join(f"{'M' + str(m):>7s}" for m in range(1, 13))
        + f"{'SUM':>8s}"
    )
    logger.info("")
    logger.info("Seasonality Coefficients:")
    logger.info("-" * len(header))
    logger.info(header)
    logger.info("-" * len(header))

    for bu in sorted(bu_coeffs.keys()):
        coeffs = bu_coeffs[bu]
        line = f"{bu:<12s}"
        total = 0.0
        for m in range(1, 13):
            c = coeffs.get(m, 0.0)
            total += c
            line += f"{c:7.3f}"
        line += f"{total:8.3f}"
        logger.info(line)

    logger.info("-" * len(header))


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute seasonality coefficients → d_coefficienti_stagionalita"
    )
    parser.add_argument(
        "--societa",
        default="ORTI",
        choices=["ORTI", "INTUR"],
        help="Company (default: ORTI)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and display, no BQ write",
    )
    args = parser.parse_args()

    logger = setup_logger()
    logger.info(f"Seasonality coefficients for {args.societa}")

    if not HAS_BQ:
        logger.error("google-cloud-bigquery not installed")
        sys.exit(1)

    client = get_client()

    # Fetch revenue data
    logger.info(f"Fetching revenue data from {F_RICAVI_STORICI}...")
    ricavi = fetch_ricavi_from_bq(client)
    logger.info(f"  {len(ricavi)} revenue rows fetched")

    if not ricavi:
        logger.warning("No revenue data found — nothing to compute")
        return

    # Compute
    rows = compute_coefficients(ricavi, args.societa, fonte="RICAVI_STORICI")

    # Validate
    validate_batch(rows, CoefficienteStagionalitaRow, context="stagionalita")
    logger.info(f"  {len(rows)} coefficient rows computed and validated")

    # Summary
    print_coefficient_table(rows, logger)

    if args.dry_run:
        logger.info("DRY RUN — no BQ write")
        return

    # Write to BQ
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(
        rows, D_COEFFICIENTI_STAGIONALITA, job_config=job_config
    )
    job.result()

    if job.errors:
        logger.error(f"BQ load errors: {job.errors}")
        sys.exit(1)

    logger.info(
        f"d_coefficienti_stagionalita loaded: {len(rows)} rows → {D_COEFFICIENTI_STAGIONALITA}"
    )
    logger.info("DONE")


if __name__ == "__main__":
    main()
