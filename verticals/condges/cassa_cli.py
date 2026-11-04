"""Cassa senza pagina: simulare, confrontare, creare varianti e promuovere il seme.

Spec: ``docs/superpowers/specs/2026-11-04-cdg-cassa-motore-headless-design.md`` (fase 1).

    hotelops cdg cassa simula   [SCENARIO] [--vista pf|scenario] [--mese YYYY-MM] [--json]
    hotelops cdg cassa confronta A B [--da YYYY-MM] [--a YYYY-MM] [--base-diverse] [--json]
    hotelops cdg cassa variante NOME --da SCENARIO [--canone NxRATA@YYYY-MM|pf]
                                     [--accendi ID] [--spegni ID] [--ipotesi TESTO] [--sostituisci]
    hotelops cdg cassa scenari
    hotelops cdg cassa promuovi NOME --autorizzato-da "Stefano, <data>, <dove>"

SCENARIO è `seme` (default), il nome di un file in `scenari/`, oppure il percorso di un JSON
esportato dall'app. I numeri sono quelli della pagina: stesso payload (`payload_da_stato`),
stesso allungamento dell'orizzonte, stesso motore. Nessuna scrittura su BigQuery, KV o Drive;
il seme cambia solo con `promuovi` e un'autorizzazione dichiarata.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from verticals.condges import cassa_fonti as cf
from verticals.condges import cassa_motore as M
from verticals.condges.build_cassa_artifact import (
    BANDA_PATH,
    CANONE_PATH,
    PF_CORRETTO_PATH,
    SEME_PATH,
    payload_da_stato,
)
from verticals.condges.cassa_scenario import (
    base_uguale,
    scenario_from_json,
    scenario_id,
)
from verticals.condges.cassa_tabelle import VUOTO, input_da_payload, payload_allungato

SOCIETA = ("ORTI", "INTUR")
SEME = SEME_PATH.name
STRATI = (PF_CORRETTO_PATH.name, CANONE_PATH.name, BANDA_PATH.name)
# Chiavi del documento che appartengono allo scenario; le altre del seme (scenari_ritirati…)
# sono del seme e passano da un seme al successivo.
CHIAVI_SCENARIO = (
    "schema",
    "nome",
    "salvato_il",
    "base",
    "scenario",
    "provenienza",
    "ipotesi",
)


class ErroreCassa(ValueError):
    """Errore d'uso: il messaggio va a video così com'è."""


# ── documenti ──


@dataclass(frozen=True)
class Documento:
    doc: dict
    raw: bytes
    etichetta: str  # come lo si chiama: «seme», un nome di scenari/, un percorso
    origine: str  # seme | app | variante
    percorso: Path


def _md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def risolvi(spec: str | None, home: Path) -> Documento:
    home = Path(home)
    if spec in (None, "", "seme"):
        p, etichetta = home / SEME, "seme"
    elif (home / "scenari" / f"{spec}.json").exists():
        p, etichetta = home / "scenari" / f"{spec}.json", spec
    elif Path(spec).is_file():
        p, etichetta = Path(spec), str(spec)
    else:
        raise ErroreCassa(
            f"scenario {spec!r} non trovato: non è «seme», non è un nome in "
            f"{home / 'scenari'}, non è un file"
        )
    if not p.exists():
        raise ErroreCassa(f"{p}: non c'è")
    raw = p.read_bytes()
    doc = json.loads(raw)
    scenario_from_json(raw)  # schema e contenuto validi, o esplode qui
    if p.resolve() == (home / SEME).resolve():
        origine = "seme"
    else:
        origine = (doc.get("provenienza") or {}).get("origine") or "app"
    return Documento(doc, raw, etichetta, origine, p)


def strati_locali(home: Path) -> dict[str, str]:
    """I file locali che cambiano i numeri della pagina, con il loro md5."""
    return {
        n: _md5((Path(home) / n).read_bytes())
        for n in STRATI
        if (Path(home) / n).exists()
    }


# ── calcolo ──


def calcola_doc(
    payload: dict, d: Documento, vista: str = "scenario"
) -> tuple[M.Risultato, dict]:
    """Come la pagina: orizzonte allungato ai mesi citati dallo scenario, poi il motore.
    `vista="pf"` è il PF di Rosa senza leve (la pill «PF»)."""
    if vista not in ("pf", "scenario"):
        raise ErroreCassa(f"vista {vista!r}: pf o scenario")
    p = payload_allungato(payload, d.doc)
    sc = VUOTO if vista == "pf" else scenario_from_json(d.raw)[0]
    return M.calcola(input_da_payload(p, sc)), p


def intestazione(
    d: Documento, payload: dict, home: Path, vista: str = "scenario"
) -> dict:
    prov = d.doc.get("provenienza") or {}
    base_doc = d.doc.get("base") or {}
    return {
        "scenario": d.doc.get("nome"),
        "etichetta": d.etichetta,
        "file": str(d.percorso),
        "origine": d.origine,
        "ipotesi_e_non_piano": d.origine != "seme" or vista == "pf",
        "vista": vista,
        "scenario_id": scenario_id(d.raw),
        "md5": _md5(d.raw),
        "salvato_il": d.doc.get("salvato_il"),
        "provenienza": prov,
        "ipotesi": list(d.doc.get("ipotesi") or []),
        "snapshot_acquisito_il": payload.get("acquisito_il"),
        "pf_base": {
            s: (payload["base"].get(s) or {}).get("file_sorgente")
            for s in payload["base"]
        },
        "base_uguale": base_uguale(base_doc, payload["base"]),
        "pf_base_scenario": {
            s: (base_doc.get(s) or {}).get("file_sorgente") for s in base_doc
        },
        "strati_locali": strati_locali(home),
        "limiti": list(payload.get("limiti") or []),
    }


def _saldi(r: M.Risultato) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for x in r.righe:
        out.setdefault(x.mese, {})[x.societa] = x.fin
    return out


def simula(payload: dict, d: Documento, home: Path, vista: str = "scenario") -> dict:
    r, p = calcola_doc(payload, d, vista)
    return {
        "intestazione": intestazione(d, payload, home, vista),
        "mesi": list(p["mesi"]),
        "mesi_ipotetici": list(p.get("mesi_ipotetici") or []),
        "risultato": M.to_dict(r),
    }


def dettaglio_mese(
    payload: dict, d: Documento, mese: str, vista: str = "scenario"
) -> dict:
    """Il mese voce per voce: totali per origine dal motore, poi le righe PF e i flussi fra
    società che il motore conta davvero (dopo le sostituzioni dello scenario). Le righe del PF
    che lo scenario sostituisce compaiono in `sostituiti`, non nei conti."""
    r, p = calcola_doc(payload, d, vista)
    if mese not in p["mesi"]:
        raise ErroreCassa(
            f"{mese}: fuori dall'orizzonte ({p['mesi'][0]} → {p['mesi'][-1]})"
        )
    sc = VUOTO if vista == "pf" else scenario_from_json(d.raw)[0]
    pf_usate, flussi_usati = M.pf_e_flussi_effettivi(input_da_payload(p, sc))
    usate = {(q.societa, q.voce_id, q.mese, q.importo) for q in pf_usate}
    out = {}
    for x in r.righe:
        if x.mese != mese:
            continue
        mie = [q for q in p["pf"] if q["societa"] == x.societa and q["mese"] == mese]
        out[x.societa] = {
            "ini": x.ini,
            "fin": x.fin,
            "entrate": x.entrate,
            "uscite": x.uscite,
            "pf": sorted(
                (
                    {
                        "voce_id": q.voce_id,
                        "direzione": q.direzione,
                        "importo": q.importo,
                    }
                    for q in pf_usate
                    if q.societa == x.societa and q.mese == mese
                ),
                key=lambda q: (q["direzione"], -q["importo"]),
            ),
            "intercompany": [
                {
                    "nome": f.nome,
                    "da": f.da,
                    "a": f.a,
                    "importo": f.importo,
                    "stato": f.stato,
                }
                for f in flussi_usati
                if f.mese == mese and x.societa in (f.da, f.a)
            ],
            "sostituiti": [
                {"voce_id": q["voce_id"], "importo": q["importo"]}
                for q in mie
                if (q["societa"], q["voce_id"], q["mese"], q["importo"]) not in usate
            ]
            + [
                {"voce_id": f["nome"], "importo": f["importo"]}
                for f in p["intercompany"]
                if f["mese"] == mese
                and x.societa in (f["da"], f["a"])
                and not any(
                    (g.nome, g.da, g.a, g.importo, g.stato)
                    == (f["nome"], f["da"], f["a"], f["importo"], f["stato"])
                    for g in flussi_usati
                    if g.mese == mese
                )
            ],
        }
    return out


def confronta(
    payload: dict,
    a: Documento,
    b: Documento,
    home: Path,
    da: str | None = None,
    fino: str | None = None,
    base_diverse: bool = False,
) -> dict:
    if (
        not base_uguale(a.doc.get("base") or {}, b.doc.get("base") or {})
        and not base_diverse
    ):
        raise ErroreCassa(
            f"{a.etichetta} e {b.etichetta} sono costruiti su PF diversi: "
            "il confronto mescolerebbe due piani. Usa --base-diverse per farlo lo stesso."
        )
    ra, pa = calcola_doc(payload, a)
    rb, pb = calcola_doc(payload, b)
    sa, sb = _saldi(ra), _saldi(rb)
    mesi = [
        m for m in (pa["mesi"] if len(pa["mesi"]) >= len(pb["mesi"]) else pb["mesi"])
    ]
    mesi = [m for m in mesi if (not da or m >= da) and (not fino or m <= fino)]
    righe = []
    for m in mesi:
        riga = {"mese": m}
        for s in SOCIETA:
            va, vb = sa.get(m, {}).get(s), sb.get(m, {}).get(s)
            riga[s] = {
                "a": va,
                "b": vb,
                "diff": None if va is None or vb is None else vb - va,
            }
        righe.append(riga)
    perche = {}
    for s in SOCIETA:
        cand = [r for r in righe if r[s]["diff"] is not None]
        if not cand:
            continue
        top = max(cand, key=lambda r: abs(r[s]["diff"]))
        ma = next(x for x in ra.righe if x.mese == top["mese"] and x.societa == s)
        mb = next(x for x in rb.righe if x.mese == top["mese"] and x.societa == s)
        perche[s] = {
            "mese": top["mese"],
            "diff_fine_mese": top[s]["diff"],
            "diff_saldo_iniziale": mb.ini - ma.ini,
            "entrate": {
                o: mb.entrate[o] - ma.entrate[o]
                for o in ma.entrate
                if mb.entrate[o] != ma.entrate[o]
            },
            "uscite": {
                o: mb.uscite[o] - ma.uscite[o]
                for o in ma.uscite
                if mb.uscite[o] != ma.uscite[o]
            },
        }
    return {
        "a": intestazione(a, payload, home),
        "b": intestazione(b, payload, home),
        "base_diverse": not base_uguale(
            a.doc.get("base") or {}, b.doc.get("base") or {}
        ),
        "righe": righe,
        "minimi": {
            "a": {s: _minimo(ra, s) for s in ra.minimi},
            "b": {s: _minimo(rb, s) for s in rb.minimi},
        },
        "perche": perche,
    }


def _minimo(r: M.Risultato, s: str) -> dict:
    m = r.minimi[s]
    return {
        "mese": m.mese,
        "saldo": m.saldo,
        "coda_mese": m.coda_mese,
        "coda_saldo": m.coda_saldo,
    }


# ── varianti ──

_CANONE = re.compile(r"^(\d+)x(\d+(?:[.,]\d{1,2})?)@(\d{4}-\d{2})$")


def applica(doc: dict, modifica: str) -> None:
    """Applica una modifica (la stessa stringa che resta in `provenienza.modifiche`)."""
    tipo, _, arg = (
        modifica.partition(": ") if ": " in modifica else modifica.partition(" ")
    )
    arg = arg.strip()
    sc = doc["scenario"]
    if tipo == "canone":
        if arg == "pf":
            sc["canone"] = None
            return
        m = _CANONE.match(arg)
        if not m:
            raise ErroreCassa(
                f"canone {arg!r}: atteso NxRATA@YYYY-MM (rata netta in euro) o «pf»"
            )
        n, rata, da = int(m[1]), M.to_cent(m[2].replace(",", ".")), m[3]
        if n < 1:
            raise ErroreCassa("canone: almeno una rata")
        sc["canone"] = {
            "netto_per_anno": {da[:4]: n * rata},
            "rate_n": n,
            "da_mese": da,
            "calendario": None,
            "aliquota_iva": (sc.get("canone") or {}).get("aliquota_iva", 22),
        }
    elif tipo in ("accendi", "spegni"):
        progetti = [p for p in sc.get("progetti") or [] if p["id"] == arg]
        if not progetti:
            ids = ", ".join(p["id"] for p in sc.get("progetti") or [])
            raise ErroreCassa(
                f"progetto {arg!r} non c'è nello scenario (ci sono: {ids})"
            )
        for p in progetti:
            p["acceso"] = tipo == "accendi"
    elif tipo == "ipotesi":
        doc.setdefault("ipotesi", []).append(arg)
    else:
        raise ErroreCassa(f"modifica {modifica!r} sconosciuta")


def modifiche_da_argomenti(
    canone: str | None = None,
    accendi: list[str] | None = None,
    spegni: list[str] | None = None,
    ipotesi: list[str] | None = None,
) -> list[str]:
    out = [f"canone: {canone}"] if canone else []
    out += [f"accendi {x}" for x in accendi or []]
    out += [f"spegni {x}" for x in spegni or []]
    out += [f"ipotesi: {x}" for x in ipotesi or []]
    return out


def deriva(padre: Documento, nome: str, modifiche: list[str]) -> dict:
    """Il documento della variante, senza provenienza: è la parte che si ricalcola dal padre."""
    doc = {k: copy.deepcopy(v) for k, v in padre.doc.items() if k in CHIAVI_SCENARIO}
    doc.pop("provenienza", None)
    doc["nome"] = nome
    for m in modifiche:
        applica(doc, m)
    return doc


def variante(
    nome: str,
    padre: Documento,
    modifiche: list[str],
    payload: dict,
    home: Path,
    creato_da: str = "cli",
    sostituisci: bool = False,
    adesso: datetime | None = None,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", nome) or "_prima_" in nome:
        raise ErroreCassa(f"nome {nome!r}: lettere, cifre, - _ . (e niente «_prima_»)")
    if nome == "seme":
        raise ErroreCassa("«seme» è riservato: il seme cambia solo con `promuovi`")
    if not modifiche:
        raise ErroreCassa("nessuna modifica: una variante identica al padre non serve")
    adesso = adesso or datetime.now()
    doc = deriva(padre, nome, modifiche)
    doc["salvato_il"] = adesso.isoformat()
    doc["provenienza"] = {
        "origine": "variante",
        "derivato_da": padre.etichetta,
        "id_padre": scenario_id(padre.raw),
        "md5_padre": _md5(padre.raw),
        "snapshot": "latest.json",
        "snapshot_data": payload.get("acquisito_il"),
        "creato_da": creato_da,
        "modifiche": list(modifiche),
    }
    testo = json.dumps(doc, ensure_ascii=False, indent=1)
    scenario_from_json(testo)  # la pagina deve poterlo aprire
    cartella = Path(home) / "scenari"
    cartella.mkdir(parents=True, exist_ok=True)
    dest = cartella / f"{nome}.json"
    if dest.exists():
        if not sostituisci:
            raise ErroreCassa(
                f"{dest} esiste già: scegli un altro nome o usa --sostituisci"
            )
        dest.rename(cartella / f"{nome}_prima_{adesso:%Y%m%d%H%M%S}.json")
    dest.write_text(testo, encoding="utf-8")
    return dest


def elenco(home: Path) -> list[dict]:
    home = Path(home)
    out = []
    files = [home / SEME] + sorted((home / "scenari").glob("*.json"))
    for f in files:
        if not f.exists() or "_prima_" in f.name:
            continue
        d = risolvi("seme" if f.name == SEME and f.parent == home else str(f), home)
        prov = d.doc.get("provenienza") or {}
        out.append(
            {
                "nome": "seme" if d.origine == "seme" else f.stem,
                "titolo": d.doc.get("nome"),
                "origine": d.origine,
                "derivato_da": prov.get("derivato_da"),
                "salvato_il": d.doc.get("salvato_il"),
                "snapshot_data": prov.get("snapshot_data"),
                "scenario_id": scenario_id(d.raw),
            }
        )
    return out


def promuovi(
    d: Documento, autorizzato_da: str | None, home: Path, adesso: datetime | None = None
) -> Path:
    """Lo scenario diventa il seme. Solo con l'autorizzazione dichiarata; il seme vecchio
    resta come `base_scenario_<ggmm>_prima_<nome>.json`. Restituisce la copia."""
    if not (autorizzato_da or "").strip():
        raise ErroreCassa(
            'promuovi: serve --autorizzato-da "<chi, quando, dove>". '
            "Il seme è la baseline approvata: nessuna promozione senza la parola di Stefano."
        )
    if d.origine == "seme":
        raise ErroreCassa("è già il seme")
    home = Path(home)
    adesso = adesso or datetime.now()
    seme_path = home / SEME
    vecchio = json.loads(seme_path.read_bytes()) if seme_path.exists() else {}
    slug = re.sub(
        r"[^A-Za-z0-9]+", "_", d.etichetta if d.origine != "app" else d.percorso.stem
    )
    copia = home / f"base_scenario_{adesso:%d%m}_prima_{slug}.json"
    if copia.exists():
        copia = home / f"base_scenario_{adesso:%d%m}_prima_{slug}_{adesso:%H%M%S}.json"
    nuovo = {k: copy.deepcopy(v) for k, v in d.doc.items() if k in CHIAVI_SCENARIO}
    for k, v in vecchio.items():
        if k not in CHIAVI_SCENARIO:
            nuovo[k] = v
    nuovo["provenienza"] = {
        **(nuovo.get("provenienza") or {}),
        "promosso_da": d.etichetta,
        "id_promosso": scenario_id(d.raw),
        "autorizzato_da": autorizzato_da.strip(),
        "promosso_il": adesso.isoformat(),
        "seme_precedente": copia.name,
    }
    testo = json.dumps(nuovo, ensure_ascii=False, indent=1)
    scenario_from_json(testo)
    if seme_path.exists():
        shutil.copy2(seme_path, copia)
    seme_path.write_text(testo, encoding="utf-8")
    return copia


# ── testo a video ──


def eur(cent: int | None) -> str:
    if cent is None:
        return "—"
    return f"{round(cent / 100):,}".replace(",", ".")


def _righe_intestazione(h: dict) -> list[str]:
    out = [
        f"Scenario: {h['scenario']}  [{h['etichetta']}]  origine: {h['origine']}"
        + (f" (salvato il {h['salvato_il']})" if h["salvato_il"] else ""),
        f"  vista: {h['vista']}  ·  id {h['scenario_id']}  ·  md5 {h['md5'][:12]}",
        f"  snapshot del {h['snapshot_acquisito_il']}  ·  PF: "
        + ", ".join(f"{s} {f}" for s, f in sorted(h["pf_base"].items())),
    ]
    if h["origine"] != "seme":
        out.append("  IPOTESI — non è il piano approvato.")
    if not h["base_uguale"]:
        out.append(
            "  ATTENZIONE base diversa: scenario su "
            + ", ".join(f"{s} {f}" for s, f in sorted(h["pf_base_scenario"].items()))
        )
    prov = h["provenienza"]
    if prov.get("derivato_da"):
        out.append(
            f"  derivato da {prov['derivato_da']}: "
            + "; ".join(
                m for m in prov.get("modifiche") or [] if not m.startswith("ipotesi:")
            )
        )
    if h["strati_locali"]:
        out.append(
            "  file locali: "
            + ", ".join(f"{n} {m[:8]}" for n, m in h["strati_locali"].items())
        )
    out += [f"  ipotesi: {x}" for x in h["ipotesi"]]
    return out


def testo_simula(s: dict) -> str:
    h, r = s["intestazione"], s["risultato"]
    ipo = set(s["mesi_ipotetici"])
    saldi: dict[str, dict[str, int]] = {}
    for x in r["righe"]:
        saldi.setdefault(x["mese"], {})[x["societa"]] = x["fin"]
    out = _righe_intestazione(h) + ["", f"{'mese':<9}{'ORTI':>14}{'INTUR':>14}"]
    for m in s["mesi"]:
        v = saldi.get(m, {})
        segno = " *" if m in ipo else ""
        out.append(f"{m:<9}{eur(v.get('ORTI')):>14}{eur(v.get('INTUR')):>14}{segno}")
    if ipo:
        out.append("  * mese oltre il PF: contano solo le leve")
    out.append("")
    for soc, m in r["minimi"].items():
        riga = f"Minimo {soc}: {eur(m['saldo'])} a {m['mese']}"
        if m.get("coda_mese"):
            riga += f" (oltre il PF: {eur(m['coda_saldo'])} a {m['coda_mese']})"
        out.append(riga)
    if h["limiti"]:
        out += ["", "Limiti dichiarati:"] + [f"  - {x}" for x in h["limiti"]]
    return "\n".join(out)


def testo_mese(det: dict, mese: str) -> str:
    out = [f"Dettaglio {mese}"]
    for soc, x in det.items():
        out.append(f"\n{soc}: inizio {eur(x['ini'])} → fine {eur(x['fin'])}")
        for lato in ("entrate", "uscite"):
            voci = {o: v for o, v in x[lato].items() if v}
            if voci:
                out.append(
                    f"  {lato}: " + ", ".join(f"{o} {eur(v)}" for o, v in voci.items())
                )
        for q in x["pf"]:
            out.append(
                f"    PF {q['direzione']} {q['voce_id']:<28}{eur(q['importo']):>12}"
            )
        for f in x["intercompany"]:
            out.append(
                f"    {f['nome']} {f['da']}→{f['a']} {eur(f['importo'])} ({f['stato']})"
            )
        for q in x["sostituiti"]:
            out.append(
                f"    sostituito dallo scenario: {q['voce_id']} {eur(q['importo'])}"
            )
    return "\n".join(out)


def testo_confronta(c: dict) -> str:
    out = ["A " + _righe_intestazione(c["a"])[0], "B " + _righe_intestazione(c["b"])[0]]
    if c["base_diverse"]:
        out.append("ATTENZIONE: A e B sono su PF diversi (--base-diverse)")
    out += [
        "",
        f"{'mese':<9}"
        + "".join(f"{s + ' A':>13}{s + ' B':>13}{'B−A':>12}" for s in SOCIETA),
    ]
    for r in c["righe"]:
        out.append(
            f"{r['mese']:<9}"
            + "".join(
                f"{eur(r[s]['a']):>13}{eur(r[s]['b']):>13}{eur(r[s]['diff']):>12}"
                for s in SOCIETA
            )
        )
    out.append("")
    for s in SOCIETA:
        ma, mb = c["minimi"]["a"].get(s), c["minimi"]["b"].get(s)
        if ma and mb:
            out.append(
                f"Minimo {s}: A {eur(ma['saldo'])} a {ma['mese']}  ·  B {eur(mb['saldo'])} a {mb['mese']}"
            )
    for s, p in c["perche"].items():
        if not p["diff_fine_mese"]:
            continue
        parti = (
            [f"saldo iniziale {eur(p['diff_saldo_iniziale'])}"]
            if p["diff_saldo_iniziale"]
            else []
        )
        parti += [f"entrate {o} {eur(v)}" for o, v in p["entrate"].items()]
        parti += [f"uscite {o} {eur(v)}" for o, v in p["uscite"].items()]
        out.append(
            f"Perché {s} a {p['mese']} (B−A {eur(p['diff_fine_mese'])}): "
            + ", ".join(parti)
        )
    return "\n".join(out)


def payload_locale(home: Path | None = None) -> dict:
    home = Path(home) if home is not None else cf.SNAPSHOT_HOME
    return payload_da_stato(cf.carica_snapshot(home), home)
