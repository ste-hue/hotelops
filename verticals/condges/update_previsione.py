#!/usr/bin/env python3
"""
Aggiorna previsione Piano Finanziario — singola voce × range mesi.

Scrive in f_piano_finanziario_input con fonte='NANOCLAW' (o custom).
Pattern: DELETE-INSERT per (societa_id, voce_id, anno, mese, fonte).
Idempotente — safe to re-run.

Usage (CLI):
    python -m actions.update_previsione \
        --voce USCITE_UTENZE --societa ORTI \
        --mesi 4-12 --importo 22000 --anno 2026

    python -m actions.update_previsione \
        --voce ENTRATE_HOTEL --societa ORTI \
        --mesi 4-10 --importo 180000 --anno 2026 --note "stagione 2026"

Usage (NanoClaw — programmatic):
    from verticals.condges.update_previsione import update_previsione
    result = update_previsione(
        voce_id="USCITE_UTENZE", societa_id="ORTI",
        anno=2026, mese_start=4, mese_end=12,
        importo_mensile=22000.0
    )
    # result = {"status": "ok", "rows_written": 9, "voce": "...", ...}

Voci valide: tutte quelle in d_voci_piano_finanziario.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone

from core.bq.client import get_client
from core.config import PROJECT

BQ_TABLE = f"{PROJECT}.hotelops.f_piano_finanziario_input"
BQ_VOCI_TABLE = f"{PROJECT}.hotelops.d_voci_piano_finanziario"
DEFAULT_FONTE = "NANOCLAW"

log = logging.getLogger("update_previsione")


def _hash(societa_id: str, voce_id: str, anno: int, mese: int, fonte: str) -> str:
    key = f"{societa_id}|{voce_id}|{anno}|{mese}|{fonte}"
    return hashlib.md5(key.encode()).hexdigest()


def get_valid_voci(bq_client) -> dict[str, str]:
    """Return {voce_id: voce_label} from d_voci_piano_finanziario."""
    rows = bq_client.query(
        f"SELECT voce_id, voce_label FROM `{BQ_VOCI_TABLE}`"
    ).result()
    return {r.voce_id: r.voce_label for r in rows}


def update_previsione(
    voce_id: str,
    societa_id: str,
    anno: int,
    mese_start: int,
    mese_end: int,
    importo_mensile: float,
    fonte: str = DEFAULT_FONTE,
    note: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Aggiorna previsione per una voce × range mesi.

    Returns dict with status, rows affected, and summary.
    """
    bq_client = get_client()

    # Validate voce
    valid_voci = get_valid_voci(bq_client)
    if voce_id not in valid_voci:
        # Try fuzzy match
        matches = [v for v in valid_voci if voce_id.upper() in v]
        return {
            "status": "error",
            "message": f"Voce '{voce_id}' non trovata.",
            "suggerimenti": matches[:5] if matches else list(valid_voci.keys()),
        }

    # Validate societa
    if societa_id not in ("ORTI", "INTUR"):
        return {
            "status": "error",
            "message": f"Società deve essere ORTI o INTUR, non '{societa_id}'",
        }

    # Validate mesi
    if not (1 <= mese_start <= 12 and 1 <= mese_end <= 12 and mese_start <= mese_end):
        return {
            "status": "error",
            "message": f"Mesi non validi: {mese_start}-{mese_end}",
        }

    mesi = list(range(mese_start, mese_end + 1))
    now = datetime.now(timezone.utc)

    # Build rows
    new_rows = []
    for mese in mesi:
        new_rows.append(
            {
                "hash_riga": _hash(societa_id, voce_id, anno, mese, fonte),
                "societa_id": societa_id,
                "voce_id": voce_id,
                "anno": anno,
                "mese": mese,
                "importo": round(importo_mensile, 2),
                "fonte": fonte,
                "note": note,
                "file_sorgente": f"nanoclaw:{now.strftime('%Y-%m-%d %H:%M')}",
                "data_caricamento": now.isoformat(),
            }
        )

    totale = round(importo_mensile * len(mesi), 2)

    if dry_run:
        return {
            "status": "dry_run",
            "voce_id": voce_id,
            "voce_label": valid_voci[voce_id],
            "societa_id": societa_id,
            "anno": anno,
            "mesi": f"{mese_start}-{mese_end}",
            "importo_mensile": importo_mensile,
            "totale_periodo": totale,
            "rows": len(new_rows),
            "fonte": fonte,
        }

    # Write via service (gate I1) — un solo writer per Streamlit/CLI/NanoClaw
    from verticals.condges.services import cash_pf_service
    from verticals.condges.services.intents import SavePrevisioneIntent

    result = cash_pf_service.save_previsione(
        SavePrevisioneIntent(
            societa_id=societa_id,
            voce_id=voce_id,
            mesi=mesi,
            importo=importo_mensile,
            anno=anno,
            fonte=fonte,
            note=note,
        )
    )
    rows_written = result.rows_written

    return {
        "status": "ok",
        "voce_id": voce_id,
        "voce_label": valid_voci[voce_id],
        "societa_id": societa_id,
        "anno": anno,
        "mesi": f"{mese_start}-{mese_end}",
        "importo_mensile": importo_mensile,
        "totale_periodo": totale,
        "rows_written": rows_written,
        "fonte": fonte,
    }


# ── Parsing linguaggio naturale (per NanoClaw) ─────────────────────────────

VOCE_ALIASES = {
    # Entrate
    "hotel": "ENTRATE_HOTEL",
    "entrate hotel": "ENTRATE_HOTEL",
    "residence": "ENTRATE_RESIDENCE",
    "entrate residence": "ENTRATE_RESIDENCE",
    "cvm": "ENTRATE_CVM",
    "entrate cvm": "ENTRATE_CVM",
    "supermercato": "ENTRATE_SUPERMERCATO",
    "entrate supermercato": "ENTRATE_SUPERMERCATO",
    "spiaggia": "ENTRATE_SPIAGGIA",
    "entrate spiaggia": "ENTRATE_SPIAGGIA",
    "affitti": "ENTRATE_AFFITTI_INTUR",
    "affitti intur": "ENTRATE_AFFITTI_INTUR",
    "farmacia": "ENTRATE_AFFITTI_MINORI",
    "caparre": "ENTRATE_CAPARRE",
    # Uscite
    "salari": "USCITE_SALARI",
    "stipendi": "USCITE_SALARI",
    "personale": "USCITE_SALARI",
    "utenze": "USCITE_UTENZE",
    "bollette": "USCITE_UTENZE",
    "materie prime": "USCITE_MATERIE_PRIME",
    "acquisti": "USCITE_MATERIE_PRIME",
    "tasse": "USCITE_TASSE",
    "imposte": "USCITE_TASSE",
    "mutui": "USCITE_MUTUI",
    "finanziamenti": "USCITE_MUTUI",
    "commissioni": "USCITE_COMMISSIONI",
    "ota": "USCITE_COMMISSIONI",
    "consulenze": "USCITE_CONSULENZE",
    "godimento beni": "USCITE_GODIMENTO_BENI",
    "fitti passivi": "USCITE_GODIMENTO_BENI",
    "canoni": "USCITE_CANONI",
    "canone passivo": "USCITE_CANONE_PASSIVO",
    "affitto ramo": "USCITE_CANONE_PASSIVO",
    "varie": "USCITE_VARIE",
    "marketing": "USCITE_MARKETING",
    "pubblicita": "USCITE_MARKETING",
    "servizi produzione": "USCITE_SERVIZI_PRODUZIONE",
    "spese bancarie": "USCITE_SPESE_BANCARIE",
}

MESI_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
    "gen": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "mag": 5,
    "giu": 6,
    "lug": 7,
    "ago": 8,
    "set": 9,
    "ott": 10,
    "nov": 11,
    "dic": 12,
}


def resolve_voce(text: str) -> str | None:
    """Resolve natural language voce to voce_id."""
    t = text.lower().strip()
    if t in VOCE_ALIASES:
        return VOCE_ALIASES[t]
    # Prefix match
    for alias, vid in VOCE_ALIASES.items():
        if t.startswith(alias) or alias.startswith(t):
            return vid
    # Direct voce_id
    if t.startswith("entrate_") or t.startswith("uscite_"):
        return t.upper()
    return None


def resolve_mese(text: str) -> int | None:
    """Resolve Italian month name to number."""
    return MESI_IT.get(text.lower().strip())


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Aggiorna previsione Piano Finanziario"
    )
    parser.add_argument(
        "--voce", required=True, help="voce_id o alias (es. 'utenze', 'USCITE_UTENZE')"
    )
    parser.add_argument("--societa", required=True, choices=["ORTI", "INTUR"])
    parser.add_argument("--anno", type=int, default=2026)
    parser.add_argument(
        "--mesi", required=True, help="Range mesi: '4-12' o '6' (singolo)"
    )
    parser.add_argument(
        "--importo", type=float, required=True, help="Importo mensile (€)"
    )
    parser.add_argument("--fonte", default=DEFAULT_FONTE)
    parser.add_argument("--note", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Resolve voce alias
    voce_id = resolve_voce(args.voce) or args.voce.upper()

    # Parse mesi range
    if "-" in args.mesi:
        parts = args.mesi.split("-")
        mese_start = resolve_mese(parts[0]) or int(parts[0])
        mese_end = resolve_mese(parts[1]) or int(parts[1])
    else:
        mese_start = resolve_mese(args.mesi) or int(args.mesi)
        mese_end = mese_start

    result = update_previsione(
        voce_id=voce_id,
        societa_id=args.societa,
        anno=args.anno,
        mese_start=mese_start,
        mese_end=mese_end,
        importo_mensile=args.importo,
        fonte=args.fonte,
        note=args.note,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
