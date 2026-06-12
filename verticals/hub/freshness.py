"""Freshness dei dati per le card della home (riusa le query di `hotelops health`)."""

from __future__ import annotations


def semaforo(
    giorni: int | None,
    soglia_attenzione: int = 3,
    soglia_allarme: int = 7,
) -> str:
    """Semaforo staleness: 🟢 entro attenzione, 🟡 entro allarme, 🔴 oltre o ignoto."""
    if giorni is None:
        return "🔴"
    if giorni <= soglia_attenzione:
        return "🟢"
    if giorni <= soglia_allarme:
        return "🟡"
    return "🔴"


def carica_freshness() -> dict:
    """Una riga per card: giorni dall'ultimo dato + numero chiave. Query BQ live."""
    from core.bq.client import get_client

    client = get_client()
    out: dict = {}

    q_fb = """
    SELECT DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data), DAY) AS giorni
    FROM `hotelops-suite.hotelops.f_consumi_economato`
    """
    out["fb"] = {"giorni": next(iter(client.query(q_fb).result())).giorni}

    q_rev = """
    SELECT
      DATE_DIFF(CURRENT_DATE('Europe/Rome'),
                MAX(PARSE_DATE('%Y-%m-%d', data_review)), DAY) AS giorni,
      ROUND(AVG(IF(PARSE_DATE('%Y-%m-%d', data_review) >=
                   DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH),
                   punteggio_norm, NULL)), 1) AS media_mese
    FROM `hotelops-suite.hotelops.f_reviews`
    """
    r = next(iter(client.query(q_rev).result()))
    out["reviews"] = {"giorni": r.giorni, "media_mese": r.media_mese}

    q_ing = """
    SELECT COUNTIF(current_status != 'PROMOTED') AS in_coda
    FROM `hotelops-suite.hotelops.v_raw_objects_current`
    """
    out["ingest"] = {"in_coda": next(iter(client.query(q_ing).result())).in_coda}

    return out
