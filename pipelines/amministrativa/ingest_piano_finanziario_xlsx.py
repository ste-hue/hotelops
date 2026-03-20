#!/usr/bin/env python3
"""
Piano Finanziario XLSX → BigQuery f_piano_finanziario_input.

Reads the "Piano Finanziario" sheet from monthly XLSX files (ORTI or INTUR).
Extracts monthly cash flow values for each voce (entrate + uscite).

Column layout (fixed across all monthly files):
  - Cols C-F (3-6): 4 months from prior year (e.g. Sep-Dec 2025)
  - Cols G-R (7-18): 12 months of current year (Jan-Dec 2026)
  - Row 2: month names in Italian (GENNAIO, FEBBRAIO, ...)
  - Row 1: year markers (2025 above C, 2026 above G)

Voce mapping (row → voce_id):
  Row 6:  Entrate Hotel           → ENTRATE_HOTEL
  Row 7:  Entrate Residence       → ENTRATE_RESIDENCE
  Row 8:  Entrate CVM             → ENTRATE_CVM
  Row 9:  Entrate Supermercato    → ENTRATE_SUPERMERCATO
  Row 10: Rientro Sospesi         → ENTRATE_RIENTRO_SOSPESI
  Row 11: Caparre Intur           → ENTRATE_CAPARRE_INTUR
  Row 15: Salari e Stipendi       → USCITE_SALARI
  Row 16: Utenze                  → USCITE_UTENZE
  Row 17: Materie Prime/Consumo   → USCITE_MATERIE_PRIME
  Row 18: Tasse e Imposte         → USCITE_TASSE
  Row 19: Commissioni Portali     → USCITE_COMMISSIONI
  Row 20: Mutui e Finaziamenti    → USCITE_MUTUI
  Row 21: Consulenze              → USCITE_CONSULENZE
  Row 22: Godimento Beni di Terzi → USCITE_GODIMENTO_BENI
  Row 23: Varie ed Eventuali      → USCITE_VARIE
  Row 24: Canoni e servizi        → USCITE_CANONI
  Row 25: Deposito Fitto          → USCITE_DEPOSITO_FITTO

Output: f_piano_finanziario_input (WRITE_APPEND with hash dedup)

Usage:
    python -m pipelines.amministrativa.ingest_piano_finanziario_xlsx \\
        --file "/path/to/ORTI - Piano Finanziario - 03_mar2026.xlsx" --dry-run
    python -m pipelines.amministrativa.ingest_piano_finanziario_xlsx \\
        --dir "/path/to/pianifinanziari/" --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import sys
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

# ── Config ────────────────────────────────────────────────────────────────────

BQ_PROJECT = "hotelops-suite"
BQ_TABLE = f"{BQ_PROJECT}.hotelops.f_piano_finanziario_input"
FONTE = "PIANO_FINANZIARIO"

# Month names → mese number
MESI_IT = {
    "GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4,
    "MAGGIO": 5, "GIUGNO": 6, "LUGLIO": 7, "AGOSTO": 8,
    "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12,
}

# Row → voce_id mapping
# Key: normalized label (first word or common substring)
VOCE_MAP: dict[str, str] = {
    "Entrate Hotel":            "ENTRATE_HOTEL",
    "Entrate Residence":        "ENTRATE_RESIDENCE",
    "Entrate CVM":              "ENTRATE_CVM",
    "Entrate Supermercato":     "ENTRATE_SUPERMERCATO",
    "Rientro Sospesi":          "ENTRATE_RIENTRO_SOSPESI",
    "Caparre Intur":            "ENTRATE_CAPARRE_INTUR",
    "Salari e Stipendi":        "USCITE_SALARI",
    "Utenze":                   "USCITE_UTENZE",
    "Materie Prime/Consumo":    "USCITE_MATERIE_PRIME",
    "Materie Prime":            "USCITE_MATERIE_PRIME",
    "Tasse e Imposte":          "USCITE_TASSE",
    "Commissioni Portali":      "USCITE_COMMISSIONI",
    "Commissioni":              "USCITE_COMMISSIONI",
    "Mutui e Finaziamenti":     "USCITE_MUTUI",
    "Mutui e Finanziamenti":    "USCITE_MUTUI",  # typo variant
    "Consulenze":               "USCITE_CONSULENZE",
    "Godimento Beni di Terzi":  "USCITE_GODIMENTO_BENI",
    "Godimento Beni":           "USCITE_GODIMENTO_BENI",
    "Varie ed Eventuali":       "USCITE_VARIE",
    "Canoni e servizi":         "USCITE_CANONI",
    "Deposito Fitto":           "USCITE_DEPOSITO_FITTO",
    # INTUR-specific voci
    "Fitto Hotel":              "ENTRATE_AFFITTI_INTUR",   # canone ORTI→INTUR (conto 53.xx)
    "Fitto AR":                 "ENTRATE_AFFITTI_INTUR",   # affitto ramo d'azienda (same 53.xx)
    "Entrate Farmacia":         "ENTRATE_AFFITTI_MINORI",  # affitto farmacia (47.95.xx)
    "Entrate Spiaggia":         "ENTRATE_SPIAGGIA",
    "Caparre da girocantare":   "ENTRATE_CAPARRE_INTUR",   # was CAPARRE_GIRO → align to d_voci
    "Godimento Benidi Terzi":   "USCITE_GODIMENTO_BENI",   # INTUR typo
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _v(x) -> float:
    """Coerce cell to float, 0.0 for None/NaN."""
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        import math
        return 0.0 if math.isnan(float(x)) else float(x)
    return 0.0


def make_hash(societa_id: str, voce_id: str, anno: int, mese: int, fonte: str) -> str:
    key = f"{societa_id}|{voce_id}|{anno}|{mese}|{fonte}"
    return hashlib.md5(key.encode()).hexdigest()


def _match_voce(label: str) -> str | None:
    """Match a row label to a voce_id."""
    label_clean = label.strip()
    # Try exact match first
    if label_clean in VOCE_MAP:
        return VOCE_MAP[label_clean]
    # Try prefix match
    for key, voce in VOCE_MAP.items():
        if label_clean.startswith(key) or key.startswith(label_clean):
            return voce
    return None


def _detect_societa(ws) -> str | None:
    """Detect società from cell A1 or A2."""
    for r in (2, 1):
        val = ws.cell(r, 1).value
        if val and isinstance(val, str):
            v = val.strip().upper()
            if "ORTI" in v:
                return "ORTI"
            if "INTUR" in v:
                return "INTUR"
    return None


def _detect_year_and_month_block(ws) -> tuple[int | None, list[tuple[int, int]]]:
    """Detect year and build (col, mese) list for the 12-month 2026 block.

    Strategy: scan row 1 for year markers, then find where the 12 months
    of that year start. Read month names from row 2.

    Returns (anno, [(col, mese), ...])
    """
    # Find the rightmost year marker in row 1 (that's the budget year)
    year_col = None
    anno = None
    for col in range(3, 20):
        val = ws.cell(1, col).value
        if val is not None:
            try:
                y = int(float(val))
                if 2025 <= y <= 2030:
                    year_col = col
                    anno = y
            except (ValueError, TypeError):
                pass

    if not anno or not year_col:
        return None, []

    # Read month names from row 2 starting at year_col
    months = []
    for col in range(year_col, year_col + 12):
        month_name = ws.cell(2, col).value
        if month_name and isinstance(month_name, str):
            mese = MESI_IT.get(month_name.strip().upper())
            if mese:
                months.append((col, mese))

    if len(months) == 12:
        return anno, months

    # Fallback: 12 consecutive months starting at year_col
    return anno, [(year_col + i, i + 1) for i in range(12)]


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_piano_finanziario_xlsx")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
        log.addHandler(h)
    return log


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_piano_finanziario(
    filepath: Path,
    societa_override: str | None,
    logger: logging.Logger,
) -> list[dict]:
    """Parse a Piano Finanziario XLSX file.

    Returns list of dicts ready for f_piano_finanziario_input.
    """
    wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
    now = datetime.now(timezone.utc)

    if "Piano Finanziario" not in wb.sheetnames:
        logger.error(f"Foglio 'Piano Finanziario' non trovato in {filepath.name}")
        wb.close()
        return []

    ws = wb["Piano Finanziario"]

    # Detect società
    societa_id = societa_override or _detect_societa(ws)
    if not societa_id:
        # Try from filename
        name_upper = filepath.name.upper()
        if "INTUR" in name_upper:
            societa_id = "INTUR"
        elif "ORTI" in name_upper:
            societa_id = "ORTI"
        else:
            logger.error(f"Impossibile determinare società da {filepath.name}")
            wb.close()
            return []

    # Detect year and month columns
    anno, month_cols = _detect_year_and_month_block(ws)
    if not anno:
        logger.warning("  Anno non rilevato — default 2026")
        anno = 2026
    if not month_cols:
        logger.error(f"  Colonne mesi non rilevate in {filepath.name}")
        wb.close()
        return []

    records: list[dict] = []
    voci_found = 0
    voci_skipped = 0

    # Scan rows 4-30 for data (entrate: ~6-11, uscite: ~15-25)
    for r in range(4, 35):
        label = ws.cell(r, 1).value
        if not label or not isinstance(label, str):
            continue
        label = label.strip()

        # Skip totals, separators, saldo
        label_upper = label.upper()
        if any(kw in label_upper for kw in ["TOTALE", "SALDO", "CASH FLOW", "===="]):
            continue

        voce_id = _match_voce(label)
        if not voce_id:
            # Check if row has any data
            has_data = any(_v(ws.cell(r, c).value) != 0 for c, _ in month_cols)
            if has_data:
                logger.warning(f"  UNMAPPED row {r}: \"{label}\" — riga saltata")
                voci_skipped += 1
            continue

        voci_found += 1
        for col, mese in month_cols:
            val = _v(ws.cell(r, col).value)
            if val == 0:
                continue

            records.append({
                "hash_riga":        make_hash(societa_id, voce_id, anno, mese, FONTE),
                "societa_id":       societa_id,
                "voce_id":          voce_id,
                "anno":             anno,
                "mese":             mese,
                "importo":          round(val, 2),
                "fonte":            FONTE,
                "note":             None,
                "file_sorgente":    filepath.name,
                "data_caricamento": now.isoformat(),
            })

    wb.close()

    logger.info(
        f"  {societa_id} {anno}: {voci_found} voci, "
        f"{len(records)} righe mensili"
        + (f" ({voci_skipped} voci non mappate)" if voci_skipped else "")
    )

    return records


# ── Pydantic validation ──────────────────────────────────────────────────────

def validate_rows(rows: list[dict], logger: logging.Logger) -> list[dict]:
    try:
        from lib.schemas import PianoFinanziarioInputRow, validate_batch
        validate_batch(rows, PianoFinanziarioInputRow, context="Piano Finanziario XLSX")
        logger.info(f"  Pydantic validation OK: {len(rows)} righe")
    except ImportError:
        logger.warning("  lib.schemas non disponibile — skip Pydantic validation")
    except Exception as e:
        logger.error(f"  Pydantic validation FAILED: {e}")
        sys.exit(1)
    return rows


# ── Quality summary ───────────────────────────────────────────────────────────

def quality_summary(rows: list[dict], logger: logging.Logger) -> None:
    by_voce: dict[str, float] = {}
    for r in rows:
        by_voce[r["voce_id"]] = by_voce.get(r["voce_id"], 0.0) + (r["importo"] or 0)

    logger.info("═" * 56)
    logger.info("  QUALITY SUMMARY — Piano Finanziario → f_piano_finanziario_input")
    logger.info("═" * 56)

    entrate = 0
    uscite = 0
    for voce, total in sorted(by_voce.items()):
        logger.info(f"  {voce:<30s}: {total:>12,.0f} €")
        if voce.startswith("ENTRATE"):
            entrate += total
        else:
            uscite += total

    logger.info(f"  {'─' * 44}")
    logger.info(f"  {'ENTRATE TOTALI':<30s}: {entrate:>12,.0f} €")
    logger.info(f"  {'USCITE TOTALI':<30s}: {uscite:>12,.0f} €")
    logger.info(f"  {'CASH FLOW':<30s}: {entrate + uscite:>12,.0f} €")
    logger.info("═" * 56)


# ── BigQuery ──────────────────────────────────────────────────────────────────

BQ_SCHEMA = [
    bigquery.SchemaField("hash_riga",        "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("societa_id",       "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("voce_id",          "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("anno",             "INTEGER",   mode="REQUIRED"),
    bigquery.SchemaField("mese",             "INTEGER",   mode="REQUIRED"),
    bigquery.SchemaField("importo",          "FLOAT64"),
    bigquery.SchemaField("fonte",            "STRING"),
    bigquery.SchemaField("note",             "STRING"),
    bigquery.SchemaField("file_sorgente",    "STRING"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
] if HAS_BQ else []


def load_to_bq(rows: list[dict], bq_client, logger: logging.Logger) -> None:
    if not rows:
        return

    # Dedup: check existing hashes
    hashes_new = {r["hash_riga"] for r in rows}
    try:
        hashes_str = ", ".join(f"'{h}'" for h in hashes_new)
        result = bq_client.query(
            f"SELECT hash_riga FROM `{BQ_TABLE}` WHERE hash_riga IN ({hashes_str})"
        ).result()
        existing = {row.hash_riga for row in result}
    except Exception:
        existing = set()

    new_rows = [r for r in rows if r["hash_riga"] not in existing]
    logger.info(f"  Nuove: {len(new_rows)}, già presenti: {len(rows) - len(new_rows)}")

    if not new_rows:
        logger.info("  Nessuna nuova riga da caricare")
        return

    job = bq_client.load_table_from_json(
        new_rows, BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
    else:
        logger.info(f"  {BQ_TABLE}: {len(new_rows)} righe inserite")


# ── CSV dump ──────────────────────────────────────────────────────────────────

FIELDS = [
    "hash_riga", "societa_id", "voce_id", "anno", "mese",
    "importo", "fonte", "note", "file_sorgente",
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
        description="Piano Finanziario XLSX → f_piano_finanziario_input"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="Single XLSX file")
    group.add_argument("--dir", help="Directory with multiple XLSX files")
    parser.add_argument("--societa", choices=["ORTI", "INTUR"],
                        help="Override società detection")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--latest-only", action="store_true",
                        help="Only process the most recent file per società")
    args = parser.parse_args()

    logger = setup_logger()

    if not HAS_OPENPYXL:
        logger.error("openpyxl non installato: pip install openpyxl")
        sys.exit(1)

    # Collect files
    if args.file:
        files = [Path(args.file)]
    else:
        dirpath = Path(args.dir)
        files = sorted(dirpath.glob("*.xlsx"))
        files = [f for f in files if not f.name.startswith("~$")]

    if not files:
        logger.error("Nessun file trovato")
        sys.exit(1)

    if args.latest_only:
        # Keep only the most recent file per società
        by_soc: dict[str, Path] = {}
        for f in files:
            name_upper = f.name.upper()
            soc = "INTUR" if "INTUR" in name_upper else "ORTI"
            by_soc[soc] = f  # Last (alphabetically) wins
        files = list(by_soc.values())
        logger.info(f"Latest-only: processing {len(files)} files")

    logger.info(f"Files: {len(files)}")

    all_rows: list[dict] = []
    for filepath in files:
        if not filepath.exists():
            logger.error(f"File non trovato: {filepath}")
            continue
        logger.info(f"→ {filepath.name}")
        rows = parse_piano_finanziario(filepath, args.societa, logger)
        all_rows.extend(rows)

    if not all_rows:
        logger.error("Nessuna riga estratta")
        sys.exit(1)

    # Dedup within batch (same hash = same voce+mese+anno+fonte)
    seen: dict[str, dict] = {}
    for r in all_rows:
        h = r["hash_riga"]
        if h not in seen:
            seen[h] = r
        else:
            # Keep the one from the more recent file
            seen[h] = r  # Last file wins
    all_rows = list(seen.values())

    validate_rows(all_rows, logger)
    quality_summary(all_rows, logger)

    if args.dry_run:
        dump_csv(all_rows, Path(args.output_dir) / "f_piano_finanziario_xlsx.csv", logger)
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
