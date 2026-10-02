"""Simulatore canone ORTI → INTUR: motore annuale a due gambe (2027–2031).

Porting 1:1 di ``calculate`` del prototipo "Panorama ORTI + INTUR" (BP Solo Terzo
Interno, 01/10/2026). Puro: nessun I/O su BigQuery, nessuna dipendenza da Streamlit.

Concetti:
- **inputs** = dati + ipotesi estratti dal BP (``model-inputs.json``, FUORI da git:
  sono numeri aziendali). Rate, interessi, ammortamenti e ponte di cassa restano gli
  importi annui della fonte: il motore non ricalcola i piani di ammortamento.
- **scenario** = le sole leve modificabili: crescita ricavi ORTI e incidenza costi
  per anno, scaletta del canone, destinatario del fitto Angelina 2027-28.
  La crescita è l'unica fonte di verità dei ricavi (ricavi = precedente × (1+g)).
- Il **canone è una scaletta contrattuale** non decrescente: cambiare ricavi o
  costi non lo muove. La banda min INTUR / max ORTI è solo diagnostica.

Gli scenari sono proiezioni → vivono come file JSON, mai nel pool ``f_*``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

SCHEMA = "canone-sim/1"
ANGELINA_INTUR = "intur"
ANGELINA_TERZI = "terzi"
_ANGELINA_FINO_AL = 2028  # il file tiene i 120k in INTUR fino al 2028
_ANGELINA_ANNI_APERTI = (2027, 2028)  # anni in cui il destinatario è una questione aperta
MAX_CANONE = 10_000_000


def home() -> Path:
    """Cartella locale (gitignored) di inputs e scenari."""
    return Path(os.environ.get("CANONE_SIM_HOME", ".hotelops_state/canone_sim"))


def inputs_path() -> Path:
    """Dati di base del BP. ``CANONE_SIM_INPUTS`` li sposta (es. secret montato nel job cloud)."""
    return Path(os.environ.get("CANONE_SIM_INPUTS") or home() / "model-inputs.json")


def load_inputs(raw: bytes) -> dict:
    """Parsa ``model-inputs.json`` e ne fissa l'impronta (versione della fonte)."""
    inputs = json.loads(raw)
    for key in ("common", "prior2025", "prior2026", "years"):
        if key not in inputs:
            raise ValueError(f"inputs: manca la chiave {key!r}")
    inputs["_sha256"] = hashlib.sha256(raw).hexdigest()
    inputs["_raw"] = raw
    return inputs


def anni(inputs: dict) -> list[int]:
    return sorted(int(y) for y in inputs["years"] if 2027 <= int(y) <= 2031)


def fonte(inputs: dict) -> dict:
    return {
        "file": inputs.get("originalUploadedFilename") or inputs.get("source", ""),
        "sha256_fonte": inputs.get("sourceSHA256", ""),
        "sha256_inputs": inputs.get("_sha256", ""),
    }


def scenario_base(inputs: dict) -> dict:
    """Scenario di partenza: crescite/costi del BP + bozza di scaletta.

    La bozza sta negli inputs (``contractDraft``); se manca, canone piatto al
    livello 2026 (neutro e non decrescente).
    """
    draft = inputs.get("contractDraft") or {}
    piatto = inputs["prior2026"]["appliedRent"]
    previous = inputs["prior2026"]["ortiRevenue"]
    per_anno = {}
    for y in anni(inputs):
        o = inputs["years"][str(y)]["orti"]
        per_anno[y] = {
            "crescita": o["revenue"] / previous - 1,
            "costi": o["operatingCostRate"],
            "canone": float(draft.get(str(y), piatto)),
        }
        previous = o["revenue"]
    return {"nome": "Base", "angelina": ANGELINA_INTUR, "anni": per_anno}


def calculate(inputs: dict, scenario: dict, canone_automatico: bool = False) -> list[dict]:
    """Una riga per anno con le due gambe e il gruppo, calcolata in sequenza.

    ``canone_automatico=True`` ignora la scaletta e applica la regola del foglio
    'Canone Motore' del BP: serve SOLO a verificare la replica dell'Excel.
    """
    prec = riga_2026(inputs)
    out = []
    for y in anni(inputs):
        p = scenario["anni"][y]
        canone = None if canone_automatico else p["canone"]
        riga = _riga(inputs, y, p["crescita"], p["costi"], canone, scenario["angelina"],
                     prec["ricavi_o"], prec["ricavi_i"], prec["cassa_i"],
                     inputs["common"]["workingCapitalRate"])
        out.append(riga)
        prec = riga
    return out


def riga_2026(inputs: dict) -> dict:
    """Anno base: canone fisso, nessun assorbimento di circolante (come nel BP)."""
    o = inputs["years"]["2026"]["orti"]
    p25 = inputs["prior2025"]
    return _riga(inputs, 2026, o["revenue"] / p25["ortiRevenue"] - 1, o["operatingCostRate"],
                 inputs["prior2026"]["appliedRent"], ANGELINA_INTUR,
                 p25["ortiRevenue"], p25["inturRevenue"], p25["inturClosingCash"], 0.0)


def _riga(inputs: dict, y: int, crescita: float, costi: float, canone: float | None,
          angelina: str, prev_rev: float, prev_intur_rev: float, prev_cash: float, w: float) -> dict:
    """Un anno. ``canone=None`` = regola automatica del BP (solo verifica)."""
    c = inputs["common"]
    t, m, s = c["taxRate"], c["maintenanceRate"], c["targetDSCR"]
    b = inputs["years"][str(y)]
    o, i = b["orti"], b["intur"]
    revenue = prev_rev * (1 + crescita)
    costi_o = revenue * costi
    ebitda_ante = revenue - costi_o
    a_terzi = y in _ANGELINA_ANNI_APERTI and angelina == ANGELINA_TERZI
    angelina_a_intur = o["angelinaRent"] if y <= _ANGELINA_FINO_AL and not a_terzi else 0.0
    altri_intur = i["beachRevenue"] + i["otherRentRevenue"] - (o["angelinaRent"] if a_terzi else 0.0)
    man_o, ccn_o = m * revenue, w * (revenue - prev_rev)
    affr = i["reserveReleasePayment"]

    # Banda alla soglia (diagnostica): max che ORTI regge, min che serve a INTUR.
    max_tax = ebitda_ante - o["angelinaRent"] - (
        s * o["debtService"] + man_o + ccn_o - t * (o["depreciation"] + o["interest"])
    ) / (1 - t)
    if ebitda_ante - max_tax - o["angelinaRent"] - o["depreciation"] - o["interest"] >= 0:
        massimo = max_tax
    else:
        massimo = ebitda_ante - o["angelinaRent"] - s * o["debtService"] - man_o - ccn_o
    fabbisogno = s * i["debtService"] + m * altri_intur + w * (altri_intur - prev_intur_rev) + affr
    min_tax = (
        fabbisogno
        - t * (i["depreciation"] + i["interest"])
        - (altri_intur - i["operatingCosts"]) * (1 - t)
    ) / (1 - t - m - w)
    if altri_intur + min_tax - i["operatingCosts"] - i["depreciation"] - i["interest"] >= 0:
        minimo = min_tax
    else:
        minimo = (fabbisogno - (altri_intur - i["operatingCosts"])) / (1 - m - w)

    if canone is None:
        canone = max(0.0, _canone_motore(minimo, massimo, c))

    ebitda_o = ebitda_ante - canone - o["angelinaRent"]
    tax_o = max(0.0, ebitda_o - o["depreciation"] - o["interest"]) * t
    ricavi_i = altri_intur + canone
    ebitda_i = ricavi_i - i["operatingCosts"]
    tax_i = max(0.0, ebitda_i - i["depreciation"] - i["interest"]) * t
    man_i, ccn_i = m * ricavi_i, w * (ricavi_i - prev_intur_rev)
    cfads_o = ebitda_o - tax_o - man_o - ccn_o
    cfads_i = ebitda_i - tax_i - man_i - ccn_i - affr
    rate_o, rate_i = o["debtService"], i["debtService"]
    br = i["cashBridge"]
    cassa_i = (
        prev_cash + ebitda_i - tax_i - rate_i - affr
        + br["newLoanDrawdowns"] - br["investmentSpend"]
        - br["investmentVATPaid"] + br["investmentVATRecovered"]
    )
    return {
        "anno": y, "canone": canone, "canone_min_intur": minimo, "canone_max_orti": massimo,
        "ricavi_o": revenue, "ricavi_o_prec": prev_rev, "crescita": crescita,
        "costi_o": costi_o, "incidenza_costi": costi,
        "angelina_o": o["angelinaRent"], "angelina_a_intur": angelina_a_intur,
        "tax_o": tax_o, "man_o": man_o, "ccn_o": ccn_o,
        "cfads_o": cfads_o, "rate_o": rate_o,
        "ricavi_i": ricavi_i, "altri_ricavi_i": altri_intur, "costi_i": i["operatingCosts"],
        "tax_i": tax_i, "man_i": man_i, "ccn_i": ccn_i, "affr_i": affr,
        "cfads_i": cfads_i, "rate_i": rate_i, "cassa_i": cassa_i,
        "rate_i_dettaglio": dict(i.get("debtServiceBreakdown", {})),
        "composizione_bp": dict(o.get("revenueBreakdown", {})), "ricavi_o_bp": o["revenue"],
        "dscr_o": _ratio(cfads_o, rate_o), "dscr_i": _ratio(cfads_i, rate_i),
        "dscr_g": _ratio(cfads_o + cfads_i, rate_o + rate_i),
        "residuo_o": cfads_o - rate_o, "residuo_i": cfads_i - rate_i,
        "manca_o": max(0.0, s * rate_o - cfads_o), "manca_i": max(0.0, s * rate_i - cfads_i),
        "manca_g": max(0.0, s * (rate_o + rate_i) - cfads_o - cfads_i),
    }


def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def _excel_round(x: float) -> float:
    # ROUND di Excel: metà lontano da zero (non il banker's rounding di Python).
    return (1 if x >= 0 else -1) * int(abs(x) + 0.5)


def _canone_motore(minimo: float, massimo: float, common: dict) -> float:
    if massimo < minimo:
        return massimo
    passo = common["roundingEUR"]
    centro = _excel_round((minimo + common["bandPosition"] * (massimo - minimo)) / passo) * passo
    return min(massimo, max(minimo, centro))


def canone_equilibrio(inputs: dict, scenario: dict, anno: int) -> float:
    """Canone che dà lo stesso DSCR alle due gambe in ``anno`` (diagnostica).

    È il punto in cui la gamba più debole sta meglio che può: alzandolo migliora
    INTUR e peggiora ORTI. Tiene fermi gli altri anni dello scenario e NON
    guarda il vincolo di non-decrescenza: non riscrive la scaletta.
    """
    prova = copia(scenario)
    lo, hi = 0.0, float(MAX_CANONE)
    for _ in range(60):
        medio = (lo + hi) / 2
        prova["anni"][anno]["canone"] = medio
        r = next(x for x in calculate(inputs, prova) if x["anno"] == anno)
        if r["dscr_o"] > r["dscr_i"]:
            lo = medio
        else:
            hi = medio
    return (lo + hi) / 2


def errori_scaletta(inputs: dict, scenario: dict) -> list[str]:
    """La scaletta parte dal canone 2026 e non scende mai. Vuoto = valida."""
    errori = []
    precedente, anno_prec = inputs["prior2026"]["appliedRent"], 2026
    for y in anni(inputs):
        canone = scenario["anni"][y]["canone"]
        if not 0 <= canone <= MAX_CANONE:
            errori.append(f"{y}: canone fuori dai limiti (0 – {MAX_CANONE:,.0f} €).".replace(",", "."))
        elif canone < precedente:
            errori.append(
                f"{y}: {canone:,.0f} € è sotto il {anno_prec} ({precedente:,.0f} €). "
                "La scaletta non può scendere: alza prima questo anno o abbassa il precedente."
                .replace(",", ".")
            )
        precedente, anno_prec = canone, y
    return errori


def imposta_ricavi(inputs: dict, scenario: dict, anno: int, ricavi: float) -> None:
    """Fissa i ricavi ORTI di un anno riscrivendone la crescita (fonte di verità).

    Gli anni successivi conservano la loro crescita %, quindi si spostano di conseguenza.
    """
    riga = next(r for r in calculate(inputs, scenario) if r["anno"] == anno)
    scenario["anni"][anno]["crescita"] = ricavi / riga["ricavi_o_prec"] - 1


def modifiche(inputs: dict, scenario: dict) -> list[dict]:
    """Cosa lo scenario cambia rispetto alla base (per distinguere dati da ipotesi)."""
    base = scenario_base(inputs)
    diff = []
    if scenario["angelina"] != base["angelina"]:
        diff.append({"anno": None, "campo": "angelina", "base": base["angelina"], "valore": scenario["angelina"]})
    for y in anni(inputs):
        for campo in ("canone", "crescita", "costi"):
            a, b = base["anni"][y][campo], scenario["anni"][y][campo]
            if abs(a - b) > 1e-9:
                diff.append({"anno": y, "campo": campo, "base": a, "valore": b})
    return diff


def scenario_to_json(inputs: dict, scenario: dict, salvato_il: datetime | None = None) -> str:
    doc = {
        "schema": SCHEMA,
        "nome": scenario["nome"],
        "salvato_il": (salvato_il or datetime.now()).isoformat(timespec="seconds"),
        "fonte": fonte(inputs),
        "angelina": scenario["angelina"],
        "anni": {str(y): dict(v) for y, v in scenario["anni"].items()},
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def scenario_from_json(inputs: dict, raw: str | bytes) -> tuple[dict, list[str]]:
    """Ritorna (scenario, avvisi). Esplode se il file non è uno scenario valido."""
    doc = json.loads(raw)
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"non è uno scenario del simulatore canone (schema {doc.get('schema')!r})")
    if doc.get("angelina") not in (ANGELINA_INTUR, ANGELINA_TERZI):
        raise ValueError(f"angelina non valido: {doc.get('angelina')!r}")
    attesi = anni(inputs)
    if sorted(int(y) for y in doc["anni"]) != attesi:
        raise ValueError(f"anni dello scenario {sorted(doc['anni'])} ≠ anni del modello {attesi}")
    scenario = {
        "nome": str(doc["nome"]),
        "angelina": doc["angelina"],
        "salvato_il": doc.get("salvato_il", ""),
        "anni": {
            int(y): {k: float(v[k]) for k in ("crescita", "costi", "canone")}
            for y, v in doc["anni"].items()
        },
    }
    errori = errori_scaletta(inputs, scenario)
    if errori:
        raise ValueError("scaletta non valida: " + " ".join(errori))
    avvisi = []
    if doc.get("fonte", {}).get("sha256_inputs") != inputs.get("_sha256"):
        avvisi.append(
            "Lo scenario è stato salvato su una versione diversa dei dati di base: "
            "le leve sono le stesse, i risultati possono differire."
        )
    return scenario, avvisi


def _slug(nome: str) -> str:
    pulito = "".join(ch if ch.isalnum() else "-" for ch in nome.strip().lower())
    return "-".join(filter(None, pulito.split("-"))) or "scenario"


def salva_scenario(inputs: dict, scenario: dict) -> Path:
    cartella = home() / "scenari"
    cartella.mkdir(parents=True, exist_ok=True)
    path = cartella / f"{_slug(scenario['nome'])}.json"
    path.write_text(scenario_to_json(inputs, scenario), encoding="utf-8")
    # Copia dei dati di base su cui lo scenario è nato: dati nuovi non lo riscrivono.
    archivio = home() / "inputs" / f"{inputs['_sha256'][:12]}.json"
    if "_raw" in inputs and not archivio.exists():
        archivio.parent.mkdir(parents=True, exist_ok=True)
        archivio.write_bytes(inputs["_raw"])
    return path


def scenari_salvati(inputs: dict) -> dict[str, dict]:
    """nome → scenario, dai file validi nella cartella (gli altri si saltano)."""
    trovati = {}
    for path in sorted((home() / "scenari").glob("*.json")):
        try:
            scenario, _ = scenario_from_json(inputs, path.read_bytes())
        except (ValueError, KeyError, TypeError):
            continue
        trovati[scenario["nome"]] = scenario
    return trovati


def copia(scenario: dict) -> dict:
    return copy.deepcopy(scenario)
