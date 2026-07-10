"""
Generate manifest.yaml — a metadata catalog of all BQ tables.

Each table gets: row count, freshness (date range), sources, and
per-column stats (type, distinct values or samples, min/max).

Usage:
    from core.bq.manifest import generate_manifest
    manifest = generate_manifest()  # returns dict
    generate_manifest(output_path="core/bq/manifest.yaml")  # writes file
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import yaml

from core.bq.client import get_client
from core.config import PROJECT, DATASET

log = logging.getLogger(__name__)

# Tables to catalog (all facts + dimensions from config.py)
TABLES = [
    "f_banche_movimenti",
    "f_movimenti_contabili",
    "f_budget_mensile",
    "f_piano_finanziario_input",
    "f_consumi_economato",
    "f_coperti_giornalieri",
    "f_bilancino",
    "f_partite_aperte_fornitori",
    "f_saldi_banca_snapshot",
    "f_saldi_banca_chiusura_mensile",
    "f_accodamenti",
    "f_ricavi_storici",
    "f_chiusura_mensile",
    "f_pf_rotazioni",
    "d_voci_piano_finanziario",
    "d_piano_conti",
    "d_categorie_conti",
    "d_fornitori",
    "d_anagrafica_fornitori",
    "d_mapping_piano_finanziario",
    "d_coefficienti_stagionalita",
    "d_budget_costi_fissi",
    "d_personale_mensile",
    "d_periodi_apertura",
]

# Columns likely to hold date/freshness info (checked in order)
DATE_CANDIDATES = [
    "data_registrazione",
    "data_operazione",
    "data_caricamento",
    "data_ingresso",
    "data_snapshot",
    "data_servizio",
    "data_documento",
]

# Columns likely to hold source file info
SOURCE_CANDIDATES = ["file_sorgente", "fonte"]

# Thresholds for value listing
VALUES_THRESHOLD = 30  # list all values if distinct <= this
SAMPLE_THRESHOLD = 100  # show top-N if distinct > VALUES_THRESHOLD
SAMPLE_SIZE = 10


def _column_stats(
    col_name: str,
    col_type: str,
    distinct: int,
    values: list | None,
    sample: list | None,
    min_val,
    max_val,
) -> dict:
    """Build stats dict for a single column."""
    stats: dict = {"type": col_type}

    if col_type in ("FLOAT", "INTEGER", "NUMERIC"):
        if min_val is not None:
            stats["min"] = min_val
        if max_val is not None:
            stats["max"] = max_val
        if distinct is not None:
            stats["distinct"] = distinct
        return stats

    if col_type in ("DATE", "TIMESTAMP", "DATETIME"):
        if min_val is not None:
            stats["min"] = str(min_val) if not isinstance(min_val, str) else min_val
        if max_val is not None:
            stats["max"] = str(max_val) if not isinstance(max_val, str) else max_val
        if distinct is not None:
            stats["distinct"] = distinct
        return stats

    # STRING columns
    if distinct is not None:
        stats["distinct"] = distinct
    if distinct is not None and distinct <= VALUES_THRESHOLD and values:
        stats["values"] = values
    elif sample:
        stats["sample"] = sample

    return stats


def _get_client():
    return get_client()


def _introspect_table(client, table_name: str) -> dict:
    """Query BQ for metadata about a single table."""
    full_id = f"{PROJECT}.{DATASET}.{table_name}"

    # 1. Get row count and schema
    try:
        table_ref = client.get_table(full_id)
    except Exception as e:
        log.warning("Table %s not found: %s", table_name, e)
        return {"error": f"not found: {e}"}

    row_count = table_ref.num_rows
    schema = [(f.name, f.field_type) for f in table_ref.schema]

    result: dict = {
        "rows": row_count,
        "columns": {},
    }

    if row_count == 0:
        for col_name, col_type in schema:
            result["columns"][col_name] = {"type": col_type}
        return result

    # 2. Find date column for freshness
    col_names = [c[0] for c in schema]
    date_col = None
    for candidate in DATE_CANDIDATES:
        if candidate in col_names:
            date_col = candidate
            break

    if date_col:
        q = f"SELECT MIN({date_col}) AS mn, MAX({date_col}) AS mx FROM `{full_id}`"
        for row in client.query(q).result():
            mn = row.mn
            mx = row.mx
            if mn is not None:
                result["freshness"] = {
                    "date_column": date_col,
                    "min": str(mn.date() if isinstance(mn, datetime) else mn),
                    "max": str(mx.date() if isinstance(mx, datetime) else mx),
                }

    # 3. Find sources
    for src_col in SOURCE_CANDIDATES:
        if src_col in col_names:
            q = f"SELECT DISTINCT {src_col} AS val FROM `{full_id}` WHERE {src_col} IS NOT NULL ORDER BY val"
            sources = [row.val for row in client.query(q).result()]
            if sources:
                result["sources"] = {src_col: sources}
            break

    # 4. Per-column stats
    for col_name, col_type in schema:
        if col_name in ("hash_riga",):
            result["columns"][col_name] = {"type": col_type}
            continue

        if col_type in ("FLOAT", "INTEGER", "NUMERIC"):
            q = f"""
            SELECT
              COUNT(DISTINCT {col_name}) AS dist,
              MIN({col_name}) AS mn,
              MAX({col_name}) AS mx
            FROM `{full_id}`
            """
            for row in client.query(q).result():
                result["columns"][col_name] = _column_stats(
                    col_name,
                    col_type,
                    distinct=row.dist,
                    values=None,
                    sample=None,
                    min_val=row.mn,
                    max_val=row.mx,
                )

        elif col_type in ("DATE", "TIMESTAMP", "DATETIME"):
            q = f"""
            SELECT
              COUNT(DISTINCT {col_name}) AS dist,
              MIN({col_name}) AS mn,
              MAX({col_name}) AS mx
            FROM `{full_id}`
            """
            for row in client.query(q).result():
                mn = row.mn
                mx = row.mx
                result["columns"][col_name] = _column_stats(
                    col_name,
                    col_type,
                    distinct=row.dist,
                    values=None,
                    sample=None,
                    min_val=str(mn.date() if isinstance(mn, datetime) else mn)
                    if mn
                    else None,
                    max_val=str(mx.date() if isinstance(mx, datetime) else mx)
                    if mx
                    else None,
                )

        elif col_type == "STRING":
            q = f"SELECT COUNT(DISTINCT {col_name}) AS dist FROM `{full_id}`"
            dist = 0
            for row in client.query(q).result():
                dist = row.dist

            values = None
            sample = None
            if dist <= VALUES_THRESHOLD:
                q = f"SELECT DISTINCT {col_name} AS val FROM `{full_id}` WHERE {col_name} IS NOT NULL ORDER BY val"
                values = [row.val for row in client.query(q).result()]
            elif dist <= SAMPLE_THRESHOLD:
                q = f"""
                SELECT {col_name} AS val, COUNT(*) AS n
                FROM `{full_id}` WHERE {col_name} IS NOT NULL
                GROUP BY {col_name} ORDER BY n DESC LIMIT {SAMPLE_SIZE}
                """
                values = [row.val for row in client.query(q).result()]
            else:
                q = f"""
                SELECT {col_name} AS val, COUNT(*) AS n
                FROM `{full_id}` WHERE {col_name} IS NOT NULL
                GROUP BY {col_name} ORDER BY n DESC LIMIT 5
                """
                sample = [row.val for row in client.query(q).result()]

            result["columns"][col_name] = _column_stats(
                col_name,
                col_type,
                distinct=dist,
                values=values,
                sample=sample,
                min_val=None,
                max_val=None,
            )

        elif col_type == "BOOLEAN":
            result["columns"][col_name] = {"type": col_type}
        else:
            result["columns"][col_name] = {"type": col_type}

    return result


def _yaml_representer_date(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data))


def generate_manifest(
    output_path: str | Path | None = None,
    tables: list[str] | None = None,
) -> dict:
    """Generate manifest dict and optionally write to YAML file.

    Args:
        output_path: If given, write YAML to this path.
        tables: If given, only catalog these tables. Default: all TABLES.

    Returns:
        The manifest dict.
    """
    client = _get_client()
    target_tables = tables or TABLES

    manifest = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": PROJECT,
        "dataset": DATASET,
        "tables": {},
    }

    for table_name in target_tables:
        log.info("Introspecting %s ...", table_name)
        manifest["tables"][table_name] = _introspect_table(client, table_name)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Custom representer for date objects
        yaml.add_representer(date, _yaml_representer_date)

        with open(path, "w") as f:
            yaml.dump(
                manifest,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
        log.info("Manifest written to %s", path)

    return manifest
