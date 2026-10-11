"""Budget camere per driver — modello puro (nessun I/O verso BigQuery).

Spec: docs/superpowers/specs/2026-10-04-budget-camere-panorama-design.md
"""

from __future__ import annotations

import calendar
import csv
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

APERTURA_2027 = (4, 20)  # prima notte venduta (Stefano, 2026-10-05)
CHIUSURA_2027 = (10, 20)  # ultima notte venduta
PROGETTO_CSV = Path(__file__).with_name("hpan26piano3.csv")
TUTTO_ANNO = ((1, 1), (12, 31))
# Notti del file per tipologia / notti delle statistiche. Sotto la soglia il file
# contiene le prenotazioni di quando fu esportato, non il consuntivo.
COPERTURA_MINIMA = 0.97


def in_calendario(
    d: date, apertura: tuple[int, int], chiusura: tuple[int, int]
) -> bool:
    return apertura <= (d.month, d.day) <= chiusura


def _ultimo_giorno(anno: int, mese: int, chiusura: tuple[int, int]) -> int:
    return chiusura[1] if mese == chiusura[0] else calendar.monthrange(anno, mese)[1]


def giorni_apertura(anno: int, apertura, chiusura) -> dict[int, int]:
    out = {}
    for mese in range(apertura[0], chiusura[0] + 1):
        primo = apertura[1] if mese == apertura[0] else 1
        out[mese] = _ultimo_giorno(anno, mese, chiusura) - primo + 1
    return out


def carica_progetto(path: Path = PROGETTO_CSV) -> dict[str, str]:
    with path.open(newline="") as f:
        return {r["room_id"]: r["categoria_2027"] for r in csv.DictReader(f)}


def inventario(
    camere: list[dict], progetto: dict[str, str] | None = None
) -> dict[str, int]:
    """Camere per categoria; col progetto, le camere indicate cambiano categoria."""
    progetto = progetto or {}
    ids = {c["room_id"] for c in camere}
    categorie = {c["tipologia"] for c in camere}
    for room_id, cat in progetto.items():
        if room_id not in ids:
            raise ValueError(f"progetto: camera {room_id} non è in d_camere")
        if cat not in categorie:
            raise ValueError(f"progetto: categoria {cat!r} non esiste in d_camere")
    return dict(Counter(progetto.get(c["room_id"], c["tipologia"]) for c in camere))


def _base_per_categoria(giornaliero, codici, apertura, chiusura) -> dict:
    """(mese, categoria) → notti, ricavo; solo i giorni del calendario."""
    out: dict = defaultdict(lambda: {"notti": 0, "ricavo": 0.0})
    for r in giornaliero:
        if not r["notti"] or not in_calendario(r["data"], apertura, chiusura):
            continue
        if r["codice"] not in codici:
            raise ValueError(
                f"tipologia venduta {r['codice']!r} non è in d_camere "
                f"({r['notti']} notti il {r['data']})"
            )
        cella = out[(r["data"].month, codici[r["codice"]])]
        cella["notti"] += r["notti"]
        cella["ricavo"] += r["ricavo"]
    return dict(out)


def _totali_pms(giornaliero, apertura, chiusura) -> dict:
    """mese → notti, ricavo 01ROOM, giorni con ricavo caricato, giorni con vendite."""
    out: dict = defaultdict(
        lambda: {"notti": 0, "ricavo": 0.0, "giorni": 0, "venduti": 0}
    )
    for r in giornaliero:
        if not in_calendario(r["data"], apertura, chiusura):
            continue
        cella = out[r["data"].month]
        cella["notti"] += r["notti"] or 0
        cella["venduti"] += 1 if r["notti"] else 0
        if r["ricavo"] is not None:
            cella["ricavo"] += r["ricavo"]
            cella["giorni"] += 1
    return dict(out)


def notti_2027(
    notti_base: dict[str, int], inv26: dict[str, int], inv27: dict[str, int]
) -> dict[str, int]:
    """Scala ogni categoria col rapporto camere 2027/2026, poi riporta al totale del mese.

    Resti assegnati col metodo del resto più alto: il totale è conservato esatto.
    """
    totale = sum(notti_base.values())
    grezzo = {c: n * inv27.get(c, 0) / inv26[c] for c, n in notti_base.items()}
    somma = sum(grezzo.values())
    if not somma:
        return dict.fromkeys(notti_base, 0)
    quote = {c: v * totale / somma for c, v in grezzo.items()}
    out = {c: int(q) for c, q in quote.items()}
    resto = totale - sum(out.values())
    for c in sorted(quote, key=lambda c: (out[c] - quote[c], c))[:resto]:
        out[c] += 1
    return out


def effetti(righe: list[dict]) -> dict:
    """Occupazione, mix, prezzo di un mese. base + i tre effetti = budget, esatto."""
    r0 = sum(r["notti_base"] * (r["prezzo_base"] or 0) for r in righe)
    t0 = sum(r["notti_base"] for r in righe)
    t1 = sum(r["notti"] for r in righe)
    a_prezzi_base = sum(r["notti"] * (r["prezzo_base"] or 0) for r in righe)
    budget = sum(r["notti"] * (r["prezzo"] or 0) for r in righe)
    medio = r0 / t0 if t0 else 0.0
    return {
        "base": r0,
        "occupazione": (t1 - t0) * medio,
        "mix": a_prezzi_base - t1 * medio,
        "prezzo": budget - a_prezzi_base,
        "budget": budget,
    }


def costruisci(
    camere: list[dict],
    categorie_giorno: list[dict],
    pms_giorno: list[dict],
    progetto: dict[str, str],
    anno_base: int = 2026,
    apertura: tuple[int, int] = APERTURA_2027,
    chiusura: tuple[int, int] = CHIUSURA_2027,
) -> dict:
    codici = {c["cod_camera"]: c["tipologia"] for c in camere}
    inv26 = inventario(camere)
    inv27 = inventario(camere, progetto)
    categorie = sorted(set(inv26) | set(inv27))
    base = _base_per_categoria(categorie_giorno, codici, apertura, chiusura)
    reale = _totali_pms(pms_giorno, *TUTTO_ANNO)
    cal = _totali_pms(pms_giorno, apertura, chiusura)
    giorni_base = giorni_apertura(anno_base, apertura, chiusura)
    giorni_budget = giorni_apertura(anno_base + 1, apertura, chiusura)

    caricati: dict = defaultdict(list)
    for r in categorie_giorno:
        if in_calendario(r["data"], apertura, chiusura):
            caricati[r["data"].month].append(r["caricato"])

    vuoto = {"notti": 0, "ricavo": 0.0, "giorni": 0, "venduti": 0}
    righe, mesi = [], []
    for mese in giorni_budget:
        fine = date(anno_base, mese, _ultimo_giorno(anno_base, mese, chiusura))
        c_mese, r_mese = cal.get(mese, vuoto), reale.get(mese, vuoto)
        nb = {c: base[(mese, c)]["notti"] for c in categorie if (mese, c) in base}
        completo_01room = c_mese["giorni"] == giorni_base[mese]
        osservato = (
            bool(caricati.get(mese))
            and min(caricati[mese]) > fine
            and completo_01room
            and sum(nb.values()) >= COPERTURA_MINIMA * c_mese["notti"]
        )
        stato = "osservato" if osservato else "stima"
        n27 = notti_2027(nb, inv26, inv27)
        ricavo_cat = sum(base[(mese, c)]["ricavo"] for c in nb)
        for c in categorie:
            cella = base.get((mese, c))
            righe.append(
                {
                    "mese": mese,
                    "categoria": c,
                    "camere_2026": inv26.get(c, 0),
                    "camere_2027": inv27.get(c, 0),
                    "stato": stato,
                    "notti_base": cella["notti"] if cella else 0,
                    "prezzo_base": cella["ricavo"] / cella["notti"] if cella else None,
                    "notti_2027": n27.get(c, 0),
                }
            )
        mesi.append(
            {
                "mese": mese,
                "stato": stato,
                "giorni_2026": r_mese["venduti"],
                "giorni_2027": giorni_budget[mese],
                "notti_reali": r_mese["notti"],
                "ricavo_reale": r_mese["ricavo"] if completo_01room else None,
                "notti_calendario": c_mese["notti"],
                "ricavo_calendario": c_mese["ricavo"] if completo_01room else None,
                "raccordo": c_mese["ricavo"] / ricavo_cat
                if osservato and ricavo_cat
                else None,
                "camere": sum(inv27.values()),
            }
        )
    return {
        "anno_base": anno_base,
        "apertura": apertura,
        "chiusura": chiusura,
        "righe": righe,
        "mesi": mesi,
    }
