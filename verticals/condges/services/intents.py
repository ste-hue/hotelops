"""Intent/result tipizzati tra surface e service. Nessuna logica BQ qui."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetRiga:
    mese: int
    codice_conto: str
    importo: float
    descrizione: str | None = None
    tipo_costo: str | None = None
    categoria_ce: str | None = None
    business_unit_id: str | None = None


@dataclass(frozen=True)
class SaveBudgetIntent:
    societa_id: str
    anno: int
    righe: list[BudgetRiga]
    fonte: str = "APP_BUDGET"


@dataclass(frozen=True)
class SavePrevisioneIntent:
    societa_id: str
    voce_id: str
    mesi: list[int]
    importo: float
    anno: int
    fonte: str = "NANOCLAW"
    note: str | None = None


@dataclass(frozen=True)
class SaveResult:
    table: str
    rows_written: int
    natural_key: list[str] = field(default_factory=list)
