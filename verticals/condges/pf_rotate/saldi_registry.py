"""Registry dichiarato dei conti-saldo banca per società (decisione D3).

Sorgente di verità dichiarata — NON inferita dalle righe del PF Excel, che possono
essere vuote o sbagliate. Serve:
  1. il gate di completezza preflight (O-A): quali ``banca_id`` DEVONO esistere in
     ``f_saldi_banca_chiusura_mensile`` per il fine-mese richiesto;
  2. step2: quali righe-saldo del PF sono conti certificati (le altre — es. BCP —
     vanno azzerate per non inquinare TOTALE BANCHE).

``banca_id`` è canonico e coincide con la chiave in BQ / nel dict saldi.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContoSaldo:
    banca_id: str
    required: bool


SALDI_REGISTRY: dict[str, tuple[ContoSaldo, ...]] = {
    "ORTI": (
        ContoSaldo("INTESA", True),
        ContoSaldo("MPS", True),
        ContoSaldo("MPS_KROSS", False),  # extra/opzionale
    ),
    "INTUR": (
        ContoSaldo("SELLA", True),
        ContoSaldo("MPS", True),
        ContoSaldo("INTESA", True),
    ),
    # BCP: escluso per sempre (D3) — non compare in nessun set.
}


def banche_richieste(societa: str) -> set[str]:
    """banca_id obbligatori per la società (devono essere in BQ a fine mese)."""
    return {c.banca_id for c in SALDI_REGISTRY.get(societa.upper(), ()) if c.required}


def banche_note(societa: str) -> set[str]:
    """Tutti i banca_id certificabili per la società (obbligatori + opzionali)."""
    return {c.banca_id for c in SALDI_REGISTRY.get(societa.upper(), ())}
