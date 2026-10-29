"""Ingest scenario di cassa del CdG (documento cdg-cassa-scenario/1) → p_*.

Il documento JSON esportato dalla pagina Cassa viene scritto in tre tabelle del
dataset hotelops_previsioni (p_scenari, p_scenario_flussi, p_progetti_pagamenti),
append-only, tutte con FK `raw_object_id`. Società unica: GROUP.

Usage:
    python -m ingest.flussi.ingest_scenario_cassa --file X.json --societa GROUP --raw-object-id Y [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.bq.write import bq_write_validated
from core.config import P_PROGETTI_PAGAMENTI, P_SCENARI, P_SCENARIO_FLUSSI
from core.schemas import (
    ProgettoPagamentoRow,
    ScenarioFlussoRow,
    ScenarioRow,
)
from verticals.condges.cassa_scenario import righe_p, scenario_id

log = logging.getLogger("ingest_scenario_cassa")

SOCIETA = "GROUP"


def ingest(path: Path, raw_object_id: str, dry_run: bool, autore: str) -> dict:
    raw = Path(path).read_bytes()
    scenari, flussi, pagamenti = righe_p(
        raw, raw_object_id, datetime.now(timezone.utc), autore
    )
    tabelle = [
        ("p_scenari", P_SCENARI, ScenarioRow, scenari),
        ("p_scenario_flussi", P_SCENARIO_FLUSSI, ScenarioFlussoRow, flussi),
        ("p_progetti_pagamenti", P_PROGETTI_PAGAMENTI, ProgettoPagamentoRow, pagamenti),
    ]
    # Tutte e tre le liste validate PRIMA di scrivere: append-only, un fallimento
    # a metà lascerebbe il padre p_scenari duplicato al retry.
    modelli = [(t, [m(**r) for r in rows]) for _, t, m, rows in tabelle]
    righe = {nome: len(rows) for nome, _, _, rows in tabelle}
    if not dry_run:
        for tabella, models in modelli:
            bq_write_validated(tabella, models, mode="append")
    return {"scenario_id": scenario_id(raw), "righe": righe}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest scenario di cassa CdG → BQ")
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--raw-object-id", required=True)
    ap.add_argument("--societa", default=None, help="Deve essere GROUP.")
    ap.add_argument("--autore", default="cli")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.societa and args.societa != SOCIETA:
        print(
            f"--societa {args.societa}: gli scenari di cassa sono solo {SOCIETA}",
            file=sys.stderr,
        )
        sys.exit(2)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    out = ingest(args.file, args.raw_object_id, args.dry_run, args.autore)
    log.info(
        "scenario_id=%s righe=%s%s",
        out["scenario_id"],
        out["righe"],
        " (dry-run)" if args.dry_run else "",
    )


if __name__ == "__main__":
    main()
