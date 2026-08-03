#!/usr/bin/env python3
"""Ingest HotelCube Power BI Daily Production Report (occupazione) → f_pms_statistiche.

One xlsx = one struttura (BU), serie giornaliera. Colonne:
  Data | Cam. Totali | OOO | Cam. Vendibili | Cam. Occupate | Cam. Day Use |
  Adulti | Ragazzi | Bambini | ARB | Infant | Pax Day Use | Importo

BU content-first dal footer "Applied filters" (CodiceHotel is …), fallback sul
prefisso filename (ANGELINA→RESIDENCE, CVM→CVM, PANORAMA→HOTEL).
`pax_in_casa` = ARB (= Adulti+Ragazzi+Bambini).
`revenue_room` = Importo; revenue_fb/parking non sono nel file → 0.

Lifecycle: SNAPSHOT, natural_key (business_unit_id, data) — ri-caricare una struttura
sostituisce i suoi giorni. La tabella non ha colonna `anno`, quindi lo scope è per giorno.

Parser_module della source POWERBI_OCCUPAZIONE_ORTI_SNAPSHOT, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_occupazione_pms --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_occupazione_pms --file <xlsx> --raw-object-id <id>
    python -m ingest.flussi.ingest_occupazione_pms --file <xlsx> --dry-run
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from core.config import F_PMS_STATISTICHE
from core.schemas import PmsStatisticheRow, make_hash, validate_batch
from ingest.flussi.ingest_produzione_pms import HOTEL_TO_BU

log = logging.getLogger("ingest.occupazione_pms")

FONTE = "POWERBI_OCCUPAZIONE"

# Prefisso filename → business_unit_id. Cross-check con Cam. Totali atteso.
NAME_TO_BU = {
    "ANGELINA": ("RESIDENCE", 20),
    "CVM": ("CVM", 10),
    "PANORAMA": ("HOTEL", 76),
}


def detect_bu(file_name: str) -> str:
    upper = file_name.upper()
    for key, (bu, _) in NAME_TO_BU.items():
        if key in upper:
            return bu
    raise ValueError(
        f"BU non deducibile dal nome '{file_name}' (atteso uno di {list(NAME_TO_BU)})"
    )


def detect_bu_from_footer(path: Path) -> str | None:
    """Content-first: 'CodiceHotel is <X>' nella cella 'Applied filters' → BU."""
    wb = load_workbook(path, read_only=True, data_only=True)
    text = ""
    for row in wb.active.iter_rows(values_only=True):
        for cell in row:
            if isinstance(cell, str) and "Applied filters" in cell:
                text = cell
    wb.close()
    if not text:
        return None
    # Export multi-struttura: l'aggregato finirebbe etichettato su UNA BU — rifiuta.
    if re.search(r"CodiceHotel is \w+\s*(,| or )", text):
        raise ValueError(
            f"CodiceHotel multiplo: serve un export per singola struttura: {text[:160]!r}"
        )
    m = re.search(r"CodiceHotel is (\w+)", text)
    if not m:
        return None
    codice = m.group(1)
    if codice not in HOTEL_TO_BU:
        raise ValueError(f"CodiceHotel sconosciuto: {codice}")
    return HOTEL_TO_BU[codice]


def _num(v) -> float:
    """Cella → float, vuoto/None → 0.0."""
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_xlsx(path: Path) -> list[dict]:
    """Estrae le righe-giorno grezze (chiavi = nomi colonna normalizzati)."""
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    out = []
    for r in rows:
        if not r or not isinstance(r[0], (datetime, date)):
            continue  # header / righe non-dato
        d = r[0].date() if isinstance(r[0], datetime) else r[0]
        out.append(
            {
                "data": d,
                "cam_totali": int(_num(r[1])),
                "ooo": int(_num(r[2])),
                "cam_vendibili": int(_num(r[3])),
                "cam_occupate": int(_num(r[4])),
                "arb": int(_num(r[9])) if len(r) > 9 else 0,
                "importo": _num(r[12]) if len(r) > 12 else 0.0,
            }
        )
    return out


def build_rows(
    raw: list[dict], bu: str, file_name: str, raw_object_id: str | None
) -> list[dict]:
    # f_pms_statistiche.data_caricamento è DATETIME (no timezone) → ISO naive
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    out = []
    for r in raw:
        vendibili = r["cam_vendibili"]
        occupate = r["cam_occupate"]
        importo = r["importo"]
        # vendibili può essere ≤ 0 quando OOO include camere extra non nell'inventario
        # base (HotelCube blocca > totali). In quel caso il denominatore onesto è
        # camere_totali (occupazione = vendute/totali). Clamp 0-100 (validator schema).
        den = vendibili if vendibili > 0 else r["cam_totali"]
        occ_pct = max(0.0, min(100.0, 100.0 * occupate / den)) if den > 0 else 0.0
        adr = importo / occupate if occupate else 0.0
        revpar = importo / den if den > 0 else 0.0
        d_iso = r["data"].isoformat()
        out.append(
            {
                "societa_id": "ORTI",
                "business_unit_id": bu,
                "data": d_iso,
                "camere_totali": r["cam_totali"],
                "camere_vendute": occupate,
                "camere_bloccate": r["ooo"],
                "occupazione_pct": round(occ_pct, 2),
                "pax_in_casa": r["arb"],
                "adr": round(adr, 2),
                "revpar": round(revpar, 2),
                "revenue_room": round(importo, 2),
                "revenue_fb": 0.0,
                "revenue_parking": 0.0,
                "revenue_totale": round(importo, 2),
                "fonte": FONTE,
                "hash_riga": make_hash(bu, d_iso),
                "raw_object_id": raw_object_id,
                "data_caricamento": now,
            }
        )
    return out


def ingest_file(
    path: Path, raw_object_id: str | None = None, dry_run: bool = False
) -> int:
    """Parse one xlsx e SNAPSHOT-write su f_pms_statistiche. Ritorna n righe."""
    bu = detect_bu_from_footer(path) or detect_bu(path.name)
    raw = parse_xlsx(path)
    rows = build_rows(raw, bu, path.name, raw_object_id)
    validate_batch(rows, PmsStatisticheRow, context=f"occupazione_pms {path.name}")
    if dry_run:
        occ = sum(1 for r in rows if r["camere_vendute"] > 0)
        log.info(
            "[DRY-RUN] %s → %s : %d righe (%d giorni occupati)",
            path.name,
            bu,
            len(rows),
            occ,
        )
        return len(rows)

    from core.bq.write import bq_write_validated

    pydantic_rows = [PmsStatisticheRow(**r) for r in rows]
    bq_write_validated(
        F_PMS_STATISTICHE,
        pydantic_rows,
        mode="snapshot",
        natural_key=["business_unit_id", "data"],
    )
    log.info("OK %s → %s : %d righe", path.name, bu, len(rows))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest Daily Production Report (occupazione) → f_pms_statistiche"
    )
    ap.add_argument(
        "--file",
        required=True,
        type=Path,
        help="xlsx Daily Production Report (occupazione)",
    )
    ap.add_argument(
        "--raw-object-id",
        default=None,
        help="FK a f_raw_objects — passato da `hotelops promote`",
    )
    ap.add_argument(
        "--societa",
        default=None,
        help="Ignorato — sempre ORTI. Accettato da `hotelops promote`.",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    n = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %d righe", n)


if __name__ == "__main__":
    main()
