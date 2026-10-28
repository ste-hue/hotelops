#!/usr/bin/env python3
"""Archivio rotazioni PF — tiene OGNI rotazione, taggata per file_sorgente.

Carica i Piano Finanziario (parsati dal parser esistente) in `f_pf_rotazioni`.
La chiave hash include `file_sorgente` → nessuna vintage sovrascrive l'altra:
marzo, aprile, maggio… coesistono. Tabella SEPARATA da `f_piano_finanziario_input`
(la cassa live NON si muove). Idempotente: ricaricare lo stesso file lo rimpiazza
(DELETE per file_sorgente + INSERT).

Chiave di riga (convenzione dal 29/10/2026):
    societa_id | voce_id | anno | mese | fonte | file_sorgente | occorrenza
`occorrenza` numera 1..N le righe dello stesso file che condividono la chiave
naturale — il foglio porta legittimamente due righe sulla stessa voce e mese
(INTUR_PF_2026-07: «Fitto Hotel» 488.000 e «Fitto AR» 60.000 a luglio, entrambe
ENTRATE_AFFITTI_INTUR; lo stesso in INTUR_PF_2026-06 a giugno e agosto) —
nell'ordine in cui il parser le restituisce, cioè l'ordine del foglio: stesso
file, stessi hash a ogni ricarico. La chiave precedente non aveva `occorrenza`
e quelle righe collidevano (3 su 22 file). Una tabella, una convenzione: il
passaggio richiede UN ricarico di tutti i file presenti nella stessa finestra.

Usage:
    python -m core.bq.load.load_pf_rotazioni ORTI_PF_2026_03.xlsx ORTI_PF_2026-05.xlsx
    python -m core.bq.load.load_pf_rotazioni --dry-run *.xlsx
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from core.bq.client import get_client
from core.config import F_PF_ROTAZIONI
from ingest.flussi.ingest_piano_finanziario_xlsx import (
    parse_piano_finanziario,
    setup_logger,
)

BQ_TABLE = F_PF_ROTAZIONI

SCHEMA = [
    bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("societa_id", "STRING"),
    bigquery.SchemaField("voce_id", "STRING"),
    bigquery.SchemaField("anno", "INTEGER"),
    bigquery.SchemaField("mese", "INTEGER"),
    bigquery.SchemaField("importo", "FLOAT64"),
    bigquery.SchemaField("fonte", "STRING"),
    bigquery.SchemaField("file_sorgente", "STRING"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
]


FONTE_DEFAULT = "PIANO_FINANZIARIO"


def _chiave(r: dict) -> tuple:
    return (
        r["societa_id"],
        r["voce_id"],
        r["anno"],
        r["mese"],
        r.get("fonte", FONTE_DEFAULT),
        r["file_sorgente"],
    )


def _hash(r: dict, occorrenza: int) -> str:
    """md5 di societa|voce|anno|mese|fonte|file_sorgente|occorrenza (vedi docstring del modulo)."""
    key = "|".join(str(x) for x in (*_chiave(r), occorrenza))
    return hashlib.md5(key.encode()).hexdigest()


def build_rows(paths: list[Path], logger) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for p in paths:
        viste: Counter[tuple] = Counter()
        for r in parse_piano_finanziario(p, None, logger):
            chiave = _chiave(r)
            viste[chiave] += 1
            out.append(
                {
                    "hash_riga": _hash(r, viste[chiave]),
                    "societa_id": r["societa_id"],
                    "voce_id": r["voce_id"],
                    "anno": r["anno"],
                    "mese": r["mese"],
                    "importo": r.get("importo"),
                    "fonte": r.get("fonte", FONTE_DEFAULT),
                    "file_sorgente": r["file_sorgente"],
                    "data_caricamento": now,
                }
            )
    doppi = [h for h, n in Counter(r["hash_riga"] for r in out).items() if n > 1]
    if doppi:
        # Caso tipico: lo stesso file_sorgente due volte nella stessa corsa (originale
        # e ricalcolato con lo stesso nome): la DELETE per file non proteggerebbe e le
        # righe finirebbero in tabella due volte.
        nomi = sorted({r["file_sorgente"] for r in out if r["hash_riga"] in doppi})
        raise ValueError(
            f"hash_riga duplicati ({len(doppi)}): stesso file_sorgente più volte? {nomi}"
        )
    return out


def file_mancanti(in_tabella: set[str], in_corsa: set[str]) -> list[str]:
    """File già in tabella che questa corsa non ricaricherebbe: resterebbero con la chiave vecchia."""
    return sorted(in_tabella - in_corsa)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="Path ai file PF xlsx")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--ricarico-completo",
        action="store_true",
        help="rifiuta la corsa se non copre TUTTI i file_sorgente già in tabella "
        "(cambio di convenzione della chiave: una tabella, una convenzione)",
    )
    args = ap.parse_args()
    logger = setup_logger()

    paths = [Path(f).expanduser() for f in args.files]
    rows = build_rows(paths, logger)
    per_file = Counter(r["file_sorgente"] for r in rows)
    logger.info(f"Totale: {len(rows)} righe su {len(paths)} file")
    for f, n in sorted(per_file.items()):
        logger.info(f"  {f}: {n} righe")
    logger.info(
        f"  hash distinti: {len({r['hash_riga'] for r in rows})} su {len(rows)} righe"
    )

    if args.dry_run:
        logger.info("DRY-RUN — nessuna scrittura.")
        return

    client = get_client()
    client.create_table(bigquery.Table(BQ_TABLE, schema=SCHEMA), exists_ok=True)
    if args.ricarico_completo:
        in_tabella = {
            r.file_sorgente
            for r in client.query(
                f"SELECT DISTINCT file_sorgente FROM `{BQ_TABLE}`"
            ).result()
        }
        mancanti = file_mancanti(in_tabella, set(per_file))
        if mancanti:
            raise SystemExit(
                f"--ricarico-completo: {len(mancanti)} file in tabella non sono in questa corsa, "
                f"resterebbero con la chiave vecchia: {mancanti}"
            )

    # Idempotenza: rimpiazza per-file (DELETE file_sorgente + INSERT).
    file_names = sorted(per_file)
    in_list = ", ".join(f"'{n}'" for n in file_names)
    client.query(
        f"DELETE FROM `{BQ_TABLE}` WHERE file_sorgente IN ({in_list})"
    ).result()

    job = client.load_table_from_json(
        rows,
        BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    logger.info(f"✓ {len(rows)} righe in {BQ_TABLE}")


if __name__ == "__main__":
    main()
