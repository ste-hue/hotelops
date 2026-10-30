"""Tabelle piatte della pagina Cassa: dal payload JSON a CSV che Excel apre senza conversioni.

La pagina esporta lo *scenario* (le leve). Questo modulo esporta **tutto quello che la pagina
sa**: il PF voce per voce, i flussi fra le società, le ancore conto per conto, i saldi mese per
mese del solo PF e dello scenario, i minimi, le rate del canone, i progetti coi loro pagamenti,
i finanziamenti e i limiti dichiarati. Serve a chi deve riparare i numeri (Rosa, il
commercialista) e lavora in Excel, non nel browser.

Nessuna lettura di BigQuery: la sorgente è il payload, cioè uno di questi tre,
che hanno lo stesso contenuto:
  * `cassa/data.json` del Worker (o il file scaricato da lì);
  * il blocco `<script type="application/json" id="dati">` dentro la pagina salvata;
  * `docs/reports/artifacts/cassa.html` prodotto da `hotelops cdg cassa`.

I saldi dello scenario sono ricalcolati qui col motore Python, non copiati dalla pagina: se la
pagina e il Python divergessero, il confronto `--verifica` lo dice invece di nasconderlo.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from verticals.condges import cassa_motore as M
from verticals.condges.cassa_scenario import scenario_from_json

# Attenzione al nome: `M.iva(netto, aliquota)` restituisce il LORDO (netto + imposta),
# non l'imposta. L'imposta è `M.iva(n, a) - n`.

# Una tabella è (intestazione, righe). I numeri restano in centesimi fino alla scrittura.
Tabella = tuple[list[str], list[list]]

_SCRIPT = re.compile(
    r'<script[^>]*type="application/json"[^>]*id="dati"[^>]*>(.*?)</script>', re.DOTALL
)
ORIGINI = ("pf", "canone", "finanziamento", "progetto", "manuale", "fatto")


def payload_da_file(path: Path) -> dict:
    """Payload da un .json (del Worker o dello snapshot) o da una pagina .html salvata."""
    testo = Path(path).read_text(encoding="utf-8")
    if testo.lstrip().startswith("{"):
        return json.loads(testo)
    m = _SCRIPT.search(testo)
    if not m:
        raise ValueError(
            f"{path}: non è un payload JSON e non contiene il blocco dati della pagina"
        )
    return json.loads(m.group(1))


def _ancora(a: dict) -> M.Ancora:
    return M.Ancora(
        societa=a["societa"],
        data=date.fromisoformat(a["data"]),
        saldo=a["saldo"],
        attestato=a["attestato"],
        conti={
            b: M.Conto(saldo=c["saldo"], attestato=c["attestato"], motivo=c["motivo"])
            for b, c in a["conti"].items()
        },
    )


def _fatto(f: dict) -> M.Fatto:
    return M.Fatto(
        societa=f["societa"],
        progetto_id=f.get("progetto_id", ""),
        fornitore_id=f.get("fornitore_id"),
        mese=f["mese"],
        importo=f["importo"],
        evento_id=f.get("evento_id", ""),
    )


def input_da_payload(payload: dict, scenario: M.Scenario) -> M.Input:
    """Ricostruisce l'ingresso del motore dal payload. Le chiavi del payload sono i campi
    delle dataclass: se un giorno divergono, questa funzione si rompe subito invece di
    calcolare su dati storti."""
    return M.Input(
        mesi=list(payload["mesi"]),
        mesi_ipotetici=frozenset(payload.get("mesi_ipotetici") or ()),
        ancore={s: _ancora(a) for s, a in payload["ancore"].items()},
        pf=[M.Riga(**r) for r in payload["pf"]],
        intercompany=[M.Flusso(**f) for f in payload["intercompany"]],
        fatti=[_fatto(f) for f in payload.get("fatti") or ()],
        scenario=scenario,
    )


VUOTO = M.Scenario(
    nome="Solo PF", progetti=[], finanziamenti=[], canone=None, manuali=[], soglia=0
)


def scenario_del_payload(
    payload: dict, documento: dict | None = None
) -> tuple[M.Scenario, str]:
    """Lo scenario da esportare: quello passato, altrimenti il seme della pagina, altrimenti vuoto."""
    doc = documento if documento is not None else payload.get("seme")
    if not doc:
        return VUOTO, VUOTO.nome
    sc, _base, _meta = scenario_from_json(json.dumps(doc))
    return sc, sc.nome


def _righe_saldi(
    righe: Iterable[M.RigaMese], etichetta: str, ipotetici: set[str]
) -> list[list]:
    out = []
    for r in righe:
        out.append(
            [etichetta, r.mese, r.societa, "sì" if r.mese in ipotetici else "no", r.ini]
            + [r.entrate.get(o, 0) for o in ORIGINI]
            + [sum(r.entrate.values())]
            + [r.uscite.get(o, 0) for o in ORIGINI]
            + [sum(r.uscite.values()), r.fin]
        )
    return out


def tabelle(payload: dict, documento: dict | None = None) -> dict[str, Tabella]:
    sc, nome = scenario_del_payload(payload, documento)
    ipo = set(payload.get("mesi_ipotetici") or ())
    base = M.calcola(input_da_payload(payload, VUOTO))
    scen = M.calcola(input_da_payload(payload, sc))

    t: dict[str, Tabella] = {}

    intest = (
        ["scenario", "mese", "societa", "mese_senza_pf", "saldo_iniziale"]
        + [f"entrate_{o}" for o in ORIGINI]
        + ["entrate_totali"]
        + [f"uscite_{o}" for o in ORIGINI]
        + ["uscite_totali", "saldo_finale"]
    )
    t["saldi_mensili"] = (
        intest,
        _righe_saldi(base.righe, "solo PF", ipo) + _righe_saldi(scen.righe, nome, ipo),
    )

    t["minimi"] = (
        ["scenario", "societa", "mese_critico", "saldo_minimo", "mesi_sotto_soglia"],
        [
            [et, s, m.mese, m.saldo, " ".join(m.sotto_soglia)]
            for et, ris in (("solo PF", base), (nome, scen))
            for s, m in sorted(ris.minimi.items())
        ],
    )

    t["pf_voci"] = (
        ["societa", "mese", "voce_id", "direzione", "origine", "importo"],
        [
            [
                r["societa"],
                r["mese"],
                r["voce_id"],
                r["direzione"],
                r["origine"],
                r["importo"],
            ]
            for r in payload["pf"]
        ],
    )

    t["flussi_fra_societa"] = (
        ["nome", "da", "a", "mese", "importo_lordo", "stato"],
        [
            [f["nome"], f["da"], f["a"], f["mese"], f["importo"], f["stato"]]
            for f in payload["intercompany"]
        ],
    )

    t["ancore_per_conto"] = (
        ["societa", "data", "banca", "saldo", "verificato_con_i_movimenti", "motivo"],
        [
            [s, a["data"], b, c["saldo"], "sì" if c["attestato"] else "no", c["motivo"]]
            for s, a in sorted(payload["ancore"].items())
            for b, c in sorted(a["conti"].items())
        ],
    )

    cr = payload.get("canone_rif") or {}
    # Due letture del canone, una per riga: le rate che il PF ha davvero, e il calendario del
    # contratto applicato ai mesi dell'orizzonte (quello che lo slider segue). Dove il contratto
    # prevede una rata e il PF non la ha, la riga del contratto la mostra e il PF resta a zero:
    # è il caso del 30/12/2026 che il limite della pagina dichiara.
    rate_pf = {m: v for m, v in (cr.get("rate_pf") or {}).items()}
    contratto = (cr.get("contratto") or {}).get("rate_mese") or {}
    iva_canone = cr.get("aliquota_iva", 22)
    righe_canone = []
    for mese in payload["mesi"]:
        lordo_pf = rate_pf.get(mese, 0)
        quota = contratto.get(mese[5:7])
        if not lordo_pf and quota is None:
            continue
        netto_pf = round(lordo_pf * 100 / (100 + iva_canone)) if lordo_pf else 0
        netto_c = quota if quota is not None else 0
        righe_canone.append(
            [
                mese,
                netto_pf,
                lordo_pf,
                netto_c,
                M.iva(netto_c, iva_canone),
                "sì" if quota is not None and not lordo_pf else "no",
            ]
        )
    t["canone_rate"] = (
        [
            "mese",
            "netto_nel_pf",
            "lordo_nel_pf",
            "netto_da_contratto",
            "lordo_da_contratto",
            "rata_del_contratto_che_il_pf_non_ha",
        ],
        righe_canone,
    )
    # Le rate fuori dall'orizzonte della pagina esistono e vanno dette, o il totale annuo non torna.
    t["canone_rate_fuori_orizzonte"] = (
        ["mese", "lordo_nel_pf"],
        [[m, v] for m, v in sorted(rate_pf.items()) if m not in payload["mesi"]],
    )

    t["progetti"] = (
        [
            "progetto_id",
            "nome",
            "societa",
            "acceso",
            "stato",
            "n_pagamenti",
            "totale_netto",
        ],
        [
            [
                p.id,
                p.nome,
                p.societa,
                "sì" if p.acceso else "no",
                p.stato,
                len(p.pagamenti),
                sum(sum(pg.mesi.values()) for pg in p.pagamenti),
            ]
            for p in sc.progetti
        ],
    )

    t["pagamenti"] = (
        [
            "progetto_id",
            "progetto",
            "societa",
            "pagamento",
            "stato",
            "aliquota_iva",
            "mese",
            "netto",
            "iva",
            "lordo",
        ],
        [
            [
                p.id,
                p.nome,
                p.societa,
                pg.nome,
                pg.stato,
                pg.aliquota_iva,
                mese,
                netto,
                M.iva(netto, pg.aliquota_iva) - netto,
                M.iva(netto, pg.aliquota_iva),
            ]
            for p in sc.progetti
            for pg in p.pagamenti
            for mese, netto in sorted(pg.mesi.items())
        ],
    )

    t["finanziamenti"] = (
        ["finanziamento_id", "nome", "societa", "stato", "mese", "tipo", "importo"],
        [
            [f.id, f.nome, f.societa, f.stato, mese, tipo, imp]
            for f in sc.finanziamenti
            for tipo, voci in (("erogazione", f.erogazioni), ("rata", f.rate))
            for mese, imp in sorted(voci.items())
        ],
    )

    t["fatti"] = (
        ["societa", "progetto_id", "fornitore_id", "mese", "importo", "evento_id"],
        [
            [
                f["societa"],
                f.get("progetto_id", ""),
                f.get("fornitore_id") or "",
                f["mese"],
                f["importo"],
                f.get("evento_id", ""),
            ]
            for f in payload.get("fatti") or []
        ],
    )

    t["limiti"] = (
        ["n", "quello_che_la_pagina_non_sa"],
        [[i + 1, x] for i, x in enumerate(payload.get("limiti") or [])],
    )

    t["versioni"] = (
        ["voce", "valore"],
        [
            ["pagina generata il", payload.get("generato_il", "")],
            ["fonti lette il", payload.get("acquisito_il", "")],
            ["scenario esportato", nome],
            ["primo mese", payload["mesi"][0]],
            ["ultimo mese", payload["mesi"][-1]],
            [
                "mesi senza PF",
                " ".join(payload.get("mesi_ipotetici") or []) or "nessuno",
            ],
        ]
        + [
            [f"PF {s}", (b or {}).get("file_sorgente", "")]
            for s, b in sorted((payload.get("base") or {}).items())
        ]
        + [
            ["canone netto annuo dichiarato (€)", _euro(cr.get("netto_annuo") or 0)],
            ["canone lordo annuo (€)", _euro(cr.get("lordo_annuo") or 0)],
            ["aliquota IVA canone (%)", cr.get("aliquota_iva", "")],
        ],
    )
    return t


# ── scrittura ────────────────────────────────────────────────────────────────
# Excel italiano: separatore «;», virgola decimale, BOM per gli accenti. Niente separatore
# delle migliaia, altrimenti Excel legge il numero come testo.
# Colonne in centesimi, dette per nome: il riconoscimento per sottostringa confondeva
# «aliquota_iva» (una percentuale) con «iva» (un importo).
DENARO = {
    "saldo",
    "saldo_iniziale",
    "saldo_finale",
    "saldo_minimo",
    "entrate_totali",
    "uscite_totali",
    "importo",
    "importo_lordo",
    "netto",
    "iva",
    "lordo",
    "totale_netto",
    "netto_nel_pf",
    "lordo_nel_pf",
    "netto_da_contratto",
    "lordo_da_contratto",
}


def _e_denaro(colonna: str) -> bool:
    return colonna in DENARO or colonna.startswith(("entrate_", "uscite_"))


def _euro(cent: int) -> str:
    segno = "-" if cent < 0 else ""
    c = abs(int(cent))
    return f"{segno}{c // 100},{c % 100:02d}"


def formatta(colonne: list[str], riga: list) -> list[str]:
    out = []
    for c, v in zip(colonne, riga):
        if _e_denaro(c) and isinstance(v, int):
            out.append(_euro(v))
        else:
            out.append("" if v is None else str(v))
    return out


def scrivi_csv(tab: dict[str, Tabella], cartella: Path) -> list[Path]:
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    scritti = []
    for nome, (colonne, righe) in sorted(tab.items()):
        p = cartella / f"{nome}.csv"
        with p.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            w.writerow(colonne)
            for r in righe:
                w.writerow(formatta(colonne, r))
        scritti.append(p)
    return scritti


def confronto_con_la_pagina(payload: dict) -> list[str]:
    """Il baseline ricalcolato qui contro quello scritto nel payload. Vuoto = identici."""
    atteso = {
        (r["mese"], r["societa"]): r["fin"]
        for r in (payload.get("baseline") or {}).get("righe") or []
    }
    if not atteso:
        return ["il payload non porta il baseline: confronto non fatto"]
    ris = M.calcola(input_da_payload(payload, VUOTO))
    fuori = [
        f"{r.societa} {r.mese}: Python {_euro(r.fin)} vs pagina {_euro(atteso[(r.mese, r.societa)])}"
        for r in ris.righe
        if (r.mese, r.societa) in atteso and r.fin != atteso[(r.mese, r.societa)]
    ]
    mancanti = [
        f"{r.societa} {r.mese}: non nel payload"
        for r in ris.righe
        if (r.mese, r.societa) not in atteso
    ]
    return fuori + mancanti
