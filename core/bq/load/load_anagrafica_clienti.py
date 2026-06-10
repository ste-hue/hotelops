#!/usr/bin/env python3
"""Carica l'anagrafica clienti (da accodamenti HotelCube *_Clienti.txt) in d_anagrafica_clienti.

Ogni riga GEN = un cliente. Dedup per codice_cliente (un cliente può comparire in più
strutture H/C/R). Dimensione gemella di d_anagrafica_fornitori — risolve il `codice_cliente`
delle fatture in f_accodamenti (chi ha fatturato: agenzia/OTA vs diretto, geografia).
SNAPSHOT: ogni run ricarica l'anagrafica completa.

Usage:
    python -m core.bq.load.load_anagrafica_clienti /tmp/acc_*/*_Clienti.txt
    python -m core.bq.load.load_anagrafica_clienti --dry-run *_Clienti.txt
"""

from __future__ import annotations

import argparse
import glob
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from core.bq.client import get_client
from core.config import PROJECT

BQ_TABLE = f"{PROJECT}.hotelops.d_anagrafica_clienti"

SCHEMA = [
    bigquery.SchemaField("codice_cliente", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ragione_sociale", "STRING"),
    bigquery.SchemaField("partita_iva", "STRING"),
    bigquery.SchemaField("indirizzo", "STRING"),
    bigquery.SchemaField("cap", "STRING"),
    bigquery.SchemaField("citta", "STRING"),
    bigquery.SchemaField("provincia", "STRING"),
    bigquery.SchemaField("nazione", "STRING"),
    bigquery.SchemaField("telefono", "STRING"),
    bigquery.SchemaField("email", "STRING"),
    bigquery.SchemaField("file_sorgente", "STRING"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
]


def _g(fields: list[str], i: int) -> str | None:
    return fields[i].strip() if len(fields) > i and fields[i].strip() else None


def parse_clienti(path: Path) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for line in path.read_text(errors="replace").splitlines():
        f = line.split("|")
        if not f or f[0] != "GEN":
            continue
        cod = _g(f, 3)
        if not cod:
            continue
        out.append(
            {
                "codice_cliente": cod,
                "ragione_sociale": _g(f, 8),
                "partita_iva": _g(f, 4),
                "indirizzo": _g(f, 10),
                "cap": _g(f, 12),
                "citta": _g(f, 13),
                "provincia": _g(f, 15),
                "nazione": _g(f, 16),
                "telefono": _g(f, 17),
                "email": _g(f, 19),
                "file_sorgente": path.name,
                "data_caricamento": now,
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="Path/glob ai file *_Clienti.txt")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows: list[dict] = []
    for pat in args.files:
        for fp in glob.glob(pat):
            rows += parse_clienti(Path(fp))

    # dedup per codice_cliente (l'ultimo vince — anagrafica più recente)
    by_cod = {r["codice_cliente"]: r for r in rows}
    rows = list(by_cod.values())
    print(f"clienti distinti: {len(rows)}")

    if args.dry_run:
        for r in rows[:8]:
            print(f"  {r['codice_cliente']:>6}  {r['ragione_sociale']}  ({r['citta']} {r['provincia']})")
        return

    client = get_client()
    client.create_table(bigquery.Table(BQ_TABLE, schema=SCHEMA), exists_ok=True)
    client.query(f"DELETE FROM `{BQ_TABLE}` WHERE TRUE").result()
    job = client.load_table_from_json(
        rows,
        BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_APPEND
        ),
    )
    job.result()
    print(f"✓ {len(rows)} clienti in {BQ_TABLE}")


if __name__ == "__main__":
    main()
