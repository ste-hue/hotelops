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
class LogCashRunIntent:
    societa_id: str
    anno: int
    mese_chiuso: int
    data_saldo: str  # ISO date
    saldo_cutover: float
    scaduto_totale: float
    totale_partite_aperte: float
    forward_buckets: dict[int, float]
    n_controlli_ok: int
    n_controlli_err: int
    n_controlli_indet: int
    saldo_proiettato_finale: float | None = None
    fonte: str = "APP_CASHFLOW"


@dataclass(frozen=True)
class SaveResult:
    table: str
    rows_written: int
    natural_key: list[str] = field(default_factory=list)
