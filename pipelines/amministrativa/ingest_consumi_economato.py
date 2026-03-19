#!/usr/bin/env python3
"""
Consumi economato → BigQuery f_consumi_economato.

Legge tutti gli xlsx da datahub/ingresso/economato_ingresso/ (struttura a cartelle
per reparto). Idempotente: usa hash_riga per non duplicare righe già caricate.

Per aggiungere nuovi mesi: metti i file xlsx nella cartella del reparto in
ingresso/economato_ingresso/ e riesegui — solo le righe nuove vengono aggiunte.

Cartelle in mappature/economato_reparti.csv → reparto/funzione/BU noti.
Cartelle sconosciute → EVENTO automatico (is_evento=true, evento_nome=nome cartella).

Usage:
    python -m pipelines.amministrativa.ingest_consumi_economato --dry-run
    python -m pipelines.amministrativa.ingest_consumi_economato
    python -m pipelines.amministrativa.ingest_consumi_economato \\
        --datahub "/path/to/hotelops_datahub"

Output BQ: f_consumi_economato  (WRITE_APPEND + dedup via hash_riga)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import sys
import unicodedata
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

DATAHUB_DEFAULT = Path(
    "/Users/stefanodellapietra/Library/CloudStorage/"
    "GoogleDrive-stefano@panoramagroup.it/My Drive/hotelops_datahub"
)
# Source = datahub/ingresso/economato_ingresso/ (struttura a cartelle per reparto)
SOURCE_DEFAULT = DATAHUB_DEFAULT / "ingresso" / "economato_ingresso"

BQ_PROJECT = "hotelops-suite"
BQ_TABLE   = f"{BQ_PROJECT}.hotelops.f_consumi_economato"
SOCIETA_ID = "ORTI"


# ── Reparto mapping ────────────────────────────────────────────────────────────

def load_reparto_mapping(datahub: Path) -> dict[str, dict]:
    """
    Loads economato_reparti.csv from datahub/dimensioni/mappature/.
    Returns dict: folder_key_lower → {reparto_id, funzione_id, business_unit_id, is_evento}
    """
    path = datahub / "dimensioni" / "mappature" / "economato_reparti.csv"
    if not path.exists():
        return {}
    mapping = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = unicodedata.normalize("NFC", row["folder_key"]).strip().lower()
            mapping[key] = {
                "reparto_id":       row["reparto_id"].strip(),
                "funzione_id":      row["funzione_id"].strip(),
                "business_unit_id": row["business_unit_id"].strip(),
                "is_evento":        row["is_evento"].strip().lower() == "true",
                "note":             row.get("note", "").strip(),
            }
    return mapping


def folder_to_key(folder_name: str) -> str:
    """
    Normalize folder name to a lookup key.
    'BRK Consumi 2025'         → 'brk'
    'Cucina_Consumi_2025'       → 'cucina'
    'HSK HOTEL Consumi_2025'    → 'hsk hotel'
    'Cucinelli_Consumi_2025'    → 'cucinelli'  ← unknown → EVENTO
    """
    s = folder_name
    # strip trailing year-related suffix
    s = re.sub(r'[\s_]+consumi[\s_]+\d{4}$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[\s_]+\d{4}$', '', s)
    s = unicodedata.normalize("NFC", s).strip().lower().replace("_", " ")
    return s


def resolve_reparto(folder_name: str, mapping: dict[str, dict]) -> dict:
    """
    Returns dimension info for a folder.
    Unknown folders → EVENTO with evento_nome = cleaned folder name.
    """
    key = folder_to_key(folder_name)
    if key in mapping:
        return dict(mapping[key])

    # Auto-detect as event: extract clean name
    evento_nome = re.sub(r'[\s_]+consumi[\s_]+\d{4}$', '', folder_name, flags=re.IGNORECASE).strip()
    evento_nome = re.sub(r'[\s_]+\d{4}$', '', evento_nome).strip()

    return {
        "reparto_id":       "EVENTO",
        "funzione_id":      "EVENTO",
        "business_unit_id": "HOTEL",
        "is_evento":        True,
        "evento_nome":      evento_nome,
    }


# ── Parse one xlsx file ────────────────────────────────────────────────────────

def evento_nome_from_filename(path: Path) -> str:
    """
    Estrae evento_nome dal nome file per file dentro la cartella eventi/.
    '04_Cucinelli Consumi_Aprile 2025.xlsx' → 'Cucinelli'
    """
    stem = path.stem
    stem = re.sub(r'^\d{2}[_\s]+', '', stem)          # rimuovi prefisso mese
    stem = re.sub(r'[\s_]+consumi[\s_\w]*$', '', stem, flags=re.IGNORECASE)
    return stem.strip() or path.stem


def parse_xlsx(path: Path, anno: int, dim: dict, logger: logging.Logger) -> list[dict]:
    """
    Parses one consumption xlsx file.

    Expected columns (Sheet1):
      Codice, Descrizione, Data, Reparto, Classe, Categoria, SubCateg.,
      U.M.A., U.M.C., Coeff Conv, Quantita, Euro
    """
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as e:
        logger.warning(f"  Impossibile leggere {path.name}: {e}")
        return []

    ws = wb.active
    rows_raw = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows_raw:
        return []

    # Find header row
    header = None
    data_start = 0
    for i, row in enumerate(rows_raw):
        if row and row[0] and str(row[0]).strip().lower() in ("codice", "cod.", "reparto"):
            header = [str(c).strip() if c else "" for c in row]
            data_start = i + 1
            break

    if header is None:
        header = [str(c).strip() if c else "" for c in rows_raw[0]]
        data_start = 1

    # Detect format: 2024 has "Reparto" in col 0, no "Data" column
    fmt_2024 = header[0].lower() == "reparto" and not any(h.lower() == "data" for h in header)

    # Column indices (case-insensitive)
    def ci(name: str) -> int:
        for i, h in enumerate(header):
            if h.lower().startswith(name.lower()):
                return i
        return -1

    col_codice  = ci("codice")
    col_desc    = ci("descri")
    col_classe  = ci("classe")
    col_cat     = ci("categor")
    col_qtq     = ci("quantit")

    if fmt_2024:
        col_importo = ci("primo")   # "Primo Per." = euro consumato nel periodo
    else:
        col_importo = ci("euro")
        col_data    = ci("data")
        col_subcat  = ci("subcateg")

    now = datetime.now(timezone.utc)
    records: list[dict] = []

    # Se siamo nella cartella generica "eventi", estrai nome dall'filename
    evento_nome = dim.get("evento_nome", "")
    if dim.get("is_evento") and evento_nome.lower() in ("eventi", "eventi 2024", "eventi 2025", "eventi 2026", ""):
        evento_nome = evento_nome_from_filename(path)

    # Mese da filename (usato per 2024 e come fallback)
    mese_filename = None
    m = re.search(r'^(\d{2})_', path.name)
    if m:
        mese_filename = int(m.group(1))

    for row in rows_raw[data_start:]:
        if not row or len(row) <= col_codice:
            continue

        codice = str(row[col_codice]).strip() if col_codice >= 0 and row[col_codice] else ""
        if not codice or codice.lower() in ("codice", "totale", ""):
            continue

        desc      = str(row[col_desc]).strip()   if col_desc >= 0 and row[col_desc] else ""
        classe    = str(row[col_classe]).strip()  if col_classe >= 0 and row[col_classe] else ""
        categoria = str(row[col_cat]).strip()     if col_cat >= 0 and row[col_cat] else ""
        quantita  = float(row[col_qtq])           if col_qtq >= 0 and isinstance(row[col_qtq], (int, float)) else 0.0
        importo   = float(row[col_importo])       if col_importo >= 0 and isinstance(row[col_importo], (int, float)) else 0.0

        if fmt_2024:
            mese = mese_filename
            subcat = ""
            reparto_r = ""
        else:
            data_cell = row[col_data] if col_data >= 0 else None
            mese = data_cell.month if isinstance(data_cell, datetime) else mese_filename
            subcat    = str(row[col_subcat]).strip() if col_subcat >= 0 and row[col_subcat] else ""
            reparto_r = str(row[ci("reparto")]).strip() if ci("reparto") >= 0 and row[ci("reparto")] else ""

        if mese is None:
            continue

        # Clean trailing dashes (e.g. "BEVERAGE - ")
        classe    = classe.rstrip(" -").strip()
        categoria = categoria.rstrip(" -").strip()
        subcat    = subcat.rstrip(" -").strip()

        # Dedup hash
        hash_src = f"{SOCIETA_ID}|{anno}|{mese}|{dim['reparto_id']}|{codice}|{quantita}|{importo}"
        hash_riga = hashlib.md5(hash_src.encode()).hexdigest()

        records.append({
            "hash_riga":         hash_riga,
            "societa_id":        SOCIETA_ID,
            "anno":              anno,
            "mese":              mese,
            "business_unit_id":  dim["business_unit_id"],
            "funzione_id":       dim["funzione_id"],
            "reparto_id":        dim["reparto_id"],
            "reparto_raw":       reparto_r,
            "is_evento":         dim["is_evento"],
            "evento_nome":       evento_nome if dim["is_evento"] else "",
            "codice_prodotto":   codice,
            "descrizione":       desc,
            "classe":            classe,
            "categoria_prodotto":categoria,
            "sottocategoria":    subcat,
            "quantita":          quantita,
            "importo":           round(importo, 4),
            "file_sorgente":     path.name,
            "data_caricamento":  now.isoformat(),
        })

    return records


# ── Walk source folder ─────────────────────────────────────────────────────────

def collect_all(source: Path, anno: int, mapping: dict[str, dict],
                logger: logging.Logger) -> list[dict]:
    """Walk source tree, parse all xlsx, return all records."""
    all_rows: list[dict] = []
    unknown_folders: set[str] = set()

    for folder in sorted(source.iterdir()):
        if not folder.is_dir():
            continue

        dim = resolve_reparto(folder.name, mapping)
        key = folder_to_key(folder.name)

        if dim["is_evento"] and key not in mapping:
            unknown_folders.add(dim.get("evento_nome", folder.name))

        xlsx_files = sorted(folder.glob("*.xlsx"))
        if not xlsx_files:
            continue

        folder_rows = 0
        for xlsx in xlsx_files:
            rows = parse_xlsx(xlsx, anno, dim, logger)
            all_rows.extend(rows)
            folder_rows += len(rows)

        tag = f"EVENTO:{dim.get('evento_nome','')}" if dim["is_evento"] else dim["reparto_id"]
        logger.info(f"  {tag:<25} {len(xlsx_files)} file  →  {folder_rows} righe")

    if unknown_folders:
        logger.info(f"  Auto-taggati come EVENTO: {sorted(unknown_folders)}")

    return all_rows


# ── BigQuery ──────────────────────────────────────────────────────────────────

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
] if HAS_BQ else []


def load_to_bq(rows: list[dict], bq_client, logger: logging.Logger) -> None:
    if not rows:
        logger.warning("Nessuna riga da caricare")
        return

    # Dedup: delete existing rows with same hash_riga to allow re-runs
    logger.info(f"  Caricamento {len(rows)} righe → {BQ_TABLE}")
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
    logger.info(f"  ✓ {len(rows)} righe caricate")


# ── CSV dump ──────────────────────────────────────────────────────────────────

FIELDS = [
    "hash_riga", "societa_id", "anno", "mese",
    "business_unit_id", "funzione_id", "reparto_id", "reparto_raw",
    "is_evento", "evento_nome",
    "codice_prodotto", "descrizione", "classe", "categoria_prodotto", "sottocategoria",
    "quantita", "importo", "file_sorgente",
]


def dump_csv(rows: list[dict], path: Path, logger: logging.Logger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    logger.info(f"  CSV: {path}  ({len(rows)} righe)")


# ── Quality summary ───────────────────────────────────────────────────────────

def quality_summary(rows: list[dict], logger: logging.Logger) -> None:
    by_funzione: dict[str, float] = {}
    by_mese: dict[int, float] = {}
    eventi: set[str] = set()
    for r in rows:
        f = r["funzione_id"]
        by_funzione[f] = by_funzione.get(f, 0.0) + r["importo"]
        by_mese[r["mese"]] = by_mese.get(r["mese"], 0.0) + r["importo"]
        if r["is_evento"] and r["evento_nome"]:
            eventi.add(r["evento_nome"])

    logger.info("═" * 52)
    logger.info("  QUALITY SUMMARY — f_consumi_economato")
    logger.info("═" * 52)
    logger.info("  Per funzione:")
    for f, tot in sorted(by_funzione.items(), key=lambda x: -x[1]):
        logger.info(f"    {f:<20} {tot:>10,.2f} €")
    logger.info("  Per mese:")
    for m, tot in sorted(by_mese.items()):
        logger.info(f"    Mese {m:02d}              {tot:>10,.2f} €")
    if eventi:
        logger.info(f"  Eventi: {sorted(eventi)}")
    logger.info(f"  Totale righe: {len(rows)}")
    logger.info(f"  Totale importo: {sum(r['importo'] for r in rows):,.2f} €")
    logger.info("═" * 52)


# ── Main ──────────────────────────────────────────────────────────────────────

def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_consumi_economato")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
        log.addHandler(h)
    return log


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consumi economato → f_consumi_economato"
    )
    parser.add_argument("--source",  default=str(SOURCE_DEFAULT),
                        help="Cartella root con i file consumi (default: Consumi_Economato_2025)")
    parser.add_argument("--datahub", default=str(DATAHUB_DEFAULT),
                        help="Path locale del datahub (per caricare economato_reparti.csv)")
    parser.add_argument("--anno",    type=int, default=2025)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    logger = setup_logger()

    if not HAS_OPENPYXL:
        logger.error("openpyxl non installato: pip install openpyxl")
        sys.exit(1)

    source  = Path(args.source)
    datahub = Path(args.datahub)

    if not source.exists():
        logger.error(f"Source non trovato: {source}")
        sys.exit(1)

    mapping = load_reparto_mapping(datahub)
    logger.info(f"Mapping caricato: {len(mapping)} reparti noti")
    logger.info(f"Source: {source}")
    logger.info(f"Anno:   {args.anno}  |  dry-run: {args.dry_run}")

    all_rows = collect_all(source, args.anno, mapping, logger)
    quality_summary(all_rows, logger)

    if args.dry_run:
        dump_csv(all_rows, Path(args.output_dir) / "f_consumi_economato.csv", logger)
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
