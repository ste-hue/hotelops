#!/usr/bin/env python3
"""
Ingest file 'consumi merce YYYY.xlsx' → f_consumi_economato.

Formato Export: Anno | Mese (testo IT) | Giorno | Reparto | Classe | Categoria |
                CodiceArticolo | DescrizioneArticolo | U.M. | Quantita | Importo

Usage:
    python -m ingest.amministrativa.ingest_consumi_merce \\
        --file "consumi merce 2025.xlsx" --dry-run
    python -m ingest.amministrativa.ingest_consumi_merce \\
        --file "consumi merce 2025.xlsx"
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from google.cloud import bigquery

BQ_PROJECT = "hotelops-suite"
BQ_TABLE   = f"{BQ_PROJECT}.hotelops.f_consumi_economato"
SOCIETA_ID = "ORTI"

MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# Mapping codice reparto → dimensioni
REPARTO_MAP: dict[str, dict] = {
    # F&B
    "BRK":      {"reparto_id": "BRK",          "funzione_id": "F&B",       "business_unit_id": "HOTEL",     "is_evento": False},
    "CUCINA":   {"reparto_id": "CUCINA",        "funzione_id": "F&B",       "business_unit_id": "HOTEL",     "is_evento": False},
    "CANTINA":  {"reparto_id": "CANTINA",       "funzione_id": "F&B",       "business_unit_id": "HOTEL",     "is_evento": False},
    "BARBEACH": {"reparto_id": "BAR_BEACH",     "funzione_id": "F&B",       "business_unit_id": "LIDO",      "is_evento": False},
    "BARHOTEL": {"reparto_id": "BAR_HOTEL",     "funzione_id": "F&B",       "business_unit_id": "HOTEL",     "is_evento": False},
    "BANCHETT": {"reparto_id": "BANCHETTI",     "funzione_id": "F&B",       "business_unit_id": "HOTEL",     "is_evento": False},
    "DCOLAZIO": {"reparto_id": "BRK",           "funzione_id": "F&B",       "business_unit_id": "HOTEL",     "is_evento": False},
    # Rooms
    "HSKHOTEL": {"reparto_id": "HSK_HOTEL",     "funzione_id": "ROOMS",     "business_unit_id": "HOTEL",     "is_evento": False},
    "HSKRES":   {"reparto_id": "HSK_AR",        "funzione_id": "ROOMS",     "business_unit_id": "RESIDENCE", "is_evento": False},
    "HSKCVM":   {"reparto_id": "HSK_CVM",       "funzione_id": "ROOMS",     "business_unit_id": "CVM",       "is_evento": False},
    "DHSKHOTE": {"reparto_id": "HSK_HOTEL",     "funzione_id": "ROOMS",     "business_unit_id": "HOTEL",     "is_evento": False},
    "RECEP":    {"reparto_id": "RECEPTION",     "funzione_id": "ROOMS",     "business_unit_id": "HOTEL",     "is_evento": False},
    "DRECEPTI": {"reparto_id": "RECEPTION",     "funzione_id": "ROOMS",     "business_unit_id": "HOTEL",     "is_evento": False},
    "POOLHTL":  {"reparto_id": "PISCINA_HP",    "funzione_id": "ROOMS",     "business_unit_id": "HOTEL",     "is_evento": False},
    "POOLRES":  {"reparto_id": "PISCINA_AR",    "funzione_id": "ROOMS",     "business_unit_id": "RESIDENCE", "is_evento": False},
    "DIPEND":   {"reparto_id": "DIPENDENTI",    "funzione_id": "ROOMS",     "business_unit_id": "HOTEL",     "is_evento": False},
    # Manutenzione
    "MANHOTEL": {"reparto_id": "MANUTENZIONE",  "funzione_id": "MAN",       "business_unit_id": "HOTEL",     "is_evento": False},
    "DMANHOTE": {"reparto_id": "MANUTENZIONE",  "funzione_id": "MAN",       "business_unit_id": "HOTEL",     "is_evento": False},
    "MANRESID": {"reparto_id": "MAN_AR",        "funzione_id": "MAN",       "business_unit_id": "RESIDENCE", "is_evento": False},
    "MANCVM":   {"reparto_id": "MAN_CVM",       "funzione_id": "MAN",       "business_unit_id": "CVM",       "is_evento": False},
    "IMBARCAZ": {"reparto_id": "IMBARCAZIONE",  "funzione_id": "LOGISTICA", "business_unit_id": "HOTEL",     "is_evento": False},
    "DEPERIME": {"reparto_id": "DEPERIMENTO",   "funzione_id": "LOGISTICA", "business_unit_id": "HOTEL",     "is_evento": False},
    # AMM / HQ
    "PROPRIET": {"reparto_id": "DIREZIONE",     "funzione_id": "AMM",       "business_unit_id": "HQ",        "is_evento": False},
    "UFFICI":   {"reparto_id": "UFFICI",        "funzione_id": "AMM",       "business_unit_id": "HQ",        "is_evento": False},
    "DUFFICID": {"reparto_id": "UFFICI",        "funzione_id": "AMM",       "business_unit_id": "HQ",        "is_evento": False},
    "OMAGGI":   {"reparto_id": "OMAGGI",        "funzione_id": "AMM",       "business_unit_id": "HOTEL",     "is_evento": False},
    # Eventi
    "EVENTI":   {"reparto_id": "EVENTO",        "funzione_id": "EVENTO",    "business_unit_id": "HOTEL",     "is_evento": True,  "evento_nome": ""},
    "EVENTO":   {"reparto_id": "EVENTO",        "funzione_id": "EVENTO",    "business_unit_id": "HOTEL",     "is_evento": True,  "evento_nome": ""},
    "EVENTOLU": {"reparto_id": "EVENTO",        "funzione_id": "EVENTO",    "business_unit_id": "LIDO",      "is_evento": True,  "evento_nome": ""},
    "EVENTORE": {"reparto_id": "EVENTO",        "funzione_id": "EVENTO",    "business_unit_id": "RESIDENCE", "is_evento": True,  "evento_nome": ""},
    "CUCINELL": {"reparto_id": "EVENTO",        "funzione_id": "EVENTO",    "business_unit_id": "HOTEL",     "is_evento": True,  "evento_nome": "Cucinelli"},
}

BQ_SCHEMA = [
    bigquery.SchemaField("hash_riga",          "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("societa_id",          "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("anno",                "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("mese",                "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("business_unit_id",    "STRING"),
    bigquery.SchemaField("funzione_id",         "STRING"),
    bigquery.SchemaField("reparto_id",          "STRING"),
    bigquery.SchemaField("reparto_raw",         "STRING"),
    bigquery.SchemaField("is_evento",           "BOOL"),
    bigquery.SchemaField("evento_nome",         "STRING"),
    bigquery.SchemaField("codice_prodotto",     "STRING"),
    bigquery.SchemaField("descrizione",         "STRING"),
    bigquery.SchemaField("classe",              "STRING"),
    bigquery.SchemaField("categoria_prodotto",  "STRING"),
    bigquery.SchemaField("sottocategoria",      "STRING"),
    bigquery.SchemaField("quantita",            "FLOAT64"),
    bigquery.SchemaField("importo",             "FLOAT64"),
    bigquery.SchemaField("file_sorgente",       "STRING"),
    bigquery.SchemaField("data_caricamento",    "TIMESTAMP"),
]


def parse_file(path: Path, logger: logging.Logger) -> list[dict]:
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows_raw = list(ws.iter_rows(values_only=True))
    wb.close()

    # Skip header row
    now = datetime.now(timezone.utc)
    records: list[dict] = []
    unknown_reparti: set[str] = set()

    for row in rows_raw[1:]:
        if not row or len(row) < 11 or not row[0] or not row[1]:
            continue

        anno        = row[0]
        mese_raw    = str(row[1]).strip().lower()
        reparto_raw = str(row[3]).strip() if row[3] else ""
        classe      = str(row[4]).strip().rstrip(" -") if row[4] else ""
        categoria   = str(row[5]).strip().rstrip(" -") if row[5] else ""
        codice      = str(row[6]).strip() if row[6] else ""
        desc        = str(row[7]).strip() if row[7] else ""
        quantita    = float(row[9])  if isinstance(row[9],  (int, float)) else 0.0
        importo     = float(row[10]) if isinstance(row[10], (int, float)) else 0.0

        if not isinstance(anno, int) or not codice or mese_raw == "data - mese":
            continue

        mese = MESI_IT.get(mese_raw)
        if mese is None:
            continue

        dim = REPARTO_MAP.get(reparto_raw)
        if dim is None:
            unknown_reparti.add(reparto_raw)
            dim = {"reparto_id": reparto_raw, "funzione_id": "UNKNOWN",
                   "business_unit_id": "HOTEL", "is_evento": False}

        evento_nome = dim.get("evento_nome", reparto_raw if dim["is_evento"] else "")

        hash_src  = f"{SOCIETA_ID}|{anno}|{mese}|{dim['reparto_id']}|{codice}|{quantita}|{importo}"
        hash_riga = hashlib.md5(hash_src.encode()).hexdigest()

        records.append({
            "hash_riga":          hash_riga,
            "societa_id":         SOCIETA_ID,
            "anno":               anno,
            "mese":               mese,
            "business_unit_id":   dim["business_unit_id"],
            "funzione_id":        dim["funzione_id"],
            "reparto_id":         dim["reparto_id"],
            "reparto_raw":        reparto_raw,
            "is_evento":          dim["is_evento"],
            "evento_nome":        evento_nome,
            "codice_prodotto":    codice,
            "descrizione":        desc,
            "classe":             classe,
            "categoria_prodotto": categoria,
            "sottocategoria":     "",
            "quantita":           quantita,
            "importo":            round(importo, 4),
            "file_sorgente":      path.name,
            "data_caricamento":   now.isoformat(),
        })

    if unknown_reparti:
        logger.warning(f"Reparti non mappati (UNKNOWN): {sorted(unknown_reparti)}")

    return records


def print_summary(records: list[dict], logger: logging.Logger) -> None:
    from collections import defaultdict
    by_mese: dict[tuple, float] = defaultdict(float)
    by_reparto: dict[str, float] = defaultdict(float)
    for r in records:
        by_mese[(r["anno"], r["mese"])] += r["importo"]
        by_reparto[r["reparto_id"]] += r["importo"]

    logger.info("═" * 52)
    logger.info(f"  Righe: {len(records)}  |  Totale: {sum(r['importo'] for r in records):,.2f} €")
    logger.info("  Per mese:")
    for (anno, mese), tot in sorted(by_mese.items()):
        logger.info(f"    {anno}-{mese:02d}  {tot:>10,.2f} €")
    logger.info("  Per reparto:")
    for rep, tot in sorted(by_reparto.items(), key=lambda x: -x[1]):
        logger.info(f"    {rep:<20} {tot:>10,.2f} €")
    logger.info("═" * 52)


def load_to_bq(records: list[dict], logger: logging.Logger) -> None:
    client = bigquery.Client(project=BQ_PROJECT)

    hashes = [r["hash_riga"] for r in records]
    hash_list = ", ".join(f"'{h}'" for h in hashes)
    existing = set()
    for row in client.query(
        f"SELECT hash_riga FROM `{BQ_TABLE}` WHERE hash_riga IN ({hash_list})"
    ).result():
        existing.add(row.hash_riga)

    new_records = [r for r in records if r["hash_riga"] not in existing]
    logger.info(f"  Già presenti: {len(existing)}  |  Nuove: {len(new_records)}")

    if not new_records:
        logger.info("  Niente da caricare.")
        return

    job = client.load_table_from_json(
        new_records, BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
        sys.exit(1)
    logger.info(f"  ✓ {len(new_records)} righe caricate in {BQ_TABLE}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log = logging.getLogger("ingest_consumi_merce")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
    log.addHandler(h)

    path = Path(args.file)
    if not path.exists():
        log.error(f"File non trovato: {path}")
        sys.exit(1)

    log.info(f"File: {path.name}  |  dry-run: {args.dry_run}")
    records = parse_file(path, log)
    print_summary(records, log)

    if args.dry_run:
        log.info("DRY RUN — nessuna scrittura su BQ.")
        return

    load_to_bq(records, log)
    log.info("✓ DONE")


if __name__ == "__main__":
    main()
