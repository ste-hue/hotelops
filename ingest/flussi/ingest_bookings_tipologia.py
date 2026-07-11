#!/usr/bin/env python3
"""Ingest Power BI "Detailed Data for Bookings" → f_bookings_tipologia.

Venduto giornaliero per tipologia venduta (consuntivo, fotografia rivedibile):
SNAPSHOT replace per (business_unit_id, data) — ricaricare un file sostituisce
i giorni presenti nel batch per quella BU.

Layout (header-based):
  Giorno | Tipologia Vendita | Camere | ARB | Infant | ADR |
  Appartamento | Appartamento Extra | Extra | Totale

BU dal prefisso filename (PANORAMA/ANGELINA/CVM — il contenuto non ha
CodiceHotel; il footer 'Applied filters' usa una negazione, inaffidabile).
Codici tipologia decodificati da d_pms_codici (dominio ROOM_TYPE).

Parser_module della source POWERBI_BOOKINGSTIPOLOGIA_ORTI_SNAPSHOT:
  python -m ingest.flussi.ingest_bookings_tipologia --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_bookings_tipologia --file <xlsx> --raw-object-id <id>
    python -m ingest.flussi.ingest_bookings_tipologia --file <xlsx> --dry-run
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from core.config import F_BOOKINGS_TIPOLOGIA
from core.schemas import BookingsTipologiaRow, make_hash, validate_batch

log = logging.getLogger("ingest.bookings_tipologia")

FONTE = "POWERBI_BOOKINGSTIPOLOGIA"

NAME_TO_BU = {
    "PANORAMA": "HOTEL",
    "ANGELINA": "RESIDENCE",
    "CVM": "CVM",
}


def detect_bu(file_name: str) -> str:
    upper = file_name.upper()
    for key, bu in NAME_TO_BU.items():
        if key in upper:
            return bu
    raise ValueError(
        f"BU non deducibile dal nome '{file_name}' (atteso uno di {list(NAME_TO_BU)})"
    )


def _num(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_giorno(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.strptime(v.strip()[:10], "%d/%m/%Y").date()
        except ValueError:
            return None
    return None


def parse_xlsx(path: Path) -> list[dict]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    col = {name: i for i, name in enumerate(header)}

    def idx(*names: str) -> int:
        for n in names:
            if n in col:
                return col[n]
        raise ValueError(f"{path.name}: colonna {names} mancante (header: {header})")

    i_giorno = idx("giorno")
    i_tip = idx("tipologia vendita", "tipologia venduta")
    i_cam, i_arb, i_inf = idx("camere"), idx("arb"), idx("infant")
    i_adr = idx("adr")
    i_app = idx("appartamento")
    i_app_e = idx("appartamento extra")
    i_extra, i_tot = idx("extra"), idx("totale")

    out = []
    for r in rows[1:]:
        if not r or len(r) <= i_tot:
            continue
        d = _parse_giorno(r[i_giorno])
        tip = r[i_tip]
        if d is None or not tip:
            continue  # Total / footer
        out.append(
            {
                "data": d,
                "tipologia": str(tip).strip(),
                "camere": int(_num(r[i_cam])),
                "pax_arb": int(_num(r[i_arb])),
                "infant": int(_num(r[i_inf])),
                "adr": _num(r[i_adr]),
                "ricavo_camera": _num(r[i_app]),
                "ricavo_camera_extra": _num(r[i_app_e]),
                "ricavo_extra": _num(r[i_extra]),
                "ricavo_totale": _num(r[i_tot]),
            }
        )
    return out


def build_rows(righe: list[dict], bu: str, raw_object_id: str | None) -> list[dict]:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    out = []
    for r in righe:
        d_iso = r["data"].isoformat()
        out.append(
            {
                "societa_id": "ORTI",
                "business_unit_id": bu,
                "data": d_iso,
                "tipologia": r["tipologia"],
                "camere": r["camere"],
                "pax_arb": r["pax_arb"],
                "infant": r["infant"],
                "adr": round(r["adr"], 4),
                "ricavo_camera": round(r["ricavo_camera"], 2),
                "ricavo_camera_extra": round(r["ricavo_camera_extra"], 2),
                "ricavo_extra": round(r["ricavo_extra"], 2),
                "ricavo_totale": round(r["ricavo_totale"], 2),
                "fonte": FONTE,
                "hash_riga": make_hash(bu, d_iso, r["tipologia"]),
                "raw_object_id": raw_object_id,
                "data_caricamento": now,
            }
        )
    return out


def ingest_file(
    path: Path, raw_object_id: str | None = None, dry_run: bool = False
) -> int:
    bu = detect_bu(path.name)
    righe = parse_xlsx(path)
    rows = build_rows(righe, bu, raw_object_id)
    validate_batch(
        rows, BookingsTipologiaRow, context=f"bookings_tipologia {path.name}"
    )
    if dry_run:
        log.info("[DRY-RUN] %s → %s: %d righe", path.name, bu, len(rows))
        return len(rows)

    from core.bq.write import bq_write_validated

    pydantic_rows = [BookingsTipologiaRow(**r) for r in rows]
    bq_write_validated(
        F_BOOKINGS_TIPOLOGIA,
        pydantic_rows,
        mode="snapshot",
        natural_key=["business_unit_id", "data"],
    )
    log.info("OK %s → %s: %d righe", path.name, bu, len(rows))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest Detailed Data for Bookings → f_bookings_tipologia"
    )
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument(
        "--raw-object-id",
        default=None,
        help="FK a f_raw_objects — da `hotelops promote`",
    )
    ap.add_argument(
        "--societa",
        default=None,
        help="Ignorato — sempre ORTI. Accettato da `hotelops promote`.",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    n = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %d righe", n)


if __name__ == "__main__":
    main()
