#!/usr/bin/env python3
"""
Ingest file consumi economato CONSOLIDATO (tutti i reparti in un unico xlsx).

Formato: ECO_SituazioneConsumi_DettagliP — colonne:
  Codice, Descrizione, Data, Reparto, Classe, Categoria, SubCateg.,
  U.M.A., U.M.C., Coeff Conv, Quantita, Euro

Usage:
    python -m ingest.flussi.ingest_consumi_economato_consolidato \\
        --file "Consumi Luglio-Novembre 2025.xlsx" --dry-run
    python -m ingest.flussi.ingest_consumi_economato_consolidato \\
        --file "Consumi Luglio-Novembre 2025.xlsx"
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

from core.bq.client import get_client
from core.config import PROJECT

BQ_TABLE = f"{PROJECT}.hotelops.f_consumi_economato"
SOCIETA_ID = "ORTI"

# Mapping codice reparto → dimensioni
# Fonte: economato_reparti.csv + codici dal file ECO_SituazioneConsumi
REPARTO_MAP: dict[str, dict] = {
    "BARBEACH": {
        "reparto_id": "BAR_BEACH",
        "funzione_id": "F&B",
        "business_unit_id": "LIDO",
        "is_evento": False,
    },
    "BRK": {
        "reparto_id": "BRK",
        "funzione_id": "F&B",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "CANTINA": {
        "reparto_id": "CANTINA",
        "funzione_id": "F&B",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "CUCINA": {
        "reparto_id": "CUCINA",
        "funzione_id": "F&B",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "DEPERIME": {
        "reparto_id": "DEPERIMENTO",
        "funzione_id": "LOGISTICA",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "DIPEND": {
        "reparto_id": "DIPENDENTI",
        "funzione_id": "ROOMS",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "DMANHOTE": {
        "reparto_id": "MANUTENZIONE",
        "funzione_id": "MAN",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "DUFFICID": {
        "reparto_id": "UFFICI",
        "funzione_id": "AMM",
        "business_unit_id": "HQ",
        "is_evento": False,
    },
    "EVENTI": {
        "reparto_id": "EVENTO",
        "funzione_id": "EVENTO",
        "business_unit_id": "HOTEL",
        "is_evento": True,
    },
    "HSKCVM": {
        "reparto_id": "HSK_CVM",
        "funzione_id": "ROOMS",
        "business_unit_id": "CVM",
        "is_evento": False,
    },
    "HSKHOTEL": {
        "reparto_id": "HSK_HOTEL",
        "funzione_id": "ROOMS",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "HSKRES": {
        "reparto_id": "HSK_AR",
        "funzione_id": "ROOMS",
        "business_unit_id": "RESIDENCE",
        "is_evento": False,
    },
    "IMBARCAZ": {
        "reparto_id": "IMBARCAZIONE",
        "funzione_id": "LOGISTICA",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "MANHOTEL": {
        "reparto_id": "MANUTENZIONE",
        "funzione_id": "MAN",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "OMAGGI": {
        "reparto_id": "OMAGGI",
        "funzione_id": "AMM",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "POOLHTL": {
        "reparto_id": "PISCINA_HP",
        "funzione_id": "ROOMS",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "POOLRES": {
        "reparto_id": "PISCINA_AR",
        "funzione_id": "ROOMS",
        "business_unit_id": "RESIDENCE",
        "is_evento": False,
    },
    "PROPRIET": {
        "reparto_id": "DIREZIONE",
        "funzione_id": "AMM",
        "business_unit_id": "HQ",
        "is_evento": False,
    },
    "RECEP": {
        "reparto_id": "RECEPTION",
        "funzione_id": "ROOMS",
        "business_unit_id": "HOTEL",
        "is_evento": False,
    },
    "UFFICI": {
        "reparto_id": "UFFICI",
        "funzione_id": "AMM",
        "business_unit_id": "HQ",
        "is_evento": False,
    },
}

BQ_SCHEMA = [
    bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("anno", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("mese", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("business_unit_id", "STRING"),
    bigquery.SchemaField("funzione_id", "STRING"),
    bigquery.SchemaField("reparto_id", "STRING"),
    bigquery.SchemaField("reparto_raw", "STRING"),
    bigquery.SchemaField("is_evento", "BOOL"),
    bigquery.SchemaField("evento_nome", "STRING"),
    bigquery.SchemaField("codice_prodotto", "STRING"),
    bigquery.SchemaField("descrizione", "STRING"),
    bigquery.SchemaField("classe", "STRING"),
    bigquery.SchemaField("categoria_prodotto", "STRING"),
    bigquery.SchemaField("sottocategoria", "STRING"),
    bigquery.SchemaField("quantita", "FLOAT64"),
    bigquery.SchemaField("importo", "FLOAT64"),
    bigquery.SchemaField("file_sorgente", "STRING"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
]


def parse_file(path: Path, logger: logging.Logger) -> list[dict]:
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows_raw = list(ws.iter_rows(values_only=True))
    wb.close()

    # Find header row (row with "Codice" in col 0)
    header_idx = None
    for i, row in enumerate(rows_raw):
        if row and row[0] and str(row[0]).strip().lower() == "codice":
            header_idx = i
            break
    if header_idx is None:
        logger.error("Header 'Codice' non trovato nel file")
        sys.exit(1)

    header = [str(c).strip().lower() if c else "" for c in rows_raw[header_idx]]

    def ci(name: str) -> int:
        for i, h in enumerate(header):
            if h.startswith(name.lower()):
                return i
        return -1

    col_codice = ci("codice")
    col_desc = ci("descri")
    col_data = ci("data")
    col_reparto = ci("reparto")
    col_classe = ci("classe")
    col_cat = ci("categor")
    col_subcat = ci("subcateg")
    col_qtq = ci("quantit")
    col_euro = ci("euro")

    now = datetime.now(timezone.utc)
    records: list[dict] = []
    unknown_reparti: set[str] = set()

    for row in rows_raw[header_idx + 1 :]:
        if not row or not row[col_codice]:
            continue
        codice = str(row[col_codice]).strip()
        if not codice or codice.lower() in ("codice", "totale"):
            continue

        data_cell = row[col_data] if col_data >= 0 else None
        reparto_raw = (
            str(row[col_reparto]).strip()
            if col_reparto >= 0 and row[col_reparto]
            else ""
        )

        if not isinstance(data_cell, datetime):
            continue

        anno = data_cell.year
        mese = data_cell.month

        dim = REPARTO_MAP.get(reparto_raw)
        if dim is None:
            unknown_reparti.add(reparto_raw)
            dim = {
                "reparto_id": reparto_raw,
                "funzione_id": "UNKNOWN",
                "business_unit_id": "HOTEL",
                "is_evento": False,
            }

        desc = str(row[col_desc]).strip() if col_desc >= 0 and row[col_desc] else ""
        classe = (
            str(row[col_classe]).strip() if col_classe >= 0 and row[col_classe] else ""
        )
        cat = str(row[col_cat]).strip() if col_cat >= 0 and row[col_cat] else ""
        subcat = (
            str(row[col_subcat]).strip() if col_subcat >= 0 and row[col_subcat] else ""
        )
        quantita = (
            float(row[col_qtq])
            if col_qtq >= 0 and isinstance(row[col_qtq], (int, float))
            else 0.0
        )
        importo = (
            float(row[col_euro])
            if col_euro >= 0 and isinstance(row[col_euro], (int, float))
            else 0.0
        )

        classe = classe.rstrip(" -").strip()
        cat = cat.rstrip(" -").strip()
        subcat = subcat.rstrip(" -").strip()

        hash_src = f"{SOCIETA_ID}|{anno}|{mese}|{dim['reparto_id']}|{codice}|{quantita}|{importo}"
        hash_riga = hashlib.md5(hash_src.encode()).hexdigest()

        records.append(
            {
                "hash_riga": hash_riga,
                "societa_id": SOCIETA_ID,
                "anno": anno,
                "mese": mese,
                "business_unit_id": dim["business_unit_id"],
                "funzione_id": dim["funzione_id"],
                "reparto_id": dim["reparto_id"],
                "reparto_raw": reparto_raw,
                "is_evento": dim["is_evento"],
                "evento_nome": reparto_raw if dim["is_evento"] else "",
                "codice_prodotto": codice,
                "descrizione": desc,
                "classe": classe,
                "categoria_prodotto": cat,
                "sottocategoria": subcat,
                "quantita": quantita,
                "importo": round(importo, 4),
                "file_sorgente": path.name,
                "data_caricamento": now.isoformat(),
            }
        )

    if unknown_reparti:
        logger.warning(
            f"Reparti non mappati (taggati UNKNOWN): {sorted(unknown_reparti)}"
        )

    return records


def print_summary(records: list[dict], logger: logging.Logger) -> None:
    from collections import defaultdict

    by_mese: dict[tuple, float] = defaultdict(float)
    by_reparto: dict[str, float] = defaultdict(float)
    for r in records:
        by_mese[(r["anno"], r["mese"])] += r["importo"]
        by_reparto[r["reparto_id"]] += r["importo"]

    logger.info("═" * 50)
    logger.info(f"  Righe totali: {len(records)}")
    logger.info(f"  Importo totale: {sum(r['importo'] for r in records):,.2f} €")
    logger.info("  Per mese:")
    for (anno, mese), tot in sorted(by_mese.items()):
        logger.info(f"    {anno}-{mese:02d}  {tot:>10,.2f} €")
    logger.info("  Per reparto:")
    for rep, tot in sorted(by_reparto.items(), key=lambda x: -x[1]):
        logger.info(f"    {rep:<20} {tot:>10,.2f} €")
    logger.info("═" * 50)


def load_to_bq(records: list[dict], logger: logging.Logger) -> None:
    client = get_client()

    # Dedup: find hashes already in BQ
    hashes = [r["hash_riga"] for r in records]
    # BQ IN clause limit: use temp table approach for large sets
    hash_list = ", ".join(f"'{h}'" for h in hashes)
    existing = set()
    query = f"SELECT hash_riga FROM `{BQ_TABLE}` WHERE hash_riga IN ({hash_list})"
    for row in client.query(query).result():
        existing.add(row.hash_riga)

    new_records = [r for r in records if r["hash_riga"] not in existing]
    logger.info(f"  Già presenti: {len(existing)}  |  Nuove: {len(new_records)}")

    if not new_records:
        logger.info("  Niente da caricare.")
        return

    job = client.load_table_from_json(
        new_records,
        BQ_TABLE,
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
    parser.add_argument("--file", required=True, help="Path al file xlsx consolidato")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log = logging.getLogger("ingest_consumi_consolidato")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
    log.addHandler(h)

    path = Path(args.file)
    if not path.exists():
        log.error(f"File non trovato: {path}")
        sys.exit(1)

    log.info(f"File: {path.name}")
    log.info(f"Dry-run: {args.dry_run}")

    records = parse_file(path, log)
    print_summary(records, log)

    if args.dry_run:
        log.info("DRY RUN — nessuna scrittura su BQ.")
        return

    load_to_bq(records, log)
    log.info("✓ DONE")


if __name__ == "__main__":
    main()
