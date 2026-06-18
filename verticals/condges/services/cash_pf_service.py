"""Service cash/PF: unico writer canonical per budget e previsione (gate I1)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from core.bq.write import bq_write_validated
from core.config import F_BUDGET_MENSILE, F_PIANO_FINANZIARIO_INPUT
from core.schemas import BudgetMensileRow, PianoFinanziarioInputRow
from verticals.condges.services.intents import (
    SaveBudgetIntent,
    SavePrevisioneIntent,
    SaveResult,
)

_BUDGET_NATURAL_KEY = ["societa_id", "anno", "fonte"]
_PREVISIONE_NATURAL_KEY = ["societa_id", "voce_id", "anno", "mese", "fonte"]


def save_budget(intent: SaveBudgetIntent) -> SaveResult:
    """DELETE+INSERT chirurgico di f_budget_mensile per (societa_id, anno, fonte)."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        BudgetMensileRow(
            societa_id=intent.societa_id,
            anno=intent.anno,
            mese=int(r.mese),
            codice_conto=r.codice_conto,
            descrizione=r.descrizione,
            tipo_costo=r.tipo_costo,
            categoria_ce=r.categoria_ce,
            business_unit_id=r.business_unit_id,
            importo=round(float(r.importo), 2),
            fonte=intent.fonte,
            data_caricamento=now,
        )
        for r in intent.righe
    ]
    bq_write_validated(
        str(F_BUDGET_MENSILE), rows, mode="snapshot", natural_key=_BUDGET_NATURAL_KEY
    )
    return SaveResult(str(F_BUDGET_MENSILE), len(rows), _BUDGET_NATURAL_KEY)


def _previsione_hash(
    societa_id: str, voce_id: str, anno: int, mese: int, fonte: str
) -> str:
    raw = f"{societa_id}|{voce_id}|{anno}|{mese}|{fonte}"
    return hashlib.md5(raw.encode()).hexdigest()


def save_previsione(intent: SavePrevisioneIntent) -> SaveResult:
    """DELETE+INSERT per (societa_id, voce_id, anno, mese, fonte)."""
    now = datetime.now(timezone.utc)
    rows = [
        PianoFinanziarioInputRow(
            hash_riga=_previsione_hash(
                intent.societa_id, intent.voce_id, intent.anno, mese, intent.fonte
            ),
            societa_id=intent.societa_id,
            voce_id=intent.voce_id,
            anno=intent.anno,
            mese=int(mese),
            importo=round(float(intent.importo), 2),
            fonte=intent.fonte,
            note=intent.note,
            file_sorgente=f"service:{now.strftime('%Y-%m-%d %H:%M')}",
            data_caricamento=now.isoformat(),
        )
        for mese in intent.mesi
    ]
    bq_write_validated(
        str(F_PIANO_FINANZIARIO_INPUT),
        rows,
        mode="snapshot",
        natural_key=_PREVISIONE_NATURAL_KEY,
    )
    return SaveResult(str(F_PIANO_FINANZIARIO_INPUT), len(rows), _PREVISIONE_NATURAL_KEY)
