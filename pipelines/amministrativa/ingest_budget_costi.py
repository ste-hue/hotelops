#!/usr/bin/env python3
"""
Budget 2026 — costi fissi + personale → BigQuery f_budget_mensile.

Fonti:
  - MAPPATURA DEI COSTI_v_2.xlsx  → costi fissi voce-per-voce (budget_F_ORTI,
    budget_F_INTUR): i valori nelle colonne BU sono i valori 2026 deliberati.
  - Incidenza_costi_personale.xlsx → foglio 'costi aggiornati': dati per
    dipendente con colonna SOCIETA' (ORTI/INTUR) e presenze mensili.

Output: f_budget_mensile (delete-insert per anno=2026, fonte IN (MAPPATURA, INCIDENZA))

Usage:
    python -m pipelines.amministrativa.ingest_budget_costi --dry-run
    python -m pipelines.amministrativa.ingest_budget_costi \\
        --mappatura "/path/to/MAPPATURA DEI COSTI_v_2.xlsx" \\
        --incidenza "/path/to/Incidenza_costi_personale.xlsx"
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
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

# ── Defaults ──────────────────────────────────────────────────────────────────

DATAHUB = Path("/Users/stefanodellapietra/Desktop/WORK/artifacts")
DEFAULT_MAPPATURA = DATAHUB / "MAPPATURA DEI COSTI_v_2.xlsx"
DEFAULT_INCIDENZA = DATAHUB / "Incidenza_costi_personale.xlsx"

# ── BigQuery ──────────────────────────────────────────────────────────────────

BQ_PROJECT     = "hotelops-suite"
BQ_TABLE       = f"{BQ_PROJECT}.hotelops.f_budget_mensile"
ANNO           = 2026
FONTI_GESTITE  = ("MAPPATURA", "INCIDENZA")

# ── Lookup: prefisso conto → (categoria_ce, tipo_costo) ──────────────────────

CONTO_TO_CAT: dict[str, tuple[str, str]] = {
    "47": ("Ricavi",                "IP"),
    "53": ("Ricavi Extra Gestione", "IP"),
    "55": ("Acquisti",              "V"),
    "57": ("Costi Produttivi",      "F"),
    "59": ("Costi Produttivi",      "F"),
    "61": ("Costi Amministrativi",  "F"),
    "63": ("Costi Commerciali",     "F"),
    "64": ("Costi Produttivi",      "F"),
    "65": ("Costi Produttivi",      "F"),
    "67": ("Costo del Personale",   "P"),
    "71": ("Oneri Tributari",       "F"),
    "75": ("Oneri Finanziari",      "X"),
}

# BU normalize
BU_NORMALIZE: dict[str, str] = {
    "HOTEL":        "HOTEL",
    "RESIDENCE":    "RESIDENCE",
    "CASA VACANZA": "CVM",
    "SPIAGGIA":     "LIDO",
    "PM":           "HQ",
    "HQ":           "HQ",
}

# Divisione personale → BU
DIVISION_TO_BU: dict[str, str] = {
    "MANAGEMENT":   "HQ",
    "AMM/ECO":      "HQ",
    "ROOM DIVISION":"HOTEL",
    "MANUTENZIONE": "HOTEL",
    "F&B":          "HOTEL",
    "SPIAGGIA":     "LIDO",
    "PROPRIETA'":   "HOTEL",
}

CONTO_PERSONALE = "67.01.01"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _v(x) -> float:
    """Coerce any cell value to float, returning 0.0 for None/NaN."""
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        import math
        return 0.0 if math.isnan(float(x)) else float(x)
    return 0.0


def _cat(codice: str) -> tuple[str, str]:
    prefix = codice.split(".")[0] if codice else ""
    return CONTO_TO_CAT.get(prefix, ("Costi Produttivi", "F"))


def _is_conto(val) -> bool:
    return isinstance(val, str) and "." in val


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_budget_costi")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
        log.addHandler(h)
    return log


# ── 1. Costi fissi da MAPPATURA ───────────────────────────────────────────────

def parse_budget_fissi(filepath: Path, logger: logging.Logger) -> list[dict]:
    """
    Reads budget_F_ORTI and budget_F_INTUR sheets.

    Column layout:
      [0] Cod. Conto  [1] Descrizione  [2] 2025  [3] Tipo  [4] 2026 (often None)
      [5..] BU columns: HOTEL, RESIDENCE, CASA VACANZA, SPIAGGIA, [PM,] HQ

    The BU columns hold the 2026 budget amounts (voce per voce).
    Monthly distribution: 1/12 uniform.
    """
    wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
    now = datetime.now(timezone.utc)
    records: list[dict] = []

    for sheet_name, societa in [("budget_F_INTUR", "INTUR"), ("budget_F_ORTI", "ORTI")]:
        if sheet_name not in wb.sheetnames:
            logger.warning(f"  Foglio {sheet_name} non trovato — skip")
            continue

        ws = wb[sheet_name]
        rows_raw = list(ws.iter_rows(values_only=True))
        if not rows_raw:
            continue

        # Build BU column positions from header row
        header = rows_raw[0]
        bu_cols: list[tuple[int, str]] = []
        for i, h in enumerate(header):
            if i <= 4 or not h or not isinstance(h, str):
                continue
            norm = BU_NORMALIZE.get(h.strip().upper())
            if norm:
                bu_cols.append((i, norm))

        conti_loaded = 0
        for row in rows_raw[1:]:
            if not row:
                continue
            if not _is_conto(row[0]):
                continue
            desc = str(row[1]).strip() if row[1] else ""
            if desc.lower().startswith(("subtotale", "totale")):
                continue

            codice       = row[0].strip()
            categoria_ce, tipo_costo = _cat(codice)

            # Sum BU columns → 2026 annual budget per BU
            bu_amounts: dict[str, float] = {}
            bu_sum = 0.0
            for col_i, bu_id in bu_cols:
                if col_i < len(row):
                    v = _v(row[col_i])
                    bu_amounts[bu_id] = bu_amounts.get(bu_id, 0.0) + v
                    bu_sum += v

            # col[4]: explicit 2026 total — rescale BU if it differs from bu_sum
            col4 = row[4] if len(row) > 4 else None
            total_2026 = _v(col4) if col4 is not None else 0.0
            if total_2026 > 0 and bu_sum > 0 and abs(total_2026 - bu_sum) > 0.5:
                scale = total_2026 / bu_sum
                bu_amounts = {bu: v * scale for bu, v in bu_amounts.items()}
                bu_sum = total_2026

            if bu_sum == 0:
                continue

            for bu_id, annual in bu_amounts.items():
                if annual == 0:
                    continue
                for mese in range(1, 13):
                    records.append({
                        "societa_id":       societa,
                        "anno":             ANNO,
                        "mese":             mese,
                        "codice_conto":     codice,
                        "descrizione":      desc,
                        "tipo_costo":       tipo_costo,
                        "categoria_ce":     categoria_ce,
                        "business_unit_id": bu_id,
                        "importo":          round(annual / 12, 4),
                        "fonte":            "MAPPATURA",
                        "data_caricamento": now.isoformat(),
                    })
            conti_loaded += 1

        logger.info(f"  {societa} ({sheet_name}): {conti_loaded} conti")

    wb.close()
    logger.info(f"  Costi fissi totale: {len(records)} righe mensili")
    return records


# ── 2. Personale da Incidenza ─────────────────────────────────────────────────

def parse_personale_incidenza(filepath: Path, logger: logging.Logger) -> list[dict]:
    """
    Reads 'costi aggiornati' sheet.

    Column layout:
      [0] SOCIETA'  [1] DIVISION  [2] REPARTO  [3] MANSIONE
      [4] COGNOME   [5] NOME
      [6..17] Presenze mensili Gen-Dic (frazioni: 0, 0.5, 1 …)
      [18] TOT  [19] Costo Mensile  [20] Costo Totale

    Monthly cost per employee = presence[m] * Costo_Mensile.
    Grouped by societa + division + mese.
    """
    wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
    now = datetime.now(timezone.utc)

    if "costi aggiornati" not in wb.sheetnames:
        logger.error("  Foglio 'costi aggiornati' non trovato")
        wb.close()
        return []

    ws = wb["costi aggiornati"]
    agg: dict[tuple[str, str, int], float] = defaultdict(float)
    emp_count = 0

    for row in ws.iter_rows(values_only=True):
        if not row or row[0] not in ("ORTI", "INTUR"):
            continue
        soc       = row[0]
        div       = str(row[1]).strip() if row[1] else "UNKNOWN"
        sal       = _v(row[19])   # Costo Mensile
        costo_tot = _v(row[20])   # Costo Totale (fallback quando presenze=None)
        if sal == 0 and costo_tot == 0:
            continue
        emp_count += 1

        monthly_total = 0.0
        for m_idx in range(12):
            cell = row[6 + m_idx]
            if cell is None:
                continue
            if isinstance(cell, str) and cell.strip() in ("—", "-", ""):
                continue
            presence = _v(cell)
            if presence > 0:
                amount = presence * sal
                agg[(soc, div, m_idx + 1)] += amount
                monthly_total += amount

        # Se presenze tutte None ma Costo Totale > 0: distribuzione 1/12 uniforme
        if monthly_total == 0 and costo_tot > 0:
            for m_idx in range(12):
                agg[(soc, div, m_idx + 1)] += costo_tot / 12

    wb.close()
    logger.info(f"  Personale: {emp_count} dipendenti")

    records: list[dict] = []
    annual_by_soc: dict[str, float] = defaultdict(float)

    for (soc, div, mese), importo in sorted(agg.items()):
        if importo == 0:
            continue
        div_key = div.upper().replace("\u2019", "'").replace("\u2018", "'")
        bu = DIVISION_TO_BU.get(div_key, "HQ")
        records.append({
            "societa_id":       soc,
            "anno":             ANNO,
            "mese":             mese,
            "codice_conto":     CONTO_PERSONALE,
            "descrizione":      f"Personale {div}",
            "tipo_costo":       "P",
            "categoria_ce":     "Costo del Personale",
            "business_unit_id": bu,
            "importo":          round(importo, 4),
            "fonte":            "INCIDENZA",
            "data_caricamento": now.isoformat(),
        })
        annual_by_soc[soc] += importo

    for soc, total in sorted(annual_by_soc.items()):
        n = sum(1 for r in records if r["societa_id"] == soc)
        logger.info(f"  Personale {soc}: {total:,.0f}€/anno  ({n} righe mensili)")

    logger.info(f"  Personale totale: {len(records)} righe mensili")
    return records


# ── 3. Quality summary ────────────────────────────────────────────────────────

def quality_summary(rows: list[dict], logger: logging.Logger) -> None:
    by_soc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        by_soc[r["societa_id"]][r["tipo_costo"]] += r["importo"]

    logger.info("═" * 52)
    logger.info("  QUALITY SUMMARY — f_budget_mensile")
    logger.info("═" * 52)
    for soc in sorted(by_soc):
        d = by_soc[soc]
        total = sum(d.values())
        logger.info(f"  {soc}")
        for t, label in [("F","Costi fissi"), ("V","Acquisti"), ("P","Personale"), ("X","Oneri fin.")]:
            if d.get(t, 0):
                logger.info(f"    {label:<14} ({t}) : {d[t]:>12,.0f} €/anno")
        logger.info(f"    {'─'*40}")
        logger.info(f"    Totale costi       : {total:>12,.0f} €/anno")
    logger.info("═" * 52)


# ── 4. BigQuery ───────────────────────────────────────────────────────────────

BQ_SCHEMA = [
    bigquery.SchemaField("societa_id",       "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("anno",             "INTEGER",   mode="REQUIRED"),
    bigquery.SchemaField("mese",             "INTEGER",   mode="REQUIRED"),
    bigquery.SchemaField("codice_conto",     "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("descrizione",      "STRING"),
    bigquery.SchemaField("tipo_costo",       "STRING"),
    bigquery.SchemaField("categoria_ce",     "STRING"),
    bigquery.SchemaField("business_unit_id", "STRING"),
    bigquery.SchemaField("importo",          "FLOAT64"),
    bigquery.SchemaField("fonte",            "STRING"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
] if HAS_BQ else []


def load_to_bq(rows: list[dict], bq_client, logger: logging.Logger) -> None:
    if not rows:
        logger.warning("Nessuna riga da caricare")
        return

    # Delete existing rows for this anno + fonti
    fonti_sql = ", ".join(f"'{f}'" for f in FONTI_GESTITE)
    bq_client.query(
        f"DELETE FROM `{BQ_TABLE}` WHERE anno = {ANNO} AND fonte IN ({fonti_sql})"
    ).result()
    logger.info(f"  Righe precedenti anno={ANNO} cancellate")

    job = bq_client.load_table_from_json(
        rows, BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
        sys.exit(1)
    logger.info(f"  {BQ_TABLE}: {len(rows)} righe caricate")


# ── 5. CSV dump ───────────────────────────────────────────────────────────────

FIELDS = [
    "societa_id", "anno", "mese", "codice_conto", "descrizione",
    "tipo_costo", "categoria_ce", "business_unit_id", "importo", "fonte",
]


def dump_csv(rows: list[dict], path: Path, logger: logging.Logger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    logger.info(f"  CSV: {path}  ({len(rows)} righe)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Budget 2026 costi fissi + personale → f_budget_mensile"
    )
    parser.add_argument("--mappatura", default=str(DEFAULT_MAPPATURA))
    parser.add_argument("--incidenza", default=str(DEFAULT_INCIDENZA))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    logger = setup_logger()

    if not HAS_OPENPYXL:
        logger.error("openpyxl non installato: pip install openpyxl")
        sys.exit(1)

    mappatura_path = Path(args.mappatura)
    incidenza_path = Path(args.incidenza)
    for p in (mappatura_path, incidenza_path):
        if not p.exists():
            logger.error(f"File non trovato: {p}")
            sys.exit(1)

    logger.info(f"Fonte costi fissi : {mappatura_path.name}")
    logger.info(f"Fonte personale   : {incidenza_path.name}")
    logger.info(f"Anno budget       : {ANNO}")

    fissi_rows = parse_budget_fissi(mappatura_path, logger)
    pers_rows  = parse_personale_incidenza(incidenza_path, logger)
    all_rows   = fissi_rows + pers_rows

    quality_summary(all_rows, logger)

    if args.dry_run:
        dump_csv(all_rows, Path(args.output_dir) / "f_budget_mensile_costi.csv", logger)
        logger.info("DRY RUN completato — nessuna scrittura su BQ.")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = bigquery.Client(project=BQ_PROJECT)
    load_to_bq(all_rows, bq_client, logger)
    logger.info("✓ DONE")


if __name__ == "__main__":
    main()
