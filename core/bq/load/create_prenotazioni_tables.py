#!/usr/bin/env python3
"""Pre-crea le canonical della famiglia prenotazioni (idempotente).

Va eseguito PRIMA del primo promote (trappola chicken-egg:
`filter_new_rows_by_hash`/DELETE su tabella inesistente → VALIDATE_FAIL).

    python -m core.bq.load.create_prenotazioni_tables
"""

from __future__ import annotations

from google.cloud import bigquery

from core.bq.client import get_client
from core.config import F_BOOKINGS_TIPOLOGIA, F_CONSPREV_MENSILE, F_PRENOTAZIONI_OTB

PRENOTAZIONI_OTB_SCHEMA = [
    bigquery.SchemaField("snapshot_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("business_unit_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("dim_tipologia", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("tipologia", "STRING"),
    bigquery.SchemaField("camere", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("presenze_arb", "INTEGER"),
    bigquery.SchemaField("importo_lordo", "FLOAT"),
    bigquery.SchemaField("adr_lordo", "FLOAT"),
    bigquery.SchemaField("imponibile", "FLOAT"),
    bigquery.SchemaField("adr_imponibile", "FLOAT"),
    bigquery.SchemaField("fonte", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data_caricamento", "DATETIME"),
    bigquery.SchemaField("raw_object_id", "STRING"),
]

BOOKINGS_TIPOLOGIA_SCHEMA = [
    bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("business_unit_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("tipologia", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("camere", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("pax_arb", "INTEGER"),
    bigquery.SchemaField("infant", "INTEGER"),
    bigquery.SchemaField("adr", "FLOAT"),
    bigquery.SchemaField("ricavo_camera", "FLOAT"),
    bigquery.SchemaField("ricavo_camera_extra", "FLOAT"),
    bigquery.SchemaField("ricavo_extra", "FLOAT"),
    bigquery.SchemaField("ricavo_totale", "FLOAT"),
    bigquery.SchemaField("fonte", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data_caricamento", "DATETIME"),
    bigquery.SchemaField("raw_object_id", "STRING"),
]


CONSPREV_MENSILE_SCHEMA = [
    bigquery.SchemaField("snapshot_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("business_unit_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("anno", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("mese", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("classe", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("categoria", "STRING"),
    bigquery.SchemaField("addebito", "STRING"),
    bigquery.SchemaField("mese_cons", "FLOAT"),
    bigquery.SchemaField("mese_prev_cons", "FLOAT"),
    bigquery.SchemaField("mese_bdg", "FLOAT"),
    bigquery.SchemaField("mese_ap", "FLOAT"),
    bigquery.SchemaField("fonte", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data_caricamento", "DATETIME"),
    bigquery.SchemaField("raw_object_id", "STRING"),
]


def main() -> None:
    client = get_client()
    for table_id, schema in [
        (F_PRENOTAZIONI_OTB, PRENOTAZIONI_OTB_SCHEMA),
        (F_BOOKINGS_TIPOLOGIA, BOOKINGS_TIPOLOGIA_SCHEMA),
        (F_CONSPREV_MENSILE, CONSPREV_MENSILE_SCHEMA),
    ]:
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table, exists_ok=True)
        print(f"✓ {table_id}")


if __name__ == "__main__":
    main()
