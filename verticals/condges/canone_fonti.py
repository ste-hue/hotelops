"""Fonti del cruscotto canone: adapter in sola lettura, separati dal motore.

Tre tipi di numero, mai mischiati:
- **osservato**  = fatto letto dalle fonti HotelOps (PMS, bilancini, saldi banca);
- **impegno**    = obbligo contrattuale già in essere (rate dei debiti esistenti);
- **ipotesi**    = numero del business plan (crescite, costi, SAL/MCC non firmati).

Gli osservati NON entrano nel motore: affiancano la base 2026 come evidenza.
L'aggiornamento è esplicito (``aggiorna``) e produce uno snapshot datato su file;
la pagina mostra sempre la data dello snapshot, mai un valore "live".
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime
from pathlib import Path

from core.config import F_BILANCINO, F_PRODUZIONE_PMS, F_SALDI_BANCA_CHIUSURA_MENSILE
from verticals.condges import canone_sim as cs

OSSERVATO, IMPEGNO, IPOTESI = "osservato", "impegno", "ipotesi"
OK, BLOCCATA = "collegata", "bloccata"

# Conti del canone d'affitto d'azienda nel piano dei conti Esolver.
_CONTO_CANONE = {"ORTI": "65.11.01", "INTUR": "53.01.33"}
# Classi PMS: 80AFFITT = affitti attivi (supermercato), non ricavo alberghiero.
_CLASSE_CAMERE, _CLASSE_SPIAGGIA, _CLASSE_AFFITTI = "01ROOM", "04BEALL", "80AFFITT"

_SQL_PMS = f"""
SELECT business_unit_id, classe, SUM(importo_imponibile) AS importo,
       MIN(data) AS dal, MAX(data) AS al, MAX(data_caricamento) AS caricato
FROM `{F_PRODUZIONE_PMS}`
WHERE societa_id = 'ORTI' AND anno = {{anno}}
GROUP BY 1, 2
"""

_SQL_BILANCINO = f"""
WITH ultimo AS (
  SELECT societa_id, MAX(mese) AS mese FROM `{F_BILANCINO}`
  WHERE mese LIKE '{{anno}}-%' GROUP BY 1
)
SELECT b.societa_id, b.mese,
       SUM(IF(b.sezione = 'Ricavi', -b.saldo, 0)) AS ricavi,
       SUM(IF(b.sezione = 'Costi', b.saldo, 0)) AS costi,
       SUM(IF(b.codice_conto IN ('65.11.01', '53.01.33'), ABS(b.saldo), 0)) AS canone,
       MAX(b.data_ingresso) AS caricato
FROM `{F_BILANCINO}` b JOIN ultimo u USING (societa_id, mese)
WHERE b.tipo_conto = 'CE'
GROUP BY 1, 2
"""

_SQL_SALDI = f"""
SELECT societa_id, data_riferimento, SUM(saldo_eur) AS saldo, COUNT(*) AS banche
FROM `{F_SALDI_BANCA_CHIUSURA_MENSILE}`
GROUP BY 1, 2
QUALIFY data_riferimento = MAX(data_riferimento) OVER (PARTITION BY societa_id)
"""


def _query(sql: str) -> list[dict]:
    from core.bq.client import get_client

    return [dict(r) for r in get_client().query(sql).result()]


def leggi_pms(anno: int, query=_query) -> dict:
    righe = query(_SQL_PMS.format(anno=anno))
    if not righe:
        raise LookupError(f"nessuna produzione PMS per ORTI nel {anno}")
    tot = {"hotel_camere": 0.0, "hotel_altri": 0.0, "residence": 0.0, "cvm": 0.0,
           "spiaggia_ospiti": 0.0, "affitti": 0.0}
    for r in righe:
        importo, bu, classe = float(r["importo"]), r["business_unit_id"], r["classe"]
        if classe == _CLASSE_AFFITTI:
            tot["affitti"] += importo
        elif classe == _CLASSE_SPIAGGIA:
            tot["spiaggia_ospiti"] += importo
        elif bu == "HOTEL":
            tot["hotel_camere" if classe == _CLASSE_CAMERE else "hotel_altri"] += importo
        elif bu == "RESIDENCE":
            tot["residence"] += importo
        elif bu == "CVM":
            tot["cvm"] += importo
    return {
        "valori": tot,
        "periodo": f"{min(r['dal'] for r in righe):%d/%m/%Y} – {max(r['al'] for r in righe):%d/%m/%Y}",
        "al": max(r["al"] for r in righe).isoformat(),
        "caricato": max(r["caricato"] for r in righe).date().isoformat(),
    }


def _parziale(mese: str, caricato: str) -> bool:
    """Bilancino caricato prima della fine del mese a cui si riferisce."""
    anno, m = (int(x) for x in mese.split("-"))
    fine = date(anno, m, calendar.monthrange(anno, m)[1])
    return date.fromisoformat(caricato[:10]) < fine


def leggi_bilancino(anno: int, query=_query) -> dict:
    righe = query(_SQL_BILANCINO.format(anno=anno))
    if not righe:
        raise LookupError(f"nessun bilancino {anno}")
    return {
        r["societa_id"]: {
            "mese": r["mese"],
            "ricavi": float(r["ricavi"]),
            "costi": float(r["costi"]),
            "canone": float(r["canone"]),
            "caricato": str(r["caricato"])[:10],
            "parziale": _parziale(r["mese"], str(r["caricato"])),
        }
        for r in righe
    }


def leggi_saldi(query=_query) -> dict:
    righe = query(_SQL_SALDI)
    if not righe:
        raise LookupError("nessun saldo banca di fine mese")
    return {
        r["societa_id"]: {
            "al": r["data_riferimento"].isoformat(),
            "saldo": float(r["saldo"]),
            "banche": int(r["banche"]),
        }
        for r in righe
    }


_ADAPTER = {
    "pms": ("PMS HotelCube · produzione giornaliera", "f_produzione_pms", "COMPETENZA", leggi_pms, True),
    "bilancino": ("Esolver · bilancino di verifica", "f_bilancino", "COMPETENZA", leggi_bilancino, True),
    "saldi": ("Banche · saldi di fine mese", "f_saldi_banca_chiusura_mensile", "CASSA", leggi_saldi, False),
}


def aggiorna(anno: int = 2026, query=_query, adesso: datetime | None = None) -> dict:
    """Interroga le fonti osservate. Una fonte che fallisce risulta BLOCCATA, non inventata."""
    snapshot = {"acquisito_il": (adesso or datetime.now()).isoformat(timespec="seconds"), "anno": anno, "fonti": {}}
    for chiave, (nome, tabella, dimensione, leggi, vuole_anno) in _ADAPTER.items():
        voce = {"nome": nome, "tabella": tabella, "dimensione": dimensione}
        try:
            voce["dati"] = leggi(anno, query) if vuole_anno else leggi(query)
            voce["stato"] = OK
        except Exception as exc:  # qualsiasi errore di accesso = fonte bloccata, da mostrare
            voce["stato"] = BLOCCATA
            voce["errore"] = f"{type(exc).__name__}: {exc}"[:300]
        snapshot["fonti"][chiave] = voce
    return snapshot


def osservati_path() -> Path:
    return cs.home() / "osservati.json"


def salva_osservati(nuovo: dict) -> dict:
    """Scrive lo snapshot; una fonte bloccata conserva l'ultimo dato buono, con la sua data."""
    vecchio = carica_osservati() or {"fonti": {}}
    for chiave, voce in nuovo["fonti"].items():
        precedente = vecchio["fonti"].get(chiave, {})
        if voce["stato"] == BLOCCATA and "dati" in precedente:
            voce["dati"] = precedente["dati"]
            voce["dati_del"] = precedente.get("dati_del", vecchio.get("acquisito_il"))
        elif voce["stato"] == OK:
            voce["dati_del"] = nuovo["acquisito_il"]
    path = osservati_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nuovo, ensure_ascii=False, indent=2), encoding="utf-8")
    return nuovo


def carica_osservati() -> dict | None:
    path = osservati_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def stato_fonti(inputs: dict, osservati: dict | None) -> list[dict]:
    """Elenco delle fonti con tipo, dimensione, stato e data: una riga per fonte."""
    righe = []
    for chiave, (nome, tabella, dimensione, _, _) in _ADAPTER.items():
        voce = (osservati or {"fonti": {}})["fonti"].get(chiave)
        if voce is None:
            stato, del_ = "mai aggiornata", ""
        elif voce["stato"] == OK:
            stato, del_ = "collegata", voce.get("dati_del", "")
        else:
            stato = "BLOCCATA — " + voce.get("errore", "")
            del_ = voce.get("dati_del", "") + (" (ultimo dato buono)" if voce.get("dati") else "")
        righe.append({"fonte": nome, "tipo": OSSERVATO, "dimensione": dimensione, "stato": stato,
                      "acquisito_il": del_.replace("T", " "), "riferimento": f"BigQuery · {tabella}"})
    fonte = cs.fonte(inputs)
    ric = inputs.get("reconciliation", {})
    righe.append({
        "fonte": "Business plan · " + fonte["file"], "tipo": IPOTESI, "dimensione": "COMPETENZA",
        "stato": "snapshot datato" + (f" — {ric['esito']}" if ric.get("esito") else ""),
        "acquisito_il": ric.get("checkedAt", ""),
        "riferimento": f"Excel · impronta {fonte['sha256_fonte'][:12] or 'n.d.'}",
    })
    righe.append({
        "fonte": "Mutui · rate dei debiti esistenti", "tipo": IMPEGNO, "dimensione": "IMPEGNO",
        "stato": "non collegata — i piani vivono nell'app Mutui (Cloudflare), non in BigQuery: qui valgono le rate annue copiate nel BP",
        "acquisito_il": ric.get("checkedAt", ""), "riferimento": "BP · fogli Debito, ORTI, INTUR",
    })
    righe.append({
        "fonte": "Finanziamenti nuovi SAL e MCC (terzo piano)", "tipo": IPOTESI, "dimensione": "IMPEGNO",
        "stato": "snapshot datato — non firmati: condizioni e calendari del BP",
        "acquisito_il": ric.get("checkedAt", ""), "riferimento": "BP · fogli Piano SAL, Piano MCC",
    })
    return righe


# Voce → (società, tipo, unità, chiave in inputs["sourceCells"]).
_PROVENIENZA = [
    ("Ricavi ORTI (base e crescita)", "ORTI", IPOTESI, "€/anno, netti IVA", "ORTI_inputs"),
    ("Incidenza costi operativi ORTI", "ORTI", IPOTESI, "% dei ricavi", "ORTI_inputs"),
    ("Fitto Angelina pagato da ORTI", "ORTI", IMPEGNO, "€/anno", "ORTI_inputs"),
    ("Ammortamenti e oneri finanziari ORTI", "ORTI", IMPEGNO, "€/anno", "ORTI_inputs"),
    ("Rate mutui ORTI (esistenti)", "ORTI", IMPEGNO, "€/anno", "ORTI_inputs"),
    ("Spiaggia e fitti attivi INTUR", "INTUR", IPOTESI, "€/anno, netti IVA", "INTUR_inputs"),
    ("Costi operativi INTUR", "INTUR", IPOTESI, "€/anno", "INTUR_inputs"),
    ("Rate INTUR: debiti esistenti", "INTUR", IMPEGNO, "€/anno", "INTUR_inputs"),
    ("Rate INTUR: nuovi SAL e MCC", "INTUR", IPOTESI, "€/anno", "INTUR_inputs"),
    ("Affrancamento riserve INTUR", "INTUR", IMPEGNO, "€/anno", "INTUR_inputs"),
    ("Investimento, erogazioni, IVA e suo recupero", "INTUR", IPOTESI, "€/anno", "cashBridge"),
    ("Aliquota imposte, manutenzione, circolante, soglia DSCR", "Gruppo", IPOTESI, "%", "common"),
    ("Canone 2026 e ricavi dell'anno precedente", "Gruppo", IPOTESI, "€/anno", "priorRevenue"),
]


def provenienza(inputs: dict) -> list[dict]:
    celle = inputs.get("sourceCells", {})
    fonte = cs.fonte(inputs)
    return [
        {"voce": voce, "società": societa, "tipo": tipo, "unità": unita,
         "periodo": "2026–2031", "fonte": fonte["file"], "celle": celle.get(chiave, "n.d.")}
        for voce, societa, tipo, unita, chiave in _PROVENIENZA
    ]


def base_vs_osservato(inputs: dict, osservati: dict | None) -> list[dict]:
    """Base 2026 del modello accanto ai fatti osservati. Evidenza, non correzione."""
    if not osservati:
        return []
    f = osservati["fonti"]
    b = inputs["years"]["2026"]["orti"].get("revenueBreakdown", {})
    righe = []
    pms = f.get("pms", {}).get("dati")
    if pms:
        v, quando = pms["valori"], f"PMS al {date.fromisoformat(pms['al']):%d/%m/%Y}"
        for voce, modello, osservato in (
            ("Hotel · ricavi camere", b.get("rooms"), v["hotel_camere"]),
            ("Hotel · altri ricavi (quota di raccordo nel BP)", b.get("otherHotel"), v["hotel_altri"]),
            ("Angelina Residence", b.get("angelina"), v["residence"]),
            ("Casa Vacanze Maiori", b.get("cvm"), v["cvm"]),
            ("Spiaggia ospiti", b.get("guestBeach"), v["spiaggia_ospiti"]),
            ("Affitti attivi (supermercato)", b.get("supermarketRent"), v["affitti"]),
        ):
            righe.append({"voce": voce, "modello_2026": modello, "osservato": osservato, "quando": quando})
    bil = f.get("bilancino", {}).get("dati")
    if bil:
        for societa, modello in (("ORTI", inputs["years"]["2026"]["orti"]["revenue"]),
                                 ("INTUR", inputs["prior2026"]["inturRevenue"])):
            d = bil.get(societa)
            if not d:
                continue
            quando = f"bilancino {d['mese']}" + (" (parziale)" if d["parziale"] else "")
            righe.append({"voce": f"Ricavi {societa} · totale", "modello_2026": modello,
                          "osservato": d["ricavi"], "quando": quando})
            righe.append({"voce": f"Canone registrato in {societa}", "modello_2026": inputs["prior2026"]["appliedRent"],
                          "osservato": d["canone"], "quando": quando})
    saldi = f.get("saldi", {}).get("dati")
    if saldi:
        for societa, d in sorted(saldi.items()):
            righe.append({
                "voce": f"Saldo banche {societa} (cassa, non confrontabile col CFADS)",
                "modello_2026": inputs["prior2026"]["inturClosingCash"] if societa == "INTUR" else None,
                "osservato": d["saldo"],
                "quando": f"saldi al {date.fromisoformat(d['al']):%d/%m/%Y} · {d['banche']} banche",
            })
    return righe
