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
    """Legge le fonti BigQuery e compone lo snapshot (coda ipotetica inclusa)."""
    ancore = cf.leggi_ancore(query)
    righe, flussi, base, mesi = cf.leggi_baseline(query)
    fatti = cf.leggi_fatti(query)
    scenari = cf.leggi_scenari(query)
    mesi_tutti, coda = cf.mesi_ipotetici(mesi)
    coda_ordinata = [m for m in mesi_tutti if m in coda]
    return snapshot_da_fonti(
        ancore=ancore,
        pf=righe + cf.coda_ripetuta(righe, coda_ordinata),
        intercompany=flussi + cf.coda_flussi(flussi, coda_ordinata),
        base=base,
        mesi=mesi_tutti,
        mesi_ipotetici=coda,
        fatti=fatti,
        scenari=scenari,
    )


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
            f"Mesi ipotetici da {coda[0]} a {coda[-1]}: ripetono il mese omologo dell'anno prima "
            f"(il PF finisce a {pf_fine[-1] if pf_fine else '-'})."
        )
        con_righe = {r["mese"] for r in snapshot["pf"]} | {
            f["mese"] for f in snapshot["intercompany"]
        }
        vuoti = [m for m in coda if m not in con_righe]
        if vuoti:
            out.append(
                "Mesi ipotetici senza mese omologo nel PF, quindi a zero movimenti: "
                + ", ".join(vuoti)
                + "."
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


def build_payload(
    snapshot: dict,
    scenari: list[tuple[Scenario, Base, dict]],
    generato_il: datetime | None = None,
    seme: tuple[Scenario, Base] | None = None,
) -> dict:
    base = snapshot["base"]
    vuoto = Scenario("Nessuna leva", [], [])
    baseline = to_dict(calcola(input_da_snapshot(snapshot, vuoto)))
    sc_seme, base_seme = seme if seme else (vuoto, base)
    seme_doc = _scenario_doc(sc_seme, base_seme)
    seme_doc["compatibile"] = base_uguale(base_seme, base)
    salvati = []
    for sc, b, meta in scenari:
        doc = _scenario_doc(sc, b, meta)
        doc["compatibile"] = base_uguale(b, base)
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
        "baseline": baseline,
        "limiti": _limiti(snapshot, sc_seme, baseline),
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
    payload = build_payload(snapshot, scenari_da_snapshot(snapshot), seme=seme)
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
    print(f"  limiti: {len(payload['limiti'])}")
    if push_env is not None:
        push_to_kv(html, json.dumps(payload, ensure_ascii=False), push_env)
        print("Push KV OK → https://cdg.panorama-host.com")
    return out
