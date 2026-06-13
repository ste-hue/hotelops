"""Export read-only BQ → JSON per il viewer static-edge (slice 1).

NON scrive in BQ, non tocca lineage: solo SELECT sulle viste canoniche. I JSON sono
output di presentazione derivati (rigenerabili), non una fonte. Contratto versionato
(`schema`) così il frontend non si rompe quando l'output evolve.
"""

from __future__ import annotations

import decimal
import json
from pathlib import Path

from verticals.hub.freshness import semaforo

# Soglie freshness coerenti con la home Streamlit (grain mensile per F&B).
_FB_ATT, _FB_ALL = 35, 70
_REV_ATT, _REV_ALL = 7, 14

_FB_FIELDS = (
    "anno", "mese", "periodo",
    "ricavi_breakfast", "ricavi_food", "ricavi_beverage", "ricavi_fb_totali",
    "costo_breakfast", "costo_ristorante", "costo_bar", "costo_fb_totale",
    "pax_breakfast", "pax_lunch", "pax_dinner", "coperti_hotel",
    "food_cost_pct_breakfast", "food_cost_pct_ristorante", "food_cost_pct_bar",
    "food_cost_pct", "euro_per_pasto",
    "ricavi_fb_totali_ap", "costo_fb_totale_ap", "coperti_hotel_ap",
)


def shape_fb(rows: list[dict]) -> dict:
    """Righe v_fb_kpi → contratto JSON F&B. Tollera campi mancanti (None)."""
    serie = [{k: r.get(k) for k in _FB_FIELDS} for r in rows]
    return {"schema": 1, "serie": serie}


def shape_meta(generated_at: str, fresh: dict) -> dict:
    """Freshness per superficie → _meta.json (semaforo precomputato lato export)."""
    fb_g = fresh["fb"]["giorni"]
    rev_g = fresh["reviews"]["giorni"]
    return {
        "schema": 1,
        "generated_at": generated_at,
        "surfaces": {
            "fb": {"giorni": fb_g, "semaforo": semaforo(fb_g, _FB_ATT, _FB_ALL)},
            "reviews": {
                "giorni": rev_g,
                "semaforo": semaforo(rev_g, _REV_ATT, _REV_ALL),
                "media_mese": fresh["reviews"].get("media_mese"),
            },
        },
    }


def shape_reviews(serie: list[dict], piattaforme: list[dict], recenti: list[dict]) -> dict:
    """Aggregati reviews → contratto JSON: trend mensile + per piattaforma + recenti."""
    return {
        "schema": 1,
        "serie": [{"periodo": r.get("periodo"), "n": r.get("n"), "media": r.get("media")}
                  for r in serie],
        "piattaforme": [{"piattaforma": r.get("piattaforma"), "n": r.get("n"),
                         "media": r.get("media")} for r in piattaforme],
        "recenti": [{k: r.get(k) for k in (
            "data_review", "piattaforma", "punteggio_norm", "titolo",
            "riassunto_nlp", "sentiment_nlp")} for r in recenti],
    }


def shape_spiaggia(per_anno: list[dict]) -> dict:
    """Aggregati Spiaggia per anno → contratto JSON."""
    return {
        "schema": 1,
        "per_anno": [{k: r.get(k) for k in (
            "anno", "n_prenotazioni", "incassato", "incasso_medio",
            "quota_online", "quota_hotel")} for r in per_anno],
    }


def _jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if hasattr(v, "isoformat"):  # date / datetime
        return v.isoformat()
    return v


def _fb_rows_from_bq(client) -> list[dict]:
    q = """
    SELECT * FROM `hotelops-suite.hotelops.v_fb_kpi`
    WHERE anno >= 2025 ORDER BY anno, mese
    """
    return [{k: _jsonable(v) for k, v in dict(r.items()).items()}
            for r in client.query(q).result()]


def _reviews_from_bq(client) -> tuple[list[dict], list[dict], list[dict]]:
    P = "hotelops-suite.hotelops.f_reviews"
    rows = lambda q: [{k: _jsonable(v) for k, v in dict(r.items()).items()}  # noqa: E731
                      for r in client.query(q).result()]
    serie = rows(f"""
        SELECT FORMAT_DATE('%Y-%m-01', DATE_TRUNC(PARSE_DATE('%Y-%m-%d', data_review), MONTH)) AS periodo,
               COUNT(*) AS n, ROUND(AVG(punteggio_norm), 1) AS media
        FROM `{P}` WHERE data_review IS NOT NULL
        GROUP BY 1 ORDER BY 1 DESC LIMIT 18""")
    piattaforme = rows(f"""
        SELECT piattaforma, COUNT(*) AS n, ROUND(AVG(punteggio_norm), 1) AS media
        FROM `{P}` WHERE PARSE_DATE('%Y-%m-%d', data_review) >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)
        GROUP BY 1 ORDER BY n DESC""")
    recenti = rows(f"""
        SELECT data_review, piattaforma, punteggio_norm, titolo, riassunto_nlp, sentiment_nlp
        FROM `{P}` WHERE data_review IS NOT NULL ORDER BY data_review DESC LIMIT 12""")
    return list(reversed(serie)), piattaforme, recenti


def _spiaggia_from_bq(client) -> list[dict]:
    q = """
    SELECT anno,
           SUM(n_prenotazioni) AS n_prenotazioni,
           ROUND(SUM(incassato), 0) AS incassato,
           ROUND(SAFE_DIVIDE(SUM(incassato), SUM(n_prenotazioni)), 1) AS incasso_medio,
           ROUND(SAFE_DIVIDE(SUM(quota_online * n_prenotazioni), SUM(n_prenotazioni)), 3) AS quota_online,
           ROUND(SAFE_DIVIDE(SUM(quota_hotel * n_prenotazioni), SUM(n_prenotazioni)), 3) AS quota_hotel
    FROM `hotelops-suite.hotelops.v_spiaggia_kpi`
    GROUP BY anno ORDER BY anno
    """
    return [{k: _jsonable(v) for k, v in dict(r.items()).items()}
            for r in client.query(q).result()]


def export_all(out_dir: str, generated_at: str, dry_run: bool = False) -> dict:
    """Genera tutti i JSON. Ritorna {nome: dict} per ispezione/dry-run."""
    from core.bq.client import get_client
    from verticals.hub.freshness import carica_freshness

    client = get_client()
    fresh = carica_freshness()  # riusa le query provate; usiamo solo fb+reviews
    payloads = {
        "_meta": shape_meta(generated_at, fresh),
        "fb": shape_fb(_fb_rows_from_bq(client)),
        "reviews": shape_reviews(*_reviews_from_bq(client)),
        "spiaggia": shape_spiaggia(_spiaggia_from_bq(client)),
    }
    if not dry_run:
        data_dir = Path(out_dir) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            (data_dir / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return payloads
