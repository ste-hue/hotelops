"""Pure computation engine for Controllo di Gestione.

No Streamlit, no BigQuery — just DataFrames in, results out.
"""

from __future__ import annotations

import pandas as pd


CE_CATEGORIE_ORD = [
    "Ricavi",
    "Acquisti",
    "Costi Produttivi",
    "Costo del Personale",
    "Costi Commerciali",
    "Costi Amministrativi",
    "Oneri Finanziari",
]


def compute_ce_cascade(consuntivo_by_cat: pd.DataFrame) -> list[dict]:
    """Compute CE riclassificato cascade from consuntivo grouped by categoria_ce.

    Input: DataFrame with columns [categoria_ce, importo]
    Output: list of dicts with keys [label, importo, pct_ricavi, is_subtotal, indent]
    """
    totals = {}
    if not consuntivo_by_cat.empty:
        grouped = consuntivo_by_cat.groupby("categoria_ce")["importo"].sum()
        totals = grouped.to_dict()

    ricavi = totals.get("Ricavi", 0)
    acquisti = totals.get("Acquisti", 0)
    costi_prod = totals.get("Costi Produttivi", 0)
    personale = totals.get("Costo del Personale", 0)
    commerciali = totals.get("Costi Commerciali", 0)
    amministrativi = totals.get("Costi Amministrativi", 0)
    oneri_fin = totals.get("Oneri Finanziari", 0)

    costo_mp = acquisti
    costo_venduto = costo_mp + costi_prod
    margine_1 = ricavi - costo_venduto
    tot_costi_op = costo_venduto + personale + commerciali + amministrativi
    ebit = ricavi - tot_costi_op
    ebitda = ebit  # v1: ammortamenti not separated
    risultato = ebit - oneri_fin

    def _pct(val):
        return round(val / ricavi * 100, 1) if ricavi else 0

    rows = [
        {"label": "Ricavi", "importo": ricavi, "pct_ricavi": _pct(ricavi), "is_subtotal": True, "indent": 0},
        {"label": "Acquisti", "importo": -acquisti, "pct_ricavi": _pct(acquisti), "is_subtotal": False, "indent": 1},
        {"label": "Costo Materie Prime", "importo": costo_mp, "pct_ricavi": _pct(costo_mp), "is_subtotal": True, "indent": 0},
        {"label": "Costi Produttivi", "importo": -costi_prod, "pct_ricavi": _pct(costi_prod), "is_subtotal": False, "indent": 1},
        {"label": "I Margine Operativo", "importo": margine_1, "pct_ricavi": _pct(margine_1), "is_subtotal": True, "indent": 0},
        {"label": "Costo del Personale", "importo": -personale, "pct_ricavi": _pct(personale), "is_subtotal": False, "indent": 1},
        {"label": "Costi Commerciali", "importo": -commerciali, "pct_ricavi": _pct(commerciali), "is_subtotal": False, "indent": 1},
        {"label": "Costi Amministrativi", "importo": -amministrativi, "pct_ricavi": _pct(amministrativi), "is_subtotal": False, "indent": 1},
        {"label": "EBIT", "importo": ebit, "pct_ricavi": _pct(ebit), "is_subtotal": True, "indent": 0},
        {"label": "EBITDA", "importo": ebitda, "pct_ricavi": _pct(ebitda), "is_subtotal": True, "indent": 0},
        {"label": "Oneri Finanziari", "importo": -oneri_fin, "pct_ricavi": _pct(oneri_fin), "is_subtotal": False, "indent": 1},
        {"label": "Risultato Gestionale", "importo": risultato, "pct_ricavi": _pct(risultato), "is_subtotal": True, "indent": 0},
    ]
    return rows


def compute_indicatori(
    cascade: list[dict],
    tipo_costo_totals: pd.DataFrame,
) -> dict:
    """Compute KPIs from CE cascade and tipo_costo breakdown.

    cascade: output of compute_ce_cascade
    tipo_costo_totals: DataFrame with [tipo_costo, importo] (absolute values)

    Returns dict with: ebitda_pct, ros, bep_fatturato, bep_giorno, margine_contribuzione
    """
    vals = {r["label"]: r["importo"] for r in cascade}
    ricavi = vals.get("Ricavi", 0)
    ebitda = vals.get("EBITDA", 0)
    ebit = vals.get("EBIT", 0)

    tipo_sums = {}
    if not tipo_costo_totals.empty:
        tipo_sums = tipo_costo_totals.groupby("tipo_costo")["importo"].sum().to_dict()

    costi_fissi = tipo_sums.get("F", 0) + tipo_sums.get("P", 0) + tipo_sums.get("X", 0)
    costi_variabili = tipo_sums.get("V", 0)

    if ricavi > 0 and (ricavi - costi_variabili) > 0:
        bep_fatturato = costi_fissi / (1 - costi_variabili / ricavi)
        bep_giorno = int((bep_fatturato / ricavi) * 365)
    else:
        bep_fatturato = 0
        bep_giorno = 0

    margine_contr = ((ricavi - costi_variabili) / ricavi * 100) if ricavi else 0

    return {
        "ebitda_pct": round(ebitda / ricavi * 100, 1) if ricavi else 0,
        "ros": round(ebit / ricavi * 100, 1) if ricavi else 0,
        "bep_fatturato": round(bep_fatturato),
        "bep_giorno": bep_giorno,
        "margine_contribuzione": round(margine_contr, 1),
    }


def compute_proiezione_anno(
    consuntivo_ytd: float,
    tipo_costo: str,
    last_month: int,
    stagionalita: list[float] | None = None,
) -> float:
    """Project year-end from YTD actuals using seasonality.

    stagionalita: list of 12 coefficients (sum=12.0). If None, uses flat.
    For F/X types: linear projection (consuntivo / months * 12).
    For IP/V/P types: consuntivo / cumulative_seasonal_pct.
    """
    if last_month <= 0 or consuntivo_ytd == 0:
        return 0

    if tipo_costo in ("F", "X") or stagionalita is None:
        return consuntivo_ytd / last_month * 12

    cumul = sum(stagionalita[:last_month])
    if cumul <= 0:
        return consuntivo_ytd / last_month * 12  # fallback to linear

    return consuntivo_ytd / (cumul / 12)
