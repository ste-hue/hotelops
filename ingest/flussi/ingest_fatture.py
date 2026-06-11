#!/usr/bin/env python3
"""
Lista fatture Esolver (acquisto/vendita, dettagliata) → BigQuery f_fatture_righe.

Export "Lista fatture acquisto/vendita per numero dettagliata": una riga per
contropartita con cod_conto + imponibile. Complementare a f_movimenti_contabili
(scope = solo prima nota, decisione 2026-06-04): insieme coprono il CE completo.

Due layout, rilevati dal contenuto (colonna registro: "Acquisti" / "Vendite"):
- ACQUISTI: senza header row, ~78 colonne
- VENDITE:  con header row, ~96 colonne

NC/ANC vengono scritte con imponibile NEGATIVO (segno già applicato): le viste
a valle sommano senza dover conoscere la sigla documento.

Usage:
    python -m ingest.flussi.ingest_fatture --file <xlsx> --societa ORTI --dry-run
    python -m ingest.flussi.ingest_fatture --file <xlsx> --societa ORTI --raw-object-id <id>
"""

import argparse
import hashlib
import logging
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import openpyxl

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.config import F_FATTURE_RIGHE

BQ_TABLE = F_FATTURE_RIGHE

# Sigle semplici (FT, NC, AFT...) e composte (FT-UE, AFT-UE, FT-RC: reverse charge/UE)
DOC_PATTERN = re.compile(
    r"([A-Z]{2,4}(?:-[A-Z]{2,4})?)\s+n\.\s*(\d+)\s+del\s+(\d{2}/\d{2}/\d{2})"
)

# Column maps per layout (0-based). Verified on export reali 2026-06-11.
COLMAP = {
    "ACQUISTO": {
        "registro": 6,
        "cod_registro": 7,
        "tipo_registrazione": 8,
        "num_doc_originale": 9,
        "cod_clifor": 10,
        "rag_sociale": 11,
        "des_conto": 44,
        "imponibile": 56,
        "cod_conto": 57,
        "cod_iva": 58,
        "tot_documento": 68,
    },
    "VENDITA": {
        "registro": 6,
        "cod_registro": 7,
        "tipo_registrazione": 8,
        "num_doc_originale": None,
        "cod_clifor": 9,
        "rag_sociale": 10,
        "des_conto": 55,
        "imponibile": 68,
        "cod_conto": 69,
        "cod_iva": 70,
        "tot_documento": 89,
    },
}

BQ_SCHEMA = (
    [
        bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tipo_registro", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("cod_registro", "STRING"),
        bigquery.SchemaField("sigla_doc", "STRING"),
        bigquery.SchemaField("num_registrazione", "INTEGER"),
        bigquery.SchemaField("data_registrazione", "DATE"),
        bigquery.SchemaField("anno", "INTEGER"),
        bigquery.SchemaField("mese", "INTEGER"),
        bigquery.SchemaField("tipo_registrazione", "STRING"),
        bigquery.SchemaField("num_doc_originale", "STRING"),
        bigquery.SchemaField("cod_clifor", "STRING"),
        bigquery.SchemaField("rag_sociale", "STRING"),
        bigquery.SchemaField("des_conto", "STRING"),
        bigquery.SchemaField("cod_conto", "STRING"),
        bigquery.SchemaField("cod_iva", "STRING"),
        bigquery.SchemaField("imponibile", "FLOAT64"),
        bigquery.SchemaField("tot_documento", "FLOAT64"),
        bigquery.SchemaField("file_sorgente", "STRING"),
        bigquery.SchemaField("data_ingresso", "DATE"),
        bigquery.SchemaField("raw_object_id", "STRING"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_fatture")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        log.addHandler(h)
    return log


def detect_tipo_registro(rows: list[tuple]) -> str:
    """Detect ACQUISTO/VENDITA from the registro column of the first data row."""
    for row in rows:
        if not row or len(row) < 7:
            continue
        if not DOC_PATTERN.match(str(row[5] or "")):
            continue
        registro = str(row[6] or "").strip().lower()
        if registro.startswith("acquist"):
            return "ACQUISTO"
        if registro.startswith("vendit"):
            return "VENDITA"
    raise ValueError(
        "Layout non riconosciuto: nessuna riga con riferimento documento "
        "(es. 'FT n. 1 del 04/01/25') e registro Acquisti/Vendite"
    )


def make_hash(
    societa_id: str,
    tipo_registro: str,
    sigla_doc: str,
    num_registrazione: int,
    data_reg_iso: str,
    cod_conto: str,
    cod_iva: str,
    imponibile: float,
    occorrenza: int,
) -> str:
    """Content hash stabile tra export sovrapposti.

    Esclude le colonne volatili dell'export (timestamp di stampa, operatore,
    contatori pagina). `occorrenza` disambigua righe identiche dentro lo
    stesso documento (stesso conto, stessa IVA, stesso importo).
    """
    key = "|".join(
        [
            societa_id,
            tipo_registro,
            sigla_doc,
            str(num_registrazione),
            data_reg_iso,
            cod_conto,
            cod_iva or "",
            f"{imponibile:.2f}",
            str(occorrenza),
        ]
    )
    return hashlib.md5(key.encode()).hexdigest()


def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def parse_file(filepath: Path, societa_id: str, logger: logging.Logger) -> list[dict]:
    today = date.today().isoformat()
    file_sorgente = filepath.name

    wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    raw_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    tipo_registro = detect_tipo_registro(raw_rows)
    cm = COLMAP[tipo_registro]
    logger.info(
        f"  {file_sorgente}: layout {tipo_registro}, {len(raw_rows)} righe excel"
    )

    rows = []
    skipped = 0
    occ_counter: Counter = Counter()

    for raw in raw_rows:
        if not raw or len(raw) <= cm["tot_documento"]:
            skipped += 1
            continue
        m = DOC_PATTERN.match(str(raw[5] or ""))
        if not m:
            skipped += 1
            continue

        sigla_doc, num_reg, data_str = m.group(1), int(m.group(2)), m.group(3)
        data_reg = datetime.strptime(data_str, "%d/%m/%y").date()

        cod_conto = str(raw[cm["cod_conto"]] or "").strip()
        if not cod_conto:
            skipped += 1
            continue

        imponibile = _num(raw[cm["imponibile"]])
        if imponibile is None:
            skipped += 1
            continue
        segno = -1.0 if sigla_doc.startswith(("NC", "ANC")) else 1.0
        imponibile_signed = segno * imponibile

        cod_iva = str(raw[cm["cod_iva"]] or "").strip()
        cod_registro = str(raw[cm["cod_registro"]] or "").strip()

        cod_clifor_raw = raw[cm["cod_clifor"]]
        cod_clifor = (
            str(int(cod_clifor_raw))
            if isinstance(cod_clifor_raw, (int, float))
            else (str(cod_clifor_raw).strip() if cod_clifor_raw else None)
        )
        rag_sociale = (
            str(raw[cm["rag_sociale"]]).strip() if raw[cm["rag_sociale"]] else None
        )
        des_conto = str(raw[cm["des_conto"]]).strip() if raw[cm["des_conto"]] else None
        num_doc_orig = None
        if cm["num_doc_originale"] is not None and raw[cm["num_doc_originale"]]:
            num_doc_orig = str(raw[cm["num_doc_originale"]]).strip()
        tipo_registrazione = (
            str(raw[cm["tipo_registrazione"]]).strip()
            if raw[cm["tipo_registrazione"]]
            else None
        )
        tot_documento = _num(raw[cm["tot_documento"]])

        occ_key = (
            sigla_doc,
            num_reg,
            data_reg.isoformat(),
            cod_conto,
            cod_iva,
            f"{imponibile_signed:.2f}",
        )
        occorrenza = occ_counter[occ_key]
        occ_counter[occ_key] += 1

        hash_riga = make_hash(
            societa_id,
            tipo_registro,
            sigla_doc,
            num_reg,
            data_reg.isoformat(),
            cod_conto,
            cod_iva,
            imponibile_signed,
            occorrenza,
        )

        rows.append(
            {
                "hash_riga": hash_riga,
                "societa_id": societa_id,
                "tipo_registro": tipo_registro,
                "cod_registro": cod_registro or None,
                "sigla_doc": sigla_doc,
                "num_registrazione": num_reg,
                "data_registrazione": data_reg.isoformat(),
                "anno": data_reg.year,
                "mese": data_reg.month,
                "tipo_registrazione": tipo_registrazione,
                "num_doc_originale": num_doc_orig,
                "cod_clifor": cod_clifor,
                "rag_sociale": rag_sociale,
                "des_conto": des_conto,
                "cod_conto": cod_conto,
                "cod_iva": cod_iva or None,
                "imponibile": imponibile_signed,
                "tot_documento": tot_documento,
                "file_sorgente": file_sorgente,
                "data_ingresso": today,
                "raw_object_id": None,
            }
        )

    dup_interni = sum(1 for v in occ_counter.values() if v > 1)
    if dup_interni:
        logger.warning(
            f"  {dup_interni} chiavi con righe identiche nello stesso documento "
            f"(disambiguate con contatore occorrenza)"
        )
    logger.info(
        f"  {tipo_registro} {societa_id}: {len(rows)} righe, {skipped} scartate"
    )
    return rows


def load_hashes_bq(
    bq_client, societa_id: str, tipo_registro: str, logger: logging.Logger
) -> set:
    try:
        result = bq_client.query(
            f"SELECT hash_riga FROM `{BQ_TABLE}` "
            f"WHERE societa_id = '{societa_id}' AND tipo_registro = '{tipo_registro}'"
        ).result()
        hashes = {row.hash_riga for row in result}
        logger.info(
            f"  Hashes BQ esistenti {societa_id}/{tipo_registro}: {len(hashes)}"
        )
        return hashes
    except Exception as e:
        logger.warning(f"  Impossibile caricare hashes BQ: {e}")
        return set()


def write_to_bq(rows: list[dict], bq_client, logger: logging.Logger):
    if not rows:
        logger.info("  BQ: nessuna nuova riga")
        return
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = bq_client.load_table_from_json(rows, BQ_TABLE, job_config=job_config)
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
        sys.exit(1)
    logger.info(f"  BQ: {len(rows)} righe → {BQ_TABLE}")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Lista fatture Esolver (dettagliata) → f_fatture_righe"
    )
    parser.add_argument("--file", required=True, help="Export XLSX dettagliato")
    parser.add_argument("--societa", choices=["ORTI", "INTUR"], required=True)
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    parser.add_argument(
        "--raw-object-id",
        default=None,
        help="Lineage raw_object_id (promote subprocess contract): stamped on every row",
    )
    args = parser.parse_args()

    logger = setup_logger()
    rows = parse_file(Path(args.file), args.societa, logger)
    if not rows:
        logger.error("Nessuna riga estratta — layout inatteso?")
        sys.exit(1)

    if args.raw_object_id:
        for r in rows:
            r["raw_object_id"] = args.raw_object_id
        logger.info(f"  lineage raw_object_id: {args.raw_object_id}")

    tot = sum(r["imponibile"] for r in rows)
    logger.info(f"  Totale imponibile (NC negate): {tot:,.2f}")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    from core.bq.client import get_client

    bq_client = get_client()
    tipo_registro = rows[0]["tipo_registro"]
    existing = load_hashes_bq(bq_client, args.societa, tipo_registro, logger)
    new_rows = [r for r in rows if r["hash_riga"] not in existing]
    logger.info(
        f"  {len(new_rows)} nuove, {len(rows) - len(new_rows)} già presenti (dedup)"
    )
    write_to_bq(new_rows, bq_client, logger)
    logger.info("DONE")


if __name__ == "__main__":
    main()
