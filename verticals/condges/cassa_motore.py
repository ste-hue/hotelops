"""Motore cassa headless: saldi mensili per società, minimi, consolidato.

Tutti gli importi sono interi in centesimi. Nessun I/O. Le entrate/uscite sono
sempre positive; la direzione sta in `direzione`.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from core.schemas import ORIGINI_CASSA as ORIGINI

# Origine speciale delle righe manuali: «sostituzione» = al posto della voce PF di quel mese.
SOSTITUZIONE = "sostituzione"

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
    "ScalettaCanone",
    "Scenario",
    "Input",
    "RigaMese",
    "Minimo",
    "Consolidato",
    "Risultato",
    "to_cent",
    "iva",
    "calcola",
    "flussi_canone",
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
    # Riferimenti (preventivo, contratto, fattura): [{"titolo", "url"}], memoria dell'interfaccia.
    documenti: list[dict] = field(default_factory=list)


@dataclass
class Progetto:
    id: str
    nome: str
    societa: str
    acceso: bool
    stato: str
    pagamenti: list[Pagamento]
    # Parametri dei contratti da cui la pagina genera i pagamenti (anticipo, SAL, ritenuta):
    # memoria dell'interfaccia, il calcolo legge solo `pagamenti`.
    contratti: list[dict] = field(default_factory=list)
    # La cartella Drive del progetto (preventivi, fatture): memoria dell'interfaccia.
    drive_url: str | None = None


@dataclass(frozen=True)
class Finanziamento:
    id: str
    nome: str
    societa: str
    erogazioni: dict[str, int]
    rate: dict[str, int]
    stato: str
    # Quanto la banca ha promesso, in centesimi: serve al controllo «erogato X di Y» della pagina.
    # Il calcolo legge solo `erogazioni` e `rate`; None = non registrato.
    importo: int | None = None
    # Riferimenti (relazione notarile, delibera, contratto di mutuo): [{"titolo", "url"}], memoria dell'interfaccia.
    documenti: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Fatto:
    societa: str
    progetto_id: str
    fornitore_id: str | None
    mese: str
    importo: int
    evento_id: str


@dataclass(frozen=True)
class ScalettaCanone:
    netto_per_anno: dict[int, int]
    rate_n: int
    da_mese: str
    calendario: dict[str, int] | None = None
    aliquota_iva: int = 22


@dataclass(frozen=True)
class Scenario:
    nome: str
    progetti: list[Progetto]
    finanziamenti: list[Finanziamento]
    canone: ScalettaCanone | None = None
    manuali: list[Riga] = field(default_factory=list)
    soglia: int = 0
    # Il fornitore come oggetto: {id usato nei pagamenti: {nome, codice_esolver, societa, drive_url}}.
    # Memoria dell'interfaccia; il calcolo non lo legge.
    fornitori: dict = field(default_factory=dict)


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
            # la sostituzione conta nel secchio del PF: è il PF, corretto
            chiave = "pf" if riga.origine == SOSTITUZIONE else riga.origine
            (ent if riga.direzione == "E" else usc)[chiave] += riga.importo

    for r in inp.pf:
        add(r)
    for r in sc.manuali:
        add(r)
    for f in inp.intercompany:
        if f.mese != mese:
            continue
        if f.stato == "una_gamba":
            # Una sola gamba: conta dal lato di chi la conosce, mai la contropartita.
            if f.da in SOCIETA:
                if f.da == societa:
                    usc["canone"] += f.importo
            elif f.a == societa:
                ent["canone"] += f.importo
            continue
        if f.a == societa:
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


def flussi_canone(s: ScalettaCanone, mesi: list[str]) -> list[Flusso]:
    """Canone lordo ORTI -> INTUR: il calendario libero di un anno vince sulle rate."""
    out: list[Flusso] = []
    for anno, netto in sorted(s.netto_per_anno.items()):
        cal = {m: v for m, v in (s.calendario or {}).items() if m[:4] == str(anno)}
        if cal:
            lordi = {m: iva(v, s.aliquota_iva) for m, v in sorted(cal.items())}
        else:
            # Stesso mese di partenza in ogni anno; anno fuori orizzonte: saltato.
            da = f"{anno}-{s.da_mese[5:]}"
            if da not in mesi:
                continue
            lordi = distribuisci(iva(netto, s.aliquota_iva), da, s.rate_n, mesi)
        out += [
            Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", m, v, "scenario")
            for m, v in lordi.items()
            if m in mesi
        ]
    return out


def _riconcilia(
    progetti: list[Progetto], fatti: list[Fatto]
) -> tuple[list[Progetto], list[Fatto]]:
    """Riduce (su copie) i pagamenti dello stesso fornitore, dal mese piu' vecchio."""
    progetti = copy.deepcopy(progetti)
    per_id = {p.id: p for p in progetti}
    non_ric: list[Fatto] = []
    for f in fatti:
        p = per_id.get(f.progetto_id)
        slot = sorted(
            (
                (m, pag)
                for pag in (p.pagamenti if p else [])
                if f.fornitore_id is not None and pag.fornitore_id == f.fornitore_id
                for m in pag.mesi
            ),
            key=lambda x: x[0],
        )
        if not slot:
            non_ric.append(f)
            continue
        resto = f.importo
        for m, pag in slot:
            if resto <= 0:
                break
            lordo = iva(pag.mesi[m], pag.aliquota_iva)
            presa = min(resto, lordo)
            resto -= presa
            k = 100 + pag.aliquota_iva
            # Netto residuo arrotondato half-up (esatto per aliquota 0).
            pag.mesi[m] = 0 if presa == lordo else ((lordo - presa) * 100 + k // 2) // k
    return progetti, non_ric


def calcola(inp: Input) -> Risultato:
    sc = inp.scenario
    pf = inp.pf
    # Le erogazioni dello scenario sostituiscono le righe PF di finanziamento.
    con_fin = {f.societa for f in sc.finanziamenti}
    pf = [
        r
        for r in pf
        if not (r.voce_id == "ENTRATE_FINANZIAMENTI" and r.societa in con_fin)
    ]
    # Una riga manuale con origine «sostituzione» prende il posto della voce PF di quel mese
    # (società, voce, mese): il PF esce, la riga entra, e in cassa conta come PF. È la leva
    # «questa voce del PF, secondo Rosa, vale X»: non un progetto, non un'aggiunta.
    sost = {
        (r.societa, r.voce_id, r.mese) for r in sc.manuali if r.origine == SOSTITUZIONE
    }
    if sost:
        pf = [r for r in pf if (r.societa, r.voce_id, r.mese) not in sost]
    interc = inp.intercompany
    if sc.canone:
        nuovi = flussi_canone(sc.canone, inp.mesi)
        # Si tolgono i canoni PF solo degli anni in cui la scaletta emette davvero.
        anni = {f.mese[:4] for f in nuovi}
        interc = [
            f
            for f in interc
            if not (f.nome.startswith("Fitto Hotel") and f.mese[:4] in anni)
        ] + nuovi
    progetti, non_ric = _riconcilia(sc.progetti, inp.fatti)
    inp = replace(
        inp, pf=pf, intercompany=interc, scenario=replace(sc, progetti=progetti)
    )
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
        # Tutti i mesi ipotetici: nessun mese PF, il minimo e' quello della coda.
        m = min(pf or coda, key=lambda r: r.fin)
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
        fl_tutti = [f for f in inp.intercompany if f.mese == mese]
        consolidato.append(
            Consolidato(
                mese=mese,
                saldo=sum(r.fin for r in righe if r.mese == mese),
                intercompany_nettato=sum(
                    f.importo for f in fl if f.stato != "una_gamba"
                ),
                residuo=sum(f.importo for f in fl_tutti if f.stato == "una_gamba"),
            )
        )
    return Risultato(righe, minimi, consolidato, non_ric)


def distribuisci(totale: int, da: str, n: int, mesi: list[str]) -> dict[str, int]:
    if n < 1:
        raise ValueError(f"numero rate non valido: {n}")
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
