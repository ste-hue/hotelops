"""Cashflow projection logic for the condges vertical.

Pure functions — no I/O, no BQ, no side effects.
"""

from dataclasses import dataclass


@dataclass
class CashflowRow:
    mese: int
    saldo_iniziale: float
    entrate: float
    uscite_pf: float
    uscite_fornitori: float
    netto: float
    saldo_fine: float
    stato: str  # OK, ATTENZIONE, PERICOLO


def _semaphore(saldo_fine: float) -> str:
    """Return traffic-light status based on saldo_fine.

    PERICOLO  — saldo < 0
    ATTENZIONE — 0 <= saldo <= 50_000
    OK        — saldo > 50_000
    """
    if saldo_fine < 0:
        return "PERICOLO"
    if saldo_fine <= 50_000:
        return "ATTENZIONE"
    return "OK"


def project_cashflow(
    saldo_iniziale: float,
    mese_inizio: int,
    entrate_per_mese: dict[int, float],
    uscite_per_mese: dict[int, float],
    fornitori_per_mese: dict[int, float] | None = None,
    mese_fine: int = 12,
) -> list[CashflowRow]:
    """Project cashflow from mese_inizio to mese_fine.

    Args:
        saldo_iniziale: Opening balance for the first month.
        mese_inizio: First month (1-12).
        entrate_per_mese: Inflows keyed by month number. Missing months default to 0.
        uscite_per_mese: PF outflows keyed by month number. Missing months default to 0.
        fornitori_per_mese: Supplier outflows keyed by month. Missing months default to 0.
        mese_fine: Last month (inclusive). Default 12.

    Returns:
        List of CashflowRow, one per month, in order.
    """
    if fornitori_per_mese is None:
        fornitori_per_mese = {}

    rows: list[CashflowRow] = []
    saldo = saldo_iniziale

    for mese in range(mese_inizio, mese_fine + 1):
        entrate = entrate_per_mese.get(mese, 0.0)
        uscite_pf = uscite_per_mese.get(mese, 0.0)
        uscite_fornitori = fornitori_per_mese.get(mese, 0.0)
        netto = entrate - uscite_pf - uscite_fornitori
        saldo_fine = saldo + netto

        rows.append(
            CashflowRow(
                mese=mese,
                saldo_iniziale=saldo,
                entrate=entrate,
                uscite_pf=uscite_pf,
                uscite_fornitori=uscite_fornitori,
                netto=netto,
                saldo_fine=saldo_fine,
                stato=_semaphore(saldo_fine),
            )
        )
        saldo = saldo_fine

    return rows
