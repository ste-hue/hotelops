#!/usr/bin/env python3
"""
Bilanci annuali (XBRL markdown) → BigQuery f_bilanci_annuali.

Input: markdown dump di bilancio XBRL scaricato dal Registro Imprese
(formato: `## Bilancio di esercizio al 31-12-YYYY` + tabelle HTML
Stato Patrimoniale e Conto Economico).

Output: una riga per (societa_id, anno, sezione, voce).
Lifecycle: SNAPSHOT per (societa_id, anno) — DELETE + INSERT.

Usage:
    python -m ingest.flussi.ingest_bilanci_annuali --file ~/Downloads/2024_ORTI_Bilancio.md
    python -m ingest.flussi.ingest_bilanci_annuali --file a.md --file b.md --dry-run
    python -m ingest.flussi.ingest_bilanci_annuali --dir ~/Downloads --pattern '*_Bilancio.md'
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.bq.client import get_client
from core.config import F_BILANCI_ANNUALI

SEZIONI = [
    ("SP", re.compile(r"^#\s+Stato patrimoniale", re.MULTILINE)),
    ("CE", re.compile(r"^#\s+Conto economico", re.MULTILINE)),
]

RE_TABLE = re.compile(r"<table>.*?</table>", re.DOTALL)
RE_TR = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
RE_CELL = re.compile(r"<(t[dh])(\s[^>]*)?>(.*?)</\1>", re.DOTALL)
RE_COLSPAN = re.compile(r'colspan=["\']?(\d+)', re.IGNORECASE)
RE_FISCAL_YEAR = re.compile(r"Bilancio di esercizio al 31-12-(\d{4})")
RE_SOCIETA = re.compile(r"\b(ORTI|INTUR)\b")
RE_HEADER_YEAR = re.compile(r"31-12-(\d{4})")


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_bilanci_annuali")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def parse_importo(raw: str) -> float | None:
    """'1.517.236' → 1517236.0, '(195.835)' → -195835.0, '-'/''/' ' → None."""
    s = re.sub(r"\s+", "", raw)
    s = s.replace("&nbsp;", "")
    if not s or s in ("-", "—"):
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    # Italian format: dot = thousands. Remove all dots.
    # If there is a comma it is decimal.
    s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if negative else val


def _cell_text(cell_body: str) -> str:
    # Strip inner tags, markdown bold/italic, and collapse whitespace
    txt = re.sub(r"<[^>]+>", "", cell_body)
    txt = re.sub(r"\*\*([^*]+)\*\*", r"\1", txt)
    txt = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", txt)
    return re.sub(r"\s+", " ", txt).strip()


def parse_table(table_html: str) -> tuple[list[dict], int | None]:
    """Return (rows, header_year). Each row: {gruppo, voce, importo_current, importo_prior}.

    Skips colspan rows (treated as gruppo breadcrumb).
    """
    rows: list[dict] = []
    gruppo = ""
    header_year: int | None = None

    for tr_match in RE_TR.finditer(table_html):
        tr_body = tr_match.group(1)
        cells = []
        for cell_match in RE_CELL.finditer(tr_body):
            tag = cell_match.group(1)
            attrs = cell_match.group(2) or ""
            body = cell_match.group(3)
            colspan_m = RE_COLSPAN.search(attrs)
            colspan = int(colspan_m.group(1)) if colspan_m else 1
            cells.append((tag, colspan, _cell_text(body)))

        if not cells:
            continue

        # Header rows with colspan >= 2 → gruppo breadcrumb
        if len(cells) == 1 and cells[0][1] >= 2:
            txt = cells[0][2]
            if txt and txt.lower() not in ("stato patrimoniale", "conto economico"):
                gruppo = txt
            continue

        # Year header row (contains "31-12-YYYY")
        if header_year is None:
            for _, _, txt in cells:
                m = RE_HEADER_YEAR.search(txt)
                if m:
                    header_year = int(m.group(1))
                    break

        # Data row: expect 3 cells (voce, current, prior)
        if len(cells) >= 3 and cells[0][0] == "td":
            voce = cells[0][2]
            if not voce:
                continue
            cur_raw = cells[1][2]
            prior_raw = cells[2][2]
            cur = parse_importo(cur_raw)
            prior = parse_importo(prior_raw)
            if cur is None and prior is None:
                # section sub-header like "5) altri ricavi e proventi" with empty cols
                # still useful as gruppo context
                gruppo = voce
                continue
            rows.append(
                {
                    "gruppo": gruppo,
                    "voce": voce,
                    "importo_current": cur,
                    "importo_prior": prior,
                }
            )

    return rows, header_year


def parse_bilancio_md(
    path: Path, logger: logging.Logger
) -> tuple[str, int, list[dict]]:
    """Return (societa_id, anno, rows). Rows ready for BQ."""
    text = path.read_text(encoding="utf-8")

    # Detect fiscal year
    year_m = RE_FISCAL_YEAR.search(text)
    if not year_m:
        raise ValueError(
            f"{path.name}: anno non rilevato (cerca 'Bilancio di esercizio al 31-12-YYYY')"
        )
    anno = int(year_m.group(1))

    # Detect societa
    soc_m = RE_SOCIETA.search(text)
    if not soc_m:
        raise ValueError(f"{path.name}: società non rilevata (ORTI/INTUR)")
    societa_id = soc_m.group(1)

    logger.info(f"{path.name} → {societa_id} {anno}")

    # Split by sections and parse tables
    out_rows: list[dict] = []
    positions = []
    for sez, pat in SEZIONI:
        for m in pat.finditer(text):
            positions.append((m.start(), sez))
    positions.sort()

    # For each section, take the first <table> after its header
    # up to the next section start
    for i, (start, sez) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        segment = text[start:end]
        tbl_m = RE_TABLE.search(segment)
        if not tbl_m:
            logger.warning(f"  {sez}: nessuna tabella trovata")
            continue
        rows, header_year = parse_table(tbl_m.group(0))
        if header_year and header_year != anno:
            logger.warning(f"  {sez}: header year {header_year} ≠ fiscal year {anno}")
        for r in rows:
            if r["importo_current"] is None:
                continue
            out_rows.append(
                {
                    "societa_id": societa_id,
                    "anno": anno,
                    "sezione": sez,
                    "gruppo": r["gruppo"] or None,
                    "voce": r["voce"],
                    "voce_norm": normalize_voce(r["voce"]),
                    "importo_eur": r["importo_current"],
                    "fonte_file": path.name,
                }
            )
        logger.info(
            f"  {sez}: {sum(1 for r in rows if r['importo_current'] is not None)} righe con importo"
        )

    return societa_id, anno, out_rows


def normalize_voce(voce: str) -> str:
    s = voce.lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return s


BQ_SCHEMA = (
    [
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("anno", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("sezione", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("gruppo", "STRING"),
        bigquery.SchemaField("voce", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("voce_norm", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("importo_eur", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("fonte_file", "STRING"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    if HAS_BQ
    else []
)


def ensure_table(client, logger: logging.Logger) -> None:
    try:
        client.get_table(F_BILANCI_ANNUALI)
        return
    except Exception:
        pass
    logger.info(f"Creo tabella {F_BILANCI_ANNUALI}")
    table = bigquery.Table(F_BILANCI_ANNUALI, schema=BQ_SCHEMA)
    client.create_table(table)


def write_snapshot(client, rows: list[dict], logger: logging.Logger) -> None:
    if not rows:
        return
    # Group by (societa_id, anno) for DELETE-INSERT
    keys = {(r["societa_id"], r["anno"]) for r in rows}
    ensure_table(client, logger)
    for soc, anno in sorted(keys):
        q = (
            f"DELETE FROM `{F_BILANCI_ANNUALI}` "
            f"WHERE societa_id = '{soc}' AND anno = {anno}"
        )
        client.query(q).result()
        logger.info(f"DELETE {soc} {anno}")

    ingested_at = datetime.now(timezone.utc).isoformat()
    for r in rows:
        r["ingested_at"] = ingested_at

    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(rows, F_BILANCI_ANNUALI, job_config=job_config)
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
        sys.exit(1)
    logger.info(f"INSERT {len(rows)} righe → {F_BILANCI_ANNUALI}")


def main():
    ap = argparse.ArgumentParser(
        description="Ingest bilanci annuali XBRL markdown → BQ"
    )
    ap.add_argument(
        "--file", action="append", default=[], help="File markdown (ripetibile)"
    )
    ap.add_argument("--dir", help="Directory con file markdown")
    ap.add_argument("--pattern", default="*_Bilancio.md", help="Glob per --dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logger = setup_logger()

    files: list[Path] = [Path(f) for f in args.file]
    if args.dir:
        files.extend(sorted(Path(args.dir).glob(args.pattern)))
    if not files:
        logger.error("Nessun file specificato (--file o --dir)")
        sys.exit(1)

    all_rows: list[dict] = []
    for f in files:
        if not f.exists():
            logger.error(f"File non trovato: {f}")
            continue
        try:
            _, _, rows = parse_bilancio_md(f, logger)
            all_rows.extend(rows)
        except Exception as e:
            logger.error(f"{f.name}: {e}")

    logger.info(f"Totale righe parsate: {len(all_rows)}")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        # Print sample
        for r in all_rows[:5]:
            logger.info(
                f"  {r['societa_id']} {r['anno']} {r['sezione']} | {r['voce']} = {r['importo_eur']:,.2f}"
            )
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    client = get_client()
    write_snapshot(client, all_rows, logger)
    logger.info("DONE")


if __name__ == "__main__":
    main()
