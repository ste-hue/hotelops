"""Blocco A (partite aperte) e regole numeriche del generatore PF."""

from __future__ import annotations


def cascata_nc(amounts: dict[int, float]) -> dict[int, float]:
    """Scala i saldi positivi (note credito) sul primo mese con fatture
    in avanti. Input/output: {mese: importo} con debiti NEGATIVI.
    Una NC residua oltre l'ultimo mese viene scartata.
    """
    out: dict[int, float] = {}
    carry = 0.0
    for mese in sorted(amounts):
        net = amounts[mese] + carry
        if net >= 0:
            carry = net
            continue
        carry = 0.0
        out[mese] = round(net, 2)
    return out
