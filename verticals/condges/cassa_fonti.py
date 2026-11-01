"""Fonti BigQuery della pagina Cassa: sola lettura, nessun calcolo oltre alla quadratura.

Ogni lettore prende `query: Callable[[str], list[dict]]` (in produzione `query_bq`,
nei test una finta). Gli importi BigQuery passano da `to_cent` una sola volta, qui.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from core.config import (
    D_FORNITORI,
    F_BANCHE_MOVIMENTI,
    F_PIANO_FINANZIARIO_INPUT,
    F_PROGETTO_EVENTI,
    F_SALDI_BANCA_CHIUSURA_MENSILE,
    P_PROGETTI_PAGAMENTI,
    P_SCENARI,
    P_SCENARIO_FLUSSI,
)
from verticals.condges.cassa_motore import Ancora, Conto, Fatto, Flusso, Riga, to_cent
from verticals.condges.cassa_scenario import Base, scenario_da_righe

Query = Callable[[str], list[dict]]

# Società del progetto (ruling R10): un progetto sconosciuto è un errore, non un default.
PROGETTI_SOCIETA = {
    "HPAN26PIANO3": "INTUR",
    "HPAN25PIANO1": "INTUR",
    "SPIAGGIA_LOTTO7": "INTUR",
}

CANONE = "Fitto Hotel (canone)"
GODIMENTO = "Godimento beni di terzi"
V_CANONE_ORTI = "USCITE_CANONE_PASSIVO"
V_CANONE_INTUR = "ENTRATE_AFFITTI_INTUR"
V_GODIMENTO = "USCITE_GODIMENTO_BENI"
V_FINANZIAMENTI = "ENTRATE_FINANZIAMENTI"

SNAPSHOT_HOME = Path(".hotelops_state/cdg_cassa")


class BaselineNonUnica(RuntimeError):
    pass


def query_bq(sql: str) -> list[dict]:
    from core.bq.client import get_client

    return [dict(r) for r in get_client().query(sql).result()]


def _data(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _mese(anno: int, mese: int) -> str:
    return f"{anno:04d}-{mese:02d}"


def _periodo(d: date) -> int:
    return d.year * 12 + d.month


def _mese_dopo(mese: str) -> str:
    a, m = (int(x) for x in mese.split("-"))
    return _mese(a + m // 12, m % 12 + 1)


def _eur(cent: int) -> str:
    """Centesimi -> '1.549,23' (segno, punto migliaia, virgola decimale). Solo per i motivi."""
    segno = "-" if cent < 0 else ""
    e, c = divmod(abs(cent), 100)
    return f"{segno}{e:,}".replace(",", ".") + f",{c:02d}"


# ── ancore ──

_SQL_SALDI = f"""
SELECT societa_id, banca_id, data_riferimento, saldo_eur
FROM `{F_SALDI_BANCA_CHIUSURA_MENSILE}`
"""


def _sql_movimenti(dopo: date) -> str:
    return f"""
SELECT societa_id, banca_id, data_operazione, importo_netto
FROM `{F_BANCHE_MOVIMENTI}`
WHERE data_operazione > DATE '{dopo.isoformat()}'
"""


def _chiusure(query: Query) -> dict[tuple[str, str], dict[date, int]]:
    out: dict[tuple[str, str], dict[date, int]] = defaultdict(dict)
    for r in query(_SQL_SALDI):
        out[(r["societa_id"], r["banca_id"])][_data(r["data_riferimento"])] = to_cent(
            r["saldo_eur"]
        )
    return out


def _ultima_data(chiusure) -> dict[str, date]:
    ultime: dict[str, date] = {}
    for (soc, _), per_data in chiusure.items():
        ultime[soc] = max(ultime.get(soc, date.min), max(per_data))
    return ultime


def leggi_ancore(query: Query) -> dict[str, Ancora]:
    chiusure = _chiusure(query)
    ultime = _ultima_data(chiusure)
    if not ultime:
        return {}

    precedenti: dict[tuple[str, str], date] = {}
    for (soc, banca), per_data in chiusure.items():
        prima = [d for d in per_data if d < ultime[soc]]
        if ultime[soc] in per_data and prima:
            precedenti[(soc, banca)] = max(prima)

    somme: dict[tuple[str, str], list] = {}  # chiave -> [lista (data, cent)], max data
    if precedenti:
        for r in query(_sql_movimenti(min(precedenti.values()))):
            k = (r["societa_id"], r["banca_id"])
            if k in precedenti:
                somme.setdefault(k, []).append(
                    (_data(r["data_operazione"]), to_cent(r["importo_netto"]))
                )

    ancore: dict[str, Ancora] = {}
    for soc, D in ultime.items():
        conti: dict[str, Conto] = {}
        for (s, banca), per_data in chiusure.items():
            if s != soc:
                continue
            if D not in per_data:
                ultima = max(per_data)
                conti[banca] = Conto(
                    per_data[ultima],
                    False,
                    f"nessuna chiusura al {D.isoformat()} (ultima {ultima.isoformat()})",
                )
                continue
            saldo = per_data[D]
            D0 = precedenti.get((s, banca))
            if D0 is None:
                conti[banca] = Conto(saldo, False, "nessuna chiusura precedente")
                continue
            mov = somme.get((s, banca), [])
            copertura = max((d for d, _ in mov), default=D0)
            atteso = per_data[D0] + sum(c for d, c in mov if D0 < d <= D)
            if not mov:
                conti[banca] = Conto(
                    saldo, False, f"nessun movimento dopo il {D0.isoformat()}"
                )
            elif copertura < D:
                conti[banca] = Conto(
                    saldo, False, f"movimenti fino al {copertura.isoformat()}"
                )
            elif atteso != saldo:
                conti[banca] = Conto(
                    saldo, False, f"scostamento {_eur(saldo - atteso)}"
                )
            else:
                conti[banca] = Conto(
                    saldo, True, f"quadra con movimenti dal {D0.isoformat()}"
                )
        ancore[soc] = Ancora(
            societa=soc,
            data=D,
            saldo=sum(c.saldo for c in conti.values()),
            attestato=all(c.attestato for c in conti.values()),
            conti=conti,
        )
    return ancore


# ── baseline PF ──

_SQL_PF = f"""
SELECT societa_id, voce_id, anno, mese, importo, file_sorgente, raw_object_id, data_caricamento
FROM `{F_PIANO_FINANZIARIO_INPUT}`
WHERE fonte = 'PIANO_FINANZIARIO'
"""


def _direzione(voce_id: str) -> str:
    if voce_id.startswith("ENTRATE_"):
        return "E"
    if voce_id.startswith("USCITE_"):
        return "U"
    raise ValueError(f"voce PF '{voce_id}' senza prefisso ENTRATE_/USCITE_")


def _flussi_canone(orti: dict[str, int], intur: dict[str, int]) -> list[Flusso]:
    flussi = []
    for mese in sorted(set(orti) | set(intur)):
        o, i = orti.get(mese, 0), intur.get(mese, 0)
        comune = min(o, i)
        if comune > 0:
            flussi.append(Flusso(CANONE, "ORTI", "INTUR", mese, comune, "pf"))
        if o - comune > 0:
            flussi.append(
                Flusso(CANONE, "ORTI", "INTUR", mese, o - comune, "una_gamba")
            )
        if i - comune > 0:
            flussi.append(
                Flusso(CANONE, "TERZI", "INTUR", mese, i - comune, "una_gamba")
            )
    return flussi


def leggi_baseline(query: Query) -> tuple[list[Riga], list[Flusso], Base, list[str]]:
    dati = query(_SQL_PF)

    file_per_soc: dict[str, set[str]] = defaultdict(set)
    for r in dati:
        file_per_soc[r["societa_id"]].add(r["file_sorgente"])
    for soc in sorted(file_per_soc):
        if len(file_per_soc[soc]) > 1:
            raise BaselineNonUnica(
                f"{soc}: {len(file_per_soc[soc])} file_sorgente: "
                + ", ".join(sorted(file_per_soc[soc]))
            )

    ultime = _ultima_data(_chiusure(query))
    base: Base = {}
    for r in sorted(dati, key=lambda r: str(r["data_caricamento"])):
        base[r["societa_id"]] = {
            "file_sorgente": str(r["file_sorgente"]),
            "raw_object_id": str(r["raw_object_id"]),
            "data_caricamento": str(r["data_caricamento"]),
        }

    righe: list[Riga] = []
    canone_orti: dict[str, int] = defaultdict(int)
    canone_intur: dict[str, int] = defaultdict(int)
    godimento: dict[tuple[str, str], int] = defaultdict(int)
    mesi_con_righe: set[str] = set()
    for r in dati:
        soc = r["societa_id"]
        anno, m = int(r["anno"]), int(r["mese"])
        if soc not in ultime or anno * 12 + m <= _periodo(ultime[soc]):
            continue
        mese = _mese(anno, m)
        mesi_con_righe.add(mese)
        importo = to_cent(r["importo"])
        voce = r["voce_id"]
        if voce == V_CANONE_ORTI:
            canone_orti[mese] += importo
        elif voce == V_CANONE_INTUR:
            canone_intur[mese] += importo
        elif voce == V_GODIMENTO:
            godimento[(soc, mese)] += importo
        else:
            origine = "finanziamento" if voce == V_FINANZIAMENTI else "pf"
            righe.append(Riga(soc, voce, mese, importo, _direzione(voce), origine))

    flussi = _flussi_canone(canone_orti, canone_intur)
    flussi += [
        Flusso(GODIMENTO, soc, "TERZI", mese, imp, "pf")
        for (soc, mese), imp in sorted(godimento.items(), key=lambda kv: kv[0][1])
    ]

    mesi: list[str] = []
    if mesi_con_righe and ultime:
        a = min(ultime.values())
        corrente = _mese_dopo(_mese(a.year, a.month))
        ultimo = max(mesi_con_righe)
        while corrente <= ultimo:
            mesi.append(corrente)
            corrente = _mese_dopo(corrente)
    return righe, flussi, base, mesi


# ── fatti ──

_SQL_FATTI = f"""
SELECT evento_id, progetto_id, tipo_evento, data_evento, importo_eur, fornitore_id
FROM `{F_PROGETTO_EVENTI}`
WHERE tipo_evento = 'PAGAMENTO'
"""


def leggi_fatti(query: Query) -> list[Fatto]:
    fatti = []
    for r in query(_SQL_FATTI):
        if r["tipo_evento"] != "PAGAMENTO":
            continue
        pid = r["progetto_id"]
        if pid not in PROGETTI_SOCIETA:
            raise ValueError(f"progetto_id '{pid}' non in PROGETTI_SOCIETA")
        fatti.append(
            Fatto(
                societa=PROGETTI_SOCIETA[pid],
                progetto_id=pid,
                fornitore_id=r.get("fornitore_id"),
                mese=_data(r["data_evento"]).isoformat()[:7],
                importo=to_cent(r["importo_eur"]),
                evento_id=r["evento_id"],
            )
        )
    return fatti


# ── scenari ──


_SQL_FORNITORI = f"""
SELECT codice_fornitore, nome_esolver, societa_id
FROM `{D_FORNITORI}`
WHERE NOT COALESCE(is_intercompany, FALSE) AND NOT COALESCE(is_excluded, FALSE)
ORDER BY societa_id, nome_esolver"""


def leggi_fornitori(query: Query) -> list[dict]:
    """L'anagrafica fornitori di Esolver (d_fornitori): codice, nome, società.

    Serve alla pagina per riconoscere un fornitore scritto a mano e proporgli il codice;
    intercompany ed esclusi restano fuori. Sola lettura."""
    return [
        {
            "codice": int(r["codice_fornitore"]),
            "nome": str(r.get("nome_esolver") or ""),
            "societa": r.get("societa_id"),
        }
        for r in query(_SQL_FORNITORI)
        if r.get("codice_fornitore") is not None
    ]


def leggi_scenari(query: Query):
    scenari = query(f"SELECT * FROM `{P_SCENARI}`")
    flussi = query(f"SELECT * FROM `{P_SCENARIO_FLUSSI}`")
    pagamenti = query(f"SELECT * FROM `{P_PROGETTI_PAGAMENTI}`")

    # latest wins: il padre più recente comanda anche se non ha righe figlie
    # lo stesso scenario salvato da raw object diversi duplica le righe: vince il più recente
    vincente: dict[str, dict] = {}
    for s in scenari:
        corrente = vincente.get(s["scenario_id"])
        if corrente is None or str(s["data_caricamento"]) > str(
            corrente["data_caricamento"]
        ):
            vincente[s["scenario_id"]] = s
    raw = {sid: s["raw_object_id"] for sid, s in vincente.items()}

    def del_vincente(r):
        return raw.get(r["scenario_id"]) == r["raw_object_id"]

    return scenario_da_righe(
        list(vincente.values()),
        [r for r in flussi if del_vincente(r)],
        [r for r in pagamenti if del_vincente(r)],
    )


# ── orizzonte ipotetico ──


def mesi_ipotetici(mesi: list[str], coda: int = 6) -> tuple[list[str], frozenset[str]]:
    nuovi = []
    ultimo = mesi[-1]
    for _ in range(coda):
        ultimo = _mese_dopo(ultimo)
        nuovi.append(ultimo)
    return list(mesi) + nuovi, frozenset(nuovi)


def coda_ripetuta(pf: list[Riga], mesi_coda: list[str]) -> list[Riga]:
    out = []
    for mese in mesi_coda:
        anno, m = (int(x) for x in mese.split("-"))
        omologo = _mese(anno - 1, m)
        out += [
            Riga(r.societa, r.voce_id, mese, r.importo, r.direzione, "pf")
            for r in pf
            if r.mese == omologo and r.origine == "pf"
        ]
    return out


def coda_flussi(flussi: list[Flusso], mesi_coda: list[str]) -> list[Flusso]:
    out = []
    for mese in mesi_coda:
        anno, m = (int(x) for x in mese.split("-"))
        omologo = _mese(anno - 1, m)
        out += [
            Flusso(f.nome, f.da, f.a, mese, f.importo, f.stato)
            for f in flussi
            if f.mese == omologo
        ]
    return out


# ── snapshot locale ──


def salva_snapshot(dati: dict, home: Path = SNAPSHOT_HOME) -> Path:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    testo = json.dumps(dati, ensure_ascii=False, indent=2)
    path = home / f"snapshot_{datetime.now().strftime('%Y-%m-%dT%H-%M')}.json"
    path.write_text(testo, encoding="utf-8")
    (home / "latest.json").write_text(testo, encoding="utf-8")
    return path


def carica_snapshot(home: Path = SNAPSHOT_HOME) -> dict:
    f = Path(home) / "latest.json"
    if not f.exists():
        raise FileNotFoundError(
            f"Nessuno snapshot in {f}: esegui `hotelops cdg cassa --aggiorna` (legge BigQuery)"
        )
    return json.loads(f.read_text(encoding="utf-8"))
