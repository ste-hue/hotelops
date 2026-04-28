#!/usr/bin/env python3
"""
Coperti giornalieri → BigQuery f_coperti_giornalieri.

Legge file CSV/XLSX da datahub/coperti/ oppure direttamente da Google Sheet.
Ogni riga sorgente = un giorno + tipo_pasto, con colonne per BU/tipo_ospite.
Trasforma in formato lungo (una riga per data × pasto × tipo_ospite).

Strategia: latest-wins per chiave naturale (societa, data, pasto, ospite, BU).
Submission multiple del Google Form per la stessa chiave vengono collassate
intra-batch tenendo il timestamp più recente, e il DELETE-INSERT chirurgico
in BQ sostituisce qualunque versione precedente per le chiavi presenti nel
batch (lasciando intatti i record fuori dal batch).

Formati supportati:
  - CSV Google Form export:
      "Informazioni cronologiche","Breakfast Ospiti Hotel",...
  - XLSX con fogli Scarico_BRK / Scarico_LUNCH / Scarico_DINNER:
      stessa struttura del CSV (come consumi_BRK_CUCINA.xlsx)
  - Google Sheet (via rclone) con fogli Breakfast / Lunch / Dinner / Mensa Dipendenti

Usage:
    python -m ingest.flussi.ingest_coperti --dry-run
    python -m ingest.flussi.ingest_coperti
    python -m ingest.flussi.ingest_coperti \\
        --gsheet 1AlbQl7pGhCEbjXJY9di539fa73B5t5gRktN4JJYZQJM --replace
    python -m ingest.flussi.ingest_coperti \\
        --datahub "/path/to/hotelops_datahub"

Output BQ: f_coperti_giornalieri  (DELETE-INSERT chirurgico per hash_riga)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

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

from core.bq.client import get_client
from core.config import PROJECT
from core.datahub_sync import DATAHUB_ROOT as DATAHUB_DEFAULT, RCLONE_REMOTE

# ── Defaults ──────────────────────────────────────────────────────────────────

SOURCE_DEFAULT = DATAHUB_DEFAULT / "coperti"

BQ_DATASET = "hotelops"
BQ_TABLE = "f_coperti_giornalieri"
BQ_TABLE_FULL = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

SOCIETA_ID = "ORTI"  # default; override via --societa

# ── Column mappings ────────────────────────────────────────────────────────────
# Maps source column suffix → (tipo_ospite, business_unit_id)
# The prefix (Breakfast/Lunch/Dinner) is stripped before matching.
OSPITE_MAP = {
    "Ospiti Hotel": ("HOTEL", "HOTEL"),
    "Ospiti Residence": ("RESIDENCE", "RESIDENCE"),
    "Ospiti CVM": ("CVM", "CVM"),
    "Ospiti Case PM": ("PM", "HQ"),
    "Esterni": ("ESTERNI", None),
    "Courtesy": ("COURTESY", None),
    # variants in LUNCH/DINNER sheets
    "Ospiti Hotel ": ("HOTEL", "HOTEL"),
    "Ospiti Residence ": ("RESIDENCE", "RESIDENCE"),
}

PASTO_KEYWORDS = {
    "breakfast": "BRK",
    "brk": "BRK",
    "lunch": "LUNCH",
    "dinner": "DINNER",
    "cena": "DINNER",
    "pranzo": "LUNCH",
    "colazione": "BRK",
}

# Google Sheet ID for the canonical coperti source
GSHEET_ID_DEFAULT = "1AlbQl7pGhCEbjXJY9di539fa73B5t5gRktN4JJYZQJM"

MONTH_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────


def detect_tipo_pasto(text: str) -> str | None:
    t = text.lower()
    for kw, code in PASTO_KEYWORDS.items():
        if kw in t:
            return code
    return None


def parse_timestamp(val) -> date | None:
    """Convert various timestamp formats to a date."""
    if val is None:
        return None
    if isinstance(val, (datetime,)):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        val = val.strip()
        # try common formats
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                pass
    return None


def col_suffix(col_name: str, tipo_pasto: str) -> str:
    """Strip pasto prefix from column name to get the ospite type."""
    col = col_name.strip()
    # try removing known pasto prefixes
    for kw in ["Breakfast", "Lunch", "Dinner", "BRK"]:
        if col.startswith(kw):
            return col[len(kw) :].strip()
    return col


def ospite_info(suffix: str):
    """Return (tipo_ospite, business_unit_id) or None if not recognized."""
    suffix = suffix.strip()
    return OSPITE_MAP.get(suffix)


def make_hash(
    societa_id: str,
    data_servizio: date,
    tipo_pasto: str,
    tipo_ospite: str,
    business_unit_id: str | None = None,
) -> str:
    bu = business_unit_id or ""
    key = f"{societa_id}|{data_servizio}|{tipo_pasto}|{tipo_ospite}|{bu}"
    return hashlib.md5(key.encode()).hexdigest()


# ── Google Sheet download ─────────────────────────────────────────────────────


def fetch_gsheet(sheet_id: str, remote: str = RCLONE_REMOTE) -> Path:
    """Download a Google Sheet as XLSX via rclone backend copyid."""
    tmp = Path(tempfile.mkdtemp(prefix="hotelops_coperti_")) / "coperti_gsheet.xlsx"
    # not a datahub path — rclone drive.copyid exports a Sheet by fileId
    cmd = ["rclone", "backend", "copyid", f"{remote}:", sheet_id, str(tmp)]
    log.info("rclone: scarico Google Sheet %s …", sheet_id)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"rclone download failed: {result.stderr.strip()}")
    # rclone copyid drops the file without extension
    actual = tmp if tmp.exists() else tmp.with_suffix("")
    if not actual.exists():
        # rclone may save without extension
        candidates = list(tmp.parent.iterdir())
        if candidates:
            actual = candidates[0]
        else:
            raise RuntimeError("File non trovato dopo rclone download")
    if actual.suffix != ".xlsx":
        dest = actual.with_suffix(".xlsx")
        actual.rename(dest)
        actual = dest
    log.info("Scaricato: %s (%d KB)", actual.name, actual.stat().st_size // 1024)
    return actual


# ── Parsing ────────────────────────────────────────────────────────────────────


def parse_rows_from_header_data(
    header: list[str],
    data_rows: list[list],
    tipo_pasto: str,
    fonte: str,
    societa_id: str,
    ts_now: datetime,
) -> Iterator[dict]:
    """
    Given a header row and data rows (already lists of values), yield long-format dicts.
    header[0] must be the timestamp column.
    """
    # build column mapping: index → (tipo_ospite, business_unit_id)
    col_map = {}
    for i, col in enumerate(header):
        if i == 0:
            continue
        suffix = col_suffix(col, tipo_pasto)
        info = ospite_info(suffix)
        if info:
            col_map[i] = info

    if not col_map:
        log.warning(
            "  Nessuna colonna ospite riconosciuta in '%s' (pasto=%s)",
            fonte,
            tipo_pasto,
        )
        return

    for row in data_rows:
        if not any(row):
            continue
        data_servizio = parse_timestamp(row[0])
        if data_servizio is None:
            continue
        submitted_at = row[0] if isinstance(row[0], datetime) else None

        for i, (tipo_ospite, bu_id) in col_map.items():
            if i >= len(row):
                continue
            val = row[i]
            if val is None or val == "":
                continue
            try:
                n = int(float(val))
            except (TypeError, ValueError):
                continue
            if n == 0:
                continue  # skip zero entries to save space

            yield {
                "societa_id": societa_id,
                "anno": data_servizio.year,
                "mese": data_servizio.month,
                "data_servizio": data_servizio.isoformat(),
                "tipo_pasto": tipo_pasto,
                "tipo_ospite": tipo_ospite,
                "business_unit_id": bu_id,
                "n_coperti": n,
                "fonte": fonte,
                "hash_riga": make_hash(
                    societa_id, data_servizio, tipo_pasto, tipo_ospite, bu_id
                ),
                "data_caricamento": ts_now.isoformat(),
                "_submitted_at": submitted_at,
            }


def parse_csv_file(path: Path, societa_id: str, ts_now: datetime) -> list[dict]:
    """Parse a single Google Form CSV export."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            raw = list(reader)
    except Exception as e:
        log.error("  Errore lettura CSV %s: %s", path.name, e)
        return []

    if not raw:
        return []

    header = raw[0]
    data_rows = [row for row in raw[1:] if any(row)]

    # detect tipo_pasto from header or filename
    tipo_pasto = None
    for col in header:
        tp = detect_tipo_pasto(col)
        if tp:
            tipo_pasto = tp
            break
    if not tipo_pasto:
        tipo_pasto = detect_tipo_pasto(path.stem)
    if not tipo_pasto:
        log.warning("  Impossibile rilevare tipo_pasto da '%s'", path.name)
        return []

    fonte = path.name
    return list(
        parse_rows_from_header_data(
            header, data_rows, tipo_pasto, fonte, societa_id, ts_now
        )
    )


def parse_mensa_dipendenti(
    all_rows: list[tuple],
    fonte: str,
    societa_id: str,
    ts_now: datetime,
) -> list[dict]:
    """Parse 'Mensa Dipendenti' sheet (long format: timestamp, tipo_pasto, pax)."""
    header = [str(c).strip().lower() if c else "" for c in all_rows[0]]
    records = []
    for row_idx, row in enumerate(all_rows[1:]):
        if not row or not row[0]:
            continue
        data_servizio = parse_timestamp(row[0])
        if data_servizio is None:
            continue
        submitted_at = row[0] if isinstance(row[0], datetime) else None
        tipo_raw = str(row[1]).strip().upper() if row[1] else ""
        pax = row[2] if len(row) > 2 else None
        if pax is None:
            continue
        try:
            n = int(float(pax))
        except (TypeError, ValueError):
            continue
        if n == 0:
            continue

        tipo_pasto = PASTO_KEYWORDS.get(tipo_raw.lower())
        if not tipo_pasto:
            log.warning(
                "  Mensa Dipendenti: tipo_pasto '%s' non riconosciuto", tipo_raw
            )
            continue

        records.append(
            {
                "societa_id": societa_id,
                "anno": data_servizio.year,
                "mese": data_servizio.month,
                "data_servizio": data_servizio.isoformat(),
                "tipo_pasto": tipo_pasto,
                "tipo_ospite": "DIPENDENTI",
                "business_unit_id": "HQ",
                "n_coperti": n,
                "fonte": fonte,
                "hash_riga": make_hash(
                    societa_id, data_servizio, tipo_pasto, "DIPENDENTI", "HQ"
                ),
                "data_caricamento": ts_now.isoformat(),
                "_submitted_at": submitted_at,
            }
        )
    return records


def parse_xlsx_file(path: Path, societa_id: str, ts_now: datetime) -> list[dict]:
    """Parse an XLSX file — reads Scarico_*/Breakfast/Lunch/Dinner/Mensa Dipendenti sheets."""
    if not HAS_OPENPYXL:
        log.error("openpyxl non installato — skipping %s", path.name)
        return []

    rows = []
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        log.error("  Errore apertura XLSX %s: %s", path.name, e)
        return []

    # Find parseable sheets: Scarico_* or named Breakfast/Lunch/Dinner/Mensa Dipendenti
    pasto_sheets = []
    mensa_sheet = None
    for s in wb.sheetnames:
        sl = s.lower().strip()
        if sl.startswith("scarico") or detect_tipo_pasto(sl):
            pasto_sheets.append(s)
        elif "mensa" in sl or "dipendenti" in sl:
            mensa_sheet = s

    if not pasto_sheets and not mensa_sheet:
        log.info("  Nessun foglio coperti riconosciuto in %s — skip", path.name)
        wb.close()
        return []

    for sheet_name in pasto_sheets:
        tipo_pasto = detect_tipo_pasto(sheet_name)
        if not tipo_pasto:
            log.warning("  Foglio '%s': tipo_pasto non riconosciuto", sheet_name)
            continue

        ws = wb[sheet_name]
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            continue

        header = [str(c) if c is not None else "" for c in all_rows[0]]
        data_rows = [list(r) for r in all_rows[1:] if any(v is not None for v in r)]

        fonte = f"{path.name}::{sheet_name}"
        sheet_rows = list(
            parse_rows_from_header_data(
                header, data_rows, tipo_pasto, fonte, societa_id, ts_now
            )
        )
        log.info("  Foglio %-20s  %3d righe non-zero", sheet_name, len(sheet_rows))
        rows.extend(sheet_rows)

    # Parse Mensa Dipendenti if present
    if mensa_sheet:
        ws = wb[mensa_sheet]
        all_rows_mensa = list(ws.iter_rows(values_only=True))
        if all_rows_mensa:
            fonte = f"{path.name}::{mensa_sheet}"
            mensa_rows = parse_mensa_dipendenti(
                all_rows_mensa, fonte, societa_id, ts_now
            )
            log.info("  Foglio %-20s  %3d righe non-zero", mensa_sheet, len(mensa_rows))
            rows.extend(mensa_rows)

    wb.close()
    return rows


def collect_all_rows(source_dir: Path, societa_id: str) -> list[dict]:
    ts_now = datetime.now(timezone.utc)
    all_rows: list[dict] = []

    files = sorted(source_dir.iterdir()) if source_dir.exists() else []
    input_files = [
        f
        for f in files
        if f.suffix.lower() in (".csv", ".xlsx") and not f.name.startswith("~")
    ]

    if not input_files:
        log.warning("Nessun file CSV/XLSX in %s", source_dir)
        return []

    for path in input_files:
        log.info("Leggo: %s", path.name)
        if path.suffix.lower() == ".csv":
            file_rows = parse_csv_file(path, societa_id, ts_now)
        else:
            file_rows = parse_xlsx_file(path, societa_id, ts_now)
        log.info("  → %d righe non-zero", len(file_rows))
        all_rows.extend(file_rows)

    return all_rows


# ── BigQuery ───────────────────────────────────────────────────────────────────

BQ_SCHEMA = (
    [
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("anno", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("mese", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("data_servizio", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("tipo_pasto", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tipo_ospite", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("business_unit_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("n_coperti", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("fonte", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("data_caricamento", "TIMESTAMP", mode="NULLABLE"),
    ]
    if HAS_BQ
    else []
)


def dedup_latest_wins(rows: list[dict]) -> list[dict]:
    """Collapse rows sharing the same natural key, keeping the latest Form submission.

    Form submissions can be repeated (corrections, double-clicks). The natural key
    is encoded in hash_riga (societa, data, pasto, ospite, BU). Among rows with the
    same hash_riga, keep the one with the most recent _submitted_at; ties broken by
    higher n_coperti.
    """
    by_key: dict[str, dict] = {}
    for r in rows:
        k = r["hash_riga"]
        prev = by_key.get(k)
        if prev is None:
            by_key[k] = r
            continue
        prev_ts = prev.get("_submitted_at")
        cur_ts = r.get("_submitted_at")
        if cur_ts and (prev_ts is None or cur_ts > prev_ts):
            by_key[k] = r
        elif cur_ts == prev_ts and r["n_coperti"] > prev["n_coperti"]:
            by_key[k] = r
    return list(by_key.values())


def get_existing_hashes(client) -> set[str]:
    try:
        q = f"SELECT hash_riga FROM `{BQ_TABLE_FULL}`"
        result = client.query(q).result()
        return {row.hash_riga for row in result}
    except Exception:
        return set()


def ensure_table(client):
    dataset_ref = bigquery.DatasetReference(PROJECT, BQ_DATASET)
    table_ref = dataset_ref.table(BQ_TABLE)
    try:
        client.get_table(table_ref)
    except Exception:
        table = bigquery.Table(table_ref, schema=BQ_SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.MONTH,
            field="data_servizio",
        )
        client.create_table(table)
        log.info("Tabella %s creata.", BQ_TABLE_FULL)


def load_to_bq(rows: list[dict], dry_run: bool, replace: bool = False) -> None:
    if not HAS_BQ:
        log.error("google-cloud-bigquery non installato")
        sys.exit(1)

    client = get_client()
    ensure_table(client)

    if replace:
        if dry_run:
            log.info(
                "[DRY RUN] Avrei cancellato tutta la tabella e caricato %d righe.",
                len(rows),
            )
            return
        delete_q = f"DELETE FROM `{BQ_TABLE_FULL}` WHERE TRUE"
        log.info("DELETE-INSERT: cancello tutti i dati esistenti…")
        client.query(delete_q).result()
        new_rows = rows
    else:
        # Surgical DELETE-INSERT by natural key: cancello solo i record le cui
        # chiavi naturali sono presenti nel batch corrente, lasciando intatto
        # tutto il resto. Sostituzione idempotente — il foglio è source of truth
        # per le date/pasti/ospiti che tocca.
        batch_hashes = {r["hash_riga"] for r in rows}
        log.info(
            "Righe da caricare: %d (chiavi naturali distinte: %d)",
            len(rows),
            len(batch_hashes),
        )

        if dry_run:
            log.info("[DRY RUN] Avrei sostituito %d record.", len(batch_hashes))
            return

        # DELETE in chunks per evitare query troppo lunghe
        hash_list = list(batch_hashes)
        chunk_size = 1000
        for i in range(0, len(hash_list), chunk_size):
            chunk = hash_list[i : i + chunk_size]
            in_clause = ", ".join(f"'{h}'" for h in chunk)
            delete_q = (
                f"DELETE FROM `{BQ_TABLE_FULL}` WHERE hash_riga IN ({in_clause})"
            )
            client.query(delete_q).result()
        log.info("Cancellati record con chiavi naturali in batch.")
        new_rows = rows

    # Strip internal-only fields before insert
    rows_to_load = [{k: v for k, v in r.items() if not k.startswith("_")} for r in new_rows]

    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = client.load_table_from_json(rows_to_load, BQ_TABLE_FULL, job_config=job_config)
    job.result()
    log.info("Caricato: %d righe → %s", len(rows_to_load), BQ_TABLE_FULL)


# ── Quality summary ────────────────────────────────────────────────────────────


def quality_summary(rows: list[dict]) -> None:
    from collections import Counter

    by_pasto = Counter(r["tipo_pasto"] for r in rows)
    by_bu = Counter(r["tipo_ospite"] for r in rows)

    # totals per pasto
    totali: dict[str, int] = {}
    for r in rows:
        totali[r["tipo_pasto"]] = totali.get(r["tipo_pasto"], 0) + r["n_coperti"]

    mesi = sorted({(r["anno"], r["mese"]) for r in rows})
    mesi_str = ", ".join(f"{y}-{m:02d}" for y, m in mesi)

    print("\n── QUALITY SUMMARY ──────────────────────────────────────────")
    print(f"  Righe totali (non-zero): {len(rows)}")
    print(f"  Mesi coperti: {mesi_str}")
    print()
    for pasto in sorted(totali.keys()):
        n = totali.get(pasto, 0)
        c = by_pasto.get(pasto, 0)
        print(f"  {pasto:8s}  {c:4d} righe  {n:6d} coperti totali")
    print()
    print("  Distribuzione tipo_ospite:")
    for ospite, cnt in sorted(by_bu.items()):
        tot = sum(r["n_coperti"] for r in rows if r["tipo_ospite"] == ospite)
        print(f"    {ospite:12s}  {cnt:4d} righe  {tot:6d} coperti")
    print("─────────────────────────────────────────────────────────────\n")


# ── CLI ────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Ingest coperti giornalieri → BQ")
    parser.add_argument(
        "--datahub", default=str(DATAHUB_DEFAULT), help="Path datahub root"
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Override cartella sorgente (default: datahub/coperti/)",
    )
    parser.add_argument(
        "--file", default=None, help="Ingest a single XLSX file directly"
    )
    parser.add_argument(
        "--gsheet",
        nargs="?",
        const=GSHEET_ID_DEFAULT,
        default=None,
        help=f"Scarica da Google Sheet via rclone (default ID: {GSHEET_ID_DEFAULT})",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="DELETE-INSERT: cancella tutti i dati esistenti e ricarica",
    )
    parser.add_argument(
        "--societa", default=SOCIETA_ID, help="societa_id (default: ORTI)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Non scrive su BQ, stampa solo il summary",
    )
    args = parser.parse_args()

    from ingest._logging import setup_logging

    setup_logging("ingest_coperti", Path(__file__).parent / "logs")

    ts_now = datetime.now(timezone.utc)

    if args.gsheet:
        # Download from Google Sheet via rclone
        try:
            xlsx_path = fetch_gsheet(args.gsheet)
        except RuntimeError as e:
            log.error("%s", e)
            sys.exit(1)
        rows = parse_xlsx_file(xlsx_path, args.societa, ts_now)
    elif args.file:
        xlsx_path = Path(args.file)
        if not xlsx_path.exists():
            log.error("File non trovato: %s", xlsx_path)
            sys.exit(1)
        rows = parse_xlsx_file(xlsx_path, args.societa, ts_now)
    else:
        source_dir = (
            Path(args.source) if args.source else Path(args.datahub) / "coperti"
        )
        log.info("Sorgente: %s", source_dir)
        rows = collect_all_rows(source_dir, args.societa)

    if not rows:
        log.warning("Nessuna riga da caricare.")
        sys.exit(0)

    pre_dedup = len(rows)
    rows = dedup_latest_wins(rows)
    if len(rows) < pre_dedup:
        log.info(
            "Dedup latest-wins: %d → %d righe (%d submission collassate)",
            pre_dedup,
            len(rows),
            pre_dedup - len(rows),
        )

    load_to_bq(rows, dry_run=args.dry_run, replace=args.replace)
    quality_summary(rows)


if __name__ == "__main__":
    main()
