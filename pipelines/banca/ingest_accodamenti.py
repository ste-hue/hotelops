#!/usr/bin/env python3
"""
Esolver accodamenti ingestion pipeline.

Legge file TXT pipe-delimited da amministrativa_ingresso/accodamenti/,
estrae movimenti contabili e li carica in f_ledger_movimenti (BigQuery + CSV).

Parser: esolver-accodamenti (reconciliation_dino/src/parser.py).
  pip install -e /path/to/reconciliation_dino

Strutture file:
  H_*.txt → Hotel Panorama      (business_unit_id = HOTEL)
  R_*.txt → Angelina Residence  (business_unit_id = RESIDENCE)
  C_*.txt → Casa Vacanze Maiori (business_unit_id = CVM)

Tipi file processati:
  *_Movimenti.txt     → incasso_caparra, giro_caparra, movimento_generico
  *_Corrispettivi.txt → corrispettivi giornalieri per metodo pagamento
  *_Fatture.txt       → fatture emesse (TES+RIG+IVA)
  *_Clienti.txt       → SKIP (anagrafica, no movimenti)

Usage:
    python -m pipelines.banca.ingest_accodamenti \\
        --datahub /path/to/datahub --staging /tmp/accodamenti
    python -m pipelines.banca.ingest_accodamenti \\
        --datahub /path/to/datahub --staging /tmp/accodamenti --dry-run
    python -m pipelines.banca.ingest_accodamenti --inspect /path/to/C_Movimenti.txt
"""

import argparse
import csv
import hashlib
import logging
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from google.cloud import bigquery
from src.parser import parse_corrispettivi, parse_fatture, parse_movimenti

# ── Config ─────────────────────────────────────────────────────────────────────

BQ_PROJECT = "hotelops-suite"
BQ_DATASET = "hotelops"
BQ_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.f_accodamenti"

REMOTE_ACCODAMENTI = "mywork:00_hotelops_datahub/ingresso/amministrativa_ingresso/accodamenti"

DEFAULT_FUNZIONE = "CONTABILITA"
DEFAULT_LOCATION = "N_A"
SOCIETA_DEFAULT = "INTUR"

# struttura field from parser → business_unit_id
STRUTTURA_TO_BU: dict[str, str] = {
    "hotel": "HOTEL",
    "residence": "RESIDENCE",
    "cvm": "CVM",
    "unknown": "HQ",
}

# Conti Esolver → canale di pagamento (per tag + riconciliazione)
CONTO_CANALE: dict[str, str] = {
    "199001": "POS",
    "199006": "POS",
    "199002": "GESTPAY",
    "199003": "PAY_BY_LINK",
    "199007": "BONIFICO",
    "190303": "CASSA",
    "390521": "CAPARRA",
    "110301": "CREDITI",
}

FACT_HEADER = [
    "id_registrazione", "societa_id", "business_unit_id", "funzione_id",
    "location_id", "oggetto_id", "banca_id", "data_registrazione",
    "descrizione", "importo", "importo_dare", "importo_avere", "divisa",
    "riferimento_registrazione", "documento", "riferimenti_iva",
    "centro_imputazione", "data_ingresso", "file_sorgente", "riga_sorgente",
    "hash_riga",
]

BQ_SCHEMA = [
    bigquery.SchemaField("id_registrazione", "STRING"),
    bigquery.SchemaField("societa_id", "STRING"),
    bigquery.SchemaField("business_unit_id", "STRING"),
    bigquery.SchemaField("funzione_id", "STRING"),
    bigquery.SchemaField("location_id", "STRING"),
    bigquery.SchemaField("oggetto_id", "STRING"),
    bigquery.SchemaField("banca_id", "STRING"),
    bigquery.SchemaField("data_registrazione", "DATE"),
    bigquery.SchemaField("descrizione", "STRING"),
    bigquery.SchemaField("importo", "FLOAT64"),
    bigquery.SchemaField("importo_dare", "FLOAT64"),
    bigquery.SchemaField("importo_avere", "FLOAT64"),
    bigquery.SchemaField("divisa", "STRING"),
    bigquery.SchemaField("riferimento_registrazione", "STRING"),
    bigquery.SchemaField("documento", "STRING"),
    bigquery.SchemaField("riferimenti_iva", "STRING"),
    bigquery.SchemaField("centro_imputazione", "STRING"),
    bigquery.SchemaField("data_ingresso", "DATE"),
    bigquery.SchemaField("file_sorgente", "STRING"),
    bigquery.SchemaField("riga_sorgente", "INTEGER"),
    bigquery.SchemaField("hash_riga", "STRING"),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = logging.getLogger("ingest_accodamenti")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh = logging.FileHandler(log_dir / f"ingest_accodamenti_{ts}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def _parse_esolver_date(s: str) -> str | None:
    """Converte DDMMYYYY → YYYY-MM-DD."""
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[4:8]}-{s[2:4]}-{s[0:2]}"
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _md5(*args) -> str:
    return hashlib.md5("|".join(str(a) for a in args).encode()).hexdigest()


def _canale(conto: str) -> str:
    return CONTO_CANALE.get(conto.strip(), "ALTRO")


def _file_type(filename: str) -> str:
    name_lower = filename.lower()
    for t in ("movimenti", "corrispettivi", "fatture", "clienti"):
        if t in name_lower:
            return t
    return "unknown"


# ── Transform: eventi → f_ledger_movimenti rows ────────────────────────────────

def _make_row(
    societa: str,
    bu: str,
    data_str: str,
    descrizione: str,
    importo: Decimal,
    importo_dare: Decimal,
    importo_avere: Decimal,
    conto: str,
    file_name: str,
    line_no: int,
    documento: str = "",
    metodo: str = "",
) -> dict | None:
    data_iso = _parse_esolver_date(data_str)
    if not data_iso:
        return None
    if importo == Decimal("0") and importo_dare == Decimal("0") and importo_avere == Decimal("0"):
        return None

    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    canale = _canale(conto)

    return {
        "id_registrazione": f"ACC_{societa}_{bu}_{data_iso.replace('-','')}_{line_no:06d}_{ts}",
        "societa_id": societa,
        "business_unit_id": bu,
        "funzione_id": DEFAULT_FUNZIONE,
        "location_id": DEFAULT_LOCATION,
        "oggetto_id": f"{conto}_{canale}" if conto else canale,
        "banca_id": "ESOLVER",
        "data_registrazione": data_iso,
        "descrizione": (descrizione or "")[:500],
        "importo": float(importo),
        "importo_dare": float(importo_dare),
        "importo_avere": float(importo_avere),
        "divisa": "EUR",
        "riferimento_registrazione": "",
        "documento": documento,
        "riferimenti_iva": "",
        "centro_imputazione": metodo or "",
        "data_ingresso": datetime.now().strftime("%Y-%m-%d"),
        "file_sorgente": file_name,
        "riga_sorgente": line_no,
        "hash_riga": _md5(societa, bu, data_iso, float(importo), descrizione or "", conto),
    }


def events_to_rows(events: list[dict], societa: str) -> list[dict]:
    """
    Converte eventi (output di parse_movimenti/corrispettivi/fatture) in righe f_ledger_movimenti.

    - movimenti: una riga per GEN della coppia (con dare/avere espliciti)
    - corrispettivi: una riga per GEN di pagamento (incasso giornaliero per canale)
    - fatture: una riga per TES (totale imponibile+imposta, conto crediti)
    """
    rows = []

    for event in events:
        etype = event.get("type", "")
        bu = STRUTTURA_TO_BU.get(event.get("struttura", ""), "HQ")
        src_file = event.get("source_file", "")
        src_line = event.get("source_line", 0)

        if etype in ("incasso_caparra", "movimento_generico", "giro_caparra"):
            for gen in event.get("gens", []):
                dare = gen.get("importo_dare", Decimal("0"))
                avere = gen.get("importo_avere", Decimal("0"))
                row = _make_row(
                    societa=societa, bu=bu,
                    data_str=gen.get("data_doc", ""),
                    descrizione=gen.get("descrizione", "") or etype,
                    importo=dare - avere,
                    importo_dare=dare, importo_avere=avere,
                    conto=gen.get("conto_esolver", ""),
                    file_name=src_file, line_no=src_line,
                    metodo=gen.get("metodo_pagamento", ""),
                )
                if row:
                    rows.append(row)

        elif etype == "corrispettivo":
            tes = event.get("tes", {})
            for gen in event.get("gens", []):
                importo = gen.get("importo", Decimal("0"))
                if importo == Decimal("0"):
                    continue
                row = _make_row(
                    societa=societa, bu=bu,
                    data_str=gen.get("data_doc", "") or tes.get("data_doc", ""),
                    descrizione=gen.get("descrizione", "") or f"Corrispettivo {bu}",
                    importo=importo,
                    importo_dare=importo, importo_avere=Decimal("0"),
                    conto=gen.get("conto_esolver", ""),
                    file_name=src_file, line_no=src_line,
                    metodo=gen.get("metodo_pagamento", ""),
                )
                if row:
                    rows.append(row)

        elif etype == "fattura":
            tes = event.get("tes", {})
            ivas = event.get("ivas", [])
            rigs = event.get("rigs", [])
            totale = sum(iv["imponibile"] + iv["imposta"] for iv in ivas) if ivas else Decimal("0")
            if totale == Decimal("0"):
                totale = sum(r["imponibile"] for r in rigs)
            if totale == Decimal("0"):
                continue
            row = _make_row(
                societa=societa, bu=bu,
                data_str=tes.get("data_doc", ""),
                descrizione=f"Fattura {tes.get('num_doc','')} cliente {tes.get('codice_cliente','')}",
                importo=totale,
                importo_dare=totale, importo_avere=Decimal("0"),
                conto="110301",
                file_name=src_file, line_no=src_line,
                documento=str(tes.get("num_doc", "")),
            )
            if row:
                rows.append(row)

    return rows


def parse_and_transform(path: Path, societa: str, logger: logging.Logger) -> list[dict]:
    """Parsa un file Esolver e restituisce righe f_ledger_movimenti."""
    ftype = _file_type(path.name)
    filepath = str(path)

    if ftype == "clienti":
        logger.info(f"  SKIP {path.name} (anagrafica clienti)")
        return []

    if ftype == "movimenti":
        events = parse_movimenti(filepath)
    elif ftype == "corrispettivi":
        events = parse_corrispettivi(filepath)
    elif ftype == "fatture":
        events = parse_fatture(filepath)
    else:
        logger.warning(f"  SKIP {path.name} — tipo non riconosciuto: {ftype}")
        return []

    rows = events_to_rows(events, societa)
    logger.debug(f"  {path.name}: {len(events)} eventi → {len(rows)} righe")
    return rows


# ── BigQuery + CSV ─────────────────────────────────────────────────────────────

def load_hashes_bq(bq_client: bigquery.Client, logger: logging.Logger) -> set:
    try:
        result = bq_client.query(
            f"SELECT hash_riga FROM `{BQ_TABLE}`"
        ).result()
        hashes = {row.hash_riga for row in result}
        logger.info(f"Hashes BQ esistenti (f_accodamenti): {len(hashes)}")
        return hashes
    except Exception as e:
        logger.warning(f"Impossibile caricare hashes BQ: {e}")
        return set()


def write_to_bq(rows: list[dict], bq_client: bigquery.Client, logger: logging.Logger):
    df = pd.DataFrame(rows, columns=FACT_HEADER)
    df["data_registrazione"] = pd.to_datetime(df["data_registrazione"])
    df["data_ingresso"] = pd.to_datetime(df["data_ingresso"])
    df["riga_sorgente"] = df["riga_sorgente"].astype(int)
    for col in ("importo", "importo_dare", "importo_avere"):
        df[col] = df[col].astype(float)
    job_config = bigquery.LoadJobConfig(schema=BQ_SCHEMA, write_disposition="WRITE_APPEND")
    bq_client.load_table_from_dataframe(df, BQ_TABLE, job_config=job_config).result()
    logger.info(f"Scritte {len(rows)} righe → BigQuery {BQ_TABLE}")


def write_to_csv(rows: list[dict], fact_table: Path, logger: logging.Logger):
    exists = fact_table.exists()
    fact_table.parent.mkdir(parents=True, exist_ok=True)
    with open(fact_table, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FACT_HEADER)
        if not exists:
            w.writeheader()
        w.writerows(rows)
    logger.info(f"Scritte {len(rows)} righe → {fact_table.name}")


# ── rclone sync ────────────────────────────────────────────────────────────────

def sync_from_drive(staging: Path, dry_run: bool, logger: logging.Logger) -> bool:
    staging.mkdir(parents=True, exist_ok=True)
    cmd = ["rclone", "sync", REMOTE_ACCODAMENTI, str(staging)]
    if dry_run:
        cmd.append("--dry-run")
    logger.info(f"Sync {REMOTE_ACCODAMENTI} → {staging}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"rclone failed: {result.stderr}")
        return False
    logger.info("Sync completato")
    return True


# ── Inspect ────────────────────────────────────────────────────────────────────

def inspect_file(path: Path):
    """Dump struttura raw del file per debug formato."""
    print(f"\n=== INSPECT: {path} ===")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    print(f"Righe totali: {len(lines)}")
    record_types: dict[str, int] = {}
    for line in lines:
        rt = line.split("|")[0].strip()
        record_types[rt] = record_types.get(rt, 0) + 1
    print(f"Tipi record: {record_types}")
    print(f"Prime 5 righe:")
    for i, line in enumerate(lines[:5], 1):
        fields = [f.strip() for f in line.split("|")]
        print(f"  [{i:2d}] {len(fields)} campi → {fields[:12]}{'...' if len(fields)>12 else ''}")
    ftype = _file_type(path.name)
    print(f"Rilevato: tipo={ftype}")


# ── Pipeline ───────────────────────────────────────────────────────────────────

def process_file(
    path: Path,
    bq_client: bigquery.Client,
    hashes: set,
    datahub: Path,
    societa: str,
    logger: logging.Logger,
    dry_run: bool,
) -> dict:
    stats = {"file": path.name, "parsed": 0, "new": 0, "dupes": 0, "errors": 0}

    try:
        rows = parse_and_transform(path, societa, logger)
    except Exception as e:
        logger.error(f"Errore parsing {path.name}: {e}")
        stats["errors"] = 1
        return stats

    stats["parsed"] = len(rows)
    new_rows = [r for r in rows if r["hash_riga"] not in hashes]
    for r in new_rows:
        hashes.add(r["hash_riga"])
    stats["dupes"] = len(rows) - len(new_rows)
    stats["new"] = len(new_rows)

    if not new_rows or dry_run:
        if dry_run and new_rows:
            logger.info(f"  DRY RUN: scriverei {len(new_rows)} righe")
        return stats

    try:
        write_to_bq(new_rows, bq_client, logger)
    except Exception as e:
        logger.error(f"  BigQuery write fallita: {e}")

    write_to_csv(new_rows, datahub / "fatti" / "f_accodamenti.csv", logger)
    return stats


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Esolver accodamenti → f_ledger_movimenti (BigQuery + CSV)"
    )
    parser.add_argument("--datahub", help="Path to datahub root")
    parser.add_argument("--staging", help="Dir locale per file accodamenti")
    parser.add_argument("--societa", default=SOCIETA_DEFAULT, help="Società ID (default: INTUR)")
    parser.add_argument("--project", default=BQ_PROJECT)
    parser.add_argument("--no-sync", action="store_true", help="Salta rclone sync")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--inspect", metavar="FILE", help="Ispeziona file raw ed esci")
    args = parser.parse_args()

    if args.inspect:
        inspect_file(Path(args.inspect))
        return

    if not args.datahub or not args.staging:
        parser.error("--datahub e --staging sono richiesti")

    datahub = Path(args.datahub)
    staging = Path(args.staging)

    if not datahub.exists():
        print(f"Datahub non trovato: {datahub}")
        sys.exit(1)

    log_dir = datahub / "meta" / "pipeline" / "logs"
    logger = setup_logging(log_dir, args.verbose)
    logger.info("=" * 60)
    logger.info("Accodamenti ingestion pipeline START")

    if not args.no_sync:
        if not sync_from_drive(staging, args.dry_run, logger):
            sys.exit(1)

    files = sorted(staging.glob("*.txt")) + sorted(staging.glob("*.TXT"))
    logger.info(f"File in staging: {len(files)}")
    if not files:
        logger.warning("Nessun .txt trovato. Esci.")
        return

    bq_client = bigquery.Client(project=args.project)
    hashes = load_hashes_bq(bq_client, logger)

    totals: dict[str, int] = {"parsed": 0, "new": 0, "dupes": 0, "errors": 0}
    for filepath in files:
        logger.info(f"Processo: {filepath.name}")
        stats = process_file(filepath, bq_client, hashes, datahub, args.societa, logger, args.dry_run)
        for k in totals:
            totals[k] += stats.get(k, 0)
        logger.info(
            f"  → parsed={stats['parsed']}, new={stats['new']}, "
            f"dupes={stats['dupes']}, errors={stats['errors']}"
        )

    logger.info(
        f"TOTALE: parsed={totals['parsed']}, new={totals['new']}, "
        f"dupes={totals['dupes']}, errors={totals['errors']}"
    )
    logger.info("Accodamenti ingestion pipeline DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
