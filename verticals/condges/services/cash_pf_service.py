"""Service cash/PF: unico writer canonical per budget e previsione (gate I1)."""

from __future__ import annotations

from datetime import datetime, timezone

from core.bq.write import bq_write_validated
from core.config import F_BUDGET_MENSILE
from core.schemas import BudgetMensileRow
from verticals.condges.services.intents import SaveBudgetIntent, SaveResult

_BUDGET_NATURAL_KEY = ["societa_id", "anno", "fonte"]


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
