"""Incidenza costi/ricavi (CdG) — varianti di perimetro esplicite, limite versionato, nessun default.

Base dati: vista ``v_incidenza_costi_componenti`` (core/bq/views/), che espone i COMPONENTI per
(societa, anno, mese): YTD diretto dello snapshot e delta mensile aggregato (NULL se il mese non è
derivabile). Questo modulo compone il rapporto: richiede perimetro, natura e periodo espliciti e
rifiuta di scegliere un default. Il confronto con il limite usa un ``Limite`` versionato passato dal
chiamante (mai una costante nascosta) e non arrotonda. Nessun semaforo, nessun allarme: solo esiti.

Contratto: docs/reports/2026-10-18-cdg-stato-reale-e-incidenza-costi.md §6; ponte dei conti
docs/reports/2026-10-18-cdg-ponte-conti-65.md §2-ter / §7 (PR #158); issue #157.
Decisione 18/10 (Stefano): 65 % = massimo, oltre = allarme, 66 % non è tolleranza, confronto non
arrotondato, non valutabile ≠ entro limite. Periodo e perimetro: non decisi (questo modulo non li sceglie).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Perimetro(Enum):
    """Cosa si toglie dal numeratore base (classi 55–71). Tutte le Q escludono già il canone 65.11.01
    (decisione 16/10). R0 è il riferimento standalone con il canone dentro, non una variante di controllo."""

    Q1_PIANO = "Q1"  # − canone − Angelina (regola di piano del MASTER costi65)
    Q2_INTERCOMPANY = "Q2"  # − canone − Angelina (identico a Q1 sul numeratore; differisce solo per la natura)
    Q3_FITTI_GRUPPO = "Q3"  # − canone − Angelina − CVM
    Q4_FITTI_GRUPPO_NATURA = "Q4"  # − canone − Angelina − CVM (con natura)
    Q5_SOLO_CANONE = "Q5"  # − canone (Angelina e CVM inclusi)
    R0_STANDALONE_PIENO = (
        "R0"  # nessuna esclusione: canone, Angelina e CVM inclusi (riferimento)
    )


class Natura(Enum):
    """Classe 75: per classe (tutta fuori, regola storica) o per natura (servizi bancari/POS/bollo dentro)."""

    CLASSE = "classe"
    NATURA = "natura"


class Periodo(Enum):
    YTD = "ytd"
    MESE = "mese"


# Esclusioni per perimetro, sul numeratore base costi_55_71 (che contiene canone, Angelina e CVM).
_ESCLUSIONI: dict[Perimetro, tuple[str, ...]] = {
    Perimetro.Q1_PIANO: ("canone_651101", "angelina_65010591"),
    Perimetro.Q2_INTERCOMPANY: ("canone_651101", "angelina_65010591"),
    Perimetro.Q3_FITTI_GRUPPO: ("canone_651101", "angelina_65010591", "cvm_65010590"),
    Perimetro.Q4_FITTI_GRUPPO_NATURA: (
        "canone_651101",
        "angelina_65010591",
        "cvm_65010590",
    ),
    Perimetro.Q5_SOLO_CANONE: ("canone_651101",),
    Perimetro.R0_STANDALONE_PIENO: (),
}

# Natura implicita delle varianti del ponte §7 (Q1, Q3 per classe; Q2, Q4, Q5, R0 per natura).
NATURA_DEL_PONTE: dict[Perimetro, Natura] = {
    Perimetro.Q1_PIANO: Natura.CLASSE,
    Perimetro.Q2_INTERCOMPANY: Natura.NATURA,
    Perimetro.Q3_FITTI_GRUPPO: Natura.CLASSE,
    Perimetro.Q4_FITTI_GRUPPO_NATURA: Natura.NATURA,
    Perimetro.Q5_SOLO_CANONE: Natura.NATURA,
    Perimetro.R0_STANDALONE_PIENO: Natura.NATURA,
}


@dataclass(frozen=True)
class Componenti:
    """Una riga della vista per un periodo. ``None`` = non disponibile: mese non derivabile, oppure conto
    ASSENTE dallo snapshot (la vista lo espone come NULL, mai come 0: un conto presente con saldo 0 è 0)."""

    ricavi_totali: float | None
    costi_55_71: float | None
    canone_651101: float | None
    angelina_65010591: float | None
    cvm_65010590: float | None
    servizi_bancari_75: float | None
    oneri_finanziari_75: float | None

    @classmethod
    def da_riga(cls, riga, periodo: Periodo) -> Componenti:
        """Costruisce dai campi della vista: suffisso ``_ytd`` o prefisso ``delta_``."""
        get = (
            (lambda k: riga[f"{k}_ytd"])
            if periodo is Periodo.YTD
            else (lambda k: riga[f"delta_{k}"])
        )
        return cls(
            ricavi_totali=get("ricavi_totali"),
            costi_55_71=get("costi_55_71"),
            canone_651101=get("canone_651101"),
            angelina_65010591=get("angelina_65010591"),
            cvm_65010590=get("cvm_65010590"),
            servizi_bancari_75=get("servizi_bancari_75"),
            oneri_finanziari_75=get("oneri_finanziari_75"),
        )


@dataclass(frozen=True)
class Limite:
    """Limite versionato del contratto di controllo. Vive nel chiamante (bersaglio importato), non nel SQL."""

    valore: float
    verso: str  # "max" = oltre il valore scatta il superamento
    versione: str
    fonte: str

    def __post_init__(self) -> None:
        if self.verso != "max":
            raise ValueError(f"verso non supportato: {self.verso!r} (solo 'max')")
        if not _finito(self.valore):
            raise ValueError(f"limite non finito: {self.valore!r}")


def _finito(v: float | None) -> bool:
    """True solo per un numero reale finito. None, NaN e ±inf sono 'non disponibile'."""
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def numeratore(c: Componenti, perimetro: Perimetro, natura: Natura) -> float | None:
    """Costi del perimetro. None se un componente richiesto manca (mese non derivabile)."""
    if perimetro is None or natura is None:
        raise ValueError("perimetro e natura sono obbligatori: nessun default")
    if not _finito(c.costi_55_71):
        return None
    tot = float(c.costi_55_71)
    for nome in _ESCLUSIONI[perimetro]:
        v = getattr(c, nome)
        if not _finito(
            v
        ):  # conto assente (NULL) o valore non finito: nessuna evidenza che sia zero
            return None
        tot -= v
    if natura is Natura.NATURA:
        if not _finito(c.servizi_bancari_75):
            return None
        tot += c.servizi_bancari_75
    return tot


def rapporto(
    c: Componenti, perimetro: Perimetro, natura: Natura, periodo: Periodo
) -> float | None:
    """costi del perimetro / ricavi totali. None = non determinabile (ricavi zero/assenti, mese non
    derivabile). Non arrotonda, non limita a 0–1 (nei mesi di chiusura supera 1)."""
    if periodo is None:
        raise ValueError("periodo obbligatorio: nessun default")
    num = numeratore(c, perimetro, natura)
    if num is None or not _finito(c.ricavi_totali) or c.ricavi_totali == 0:
        return None
    r = num / c.ricavi_totali
    return r if _finito(r) else None


def valuta(r: float | None, limite: Limite) -> str:
    """Esito rispetto al limite, senza arrotondare: 'oltre' | 'al_limite' | 'entro' | 'non_valutabile'.
    Un rapporto non determinabile non è mai 'entro'."""
    if not _finito(r):  # None, NaN, ±inf: mai 'entro'
        return "non_valutabile"
    if r > limite.valore:
        return "oltre"
    if r == limite.valore:
        return "al_limite"
    return "entro"
