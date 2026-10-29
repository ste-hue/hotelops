"""Motore cassa headless: saldi mensili per società, minimi, consolidato.

Tutti gli importi sono interi in centesimi. Nessun I/O. Le entrate/uscite sono
sempre positive; la direzione sta in `direzione`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from core.schemas import ORIGINI_CASSA as ORIGINI

__all__ = [
    "ORIGINI",
    "Ancora",
    "Conto",
    "Riga",
    "Flusso",
    "Pagamento",
    "Progetto",
    "Finanziamento",
    "Fatto",
    "Scenario",
    "Input",
    "RigaMese",
    "Minimo",
    "Consolidato",
    "Risultato",
    "to_cent",
    "iva",
    "calcola",
    "distribuisci",
    "to_dict",
]

SOCIETA = ("ORTI", "INTUR")


def to_cent(x: float | str | Decimal) -> int:
    return int(Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)


def iva(netto: int, aliquota: int) -> int:
    return (netto * (100 + aliquota) + 50) // 100


@dataclass(frozen=True)
class Conto:
    saldo: int
    attestato: bool
    motivo: str


@dataclass(frozen=True)
class Ancora:
    societa: str
    data: date
    saldo: int
    attestato: bool
    conti: dict[str, Conto]


@dataclass(frozen=True)
class Riga:
    societa: str
    voce_id: str
    mese: str
    importo: int
    direzione: Literal["E", "U"]
    origine: str


@dataclass(frozen=True)
class Flusso:
    nome: str
    da: str
    a: str
    mese: str
    importo: int
    stato: str  # "pf" | "una_gamba" | "scenario"


@dataclass
class Pagamento:
    nome: str
    mesi: dict[str, int]
    aliquota_iva: int = 22
    stato: str = "ipotesi"
    fornitore_id: str | None = None


@dataclass
class Progetto:
    id: str
    nome: str
    societa: str
    acceso: bool
    stato: str
    pagamenti: list[Pagamento]


@dataclass(frozen=True)
class Finanziamento:
    id: str
    nome: str
    societa: str
    erogazioni: dict[str, int]
    rate: dict[str, int]
    stato: str


@dataclass(frozen=True)
class Fatto:
    societa: str
    progetto_id: str
    fornitore_id: str | None
    mese: str
    importo: int
    evento_id: str


@dataclass(frozen=True)
class Scenario:
    nome: str
    progetti: list[Progetto]
    finanziamenti: list[Finanziamento]
    canone: Any = None  # ScalettaCanone | None (Task 2)
    manuali: list[Riga] = field(default_factory=list)
    soglia: int = 0


@dataclass(frozen=True)
class Input:
    mesi: list[str]
    mesi_ipotetici: frozenset[str]
    ancore: dict[str, Ancora]
    pf: list[Riga]
    intercompany: list[Flusso]
    fatti: list[Fatto]
    scenario: Scenario


@dataclass(frozen=True)
class RigaMese:
    mese: str
    societa: str
    ini: int
    entrate: dict[str, int]
    uscite: dict[str, int]
    fin: int


@dataclass(frozen=True)
class Minimo:
    mese: str
    saldo: int
    sotto_soglia: tuple[str, ...]
    coda_mese: str | None
    coda_saldo: int | None


@dataclass(frozen=True)
class Consolidato:
    mese: str
    saldo: int
    intercompany_nettato: int
    residuo: int


@dataclass(frozen=True)
class Risultato:
    righe: list[RigaMese]
    minimi: dict[str, Minimo]
    consolidato: list[Consolidato]
    non_riconciliati: list[Fatto]


def _movimenti(
    inp: Input, societa: str, mese: str
) -> tuple[dict[str, int], dict[str, int]]:
    ent = dict.fromkeys(ORIGINI, 0)
    usc = dict.fromkeys(ORIGINI, 0)
    sc = inp.scenario

    def add(riga: Riga) -> None:
        if riga.societa == societa and riga.mese == mese:
            (ent if riga.direzione == "E" else usc)[riga.origine] += riga.importo

    for r in inp.pf:
        add(r)
    for r in sc.manuali:
        add(r)
    for f in inp.intercompany:
        if f.mese != mese:
            continue
        if f.a == societa and f.stato != "una_gamba":
            ent["canone"] += f.importo
        if f.da == societa:
            usc["canone"] += f.importo
    for fin in sc.finanziamenti:
        if fin.societa == societa:
            ent["finanziamento"] += fin.erogazioni.get(mese, 0)
            usc["finanziamento"] += fin.rate.get(mese, 0)
    for p in sc.progetti:
        if p.acceso and p.societa == societa:
            for pag in p.pagamenti:
                usc["progetto"] += iva(pag.mesi.get(mese, 0), pag.aliquota_iva)
    for f in inp.fatti:
        if f.societa == societa and f.mese == mese:
            usc["fatto"] += f.importo
    return ent, usc


def calcola(inp: Input) -> Risultato:
    righe: list[RigaMese] = []
    for soc in SOCIETA:
        saldo = inp.ancore[soc].saldo
        for mese in inp.mesi:
            ent, usc = _movimenti(inp, soc, mese)
            fin = saldo + sum(ent.values()) - sum(usc.values())
            righe.append(RigaMese(mese, soc, saldo, ent, usc, fin))
            saldo = fin

    minimi = {}
    for soc in SOCIETA:
        mie = [r for r in righe if r.societa == soc]
        pf = [r for r in mie if r.mese not in inp.mesi_ipotetici]
        coda = [r for r in mie if r.mese in inp.mesi_ipotetici]
        m = min(pf, key=lambda r: r.fin)
        c = min(coda, key=lambda r: r.fin) if coda else None
        minimi[soc] = Minimo(
            mese=m.mese,
            saldo=m.fin,
            sotto_soglia=tuple(r.mese for r in pf if r.fin < inp.scenario.soglia),
            coda_mese=c.mese if c else None,
            coda_saldo=c.fin if c else None,
        )

    consolidato = []
    for mese in inp.mesi:
        fl = [
            f
            for f in inp.intercompany
            if f.mese == mese and f.da in SOCIETA and f.a in SOCIETA
        ]
        consolidato.append(
            Consolidato(
                mese=mese,
                saldo=sum(r.fin for r in righe if r.mese == mese),
                intercompany_nettato=sum(
                    f.importo for f in fl if f.stato != "una_gamba"
                ),
                residuo=sum(f.importo for f in fl if f.stato == "una_gamba"),
            )
        )
    return Risultato(righe, minimi, consolidato, [])


def distribuisci(totale: int, da: str, n: int, mesi: list[str]) -> dict[str, int]:
    if da not in mesi or mesi.index(da) + n > len(mesi):
        raise ValueError(f"oltre l'orizzonte: {n} rate da {da}")
    i = mesi.index(da)
    quota = totale // n
    out = {m: quota for m in mesi[i : i + n - 1]}
    out[mesi[i + n - 1]] = totale - quota * (n - 1)
    return out


def to_dict(r: Risultato) -> dict:
    d = asdict(r)
    for m in d["minimi"].values():
        m["sotto_soglia"] = list(m["sotto_soglia"])
    return d
