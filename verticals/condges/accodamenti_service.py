from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

from verticals.condges.cassa_giornaliera import run_accodamenti_to_excel
from core.bq.client import get_client
from ingest.banca.ingest_accodamenti import BQ_TABLE, parse_and_transform, write_to_bq

logger = logging.getLogger(__name__)


@dataclass
class BatchPreview:
    input_dir: Path
    txt_files: int
    parsed_rows: int
    candidate_hashes: int
    existing_hashes: int
    new_rows: int
    min_date: str | None
    max_date: str | None


def _collect_txt_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.rglob("*.txt")) + sorted(input_dir.rglob("*.TXT"))


def parse_rows_from_folder(input_dir: Path, societa: str = "INTUR") -> list[dict]:
    rows: list[dict] = []
    for filepath in _collect_txt_files(input_dir):
        rel_path = str(filepath.relative_to(input_dir))
        rows.extend(
            parse_and_transform(
                path=filepath,
                societa=societa,
                logger=logger,
                rel_path=rel_path,
            )
        )
    return rows


def _existing_hashes(candidate_hashes: list[str]) -> set[str]:
    if not candidate_hashes:
        return set()

    client = get_client()
    found: set[str] = set()
    chunk_size = 10_000

    for i in range(0, len(candidate_hashes), chunk_size):
        chunk = candidate_hashes[i : i + chunk_size]
        job = client.query(
            f"""
            SELECT hash_riga
            FROM `{BQ_TABLE}`
            WHERE hash_riga IN UNNEST(@hashes)
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("hashes", "STRING", chunk)
                ]
            ),
        )
        found.update(r.hash_riga for r in job.result())
    return found


def preview_folder(input_dir: Path, societa: str = "INTUR") -> tuple[BatchPreview, list[dict], list[dict]]:
    txt_files = _collect_txt_files(input_dir)
    rows = parse_rows_from_folder(input_dir, societa=societa)

    hashes = [r["hash_riga"] for r in rows]
    existing = _existing_hashes(hashes)
    new_rows = [r for r in rows if r["hash_riga"] not in existing]

    dates = [r["data_registrazione"] for r in rows if r.get("data_registrazione")]
    preview = BatchPreview(
        input_dir=input_dir,
        txt_files=len(txt_files),
        parsed_rows=len(rows),
        candidate_hashes=len(set(hashes)),
        existing_hashes=len(existing),
        new_rows=len(new_rows),
        min_date=min(dates) if dates else None,
        max_date=max(dates) if dates else None,
    )
    return preview, rows, new_rows


def ingest_rows(new_rows: list[dict]) -> int:
    if not new_rows:
        return 0
    write_to_bq(new_rows, get_client(), logger)
    return len(new_rows)


def current_watermark() -> str | None:
    client = get_client()
    row = next(
        iter(
            client.query(
                f"SELECT MAX(data_registrazione) AS max_data FROM `{BQ_TABLE}`"
            ).result()
        ),
        None,
    )
    if row is None or row.max_data is None:
        return None
    return row.max_data.strftime("%Y-%m-%d")


def generate_excel_from_folder(input_dir: Path, output_path: Path) -> dict:
    return run_accodamenti_to_excel(input_dir, output_path)


def generate_cumulative_excel_from_bq(start_date: date, output_path: Path) -> dict:
    """Export cumulativo da f_accodamenti a partire da una data scelta utente."""
    client = get_client()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sql_raw = f"""
    SELECT
      data_registrazione,
      business_unit_id,
      descrizione,
      importo,
      importo_dare,
      importo_avere,
      centro_imputazione,
      documento,
      file_sorgente,
      hash_riga
    FROM `{BQ_TABLE}`
    WHERE data_registrazione >= @start_date
    ORDER BY data_registrazione, business_unit_id, file_sorgente, hash_riga
    """
    raw_job = client.query(
        sql_raw,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "start_date", "DATE", start_date.isoformat()
                )
            ]
        ),
    )
    raw_df = raw_job.to_dataframe()

    if raw_df.empty:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            pd.DataFrame(
                [{"note": f"Nessun dato in f_accodamenti da {start_date.isoformat()}"}]
            ).to_excel(writer, index=False, sheet_name="Info")
        return {"output": str(output_path), "rows": 0, "start_date": start_date.isoformat()}

    sql_daily = f"""
    SELECT
      data_registrazione,
      business_unit_id,
      COUNT(*) AS righe,
      ROUND(SUM(importo), 2) AS importo_netto,
      ROUND(SUM(importo_dare), 2) AS totale_dare,
      ROUND(SUM(importo_avere), 2) AS totale_avere
    FROM `{BQ_TABLE}`
    WHERE data_registrazione >= @start_date
    GROUP BY data_registrazione, business_unit_id
    ORDER BY data_registrazione, business_unit_id
    """
    daily_df = client.query(
        sql_daily,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "start_date", "DATE", start_date.isoformat()
                )
            ]
        ),
    ).to_dataframe()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        daily_df.to_excel(writer, index=False, sheet_name="Riepilogo da BQ")
        raw_df.to_excel(writer, index=False, sheet_name="Dettaglio da BQ")

    return {
        "output": str(output_path),
        "rows": int(len(raw_df)),
        "start_date": start_date.isoformat(),
    }
