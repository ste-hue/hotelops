#!/usr/bin/env python3
"""Ingest dump JSON completo Spiagge.it → 3 tabelle canonical (fan-out 1→3).

Un dump = il DB intero di booking. Lifecycle SNAPSHOT full-replace: ogni dump
sostituisce integralmente le 3 tabelle. Il full-replace è ottenuto con
bq_write_validated(mode="snapshot", natural_key=["societa_id"]): siccome ogni
riga è societa_id='INTUR', il DELETE chirurgico del gate svuota la tabella prima
del re-insert.

È il parser_module della source SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT, invocato da
`hotelops promote` come:
    python -m ingest.flussi.ingest_spiaggia --file X.json --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_spiaggia --file <json> --raw-object-id <id>
    python -m ingest.flussi.ingest_spiaggia --file <json> --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.config import (
    F_SPIAGGIA_CASH_FLOWS,
    F_SPIAGGIA_RESERVATIONS,
    F_SPIAGGIA_SPOTS,
)
from core.schemas import (
    SpiaggiaCashFlowRow,
    SpiaggiaReservationRow,
    SpiaggiaSpotRow,
    make_hash,
    validate_batch,
)

log = logging.getLogger("ingest.spiaggia")

# Dimensioni fisse del vertical (vedi spec): la spiaggia è INTUR / LIDO.
SOCIETA = "INTUR"
BUSINESS_UNIT = "LIDO"
LOCATION = "LIDO"

# Legenda metodi pagamento Spiagge.it: IGNOTA. Riempire qui quando nota
# (es. {1: "contanti", 14: "POS"}) e ri-promuovere il dump. Finché vuota,
# method_label resta "metodo_<codice>".
METHOD_LABELS: dict[int, str] = {}


def to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_bool(v: Any) -> bool:
    """0/1/None → bool. None e falsy → False."""
    return bool(v) if v is not None else False


def to_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def unix_to_date(v: Any) -> Optional[date]:
    """Unix seconds → date UTC. 0/None/falsy → None (filtra epoch-junk 1970)."""
    n = to_int(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def unix_to_ts(v: Any) -> Optional[datetime]:
    """Unix seconds → datetime UTC. 0/None/falsy → None."""
    n = to_int(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def method_label(code: Optional[int]) -> str:
    if code is None:
        return "sconosciuto"
    return METHOD_LABELS.get(code, f"metodo_{code}")


def find_prefix(dump: dict) -> str:
    """Deduce il prefisso tabella dal dump (es. 'it-sa-84010-panorama-beach_').

    Cerca la chiave che termina in '_reservations'. Robusto a license_code
    diversi (altra spiaggia) senza hardcodare il nome.
    """
    suffix = "_reservations"
    for k in dump:
        if k.endswith(suffix):
            return k[: -len("reservations")]
    raise ValueError("dump senza tabella *_reservations: non è un dump Spiagge.it")


def extract_table(dump: dict, prefix: str, table: str) -> list[dict]:
    """Estrae una tabella {columns, rows} → list[dict] per nome colonna."""
    key = f"{prefix}{table}"
    block = dump.get(key)
    if block is None:
        raise KeyError(f"tabella mancante nel dump: {key}")
    cols = block["columns"]
    return [dict(zip(cols, row)) for row in block["rows"]]


def _dims(oggetto_id: Optional[str]) -> dict:
    """Le 5 dimensioni del vertical (funzione_id sempre None per la spiaggia)."""
    return {
        "societa_id": SOCIETA,
        "business_unit_id": BUSINESS_UNIT,
        "location_id": LOCATION,
        "oggetto_id": oggetto_id,
        "funzione_id": None,
    }


def build_reservation_rows(
    recs: list[dict], file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[SpiaggiaReservationRow]:
    out: list[SpiaggiaReservationRow] = []
    for d in recs:
        spot_name = to_str(d.get("spot_name"))
        out.append(SpiaggiaReservationRow(
            **_dims(spot_name),
            id=int(d["id"]),
            license_code=to_str(d.get("license_code")),
            spot_type=to_str(d.get("spot_type")),
            spot_name=spot_name,
            status=to_int(d.get("status")),
            seasonal=to_bool(d.get("seasonal")),
            deleted=to_bool(d.get("deleted")),
            online=to_bool(d.get("online")),
            hotel=to_str(d.get("hotel")),
            hotel_room=to_str(d.get("hotel_room")),
            start_date=unix_to_date(d.get("start_date")),
            end_date=unix_to_date(d.get("end_date")),
            beds=to_int(d.get("beds")),
            chairs=to_int(d.get("chairs")),
            first_name=to_str(d.get("first_name")),
            last_name=to_str(d.get("last_name")),
            email=to_str(d.get("email")),
            phone=to_str(d.get("phone_number")),
            list_total=to_float(d.get("list_total")),
            paid_total=to_float(d.get("paid_total")),
            gross_booking_value=to_float(d.get("gross_booking_value")),
            discount=to_float(d.get("discount")),
            channel=to_str(d.get("channel")),
            invoice_number=to_str(d.get("invoice_number")),
            invoice_company=to_str(d.get("invoice_company")),
            utm_source=to_str(d.get("utm_source")),
            utm_medium=to_str(d.get("utm_medium")),
            utm_campaign=to_str(d.get("utm_campaign")),
            created_at=unix_to_ts(d.get("created_at")),
            updated_at=unix_to_ts(d.get("updated_at")),
            raw_object_id=raw_object_id,
            file_sorgente=file_name,
            hash_riga=make_hash("reservations", str(d["id"])),
            data_caricamento=now,
        ))
    return out


def build_cash_flow_rows(
    recs: list[dict], file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[SpiaggiaCashFlowRow]:
    out: list[SpiaggiaCashFlowRow] = []
    for d in recs:
        method = to_int(d.get("method"))
        out.append(SpiaggiaCashFlowRow(
            **_dims(None),
            id=int(d["id"]),
            reservation_id=to_int(d.get("reservation_id")),
            method=method,
            method_label=method_label(method),
            amount=to_float(d.get("amount")),
            date=unix_to_date(d.get("date")),
            receipt_id=to_int(d.get("receipt_id")),
            invoice_id=to_int(d.get("invoice_id")),
            deleted=to_bool(d.get("deleted")),
            created_at=unix_to_ts(d.get("created_at")),
            updated_at=unix_to_ts(d.get("updated_at")),
            raw_object_id=raw_object_id,
            file_sorgente=file_name,
            hash_riga=make_hash("cash_flows", str(d["id"])),
            data_caricamento=now,
        ))
    return out


def build_spot_rows(
    recs: list[dict], file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[SpiaggiaSpotRow]:
    out: list[SpiaggiaSpotRow] = []
    for d in recs:
        name = to_str(d.get("name"))
        out.append(SpiaggiaSpotRow(
            **_dims(name),
            id=int(d["id"]),
            uuid=to_str(d.get("uuid")),
            name=name,
            type=to_str(d.get("type")),
            sector=to_int(d.get("sector")),
            price_list_id=to_int(d.get("price_list_id")),
            pos_x=to_int(d.get("pos_x")),
            pos_y=to_int(d.get("pos_y")),
            element_type=to_str(d.get("element_type")),
            raw_object_id=raw_object_id,
            file_sorgente=file_name,
            hash_riga=make_hash("spots", str(d["id"])),
            data_caricamento=now,
        ))
    return out


# (table_name, builder, target table) per il fan-out 1→3.
_TABLES = [
    ("reservations", build_reservation_rows, F_SPIAGGIA_RESERVATIONS),
    ("cash_flows", build_cash_flow_rows, F_SPIAGGIA_CASH_FLOWS),
    ("spots", build_spot_rows, F_SPIAGGIA_SPOTS),
]


def ingest_file(
    path: Path, raw_object_id: Optional[str] = None, dry_run: bool = False
) -> dict[str, int]:
    """Parsa un dump JSON e fa full-replace SNAPSHOT delle 3 tabelle.

    Ritorna {table_name: n_righe}. Full-replace via natural_key=["societa_id"]:
    ogni riga è INTUR ⇒ il DELETE del gate svuota la tabella prima del re-insert.
    """
    with open(path, encoding="utf-8") as fh:
        dump = json.load(fh)
    prefix = find_prefix(dump)
    now = datetime.now(timezone.utc)

    counts: dict[str, int] = {}
    for table_name, builder, target in _TABLES:
        recs = extract_table(dump, prefix, table_name)
        rows = builder(recs, path.name, raw_object_id, now)
        if rows:
            validate_batch(
                [r.model_dump() for r in rows],
                type(rows[0]),
                context=f"spiaggia {table_name} {path.name}",
            )
        counts[table_name] = len(rows)

        if dry_run:
            log.info("[DRY-RUN] %s → %s : %d righe", table_name, target, len(rows))
            continue

        from core.bq.write import bq_write_validated

        bq_write_validated(
            target,
            rows,
            mode="snapshot",
            natural_key=["societa_id"],
        )
        log.info("OK %s → %s : %d righe (full-replace)", table_name, target, len(rows))

    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest dump Spiagge.it → 3 tabelle canonical")
    ap.add_argument("--file", required=True, type=Path, help="dump JSON Spiagge.it")
    ap.add_argument(
        "--raw-object-id",
        default=None,
        help="FK a f_raw_objects — passato da `hotelops promote`",
    )
    ap.add_argument(
        "--societa",
        default=None,
        help="Ignorato — la spiaggia è sempre INTUR. Accettato da `hotelops promote`.",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    counts = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %s", counts)


if __name__ == "__main__":
    main()
