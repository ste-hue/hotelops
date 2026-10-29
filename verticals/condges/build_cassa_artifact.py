"""Build della pagina Cassa (CdG): una pagina HTML autonoma.

Stesso schema di ``build_canone_artifact``: il payload entra nel template come
JSON, il motore gira nel browser (porting JS di ``cassa_motore``, verificato dai
test contro il Python con uguaglianza intera). Numeri aziendali → l'output sta in
``docs/reports/artifacts/`` e lo snapshot in ``.hotelops_state/cdg_cassa/``
(entrambi gitignored).

    hotelops cdg cassa [--aggiorna] [--push] [--out FILE]

``--aggiorna`` rilegge BigQuery (sola lettura) e rinnova lo snapshot datato;
senza, usa ``latest.json``. ``--push`` pubblica HTML e dati nel KV del Worker
``cdg`` (panorama_apps), dietro Cloudflare Access.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from verticals.condges import cassa_fonti as cf
from verticals.condges.cassa_motore import (
    Ancora,
    Conto,
    Fatto,
    Flusso,
    Input,
    Riga,
    Scenario,
    calcola,
    to_dict,
)
from verticals.condges.cassa_scenario import (
    SCHEMA,
    Base,
    base_uguale,
    carica_seme,
    scenario_from_json,
    scenario_to_json,
)

DEFAULT_OUT = Path("docs/reports/artifacts/cassa.html")
SEME_PATH = cf.SNAPSHOT_HOME / "base_scenario.json"
CANONE_PATH = cf.SNAPSHOT_HOME / "canone_dichiarato.json"
TEMPLATE = Path(__file__).with_name("cassa_template.html")

KV_KEY = "cassa_html"
KV_DATA_KEY = "cassa_data"
PUSH_ENV_VARS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CDG_KV_NAMESPACE_ID")


# ── snapshot: JSON puro <-> oggetti del motore ──


def _scenario_doc(sc: Scenario, base: Base, meta: dict | None = None) -> dict:
    meta = meta or {}
    doc = json.loads(scenario_to_json(sc, base, nome=meta.get("nome")))
    if meta.get("salvato_il"):
        doc["salvato_il"] = str(meta["salvato_il"])
    return doc


def snapshot_da_fonti(
    ancore: dict[str, Ancora],
    pf: list[Riga],
    intercompany: list[Flusso],
    base: Base,
    mesi: list[str],
    mesi_ipotetici: frozenset[str],
    fatti: list[Fatto],
    scenari: list[tuple[Scenario, Base, dict]],
    acquisito_il: datetime | None = None,
) -> dict:
    """Forma JSON dello snapshot (date ISO, frozenset -> lista ordinata, dataclass -> dict)."""
    return {
        "acquisito_il": (acquisito_il or datetime.now()).isoformat(timespec="minutes"),
        "mesi": list(mesi),
        "mesi_ipotetici": [m for m in mesi if m in mesi_ipotetici],
        "ancore": {
            soc: {**asdict(a), "data": a.data.isoformat()} for soc, a in ancore.items()
        },
        "base": base,
        "pf": [asdict(r) for r in pf],
        "intercompany": [asdict(f) for f in intercompany],
        "fatti": [asdict(f) for f in fatti],
        "scenari": [_scenario_doc(sc, b, meta) for sc, b, meta in scenari],
    }


def input_da_snapshot(snapshot: dict, scenario: Scenario) -> Input:
    ancore = {
        soc: Ancora(
            societa=a["societa"],
            data=date.fromisoformat(a["data"]),
            saldo=a["saldo"],
            attestato=a["attestato"],
            conti={b: Conto(**c) for b, c in a["conti"].items()},
        )
        for soc, a in snapshot["ancore"].items()
    }
    return Input(
        mesi=list(snapshot["mesi"]),
        mesi_ipotetici=frozenset(snapshot["mesi_ipotetici"]),
        ancore=ancore,
        pf=[Riga(**r) for r in snapshot["pf"]],
        intercompany=[Flusso(**f) for f in snapshot["intercompany"]],
        fatti=[Fatto(**f) for f in snapshot["fatti"]],
        scenario=scenario,
    )


def input_da_dict(d: dict) -> Input:
    """Snapshot con dentro un documento scenario (`d["scenario"]`, schema cdg-cassa-scenario/1)."""
    sc, _, _ = scenario_from_json(json.dumps(d["scenario"]))
    return input_da_snapshot(d, sc)


def scenari_da_snapshot(snapshot: dict) -> list[tuple[Scenario, Base, dict]]:
    return [scenario_from_json(json.dumps(doc)) for doc in snapshot.get("scenari", [])]


def acquisisci(query=cf.query_bq) -> dict:
    """Legge le fonti BigQuery e compone lo snapshot (mesi oltre il PF senza righe)."""
    ancore = cf.leggi_ancore(query)
    righe, flussi, base, mesi = cf.leggi_baseline(query)
    fatti = cf.leggi_fatti(query)
    scenari = cf.leggi_scenari(query)
    # I mesi oltre il PF restano nell'orizzonte (le leve ci arrivano) ma senza
    # righe PF né flussi copiati: nessun saldo inventato, solo effetto delle leve.
    mesi_tutti, coda = cf.mesi_ipotetici(mesi)
    return snapshot_da_fonti(
        ancore=ancore,
        pf=righe,
        intercompany=flussi,
        base=base,
        mesi=mesi_tutti,
        mesi_ipotetici=coda,
        fatti=fatti,
        scenari=scenari,
    )


def senza_coda(snapshot: dict) -> dict:
    """Toglie righe PF e flussi intercompany dai mesi oltre il PF (snapshot vecchi
    li portavano copiati dal mese omologo). La pagina non mostra saldi là, solo
    l'effetto incrementale delle leve."""
    coda = set(snapshot.get("mesi_ipotetici", []))
    if not coda:
        return snapshot
    return {
        **snapshot,
        "pf": [r for r in snapshot["pf"] if r["mese"] not in coda],
        "intercompany": [f for f in snapshot["intercompany"] if f["mese"] not in coda],
    }


def canone_pf(intercompany: list[dict], aliquota_iva: int = 22) -> list[dict]:
    """Canone Fitto Hotel come sta nel PF, per anno: lordo, netto (IVA scorporata
    half-up), mesi e numero di rate. È il punto di partenza dello slider."""
    per_anno: dict[str, list[dict]] = {}
    for f in intercompany:
        if f["nome"].startswith("Fitto Hotel") and f["stato"] == "pf":
            per_anno.setdefault(f["mese"][:4], []).append(f)
    out = []
    k = 100 + aliquota_iva
    for anno in sorted(per_anno):
        fl = sorted(per_anno[anno], key=lambda f: f["mese"])
        lordo = sum(f["importo"] for f in fl)
        out.append(
            {
                "anno": int(anno),
                "lordo": lordo,
                "netto": (lordo * 100 + k // 2) // k,
                "aliquota_iva": aliquota_iva,
                "mesi": [f["mese"] for f in fl],
                "rate_n": len(fl),
                "da_mese": fl[0]["mese"],
            }
        )
    return out


def canone_riferimento(intercompany: list[dict], dichiarato: dict | None = None) -> dict:
    """Il canone di riferimento dello slider. L'annuo viene dal file dichiarato
    (`canone_dichiarato.json`: netto_annuo, aliquota_iva, rate_pf, fonte); le rate nell'orizzonte
    vengono dal PF nel payload. Senza file dichiarato l'annuo è la somma delle rate PF
    nell'orizzonte, e si dice che NON è l'annuo."""
    al = int((dichiarato or {}).get("aliquota_iva", 22))
    k = 100 + al
    rate = sorted(
        (f for f in intercompany if f["nome"].startswith("Fitto Hotel") and f["stato"] == "pf"),
        key=lambda f: f["mese"],
    )
    per_mese: dict[str, int] = {}
    for f in rate:
        per_mese[f["mese"]] = per_mese.get(f["mese"], 0) + f["importo"]
    rate_orizzonte = [
        {"mese": m, "lordo": v, "netto": (v * 100 + k // 2) // k} for m, v in per_mese.items()
    ]
    netto_pf = sum(r["netto"] for r in rate_orizzonte)
    contratto = None
    if dichiarato and dichiarato.get("calendario_contratto"):
        contratto = {
            "rate_mese": {str(m).zfill(2): int(v) for m, v in dichiarato["calendario_contratto"].items()},
            "fonte": dichiarato.get("contratto_fonte", ""),
        }
    if dichiarato and dichiarato.get("netto_annuo"):
        netto_annuo = int(dichiarato["netto_annuo"])
        return {
            "dichiarato": True,
            "contratto": contratto,
            "netto_annuo": netto_annuo,
            "lordo_annuo": (netto_annuo * k + 50) // 100,
            "aliquota_iva": al,
            "rate_pf": {m: int(v) for m, v in (dichiarato.get("rate_pf") or {}).items()},
            "fonte": dichiarato.get("fonte", ""),
            "dichiarato_il": dichiarato.get("dichiarato_il"),
            "rate_orizzonte": rate_orizzonte,
            "netto_pf_orizzonte": netto_pf,
        }
    return {
        "dichiarato": False,
        "contratto": None,
        "netto_annuo": netto_pf,
        "lordo_annuo": (netto_pf * k + 50) // 100,
        "aliquota_iva": al,
        "rate_pf": {},
        "fonte": "nessun annuo dichiarato: somma delle rate PF nell'orizzonte, non è l'annuo",
        "dichiarato_il": None,
        "rate_orizzonte": rate_orizzonte,
        "netto_pf_orizzonte": netto_pf,
    }


# ── payload ──


def _eur(cent: int) -> str:
    segno = "-" if cent < 0 else ""
    e, c = divmod(abs(cent), 100)
    return f"{segno}{e:,}".replace(",", ".") + f",{c:02d} €"


def _limiti(snapshot: dict, seme: Scenario, baseline: dict) -> list[str]:
    out = []
    for soc, a in snapshot["ancore"].items():
        for banca, c in a["conti"].items():
            if not c["attestato"]:
                out.append(
                    f"{soc} · {banca}: saldo dichiarato al {a['data']}, non attestato ({c['motivo']})."
                )
    coda = snapshot["mesi_ipotetici"]
    if coda:
        pf_fine = [m for m in snapshot["mesi"] if m not in coda]
        out.append(
            f"Mesi da {coda[0]} a {coda[-1]} senza PF (il PF finisce a "
            f"{pf_fine[-1] if pf_fine else '-'}): nessun saldo previsto; la pagina mostra "
            "solo l'effetto cumulato delle leve dello scenario, non un saldo di cassa."
        )
    out.append(
        "I pagamenti di progetto sono netti: l'IVA si applica per aliquota (0/10/22%) "
        "nel mese del pagamento, con arrotondamento al centesimo."
    )
    senza_rate = [f for f in seme.finanziamenti if f.erogazioni and not f.rate]
    if senza_rate:
        out.append(
            "Rate dei nuovi finanziamenti assenti: "
            + ", ".join(f.nome for f in senza_rate)
            + " entrano come erogazioni senza rimborso nell'orizzonte."
        )
    da_verificare = [f for f in seme.finanziamenti if f.stato == "da verificare"]
    if da_verificare:
        out.append(
            "Finanziamenti da verificare: "
            + ", ".join(f.nome for f in da_verificare)
            + " — erogazioni ipotizzate, non deliberate; sostituiscono le righe PF "
            "ENTRATE_FINANZIAMENTI della società."
        )
    n = len(baseline["non_riconciliati"])
    if n:
        tot = sum(f["importo"] for f in baseline["non_riconciliati"])
        out.append(
            f"Fatti non riconciliati: {n} pagamenti ({_eur(tot)}) senza un pagamento "
            "di progetto dello stesso fornitore nello scenario; contano comunque come uscita."
        )
    return out


def _limiti_canone(c: dict, mesi: list[str] = (), mesi_ipotetici: set[str] = frozenset()) -> list[str]:
    out = []
    if c.get("contratto"):
        k = 100 + c["aliquota_iva"]
        pf = {r["mese"]: r["lordo"] for r in c["rate_orizzonte"]}
        for m in mesi:
            if m in mesi_ipotetici:
                continue
            netto = c["contratto"]["rate_mese"].get(m[5:7])
            if netto is None:
                continue
            lordo = (netto * k + 50) // 100
            if pf.get(m, 0) != lordo:
                out.append(
                    f"Contratto art. 3: rata del canone il 30/{m[5:7]}/{m[:4]} = {_eur(lordo)} lordo; "
                    f"il PF ne ha {_eur(pf.get(m, 0))}: ORTI e INTUR differiscono dal contratto di "
                    f"{_eur(lordo - pf.get(m, 0))} da quel mese (lo slider usa il calendario del contratto)."
                )
    if c["dichiarato"]:
        rate = ", ".join(f"{m} {_eur(v)}" for m, v in sorted(c["rate_pf"].items())) or "nessuna"
        return out + [
            f"Canone Fitto Hotel: annuo dichiarato {_eur(c['netto_annuo'])} netto "
            f"({_eur(c['lordo_annuo'])} lordo, IVA {c['aliquota_iva']}%), dichiarato il "
            f"{c['dichiarato_il'] or '-'}; il PF ne mostra queste rate: {rate}. "
            "Lo slider scala le rate del PF nell'orizzonte in proporzione all'annuo; "
            "le rate fuori orizzonte non entrano in cassa qui."
        ]
    return [
        f"Canone Fitto Hotel: nessun annuo dichiarato; lo slider parte da {_eur(c['netto_annuo'])} "
        "netto = somma delle rate PF nell'orizzonte, che NON è l'annuo."
    ]


def build_payload(
    snapshot: dict,
    scenari: list[tuple[Scenario, Base, dict]],
    generato_il: datetime | None = None,
    seme: tuple[Scenario, Base] | None = None,
    seme_salvato_il: str | None = None,
    canone_dichiarato: dict | None = None,
) -> dict:
    snapshot = senza_coda(snapshot)
    base = snapshot["base"]
    vuoto = Scenario("Nessuna leva", [], [])
    baseline = to_dict(calcola(input_da_snapshot(snapshot, vuoto)))
    sc_seme, base_seme = seme if seme else (vuoto, base)
    seme_doc = _scenario_doc(
        sc_seme, base_seme, {"salvato_il": seme_salvato_il} if seme_salvato_il else None
    )
    seme_doc["compatibile"] = base_uguale(base_seme, base)
    salvati, sostituiti = [], []
    for sc, b, meta in scenari:
        doc = _scenario_doc(sc, b, meta)
        doc["compatibile"] = base_uguale(b, base)
        # Il seme locale è la versione viva: un salvato con lo stesso nome è una
        # sua copia (o una versione superata) e non entra nel menu, ma resta dichiarato.
        if seme and doc["nome"] == seme_doc["nome"]:
            sostituiti.append({"nome": doc["nome"], "salvato_il": doc.get("salvato_il")})
            continue
        salvati.append(doc)
    return {
        "schema": SCHEMA,
        "generato_il": (generato_il or datetime.now()).isoformat(timespec="minutes"),
        "acquisito_il": snapshot.get("acquisito_il"),
        "mesi": list(snapshot["mesi"]),
        "mesi_ipotetici": list(snapshot["mesi_ipotetici"]),
        "ancore": snapshot["ancore"],
        "base": base,
        "pf": snapshot["pf"],
        "intercompany": snapshot["intercompany"],
        "fatti": snapshot["fatti"],
        "seme": seme_doc,
        "scenari": salvati,
        "scenari_sostituiti": sostituiti,
        "canone_rif": canone_riferimento(snapshot["intercompany"], canone_dichiarato),
        "baseline": baseline,
        "limiti": _limiti(snapshot, sc_seme, baseline)
        + _limiti_canone(
            canone_riferimento(snapshot["intercompany"], canone_dichiarato),
            list(snapshot["mesi"]),
            set(snapshot["mesi_ipotetici"]),
        ),
    }


def render_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data_json)


# ── push KV (Worker "cdg", repo panorama_apps) ──


def load_push_env() -> dict[str, str]:
    import os

    env = {k: os.environ.get(k, "") for k in PUSH_ENV_VARS}
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise RuntimeError(
            f"--push richiede variabili d'ambiente mancanti: {', '.join(missing)}"
        )
    return env


def push_to_kv(html: str, data_json: str, env: dict[str, str]) -> None:
    import requests

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{env['CLOUDFLARE_ACCOUNT_ID']}"
        f"/storage/kv/namespaces/{env['CDG_KV_NAMESPACE_ID']}/bulk"
    )
    r = requests.put(
        url,
        json=[{"key": KV_KEY, "value": html}, {"key": KV_DATA_KEY, "value": data_json}],
        headers={"Authorization": f"Bearer {env['CLOUDFLARE_API_TOKEN']}"},
        timeout=60,
    )
    if not (r.ok and r.json().get("success")):
        raise RuntimeError(f"Push KV fallito: HTTP {r.status_code} — {r.text[:500]}")


# ── run ──


def run(out: Path = DEFAULT_OUT, aggiorna: bool = False, push: bool = False) -> Path:
    push_env = None
    if push:
        from core.env import load_dotenv_file

        load_dotenv_file()
        push_env = load_push_env()

    if aggiorna:
        snapshot = acquisisci()
        print(f"Snapshot {cf.salva_snapshot(snapshot)}")
    else:
        snapshot = cf.carica_snapshot()
    seme = carica_seme(SEME_PATH) if SEME_PATH.exists() else None
    seme_salvato_il = (
        json.loads(SEME_PATH.read_text(encoding="utf-8")).get("salvato_il") if seme else None
    )
    canone_dichiarato = (
        json.loads(CANONE_PATH.read_text(encoding="utf-8")) if CANONE_PATH.exists() else None
    )
    payload = build_payload(
        snapshot,
        scenari_da_snapshot(snapshot),
        seme=seme,
        seme_salvato_il=seme_salvato_il,
        canone_dichiarato=canone_dichiarato,
    )
    html = render_html(payload)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Scritto {out}")
    for soc, a in payload["ancore"].items():
        stato = "attestato" if a["attestato"] else "dichiarato"
        print(f"  {soc}: ancora {a['data']} {_eur(a['saldo'])} ({stato})")
        for banca, c in a["conti"].items():
            print(f"    {banca}: {_eur(c['saldo'])} — {c['motivo']}")
    for soc, m in payload["baseline"]["minimi"].items():
        print(f"  {soc}: minimo baseline {m['mese']} {_eur(m['saldo'])}")
    print(
        f"  seme: {payload['seme']['nome']} (compatibile={payload['seme']['compatibile']})"
    )
    for s in payload["scenari"]:
        print(f"  scenario salvato: {s['nome']} compatibile={s['compatibile']}")
    for s in payload["scenari_sostituiti"]:
        print(f"  scenario salvato nascosto (stesso nome del seme): {s['nome']} {s['salvato_il']}")
    c = payload["canone_rif"]
    print(
        f"  canone di riferimento: {_eur(c['netto_annuo'])} netto/anno "
        f"({'dichiarato' if c['dichiarato'] else 'NON dichiarato: somma rate PF nell orizzonte'}); "
        f"rate PF nell'orizzonte: {', '.join(r['mese'] + ' ' + _eur(r['lordo']) for r in c['rate_orizzonte']) or 'nessuna'}"
    )
    print(f"  limiti: {len(payload['limiti'])}")
    if push_env is not None:
        push_to_kv(html, json.dumps(payload, ensure_ascii=False), push_env)
        print("Push KV OK → https://cdg.panorama-host.com")
    return out
