"""Scenario cassa: documento JSON <-> righe `p_*` <-> `Scenario` del motore.

Conversione pura, nessun I/O salvo `carica_seme`. Importi sempre interi in
centesimi. Il canone a scaletta è un parametro (in `ScenarioRow.parametri`),
non viene espanso in righe.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from core.schemas import (
    ProgettoPagamentoRow,
    ScenarioFlussoRow,
    ScenarioRow,
    validate_batch,
)
from verticals.condges.cassa_motore import (
    Finanziamento,
    Pagamento,
    Progetto,
    Riga,
    ScalettaCanone,
    Scenario,
)

SCHEMA = "cdg-cassa-scenario/1"
Base = dict[str, dict]


def _cent(v):
    if type(v) is not int:
        raise ValueError(f"importo {v!r} non è intero: servono centesimi interi")
    return v


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _mesi(d: dict) -> dict[str, int]:
    return {m: _cent(v) for m, v in d.items()}


def _scaletta_to_dict(c: ScalettaCanone | None) -> dict | None:
    if c is None:
        return None
    return {
        "netto_per_anno": {str(a): v for a, v in c.netto_per_anno.items()},
        "rate_n": c.rate_n,
        "da_mese": c.da_mese,
        "calendario": c.calendario,
        "aliquota_iva": c.aliquota_iva,
    }


def _scaletta_from_dict(d: dict | None) -> ScalettaCanone | None:
    if d is None:
        return None
    cal = d.get("calendario")
    return ScalettaCanone(
        netto_per_anno={int(a): _cent(v) for a, v in d["netto_per_anno"].items()},
        rate_n=d["rate_n"],
        da_mese=d["da_mese"],
        calendario=None if cal is None else _mesi(cal),
        aliquota_iva=d.get("aliquota_iva", 22),
    )


def scenario_to_json(
    sc: Scenario,
    base: Base,
    nome: str | None = None,
    salvato_il: datetime | None = None,
) -> str:
    doc = {
        "schema": SCHEMA,
        "nome": nome if nome is not None else sc.nome,
        "salvato_il": (salvato_il or datetime.now()).isoformat(),
        "base": base,
        "scenario": {
            "nome": sc.nome,
            "soglia": sc.soglia,
            "canone": _scaletta_to_dict(sc.canone),
            "progetti": [
                {
                    "id": p.id,
                    "nome": p.nome,
                    "societa": p.societa,
                    "acceso": p.acceso,
                    "stato": p.stato,
                    "pagamenti": [
                        {
                            "nome": g.nome,
                            "mesi": g.mesi,
                            "aliquota_iva": g.aliquota_iva,
                            "stato": g.stato,
                            "fornitore_id": g.fornitore_id,
                        }
                        for g in p.pagamenti
                    ],
                    "contratti": p.contratti,
                }
                for p in sc.progetti
            ],
            "finanziamenti": [
                {
                    "id": f.id,
                    "nome": f.nome,
                    "societa": f.societa,
                    "erogazioni": f.erogazioni,
                    "rate": f.rate,
                    "stato": f.stato,
                }
                for f in sc.finanziamenti
            ],
            "manuali": [
                {
                    "societa": r.societa,
                    "voce_id": r.voce_id,
                    "mese": r.mese,
                    "importo_cent": r.importo,
                    "direzione": r.direzione,
                    "origine": r.origine,
                }
                for r in sc.manuali
            ],
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=1)


def _load(raw: str | bytes) -> dict:
    doc = json.loads(raw)
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"schema {doc.get('schema')!r} diverso da {SCHEMA}")
    return doc


def scenario_from_json(raw: str | bytes) -> tuple[Scenario, Base, dict]:
    doc = _load(raw)
    s = doc["scenario"]
    progetti = [
        Progetto(
            id=p["id"],
            nome=p["nome"],
            societa=p["societa"],
            acceso=p["acceso"],
            stato=p["stato"],
            pagamenti=[
                Pagamento(
                    nome=g["nome"],
                    mesi=_mesi(g["mesi"]),
                    aliquota_iva=g["aliquota_iva"],
                    stato=g["stato"],
                    fornitore_id=g.get("fornitore_id"),
                )
                for g in p["pagamenti"]
            ],
            contratti=p.get("contratti", []),
        )
        for p in s["progetti"]
    ]
    for p in progetti:
        nomi = [g.nome for g in p.pagamenti]
        for n in set(nomi):
            if nomi.count(n) > 1:
                raise ValueError(f"progetto {p.id}: pagamento {n!r} duplicato")
    fin = [
        Finanziamento(
            id=f["id"],
            nome=f["nome"],
            societa=f["societa"],
            erogazioni=_mesi(f["erogazioni"]),
            rate=_mesi(f["rate"]),
            stato=f["stato"],
        )
        for f in s["finanziamenti"]
    ]
    manuali = [
        Riga(
            r["societa"],
            r["voce_id"],
            r["mese"],
            _cent(r["importo_cent"]),
            r["direzione"],
            r["origine"],
        )
        for r in s["manuali"]
    ]
    sc = Scenario(
        nome=s["nome"],
        progetti=progetti,
        finanziamenti=fin,
        canone=_scaletta_from_dict(s["canone"]),
        manuali=manuali,
        soglia=_cent(s["soglia"]),
    )
    meta = {k: doc.get(k) for k in ("nome", "salvato_il", "schema")}
    return sc, doc["base"], meta


def scenario_id(raw: str | bytes) -> str:
    doc = _load(raw)
    doc.pop("salvato_il", None)
    return hashlib.sha256(_dumps(doc).encode()).hexdigest()[:16]


def righe_p(
    raw: str | bytes, raw_object_id: str, now: datetime, autore: str
) -> tuple[list[dict], list[dict], list[dict]]:
    sc, base, meta = scenario_from_json(raw)
    sid = scenario_id(raw)
    ts = now.isoformat()
    comuni = {
        "scenario_id": sid,
        "raw_object_id": raw_object_id,
        "data_caricamento": ts,
    }

    parametri = {
        "scenario_nome": sc.nome,
        "canone": _scaletta_to_dict(sc.canone),
        "soglia": sc.soglia,
        "progetti": [
            {
                "id": p.id,
                "nome": p.nome,
                "societa": p.societa,
                "stato": p.stato,
                "contratti": p.contratti,
            }
            for p in sc.progetti
        ],
        "finanziamenti": [
            {"id": f.id, "nome": f.nome, "societa": f.societa, "stato": f.stato}
            for f in sc.finanziamenti
        ],
    }
    scenari = [
        {
            **comuni,
            "nome": meta["nome"],
            "creato_il": meta["salvato_il"] or ts,
            "autore": autore,
            "schema_doc": SCHEMA,
            "base": _dumps(base),
            "parametri": _dumps(parametri),
            "progetti_accesi": [p.id for p in sc.progetti if p.acceso],
            "note": None,
            "hash_riga": _hash(sid),
        }
    ]

    flussi = []

    def flusso(societa, mese, voce, importo, direzione, origine):
        flussi.append(
            {
                **comuni,
                "societa_id": societa,
                "mese": mese,
                "voce_id": voce,
                "importo_cent": importo,
                "direzione": direzione,
                "origine": origine,
                "hash_riga": _hash(
                    sid, societa, mese, voce, direzione, origine, importo
                ),
            }
        )

    for f in sc.finanziamenti:
        for m, v in f.erogazioni.items():
            flusso(f.societa, m, f.id, v, "E", "finanziamento")
        for m, v in f.rate.items():
            flusso(f.societa, m, f.id, v, "U", "finanziamento")
    for r in sc.manuali:
        flusso(r.societa, r.mese, r.voce_id, r.importo, r.direzione, "manuale")

    pagamenti = [
        {
            **comuni,
            "progetto_id": p.id,
            "pagamento": g.nome,
            "mese": m,
            "importo_netto_cent": v,
            "aliquota_iva": g.aliquota_iva,
            "stato": g.stato,
            "fornitore_id": g.fornitore_id,
            "societa_id": p.societa,
            "hash_riga": _hash(sid, p.id, g.nome, m),
        }
        for p in sc.progetti
        for g in p.pagamenti
        for m, v in g.mesi.items()
    ]

    def dump(rows, model, ctx):
        return [model(**r).model_dump() for r in validate_batch(rows, model, ctx)]

    return (
        dump(scenari, ScenarioRow, "p_scenari"),
        dump(flussi, ScenarioFlussoRow, "p_scenario_flussi"),
        dump(pagamenti, ProgettoPagamentoRow, "p_progetti_pagamenti"),
    )


def scenario_da_righe(
    scenari: list[dict], flussi: list[dict], pagamenti: list[dict]
) -> list[tuple[Scenario, Base, dict]]:
    risultati = []
    for s in scenari:
        sid = s["scenario_id"]
        par = json.loads(s["parametri"])
        fl = [r for r in flussi if r["scenario_id"] == sid]
        pg = [r for r in pagamenti if r["scenario_id"] == sid]

        progetti = []
        for pm in par["progetti"]:
            pagam: dict[str, Pagamento] = {}
            for r in (r for r in pg if r["progetto_id"] == pm["id"]):
                g = pagam.setdefault(
                    r["pagamento"],
                    Pagamento(
                        nome=r["pagamento"],
                        mesi={},
                        aliquota_iva=r["aliquota_iva"],
                        stato=r["stato"],
                        fornitore_id=r["fornitore_id"],
                    ),
                )
                g.mesi[r["mese"]] = r["importo_netto_cent"]
            progetti.append(
                Progetto(
                    id=pm["id"],
                    nome=pm["nome"],
                    societa=pm["societa"],
                    acceso=pm["id"] in s["progetti_accesi"],
                    stato=pm["stato"],
                    pagamenti=list(pagam.values()),
                    contratti=pm.get("contratti", []),
                )
            )

        def leva(fid, direzione):
            return {
                r["mese"]: r["importo_cent"]
                for r in fl
                if r["origine"] == "finanziamento"
                and r["voce_id"] == fid
                and r["direzione"] == direzione
            }

        finanz = [
            Finanziamento(
                id=f["id"],
                nome=f["nome"],
                societa=f["societa"],
                erogazioni=leva(f["id"], "E"),
                rate=leva(f["id"], "U"),
                stato=f["stato"],
            )
            for f in par["finanziamenti"]
        ]
        manuali = [
            Riga(
                r["societa_id"],
                r["voce_id"],
                r["mese"],
                r["importo_cent"],
                r["direzione"],
                r["origine"],
            )
            for r in fl
            if r["origine"] == "manuale"
        ]
        sc = Scenario(
            nome=par["scenario_nome"],
            progetti=progetti,
            finanziamenti=finanz,
            canone=_scaletta_from_dict(par["canone"]),
            manuali=manuali,
            soglia=par["soglia"],
        )
        meta = {
            "nome": s["nome"],
            "salvato_il": s["creato_il"],
            "schema": s["schema_doc"],
        }
        risultati.append((sc, json.loads(s["base"]), meta))
    return risultati


def base_uguale(a: Base, b: Base) -> bool:
    return all(
        s in a and s in b and a[s].get("raw_object_id") == b[s].get("raw_object_id")
        for s in set(a) | set(b)
    )


def carica_seme(path: Path) -> tuple[Scenario, Base]:
    sc, base, _ = scenario_from_json(Path(path).read_text(encoding="utf-8"))
    return sc, base
