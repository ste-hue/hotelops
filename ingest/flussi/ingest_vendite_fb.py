#!/usr/bin/env python3
"""
Vendite F&B (POS) → BigQuery f_vendite_fb.

Legge l'export "Consumptions F&B Data.xlsx" da HotelCube/POS — granularità
giorno × sala × articolo — e carica in f_vendite_fb (APPEND, dedup hash_riga).

È il lato RICAVO del food cost: si incrocia con f_consumi_economato (lato
COSTO) tramite v_food_cost_mensile per ottenere food cost ratio per BU/sala/mese.

Pattern: passa dal bq-write-gate (Sprint 1) — Pydantic validation + serialization
boundary check + filter_new_rows_by_hash dedup + PipelineRun lineage.

Usage:
    python -m ingest.flussi.ingest_vendite_fb \\
        --file "/path/to/Consumptions F&B Data.xlsx" --dry-run
    python -m ingest.flussi.ingest_vendite_fb \\
        --file "/path/to/Consumptions F&B Data.xlsx"
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import openpyxl

from core.bq.client import get_client
from core.bq.dedup import filter_new_rows_by_hash
from core.bq.write import bq_write_validated
from core.config import PROJECT
from core.pipeline_run import PipelineRun
from core.schemas import VenditaFbRow

# ── Defaults ──────────────────────────────────────────────────────────────────

BQ_TABLE = f"{PROJECT}.hotelops.f_vendite_fb"
SOCIETA_ID = "ORTI"  # bar/ristorante hotel sono tutti ORTI

log = logging.getLogger("ingest_vendite_fb")


# ── Mapping ───────────────────────────────────────────────────────────────────

# Sala raw (dall'export) → (sala normalizzata, business_unit_id)
SALA_MAP: dict[str, tuple[str, str]] = {
    "BAR": ("BAR", "HOTEL"),
    "RISTO LUNCH": ("RISTO_LUNCH", "HOTEL"),
    "RISTO DINNER": ("RISTO_DINNER", "HOTEL"),
}

# Mese italiano → numero
MESE_IT: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def _make_hash(
    societa: str, data_serv: date, sala: str, codice: str,
    quantita: float, netto: float
) -> str:
    """Hash naturale: una riga = una vendita di articolo X in sala Y a giorno Z.

    NOTA: include quantita+netto perché lo stesso articolo può essere venduto
    più volte nello stesso giorno/sala con quantità/prezzi diversi (sconti,
    happy hour, etc.). Senza questi due campi le righe collasserebbero.
    """
    key = f"{societa}|{data_serv}|{sala}|{codice}|{quantita}|{netto}"
    return hashlib.md5(key.encode()).hexdigest()


def _to_date(anno: int, mese_str: str, giorno: int) -> date | None:
    """Costruisce data da (anno, mese italiano, giorno)."""
    mese = MESE_IT.get(str(mese_str).strip().lower())
    if mese is None:
        return None
    try:
        return date(anno, mese, giorno)
    except (ValueError, TypeError):
        return None


# ── Parsing ────────────────────────────────────────────────────────────────────


def parse_xlsx(filepath: Path) -> list[dict]:
    """Parse il file POS export. Restituisce dict pronti per VenditaFbRow."""
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    log.info(f"Parsing {filepath.name} (sheet: {ws.title})")

    now = datetime.now(timezone.utc)
    records: list[dict] = []
    skipped_no_sala = 0
    skipped_invalid_date = 0
    skipped_no_amount = 0
    skipped_filter_note = 0
    seen_unmapped_sale: set[str] = set()

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # header
        if not row:
            continue

        anno_raw = row[0]
        # Skip the trailing "Applied filters: ..." note row
        if isinstance(anno_raw, str) and "Applied filters" in anno_raw:
            skipped_filter_note += 1
            continue
        try:
            anno = int(anno_raw) if anno_raw is not None else None
        except (TypeError, ValueError):
            skipped_invalid_date += 1
            continue
        if anno is None:
            continue

        mese_raw = row[1]
        giorno_raw = row[2]
        sala_raw = row[3]
        codice = row[4]
        descrizione = row[5]
        tipo = row[6]
        sub_tipo = row[7]
        quantita = row[8]
        lordo = row[9]
        sconto = row[10]
        netto = row[11]
        # row[12] = Menu (non usato), row[13] = Segmento Cliente (Ristocube)
        segmento = (
            str(row[13]).strip()
            if len(row) > 13 and row[13] is not None and str(row[13]).strip()
            else None
        )

        # Skip rows without sala
        if not sala_raw:
            skipped_no_sala += 1
            continue

        sala_key = str(sala_raw).strip().upper()
        if sala_key not in SALA_MAP:
            seen_unmapped_sale.add(sala_key)
            continue
        sala_norm, bu = SALA_MAP[sala_key]

        try:
            giorno = int(giorno_raw)
        except (TypeError, ValueError):
            skipped_invalid_date += 1
            continue

        data_serv = _to_date(anno, mese_raw, giorno)
        if data_serv is None:
            skipped_invalid_date += 1
            continue

        try:
            qta = float(quantita) if quantita is not None else 0.0
            imp_netto = float(netto) if netto is not None else 0.0
            imp_lordo = float(lordo) if lordo is not None else imp_netto
            imp_sconto = float(sconto) if sconto is not None else None
        except (TypeError, ValueError):
            skipped_no_amount += 1
            continue

        records.append(
            {
                "hash_riga": _make_hash(
                    SOCIETA_ID, data_serv, sala_norm,
                    str(codice or ""), qta, imp_netto,
                ),
                "societa_id": SOCIETA_ID,
                "business_unit_id": bu,
                "anno": data_serv.year,
                "mese": data_serv.month,
                "data_servizio": data_serv,
                "sala": sala_norm,
                "codice_articolo": str(codice or "").strip(),
                "descrizione": str(descrizione or "").strip(),
                "tipo_piatto": str(tipo or "").strip(),
                "sub_tipo_piatto": str(sub_tipo).strip() if sub_tipo else None,
                "quantita": qta,
                "importo_lordo": imp_lordo,
                "sconto": imp_sconto,
                "importo_netto": imp_netto,
                "segmento_cliente": segmento,
                "file_sorgente": filepath.name,
                "data_caricamento": now,
            }
        )

    wb.close()

    log.info(f"Parsed: {len(records)} righe")
    if skipped_no_sala or skipped_invalid_date or skipped_no_amount or skipped_filter_note:
        log.info(
            f"Skipped: no_sala={skipped_no_sala} invalid_date={skipped_invalid_date} "
            f"no_amount={skipped_no_amount} filter_note={skipped_filter_note}"
        )
    if seen_unmapped_sale:
        log.warning(f"Sale non mappate (skipped): {sorted(seen_unmapped_sale)}")

    return records


# ── BQ table ───────────────────────────────────────────────────────────────────


def ensure_table(client) -> None:
    """Create f_vendite_fb if missing."""
    from google.cloud import bigquery

    try:
        client.get_table(BQ_TABLE)
        return
    except Exception:
        pass

    schema = [
        bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("business_unit_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("anno", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("mese", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("data_servizio", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("sala", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("codice_articolo", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("descrizione", "STRING"),
        bigquery.SchemaField("tipo_piatto", "STRING"),
        bigquery.SchemaField("sub_tipo_piatto", "STRING"),
        bigquery.SchemaField("quantita", "FLOAT"),
        bigquery.SchemaField("importo_lordo", "FLOAT"),
        bigquery.SchemaField("sconto", "FLOAT"),
        bigquery.SchemaField("importo_netto", "FLOAT"),
        bigquery.SchemaField("segmento_cliente", "STRING"),
        bigquery.SchemaField("file_sorgente", "STRING"),
        bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
    ]
    table = bigquery.Table(BQ_TABLE, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.MONTH,
        field="data_servizio",
    )
    client.create_table(table)
    log.info(f"Created table {BQ_TABLE}")


def _summary(records: list[dict]) -> None:
    from collections import Counter

    by_mese = Counter()
    by_sala = Counter()
    netto_by_mese: dict[tuple, float] = {}
    netto_total = 0.0

    for r in records:
        k = (r["anno"], r["mese"])
        by_mese[k] += 1
        by_sala[r["sala"]] += 1
        netto_by_mese[k] = netto_by_mese.get(k, 0.0) + r["importo_netto"]
        netto_total += r["importo_netto"]

    log.info(f"  SUMMARY: {len(records)} righe, netto totale €{netto_total:,.0f}")
    log.info("  Per mese:")
    for k in sorted(netto_by_mese.keys()):
        log.info(f"    {k[0]}-{k[1]:02d}  {by_mese[k]:>5} righe   €{netto_by_mese[k]:>10,.0f}")
    log.info("  Per sala:")
    for s, n in by_sala.most_common():
        log.info(f"    {s:<15} {n:>5}")


# ── Load ───────────────────────────────────────────────────────────────────────


def load_to_bq(records: list[dict], dry_run: bool = False) -> None:
    """Append-with-dedup tramite il gate Sprint 1."""
    if not records:
        log.warning("Nessuna riga da caricare")
        return

    if dry_run:
        log.info(f"DRY RUN: would load {len(records)} rows to {BQ_TABLE}")
        _summary(records)
        return

    client = get_client()
    ensure_table(client)

    # Dedup vs BQ esistente: filtra le righe il cui hash_riga è già presente
    new_records = filter_new_rows_by_hash(BQ_TABLE, records, "hash_riga")
    if not new_records:
        log.info("Tutte le righe sono già presenti — niente da scrivere")
        return

    pydantic_rows = [VenditaFbRow(**r) for r in new_records]
    bq_write_validated(BQ_TABLE, pydantic_rows, mode="append")
    _summary(new_records)


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest vendite F&B (POS) → f_vendite_fb"
    )
    parser.add_argument("--file", required=True, help="Path al file XLSX export POS")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no BQ write")
    args = parser.parse_args()

    from ingest._logging import setup_logging

    setup_logging("ingest_vendite_fb", Path(__file__).parent / "logs")

    filepath = Path(args.file)
    if not filepath.exists():
        log.error(f"File not found: {filepath}")
        sys.exit(1)

    with PipelineRun(
        "ingest_vendite_fb",
        societa_id=SOCIETA_ID,
        file_sorgente=filepath.name,
    ):
        records = parse_xlsx(filepath)
        if not records:
            log.warning("Nessuna riga estratta")
            sys.exit(0)
        load_to_bq(records, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
